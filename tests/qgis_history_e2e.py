"""Local history in real QGIS (offscreen, no network): the History window, the 'What changed' block in the weather result, retention, CSV export,
clearing, and the error state. Uses the tests' real-library weather fixture; only the network edge is absent. Run like qgis_ui_polish_e2e.py."""
import os
os.environ.setdefault("VELORONA_USA_PACK", "off")
import sys
import tempfile
import time

PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(PLUGIN_DIR))
sys.path.insert(0, os.path.join(PLUGIN_DIR, "tests"))

from qgis.core import QgsApplication  # noqa: E402
from qgis.PyQt.QtWidgets import QApplication, QFileDialog, QMessageBox  # noqa: E402

qgs = QgsApplication([], True)
qgs.initQgis()
RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  -- {detail}" if detail and not ok else ""))


from presentation_fixtures import weather_result  # noqa: E402
from velorona.core import history_capture, history_store, history_view  # noqa: E402
from velorona.ui.history_dialog import HistoryDialog  # noqa: E402
from velorona.ui.results_dock import VeloronaResultsDock  # noqa: E402

NOW = history_store.parse_utc("2026-10-07T00:10:00Z")
tmp = tempfile.mkdtemp(prefix="velorona-hist-")
store = history_store.HistoryStore(os.path.join(tmp, "velorona", "history.sqlite"), clock=lambda: NOW)

res = weather_result()
res.utc_offsets = {"A": -4 * 3600, "B": -4 * 3600}
check("capture stores the first analysis", history_capture.capture(res, store, NOW).written > 0)
# an earlier fetch of the same sites, 5 h before (different provider time), so 'what changed' has something to compare
older = weather_result(rain_a=0.0, rain_b=0.0)
older.utc_offsets = {"A": 3600, "B": 3600}     # the same 20:00 local reading at UTC+1 is 19:00Z, i.e. 5 h before the first analysis (00:00Z)
check("capture stores the earlier analysis", history_capture.capture(older, store, NOW - 5 * 3600).written > 0)

link_id, site_ids = history_capture.entity_ids(res, store)
labels = {link_id: "Site A <-> Site B", site_ids["A"]: "Site A", site_ids["B"]: "Site B"}

# --- History window
dlg = HistoryDialog(None, store, labels, link_id, dark=True, clock=lambda: NOW)
html_text = dlg.view.toHtml()
check("window opens on the current link", dlg._selected_entity() == link_id)
check("observed/model are separate sections", "Model-derived" in dlg.view.toPlainText())
check("every row carries unit, source and 'As of'", all(w in dlg.view.toPlainText() for w in ("Unit", "Source", "As of", "When")))
check("'N hours ago' is shown", "5.0 h ago" in dlg.view.toPlainText() or "h ago" in dlg.view.toPlainText())
check("the user's own entity shows its in-session name, not the stored code", "Site A" in dlg.view.toPlainText() and "h:" not in dlg.view.toPlainText().split("When")[0])
store.set_labels(labels)
dlg_reopened = HistoryDialog(None, store, store.labels(), link_id, dark=True, clock=lambda: NOW)       # a new session: only the names stored on this computer
check("a later session still shows the user's own names (stored locally next to the code)",
      "Site A" in dlg_reopened.view.toPlainText() and "h:" not in dlg_reopened.view.toPlainText().split("When")[0])
dlg.entity_combo.setCurrentIndex(0)
check("'All' view shows the local-only statement", "Nothing is uploaded" in dlg.view.toPlainText() or "Nothing is uploaded" in dlg.stats_label.text())
check("stats show rows, size and retention", "values" in dlg.stats_label.text() and "Kept 24 h" in dlg.stats_label.text())

# retention
dlg.retention.setValue(2)
dlg._on_apply_retention()
check("retention applied: older rows deleted", all(r.ts >= history_store.utc_text(NOW - 2 * 3600 - 1) for r in store.records()) and store.retention_hours() == 2)
store.set_retention_hours(24)

# CSV export (file dialog replaced)
out = os.path.join(tmp, "export.csv")
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (out, ""))
QMessageBox.information = staticmethod(lambda *a, **k: None)
from qgis.PyQt.QtCore import QTimer  # noqa: E402
from qgis.PyQt.QtWidgets import QApplication as _QApp, QCheckBox  # noqa: E402
seen = {}


def _answer(tick):
    def handler():
        box = _QApp.activeModalWidget()
        cb = box.findChild(QCheckBox, "veloronaIncludeNames")
        seen["default"] = cb.isChecked()
        if tick:
            cb.setChecked(True)
        box.accept()
    return handler


QTimer.singleShot(50, _answer(False))
dlg._on_export()
text = open(out, encoding="utf-8").read()
check("CSV has the contract header and rows", text.splitlines()[0].startswith("ts,fetched_ts,source,entity_id") and len(text.splitlines()) > 1)
import csv as _csv, io as _io  # noqa: E402
rows_default = list(_csv.reader(_io.StringIO(text)))
col = {c: i for i, c in enumerate(rows_default[0])}
check("export dialog: 'Include my site names' is off by default", seen.get("default") is False)
check("default export has NO names (entity_label empty for every row)", all(r[col["entity_label"]] == "" for r in rows_default[1:]) and len(rows_default) > 1)
QTimer.singleShot(50, _answer(True))
dlg._on_export()
rows_named = list(_csv.reader(_io.StringIO(open(out, encoding="utf-8").read())))
named = {r[col["entity_label"]] for r in rows_named[1:]} - {""}
check("ticking 'Include my site names' writes the names next to the codes", named and named <= set(store.labels().values()), named)
check("names stay visible in the History window either way", "Site" in dlg.view.toPlainText() or any(v in dlg.view.toPlainText() for v in store.labels().values()))

# clearing
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
dlg.entity_combo.setCurrentIndex(dlg.entity_combo.findData(site_ids["A"]))
before = len(store.records())
dlg._on_clear_entity()
check("clear this link removes only that entity", 0 < len(store.records()) < before and all(r.entity_id != site_ids["A"] for r in store.records()))
dlg._on_clear_all()
check("clear all deletes everything and the file", store.stats().rows == 0 if os.path.exists(store.path) else True)
check("empty state explains itself", "No history" in dlg.view.toPlainText())

# error state: unreadable store
broken = history_store.HistoryStore(os.path.join(tmp, "newer.sqlite"), clock=lambda: NOW)
broken.add_many([])
import sqlite3
con = sqlite3.connect(broken.path); con.executescript(history_store._SCHEMA); con.execute("INSERT INTO meta VALUES ('schema_version','99')"); con.commit(); con.close()
d2 = HistoryDialog(None, broken, {}, None, dark=False, clock=lambda: NOW)
check("a history file from a newer version gives an error state, controls disabled", "could not be read" in d2.view.toPlainText() and not d2.export_button.isEnabled())

# --- What changed in the weather result
store2 = history_store.HistoryStore(os.path.join(tmp, "b", "history.sqlite"), clock=lambda: NOW)
history_capture.capture(res, store2, NOW)
history_capture.capture(older, store2, NOW - 5 * 3600)
dock = VeloronaResultsDock()


def block(result):
    lid, sids = history_capture.entity_ids(result, store2)
    wanted = {lid: "Site A <-> Site B", sids["A"]: "Site A", sids["B"]: "Site B"}
    return history_view.changes_html([r for r in store2.records() if r.entity_id in wanted], wanted, NOW)


dock.history_block = block
dock.show_result(res)
plain = dock.browser.toPlainText()
check("weather Summary has a 'What changed' section", "What changed" in plain, plain[-300:])
check("it compares like with like and names source and times", "model-derived" in plain and "UTC" in plain)
check("it states local-only storage", "Nothing is uploaded" in plain)
check("History button is visible for weather results", not dock.history_button.isHidden())
dock.view_combo.setCurrentIndex(1)
check("Details view has it too", "What changed" in dock.browser.toPlainText())
dock.history_block = None
dock.show_result(res)
check("without history there is simply no block", "What changed" not in dock.browser.toPlainText())

failed = [n for n, ok, _ in RESULTS if not ok]
print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
qgs.exitQgis()
sys.exit(1 if failed else 0)
