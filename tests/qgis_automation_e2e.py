"""Velorona automation -- QGIS runtime test.

Real QgsApplication, real QgsTask on QGIS's task manager, real dialog widgets, the real plugin class.
Only the elevation HTTP call is replaced (by a deterministic stub), so the run needs no network; set
VELORONA_LIVE=1 to add one run against the live Open-Meteo elevation service.

    tests/run_qgis_tests.sh    (runs this after the unit tests)
"""

import json
import os
import shutil
import sys
import tempfile
import time

PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(PLUGIN_DIR))

from qgis.core import Qgis, QgsApplication, QgsVectorLayer  # noqa: E402
from qgis.PyQt.QtWidgets import QFileDialog, QMainWindow, QMessageBox  # noqa: E402

qgs = QgsApplication([], True)
qgs.initQgis()

PKG = os.path.basename(PLUGIN_DIR)
import importlib  # noqa: E402

plugin_mod = importlib.import_module(f"{PKG}.plugin")
dialog_mod = importlib.import_module(f"{PKG}.ui.automation_dialog")
qtask = importlib.import_module(f"{PKG}.core.automation.qgis_task")
importlib.import_module(f"{PKG}.core.automation")   # puts the bundled aei_workflow on sys.path, as the plugin does
inputs = importlib.import_module("aei_workflow.inputs")
engine = importlib.import_module("aei_workflow.engine")
store_mod = importlib.import_module("aei_workflow.store")
terrestrial = importlib.import_module(f"{PKG}.core.engines.terrestrial")
from aei_link_clearance import terrain  # noqa: E402

RESULTS = []
HEADER = "link_id,site_a_lat,site_a_lon,site_a_height_m,site_b_lat,site_b_lon,site_b_height_m,frequency_ghz"


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    return ok


def pump(seconds=0.0, until=None, timeout=30.0):
    """Run the GUI event loop. Returns (elapsed, longest gap between event-loop turns)."""
    start = last = time.monotonic()
    worst = 0.0
    while True:
        QgsApplication.processEvents()
        now = time.monotonic()
        worst = max(worst, now - last)
        last = now
        if until is not None and until():
            break
        if until is None and now - start >= seconds:
            break
        if now - start > timeout:
            break
        time.sleep(0.005)
    return time.monotonic() - start, worst


warnings_shown = []
QMessageBox.warning = staticmethod(lambda *a, **k: warnings_shown.append(a[1:3]))

TMP = tempfile.mkdtemp(prefix="velorona_auto_e2e_")
STORE = os.path.join(TMP, "store")


def write_csv(name, body):
    path = os.path.join(TMP, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(HEADER + "\n" + body)
    return path


GOOD = "\n".join(f"L{i},43.{60 + i},-79.38,30,43.{70 + i},-79.41,30,6.0" for i in range(1, 5))
CSV_MIXED = write_csv("mixed.csv", GOOD + "\nBAD,abc,1,1,1,1,1,1\nTALL,43.7,-79.4,5000,43.8,-79.3,25,11\n")


def slow_flat_terrain(delay):
    def get(points, timeout=15.0):
        time.sleep(delay)
        return [100.0] * len(points)
    return get


# -- 1. shared bounds are the plugin's own ----------------------------------------------------------
print("== input validation uses the plugin's own bounds ==")
bounds = inputs.default_bounds()
check("default_bounds() == terrestrial PARAM_SPEC min/max",
      bounds == {p["key"]: (p["min"], p["max"]) for p in terrestrial.PARAM_SPEC if "min" in p}, str(bounds))
v = inputs.validate_links_csv(open(CSV_MIXED, encoding="utf-8").read())
check("real bounds reject a 5000 m antenna and a non-numeric row, keep 4 good links",
      len(v["accepted"]) == 4 and len(v["rejected"]) == 2 and any("site_a_height_m" in r["reason"] for r in v["rejected"]))

# -- 2. plugin wiring ---------------------------------------------------------------------------------
print("== plugin wiring ==")


class Iface:
    def __init__(self):
        self.window = QMainWindow()
        self.actions = []

    def mainWindow(self):
        return self.window

    def addToolBarIcon(self, a):
        pass

    def addPluginToMenu(self, m, a):
        self.actions.append(a.text())

    def removePluginMenu(self, m, a):
        pass

    def removeToolBarIcon(self, a):
        pass

    def mapCanvas(self):
        from qgis.gui import QgsMapCanvas
        return QgsMapCanvas()


iface = Iface()
plugin = plugin_mod.VeloronaPlugin(iface)
plugin.initGui()
check("menu has the Automate action", "Automate: Batch Path Clearance Runs" in iface.actions, str(iface.actions))
plugin.unload()
check("unload with no dialog open is clean", plugin.automation_dialog is None)

versions = qtask.collect_versions()
check("versions: plugin version comes from metadata.txt, QGIS and engine versions present",
      versions["velorona_plugin"] and versions["qgis"] == Qgis.version() and versions["analysis_engine"]["aei-link-clearance"],
      json.dumps(versions))

# -- 3. run through the dialog: responsiveness, progress, saved history -------------------------------
print("== background run through the dialog (4 links, 0.4 s each, service stubbed) ==")
terrain.get_elevations = slow_flat_terrain(0.4)
dlg = dialog_mod.AutomationDialog(None, store_root=STORE)
dlg.name_edit.setText("Weekly Toronto check")
dlg.path_edit.setText(CSV_MIXED)
dlg.pause_spin.setValue(0.0)
dlg.validate_input()
check("validation summary shows 4 ready / 2 rejected and enables Run",
      "4 link(s) ready" in dlg.validation_view.toPlainText() and "2 row(s) rejected" in dlg.validation_view.toPlainText()
      and dlg.run_button.isEnabled())
check("queued rows appear for every accepted link", dlg.results_table.rowCount() == 4)

t0 = time.monotonic()
dlg.start_run()
started_returns_fast = time.monotonic() - t0
check("start_run returns immediately (does not block the GUI thread)", started_returns_fast < 0.3, f"{started_returns_fast:.3f}s")
check("controls locked while running; Cancel enabled", dlg.running and not dlg.run_button.isEnabled() and dlg.cancel_button.isEnabled())
elapsed, worst_gap = pump(until=lambda: not dlg.running)
check("run took real time in the background (>=1.2 s) yet the event loop never stalled > 0.25 s",
      elapsed >= 1.2 and worst_gap < 0.25, f"elapsed {elapsed:.2f}s, longest event-loop gap {worst_gap * 1000:.0f} ms")
statuses = [dlg.results_table.item(r, 1).text() for r in range(dlg.results_table.rowCount())]
check("every link row updated to ok with a line-of-sight verdict",
      statuses == ["ok"] * 4 and all(dlg.results_table.item(r, 2).text() for r in range(4)), str(statuses))
check("status line reports PARTIAL (2 rows were rejected), not success", "PARTIAL" in dlg.status.text(), dlg.status.text())

summaries, problems = dlg.store.list_runs()
check("run is on disk and listed in history", len(summaries) == 1 and summaries[0]["status"] == "partial" and not problems)
run = dlg.store.load_run(summaries[0]["run_id"])
check("record has workflow snapshot, input hash, per-link timestamps, versions, provenance",
      run["workflow_snapshot"]["name"] == "Weekly Toronto check" and len(run["input"]["sha256"]) == 64
      and all(l["analyzed_at"] for l in run["links"]) and run["versions"]["qgis"] == Qgis.version()
      and run["provenance"]["historical_replay_supported"] is False)
check("workflow was saved with the run", [w["name"] for w in dlg.store.list_workflows()[0]] == ["Weekly Toronto check"])
check("no modal warnings were raised", not warnings_shown, str(warnings_shown))

# -- 4. reopen in a "new session" ---------------------------------------------------------------------
print("== reopen ==")
dlg.close()
dlg2 = dialog_mod.AutomationDialog(None, store_root=STORE)
check("a fresh dialog on the same folder lists the run and the workflow",
      dlg2.history_table.rowCount() == 1 and dlg2.workflow_combo.findText("Weekly Toronto check") > 0)
dlg2.history_table.selectRow(0)
dlg2.open_selected_run()
check("opening the run shows its 4 links + 2 rejected rows and says it is a stored record",
      dlg2.results_table.rowCount() == 6 and "not a fresh analysis" in dlg2.validation_view.toPlainText())

# -- 5. cancellation ------------------------------------------------------------------------------------
print("== cancellation ==")
terrain.get_elevations = slow_flat_terrain(0.3)
dlg2.path_edit.setText(write_csv("ten.csv", "\n".join(f"C{i},43.{60 + i},-79.38,30,43.{70 + i},-79.41,30,6.0" for i in range(10))))
dlg2.workflow_combo.setCurrentIndex(0)
dlg2.name_edit.setText("Cancel me")
dlg2.path_edit.setText(os.path.join(TMP, "ten.csv"))
dlg2.start_run()
pump(until=lambda: dlg2.progress.value() >= 10 or not dlg2.running, timeout=10)
dlg2.cancel_run()
pump(until=lambda: not dlg2.running, timeout=15)
runs = [s for s in dlg2.store.list_runs()[0] if s["workflow_name"] == "Cancel me"]
crun = dlg2.store.load_run(runs[0]["run_id"])
check("canceled run is saved as 'canceled'", crun["status"] == "canceled", crun["status"])
check("finished links kept with results, the rest marked not_run",
      0 < crun["counts"]["ok"] < 10 and crun["counts"]["not_run"] == 10 - crun["counts"]["ok"]
      and all(l["result"] for l in crun["links"] if l["status"] == "ok"), json.dumps(crun["counts"]))
check("status line says CANCELED", "CANCELED" in dlg2.status.text(), dlg2.status.text())

# -- 6. every link failing is FAILED, with per-link errors ----------------------------------------------


def down(points, timeout=15.0):
    raise ConnectionError("Open-Meteo unreachable (simulated)")


print("== service outage ==")
terrain.get_elevations = down
dlg2.workflow_combo.setCurrentIndex(0)
dlg2.name_edit.setText("Outage")
dlg2.path_edit.setText(write_csv("two.csv", "\n".join(GOOD.splitlines()[:2])))
dlg2.attempts_spin.setValue(1)
dlg2.start_run()
pump(until=lambda: not dlg2.running, timeout=15)
orun = dlg2.store.load_run([s for s in dlg2.store.list_runs()[0] if s["workflow_name"] == "Outage"][0]["run_id"])
check("outage run is FAILED, no result was invented", orun["status"] == "failed" and all(l["result"] is None for l in orun["links"]))
check("per-link errors are shown in the table",
      all("unreachable" in dlg2.results_table.item(r, 4).text() for r in range(2)))
check("status line says FAILED", "FAILED" in dlg2.status.text())

# -- 7. real engine + real analysis through the task, with terrain stub ---------------------------------
print("== real aei_link_clearance through WorkflowTask ==")
terrain.get_elevations = lambda pts, timeout=15.0: [100.0] * len(pts)
wf = importlib.import_module("aei_workflow.workflow").new_workflow("direct", workflow_id="direct1")
val = inputs.validate_links_csv(open(write_csv("one.csv", GOOD.splitlines()[0]), encoding="utf-8").read())
task = qtask.WorkflowTask(wf, val, {"name": "one.csv", "sha256": "0" * 64}, store_mod.RunStore(STORE))
got = []
task.run_finished.connect(got.append)
task.link_done.connect(lambda d, t, l: got.append(("link", d, t)))
QgsApplication.taskManager().addTask(task)
pump(until=lambda: any(isinstance(g, dict) for g in got), timeout=15)
final = next(g for g in got if isinstance(g, dict))
check("real engine: completed, link_done signal delivered before run_finished",
      final["status"] == "completed" and got[0] == ("link", 1, 1) and final["links"][0]["result"]["distance_km"] > 10)

# -- 8. exports open in QGIS ------------------------------------------------------------------------------
print("== export package ==")
export_dir = os.path.join(TMP, "exports")
os.makedirs(export_dir)
QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: export_dir)
dlg2._reload_history()
row = next(r for r in range(dlg2.history_table.rowCount()) if dlg2.history_table.item(r, 1).text() == "Weekly Toronto check")
dlg2.history_table.selectRow(row)
dlg2.export_selected_run()
pkg = os.path.join(export_dir, f"velorona-run-{run['run_id']}")
check("package folder written", os.path.isdir(pkg) and sorted(os.listdir(pkg)) ==
      ["input_links.csv", "links.geojson", "manifest.json", "report.md", "results.csv", "run.json"], str(os.listdir(pkg)))
layer = QgsVectorLayer(os.path.join(pkg, "links.geojson"), "links", "ogr")
check("links.geojson loads in QGIS as a valid line layer with one feature per analysed link",
      layer.isValid() and layer.featureCount() == 4 and layer.geometryType().name == "Line",
      f"valid={layer.isValid()} n={layer.featureCount()}")
first = next(layer.getFeatures())
check("GeoJSON feature carries run_id and link_id", first["run_id"] == run["run_id"] and first["link_id"] == "L1")
fields = [f.name() for f in layer.fields()]
check("GeoJSON attributes carry the full per-link result (the table a GIS user works from)",
      all(k in fields for k in ("clearance_ratio", "los_status", "near_threshold", "terrain_clearance_m", "warnings")), str(fields))
# results.csv is deliberately NOT claimed to load in GIS tools: like the plugin's Evidence CSV it begins with
# '#' preamble lines, which OGR reads as the header row. Spreadsheets and people are its audience.

# -- 9. compare through the UI ------------------------------------------------------------------------------
print("== comparison ==")
terrain.get_elevations = lambda pts, timeout=15.0: [100.0] * len(pts)
dlg2.workflow_combo.setCurrentIndex(dlg2.workflow_combo.findText("Weekly Toronto check"))
dlg2.start_run()
pump(until=lambda: not dlg2.running, timeout=20)
dlg2._reload_history()
rows = [r for r in range(dlg2.history_table.rowCount()) if dlg2.history_table.item(r, 1).text() == "Weekly Toronto check"]
check("two runs of the workflow now exist", len(rows) == 2, str(rows))
dlg2.history_table.clearSelection()
for r in rows:
    dlg2.history_table.selectRow(r) if r == rows[0] else dlg2.history_table.setRangeSelected(
        __import__("qgis.PyQt.QtWidgets", fromlist=["QTableWidgetSelectionRange"]).QTableWidgetSelectionRange(r, 0, r, 6), True)
dlg2.compare_selected_runs()
cmp = dlg2._compare_dialog.comparison
check("same workflow + file + params + stub terrain: comparable, nothing changed",
      cmp["comparable"] and cmp["summary"]["results_changed"] == 0 and cmp["summary"]["compared"] == 4, json.dumps(cmp["summary"]))

# -- 10. backup / restore through the dialog -------------------------------------------------------------
print("== backup / restore ==")
bak = os.path.join(TMP, "b.zip")
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (bak, ""))
dlg2.backup_history()
n_runs = len(dlg2.store.list_runs()[0])
check("backup zip written", os.path.exists(bak))
dlg3 = dialog_mod.AutomationDialog(None, store_root=os.path.join(TMP, "restored"))
QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (bak, ""))
dlg3.restore_history()
check("restore into an empty profile brings back every run",
      len(dlg3.store.list_runs()[0]) == n_runs and dlg3.history_table.rowCount() == n_runs, f"{n_runs} runs")

# -- 11. plugin dialog lifecycle -------------------------------------------------------------------------------
print("== plugin dialog lifecycle ==")
plugin = plugin_mod.VeloronaPlugin(iface)
plugin.initGui()
plugin.show_automation()
first_dialog = plugin.automation_dialog
plugin.show_automation()
check("show_automation reuses one dialog", first_dialog is plugin.automation_dialog and first_dialog.isVisible())
plugin.unload()
check("unload closes and releases the dialog", plugin.automation_dialog is None)

# -- 12. one store shared with the headless CLI ------------------------------------------------------------------------
print("== shared store with velorona-run ==")
from datetime import datetime, timezone  # noqa: E402
service = importlib.import_module("aei_workflow.service")
locking = importlib.import_module("aei_workflow.locking")
bounds_mod = importlib.import_module("aei_workflow.bounds")
check("plugin PARAM_SPEC is the shared bounds object (no second copy)", terrestrial.PARAM_SPEC is bounds_mod.TERRESTRIAL_PARAM_SPEC)
SHARED = os.path.join(TMP, "shared-store")
sstore = service.open_store(SHARED)
cli_wf = importlib.import_module("aei_workflow.workflow").new_workflow(
    "Nightly (CLI)", workflow_id="cli-nightly", input_path=os.path.join(TMP, "one.csv"),
    schedule={"kind": "daily", "at": "02:00", "grace_minutes": 30}, tz="America/Toronto", execution={"retry_delay_s": 0, "max_attempts": 1})
service.install_workflow(sstore, cli_wf)
t0 = datetime(2026, 9, 29, 12, tzinfo=timezone.utc)
service.tick(sstore, t0)
service.tick(sstore, datetime(2026, 10, 2, 15, tzinfo=timezone.utc))          # machine was off: 3 occurrences missed
dlg4 = dialog_mod.AutomationDialog(None, store_root=SHARED)
statuses = [dlg4.history_table.item(r, 2).text() for r in range(dlg4.history_table.rowCount())]
check("a history written by the CLI (3 missed occurrences) opens in the QGIS dialog", statuses == ["missed"] * 3, str(statuses))
check("the CLI's scheduled workflow is listed for QGIS", dlg4.workflow_combo.findText("Nightly (CLI)") > 0)

# a run left 'running' by the CLI, with a LIVE holder: opening QGIS must not relabel it
dead = json.loads(json.dumps(sstore.load_run(sstore.list_runs()[0][0]["run_id"])))
dead.update(run_id="live-elsewhere", status="running", finished_at=None)
sstore.save_run(dead)
with locking.WorkflowLock(SHARED, "cli-nightly"):
    dlg5 = dialog_mod.AutomationDialog(None, store_root=SHARED)
    check("QGIS leaves a run alone while another process holds the workflow lock", sstore.load_run("live-elsewhere")["status"] == "running")
    # ... and a QGIS run of the same workflow is refused instead of overlapping
    terrain.get_elevations = lambda pts, timeout=15.0: [100.0] * len(pts)
    clash = qtask.WorkflowTask(cli_wf, val, {"name": "one.csv", "sha256": "0" * 64}, sstore)
    res = []
    clash.run_finished.connect(res.append)
    QgsApplication.taskManager().addTask(clash)
    pump(until=lambda: bool(res) or clash.status() in (clash.TaskStatus.Complete, clash.TaskStatus.Terminated), timeout=15)
    pump(0.3)
    check("a QGIS run is refused while the CLI's lock is held, with a clear reason, and creates no run",
          clash.run_record is None and "already running" in (clash.error or "") and len(sstore.list_runs("cli-nightly")[0]) == 4, str(clash.error))
dlg6 = dialog_mod.AutomationDialog(None, store_root=SHARED)
check("once nothing holds the lock, opening QGIS recovers the dead run as interrupted", sstore.load_run("live-elsewhere")["status"] == "interrupted")

# -- optional live check -------------------------------------------------------------------------------------------
if os.environ.get("VELORONA_LIVE") == "1":
    print("== LIVE: Open-Meteo elevation ==")
    import importlib as _il
    _il.reload(terrain)
    live_val = inputs.validate_links_csv(open(write_csv("live.csv", GOOD.splitlines()[0]), encoding="utf-8").read())
    live = qtask.WorkflowTask(wf, live_val, {"name": "live.csv", "sha256": "0" * 64}, store_mod.RunStore(STORE))
    out = []
    live.run_finished.connect(out.append)
    QgsApplication.taskManager().addTask(live)
    pump(until=lambda: bool(out), timeout=60)
    check("live run finished with a definite status", out and out[0]["status"] in ("completed", "failed"),
          f"{out[0]['status']}: {out[0]['links'][0].get('error') or out[0]['links'][0]['result']['los_status']}")

failed = [r for r in RESULTS if not r[1]]
print(f"\n{len(RESULTS) - len(failed)} passed, {len(failed)} failed")
shutil.rmtree(TMP, ignore_errors=True)
qgs.exitQgis()
sys.exit(1 if failed else 0)
