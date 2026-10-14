"""Satellites layer data path, end to end in a REAL QGIS runtime (real QgsProject, QgsMapCanvas, QgsMessageBar, real plugin, real layer tree).

Run inside a QGIS 4.x Python (see tests/run_qgis_tests.sh or .github/workflows/qgis-runtime.yml). Input: ORBIT_CACHE_DIR, a directory holding an OrbitCache that a
previous step filled from the REAL source (tools/live_orbit_probe.py). This test never contacts the source: the plugin is pointed at that cache, and
`requests.get` is replaced by a function that fails the test if anything tries the network where no request is expected.

What is real: QGIS, the plugin, the layer, feature attributes, the message bar, the analysis engine, and the orbital records (from the real response).
What is NOT real: the failure/stale scenarios use a fake HTTP answer (clearly named below); the decayed record is synthetic; the OMM-only record is a REAL record
with its TLE fields cleared (the real GEO groups currently contain no catalog id above 99999)."""

import json
import math
import threading
import os
import shutil
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone

PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(PLUGIN_DIR))

from qgis.core import QgsApplication, QgsProject  # noqa: E402
from qgis.gui import QgsLayerTreeMapCanvasBridge, QgsMapCanvas, QgsMessageBar  # noqa: E402
from qgis.PyQt.QtWidgets import QApplication, QMainWindow  # noqa: E402

qgs = QgsApplication([], True)
qgs.initQgis()
RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    return ok


class FakeIface:
    def __init__(self):
        self.window = QMainWindow()
        self.canvas = QgsMapCanvas()
        self.window.setCentralWidget(self.canvas)
        self.canvas.resize(1000, 700)
        self._bar = QgsMessageBar(self.window)
        self.docks = []

    def mapCanvas(self): return self.canvas
    def mainWindow(self): return self.window
    def messageBar(self): return self._bar
    def addToolBarIcon(self, a): pass
    def addPluginToMenu(self, m, a): pass
    def removePluginMenu(self, m, a): pass
    def removeToolBarIcon(self, a): pass
    def setActiveLayer(self, layer): self.active_layer = layer
    def activeLayer(self): return getattr(self, "active_layer", None)
    def addDockWidget(self, area, dock): self.docks.append(dock); self.window.addDockWidget(area, dock)
    def removeDockWidget(self, dock): self.window.removeDockWidget(dock)


iface = FakeIface()
iface.window.show()
project = QgsProject.instance()
bridge = QgsLayerTreeMapCanvasBridge(project.layerTreeRoot(), iface.canvas)

import requests  # noqa: E402
from velorona.core import layers as layer_helpers  # noqa: E402
from velorona.core.engines import satellite_earth_space  # noqa: E402
from velorona.core.sources import orbit_data, satellite_feed  # noqa: E402
import velorona.plugin as plugin_module  # noqa: E402
from velorona.plugin import VeloronaPlugin  # noqa: E402

REAL_CACHE = os.environ["ORBIT_CACHE_DIR"]
real_get = requests.get
net_calls = []


def _is_source(u):
    return "celestrak.org" in str(u)


def forbid_network(*a, **k):
    """Requests to the orbital source fail the test; other services (the plugin's other layers) are left alone."""
    u = a[0] if a else k.get("url")
    if not _is_source(u):
        return real_get(*a, **k)
    net_calls.append(u)
    raise AssertionError("unexpected request to the orbital source")


class FakeResp:
    def __init__(self, status, text="", headers=None):
        self.status_code, self.text, self.headers = status, text, headers or {}


plugin = VeloronaPlugin(iface)
warnings = []
plugin._warn = lambda m: warnings.append(m)
plugin._error = lambda m: warnings.append("ERROR: " + m)
active_cache = {"dir": REAL_CACHE}
plugin._orbit_cache = lambda: orbit_data.OrbitCache(active_cache["dir"])
pushes = []
_real_push = iface.messageBar().pushMessage
iface.messageBar().pushMessage = lambda *a, **k: (pushes.append(a), _real_push(*a, **k))[1]

print("\n== 1. real plugin, real layers ==")
plugin.initGui()
plugin.action_load_public.trigger()
for _ in range(30):
    qgs.processEvents()
sat_layer = layer_helpers.find_owned_layer(project, layer_helpers.SOURCE_SATELLITES)
gs_layer = layer_helpers.find_owned_layer(project, layer_helpers.SOURCE_GROUND_STATIONS)
node = project.layerTreeRoot().findLayer(sat_layer.id())
check("Satellites layer exists, is empty and hidden after load (nothing fetched while hidden)", sat_layer is not None and sat_layer.featureCount() == 0 and not node.isVisible())
names = [f.name() for f in sat_layer.fields()]
check("layer has the provenance and OMM fields", all(n in names for n in ("retrieved_at", "data_status", "omm_json", "tle_epoch", "norad_cat_id")), str(names))


def wait_task(timeout=90):
    """The load runs in a QgsTask worker thread; its result is applied in the GUI thread when the event loop runs."""
    t0 = time.monotonic()
    while plugin._satellites_task is not None and time.monotonic() - t0 < timeout:
        qgs.processEvents()
        time.sleep(0.02)
    qgs.processEvents()
    return plugin._satellites_task is None


worker_on_gui_thread = []
_orig_load = satellite_feed.load_groups


def _spy_load(*a, **k):
    worker_on_gui_thread.append(threading.current_thread() is threading.main_thread())
    return _orig_load(*a, **k)


satellite_feed.load_groups = _spy_load


def toggle_on():
    plugin._satellites_fetched_at = None
    node.setItemVisibilityChecked(False); qgs.processEvents(); wait_task()
    pushes.clear(); warnings.clear()
    node.setItemVisibilityChecked(True); qgs.processEvents()
    return wait_task()


print("\n== 2. REAL cached records -> layer (no network allowed) ==")
requests.get = forbid_network
toggle_on()
n = sat_layer.featureCount()
check("real records populate the layer without any request (cache hit)", n > 100 and not net_calls, f"{n} features, {len(net_calls)} requests")
feats = list(sat_layer.getFeatures())
f0 = feats[0]
ids = [str(f["norad_cat_id"]) for f in feats]
check("the load ran in a worker thread, not the GUI thread", worker_on_gui_thread and not any(worker_on_gui_thread), str(worker_on_gui_thread))
check("catalog ids are kept as full text and are unique", len(ids) == len(set(ids)) and all(i.isdigit() for i in ids), ids[:3])
check("every feature carries retrieval time, status and the OMM record", all(f["retrieved_at"] and f["data_status"] == "fresh" and json.loads(f["omm_json"])["NORAD_CAT_ID"] for f in feats))
check("positions are finite and on Earth", all(abs(f.geometry().asPoint().y()) <= 90 and abs(f.geometry().asPoint().x()) <= 180 for f in feats))
check("source text carries the group and retrieval time", "retrieved" in f0["source"] and f0["retrieved_at"][:10] in f0["source"], f0["source"])
check("a fresh load raises no stale/unavailable message", not [m for m in warnings if "stale" in m.lower() or "unavailable" in m.lower() or "older" in m.lower()], str(warnings))
check("element-set epoch is an ISO UTC time and older than the retrieval time", f0["tle_epoch"].endswith("Z") and f0["tle_epoch"] <= f0["retrieved_at"], f"{f0['tle_epoch']} / {f0['retrieved_at']}")

print("\n== 3. toggling again does not ask the source ==")
for _ in range(3):
    toggle_on()
check("three more off/on toggles made no request", not net_calls and sat_layer.featureCount() == n, f"{len(net_calls)} requests")

print("\n== 4. real analysis engine on a real satellite ==")
# the layer was repopulated by the toggles above, so feature ids changed: take the CURRENT first feature
f0 = next(sat_layer.getFeatures())
gs = next(gs_layer.getFeatures())
results = []
plugin._show_result = lambda r: results.append(r)
gs_layer.selectByIds([gs.id()]); sat_layer.selectByIds([f0.id()])
plugin.run_satellite()
r = results[-1] if results else None
check("run_satellite produced a result for a real satellite", r is not None and math.isfinite(r.elevation_deg) and math.isfinite(r.slant_range_km), str(r))
check("result names the satellite and its element-set epoch", r is not None and r.satellite_name == f0["name"] and r.tle_epoch == f0["tle_epoch"])
elev_tle = r.elevation_deg if r else None

print("\n== 5. OMM-only: a REAL record with its TLE fields cleared (as an id above 99999 would be) ==")
sat_layer.dataProvider().changeAttributeValues({f0.id(): {sat_layer.fields().indexOf("tle_line1"): None, sat_layer.fields().indexOf("tle_line2"): None}})
sat_layer.updateFields(); qgs.processEvents()
f0b = sat_layer.getFeature(f0.id())
check("the feature has no TLE lines but still has its OMM record", not f0b["tle_line1"] and not f0b["tle_line2"] and f0b["omm_json"])
sat_layer.removeSelection(); sat_layer.selectByIds([f0.id()])
plugin.run_satellite()
r2 = results[-1]
check("the analysis engine runs on the OMM record alone", r2 is not results[0] and math.isfinite(r2.elevation_deg))
check("OMM-only and TLE results agree (elevation within 0.05 deg)", abs(r2.elevation_deg - elev_tle) < 0.05, f"{elev_tle:.4f} vs {r2.elevation_deg:.4f}")

print("\n== 6. a decayed / invalid element set is refused (SYNTHETIC record) ==")
ep = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000000")
bad = {"OBJECT_NAME": "SYNTH-DECAY", "OBJECT_ID": "2026-001A", "EPOCH": ep, "MEAN_MOTION": 16.0, "ECCENTRICITY": 0.5, "INCLINATION": 0.05, "RA_OF_ASC_NODE": 80.0,
       "ARG_OF_PERICENTER": 100.0, "MEAN_ANOMALY": 20.0, "EPHEMERIS_TYPE": 0, "CLASSIFICATION_TYPE": "U", "NORAD_CAT_ID": 90009, "ELEMENT_SET_NO": 999, "REV_AT_EPOCH": 1, "BSTAR": 0.0,
       "MEAN_MOTION_DOT": 0.0, "MEAN_MOTION_DDOT": 0.0}
f_bad = sat_layer.getFeature(f0.id())
sat_layer.dataProvider().changeAttributeValues({f0.id(): {sat_layer.fields().indexOf("omm_json"): json.dumps(bad)}})
sat_layer.updateFields(); qgs.processEvents()
sat_layer.removeSelection(); sat_layer.selectByIds([f0.id()])     # selecting also shows the plugin's own selection result; count after that
warnings.clear()
before = len(results)
plugin.run_satellite()
check("the engine refuses it with an explanation and returns no result", len(results) == before and any("cannot be propagated" in w or "below the Earth" in w for w in warnings), str(warnings))

print("\n== 7. source refuses (HTTP 429, FAKE answer): empty layer, one request, back-off persisted ==")
tmp = tempfile.mkdtemp()
active_cache["dir"] = tmp
calls = []


def fake_429(url, **k):
    if not _is_source(url):
        return real_get(url, **k)
    calls.append(url)
    return FakeResp(429, "", {"Retry-After": "3600"})


requests.get = fake_429
toggle_on()
check("unavailable: layer is empty, nothing substituted", sat_layer.featureCount() == 0)
check("exactly one request was made (no further group after the failure)", len(calls) == 1, f"{len(calls)}")
check("the user is told, in the message bar, that satellite data is unavailable", any("unavailable" in str(p).lower() for p in pushes), str(pushes))
for _ in range(3):
    toggle_on()
check("three more toggles make no further request (back-off)", len(calls) == 1, f"{len(calls)}")
files = sorted(os.listdir(tmp))
check("the back-off is on disk (survives a restart)", any(json.load(open(os.path.join(tmp, f))).get("not_before") for f in files if f.startswith("orbit_")), str(files))

print("\n== 7b. a SLOW source (FAKE 3 s answer) does not block the GUI ==")
tmp3 = tempfile.mkdtemp()
active_cache["dir"] = tmp3
slow_calls = []


def slow_source(url, **k):
    if not _is_source(url):
        return real_get(url, **k)
    slow_calls.append(url)
    time.sleep(3)
    return FakeResp(503)


requests.get = slow_source
plugin._satellites_fetched_at = None
node.setItemVisibilityChecked(False); qgs.processEvents(); wait_task()
t0 = time.monotonic()
node.setItemVisibilityChecked(True); qgs.processEvents()
dt = time.monotonic() - t0
running = plugin._satellites_task is not None
ticks = 0
t1 = time.monotonic()
while plugin._satellites_task is not None and time.monotonic() - t1 < 30:
    qgs.processEvents(); ticks += 1; time.sleep(0.01)
check("the toggle returned immediately and the task was running", dt < 1.0 and running, f"{dt:.2f}s, running={running}")
check("the event loop kept turning during the 3 s request (GUI responsive)", ticks > 50, f"{ticks} iterations")
check("the slow failure ended as unavailable with one request", sat_layer.featureCount() == 0 and len(slow_calls) == 1, f"{len(slow_calls)}")

print("\n== 8. stale cache + source down (FAKE answer): stale rows, labelled ==")
tmp2 = tempfile.mkdtemp()
for fn in os.listdir(REAL_CACHE):
    shutil.copy(os.path.join(REAL_CACHE, fn), tmp2)
c2 = orbit_data.OrbitCache(tmp2)
old = orbit_data.iso_ms(datetime.now(timezone.utc) - timedelta(hours=5))
for g in satellite_feed.GEO_GROUPS:
    e = c2.read(g)
    if e:
        e["retrieved_at_utc"] = old; e["not_before"] = None; c2.write(g, e)
active_cache["dir"] = tmp2
calls.clear()
requests.get = lambda url, **k: (calls.append(url), FakeResp(503))[1] if _is_source(url) else real_get(url, **k)
toggle_on()
fs = list(sat_layer.getFeatures())
check("old cache is shown but every row is flagged stale", len(fs) > 100 and all(x["data_status"] == "stale" for x in fs), f"{len(fs)} rows")
check("the retrieval time shown is the OLD one, not now", all(x["retrieved_at"] == old for x in fs))
check("one request only; the message bar says the data is older", len(calls) == 1 and any("older" in str(p).lower() or "stale" in str(p).lower() for p in pushes), f"{len(calls)} / {pushes}")

requests.get = real_get
# orderly teardown (a worker thread or a plugin timer alive at exitQgis() crashed the interpreter on exit): cancel tasks, unload the plugin, then exit
QgsApplication.taskManager().cancelAll()
wait_task(10)
plugin.unload()
qgs.processEvents()
passed = sum(1 for _, ok, _ in RESULTS if ok)
print(f"\n===== {passed}/{len(RESULTS)} checks passed =====")
for name, ok, detail in RESULTS:
    if not ok:
        print(f"  FAILED: {name} -- {detail}")
qgs.exitQgis()
sys.exit(0 if passed == len(RESULTS) else 1)
