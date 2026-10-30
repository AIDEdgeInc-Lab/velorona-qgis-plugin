"""Link-selection weather runs in the background (real QGIS, offscreen, no network): the record is shown at once with a 'Loading weather' note, the
request runs off the interface thread, one at a time, the newest selection wins, a finished request refreshes the panel only if that link is still
the selected one, and failures are stated (and a deterministic input problem is never remembered as an outage). The weather engine is a double that
lives in this file only. Run like qgis_selection_sync_e2e.py."""
import os
os.environ.setdefault("VELORONA_USA_PACK", "off")       # USA data is on by default (online); these suites are offline and about other things
import sys

PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(PLUGIN_DIR))

from qgis.core import (QgsApplication, QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsFeature, QgsGeometry,  # noqa: E402
                       QgsPointXY, QgsProject, QgsRectangle)
from qgis.gui import QgsLayerTreeMapCanvasBridge, QgsMapCanvas, QgsMessageBar  # noqa: E402
from qgis.PyQt.QtCore import QMetaType, QObject, Qt, pyqtSignal  # noqa: E402
from qgis.PyQt.QtWidgets import QApplication, QMainWindow  # noqa: E402

qgs = QgsApplication([], True)
qgs.initQgis()
RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  -- {detail}" if detail and not ok else ""))


class FakeIface(QObject):
    currentLayerChanged = pyqtSignal(object)      # QGIS emits this when the Layers panel's current layer changes

    def __init__(self):
        super().__init__()
        self.window = QMainWindow()
        self.window.resize(1500, 900)
        self.canvas = QgsMapCanvas()
        self.window.setCentralWidget(self.canvas)
        self.canvas.resize(900, 700)
        self._bar = QgsMessageBar(self.window)
        self.pushed = []
        _push = self._bar.pushMessage
        self._bar.pushMessage = lambda *a, **k: (self.pushed.append(a), _push(*a, **k))

    def mapCanvas(self): return self.canvas
    def mainWindow(self): return self.window
    def messageBar(self): return self._bar
    def addToolBarIcon(self, a): pass
    def addPluginToMenu(self, m, a): pass
    def removePluginMenu(self, m, a): pass
    def removeToolBarIcon(self, a): pass
    def setActiveLayer(self, layer):
        self.active = layer
        self.currentLayerChanged.emit(layer)
    def activeLayer(self): return getattr(self, "active", None)
    def addDockWidget(self, area, dock): self.window.addDockWidget(area, dock)
    def removeDockWidget(self, dock): self.window.removeDockWidget(dock)


iface = FakeIface()
iface.window.show()
project = QgsProject.instance()
bridge = QgsLayerTreeMapCanvasBridge(project.layerTreeRoot(), iface.canvas)

from velorona.core import layers as L  # noqa: E402
from velorona.core.sources import orbit_data, satellite_feed, space_public, terrestrial_public  # noqa: E402
import velorona.plugin as PM  # noqa: E402

plugin = PM.VeloronaPlugin(iface)
warnings = []
plugin._warn = lambda m: warnings.append(m)
plugin._error = lambda m: warnings.append("ERROR: " + m)
plugin._basemap_renderer = lambda dark: None            # offline: no basemap fetch
# Live providers are doubles in this file. Default: the service is DOWN.
state = {"mode": "down", "calls": 0}


def fake_towers(bbox):
    state["calls"] += 1
    if state["mode"] == "down":
        raise RuntimeError("HTTP 503 from the (simulated) service")
    lon = (bbox[0] + bbox[2]) / 2
    lat = (bbox[1] + bbox[3]) / 2
    recs = [{"id": "t1", "latitude": lat, "longitude": lon, "name": "real-looking tower", "source": "x", "coverage": "Ontario"},
            {"id": "t2", "latitude": 999.0, "longitude": lon, "name": "invalid latitude", "source": "x", "coverage": "Ontario"},
            {"id": "t3", "latitude": float("nan"), "longitude": lon, "name": "NaN latitude", "source": "x", "coverage": "Ontario"},
            {"id": "t4", "latitude": None, "longitude": None, "name": "no coordinates", "source": "x", "coverage": "Ontario"}]
    if state["mode"] == "empty":
        return [], False
    return recs, state["mode"] == "truncated"


terrestrial_public.fetch_geohub_towers = fake_towers
terrestrial_public.fetch_ised_cellular = lambda bbox: ([], False)


import threading  # noqa: E402
import time  # noqa: E402

sys.path.insert(0, os.path.join(PLUGIN_DIR, "tests"))
from presentation_fixtures import weather_result  # noqa: E402
from velorona.core import validation  # noqa: E402

plugin.initGui()
plugin.action_load_public.trigger()
for _ in range(20):
    qgs.processEvents()
links = L.find_owned_layer(project, L.SOURCE_FIXED_LINKS)
me = PM.microwave_exposure


def ghz(fid):
    g, _ = me.frequency_ghz_from_record(links.getFeature(fid)["frequencies_mhz"])
    return g


usable = [f for f in sorted(links.allFeatureIds()) if ghz(f) and 1.0 <= ghz(f) <= 100.0][:4]
check("the sample links include four with a frequency inside the rain model's range", len(usable) == 4, str(len(usable)))
A, B, C, D = usable

calls, gates, lock = [], {}, threading.Lock()
state = {"running": 0, "max": 0, "mode": "ok"}


def fake_analyze(site_a, site_b, data, params, **kw):
    key = data.get("authorization_number") or data.get("id")
    with lock:
        calls.append((key, threading.current_thread() is threading.main_thread()))
        state["running"] += 1
        state["max"] = max(state["max"], state["running"])
        gate = gates.setdefault(key, threading.Event())
    try:
        if not gate.wait(20):
            raise RuntimeError("test gate never released")
        if state["mode"] == "down":
            raise RuntimeError("HTTP 503 from the (simulated) weather service")
        if state["mode"] == "range":
            raise validation.NoDataError("weather", ["frequency is outside the rain model's 1-100 GHz range"], transient=False)
        return weather_result()
    finally:
        with lock:
            state["running"] -= 1


me.analyze_link_record = fake_analyze


def key_of(fid):
    f = links.getFeature(fid)
    return f["authorization_number"] if "authorization_number" in links.fields().names() and f["authorization_number"] else f["id"]


def release(fid):
    gates.setdefault(str(key_of(fid)), threading.Event()).set()


def settle(limit=30.0):
    end = time.time() + limit
    while time.time() < end and (plugin._link_weather_task is not None or plugin._link_weather_wanted is not None):
        qgs.processEvents()
        time.sleep(0.02)
    qgs.processEvents()


def select(fid):
    links.removeSelection()
    qgs.processEvents()
    links.selectByIds([fid])
    qgs.processEvents()
    return plugin.dock._result


print("== 1. the record is shown at once; the weather arrives later ==")
t0 = time.time()
inv = select(A)
check("the selection returned while the weather request was still blocked (not on the interface thread)", time.time() - t0 < 10 and state["running"] <= 1)
check("the panel is a link investigation marked as loading", getattr(inv, "kind", "") == "link-investigation" and inv.weather_pending and inv.exposure is None)
text = plugin.dock.browser.toPlainText()
check("the panel says the weather is loading, not that it failed", "Fetching weather at both endpoints" in text and "could not be retrieved" not in text)
for _ in range(10):
    qgs.processEvents()
check("the request ran in a worker thread", bool(calls) and calls[0][1] is False, str(calls))
release(A)
settle()
check("when it finished the same panel got the weather", plugin.dock._result is inv and inv.exposure is not None and not inv.weather_pending)
check("... and no longer says fetching", "Fetching weather" not in plugin.dock.browser.toPlainText())
n = len(calls)
inv2 = select(A)
check("selecting the link again is answered from the cache without a new request", inv2.exposure is not None and len(calls) == n)

print("== 2. one request at a time; the newest selection wins; a stale result is cached but not shown ==")
calls.clear(); state["max"] = 0
invB = select(B)
spin_until = time.time() + 5
while time.time() < spin_until and not calls:
    qgs.processEvents(); time.sleep(0.02)
invC = select(C)
invD = select(D)
check("later selections wait; only one request is in flight", state["max"] == 1 and len(calls) == 1, str((state, calls)))
release(B)
settle(1.0)
check("B's result did not replace the panel of the link now selected", plugin.dock._result is invD)
check("... but B was cached for next time", select(B).exposure is not None)
invD = select(D)
release(D)
settle()
check("the newest selection (D) was fetched and shown; the skipped middle one (C) was never requested", invD.exposure is not None
      and all(c[0] != key_of(C) for c in calls) and len(calls) <= 3, str(calls))

print("== 3. failures are stated ==")
state["mode"] = "down"
# links not yet asked about (A-D are cached from the sections above)
links_extra = [f for f in sorted(links.allFeatureIds()) if ghz(f) and 1.0 <= ghz(f) <= 100.0][4:8]
E, F = links_extra[0], links_extra[1]
invE = select(E); release(E); settle()
check("a provider outage is stated in the panel with its reason", invE.exposure is None and "503" in (invE.weather_error or "") and not invE.weather_pending
      and "503" in plugin.dock.browser.toPlainText())
nE = len(calls)
select(E); settle()
check("the outage is remembered briefly (not retried at once)", len(calls) == nE)
state["mode"] = "range"
invF = select(F); release(F); settle()
check("a deterministic input problem is stated with its reason", invF.exposure is None and "1-100 GHz" in (invF.weather_error or ""))
nF = len(calls); gates.clear()
invF2 = select(F); release(F); settle()
check("... and is not remembered as an outage (asked again, same reason)", len(calls) == nF + 1 and "moment ago" not in (invF2.weather_error or ""))

print("== 4. nothing left behind ==")
check("no task is left running", plugin._link_weather_task is None and plugin._link_weather_wanted is None)
plugin.unload()
check("unloading leaves nothing queued", plugin._link_weather_wanted is None)

failed = [r for r in RESULTS if not r[1]]
print(f"\n===== {len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed =====")
for name, _ok, detail in failed:
    print("FAILED:", name, detail)
os._exit(1 if failed else 0)
