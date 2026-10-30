"""Automatic recording (real QGIS, offscreen, no network): off by default; on/off and links in the History window; rounds run in a QgsTask,
one link at a time, values captured with the real fetch time; a 429 stops the round and backs off; three busy rounds pause; the free-plan
limit holds; the user's own names are stored only when ticked; unloading stops everything. The weather engine is a double in this file.

(The original description of the suite this one was copied from follows.) Link-selection weather runs in the background (real QGIS, offscreen, no network): the record is shown at once with a 'Loading weather' note, the
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

import tempfile  # noqa: E402
from velorona.core import auto_record, history_store, history_capture  # noqa: E402
from velorona.ui.history_dialog import HistoryDialog  # noqa: E402

tmp = tempfile.mkdtemp()
store = history_store.HistoryStore(os.path.join(tmp, "history.sqlite"))
plugin._history_store = lambda: store
calls, mode = [], {"m": "ok"}


import presentation_fixtures as _F  # noqa: E402
_orig_obs = _F.obs
_tick = {"n": 0}


def _fresh_ts():
    # each fetch is one minute after the previous one (inside the last 10 min), as consecutive model updates would be
    _tick["n"] += 1
    return time.strftime("%Y-%m-%dT%H:%M", time.gmtime(time.time() - 600 + 60 * _tick["n"]))


_F.obs = lambda site, rain, temp=10.0, wind=10.0, ts=None: _orig_obs(site, rain, temp, wind, ts or _fresh_ts())


def stamped(r):
    r.utc_offsets = {sid: 0 for sid in r.representativeness}      # the provider's UTC offset, needed to store a value with a UTC time
    return r


def own_result(name_a="Own A", lat_shift=0.0):
    from aei_mw_exposure import MicrowaveLink, MicrowaveSite, Provenance, calculate_exposure
    from aei_mw_exposure.representativeness import assess_representativeness
    import presentation_fixtures as F
    sa = MicrowaveSite(id="own-1", name=name_a, latitude=F.A[0] + lat_shift, longitude=F.A[1], provenance=Provenance.USER_PROVIDED, source="test")
    sb = MicrowaveSite(id="own-2", name="Own B", latitude=F.B[0], longitude=F.B[1], provenance=Provenance.USER_PROVIDED, source="test")
    link = MicrowaveLink(id="my-link", site_a=sa, site_b=sb, frequency_ghz=18.0, polarization="V", fade_margin_db=32.0,
                         provenance=Provenance.USER_PROVIDED, source="test")
    by_site = {"own-1": F.obs(sa, 2.4), "own-2": F.obs(sb, 0.5)}
    reps = {s.id: assess_representativeness(site=s, nearest_station=None, station_distance_km=None, station_reports_precipitation=True,
                                            model_observation=by_site[s.id]) for s in (sa, sb)}
    from types import SimpleNamespace
    return stamped(SimpleNamespace(kind="microwave-exposure", exposure=calculate_exposure(link, by_site), representativeness=reps,
                                   weather_errors={}, history={}, precipitation={}))


def fake_record(site_a, site_b, data, params, **kw):
    calls.append((data.get("authorization_number") or data.get("id"), threading.current_thread() is threading.main_thread(), kw.get("history_fetcher")))
    if mode["m"] == "busy":
        raise validation.NoDataError("weather", ["Could not fetch live weather (Open-Meteo) for: A (the service is rate-limiting requests (HTTP 429); try again in a minute.)"], transient=True)
    return stamped(weather_result())


def fake_sites(site_a, site_b, params, **kw):
    calls.append(("own", threading.current_thread() is threading.main_thread(), kw.get("history_fetcher")))
    return own_result(site_a.name)


def settle(limit=20.0):
    end = time.time() + limit
    while time.time() < end and (plugin._link_weather_task is not None or plugin._record_task is not None):
        qgs.processEvents()
        time.sleep(0.02)
    qgs.processEvents()


def select(fid):
    links.removeSelection(); qgs.processEvents()
    links.selectByIds([fid]); qgs.processEvents()
    settle()
    return plugin.dock._result


me.analyze_link_record = fake_record
print("== 1. off by default ==")
check("recording is off at start, nothing is due", not plugin.recorder.enabled and not plugin.recorder.due(time.time() + 10 ** 6))
check("the free-plan limit comes from the plan file (or the built-in free limits)", plugin.recorder.max_links == 10)
inv = select(A)
check("the selected link has weather (precondition)", getattr(inv, "exposure", None) is not None)
n_calls = len(calls)
plugin._record_tick()
check("ticking while off fetches nothing", len(calls) == n_calls and plugin._record_task is None)

print("== 2. the History window: add the shown link, switch on, a round runs in the background ==")
dlg = HistoryDialog(None, store, {}, None, recording=plugin)
plugin._recording_panel = panel = dlg.recording_panel
check("History has an 'Automatic recording' box, unticked", panel is not None and not panel.enabled_box.isChecked() and "I-RECORD-OFF" in panel.status.text())
panel.add_button.click()
check("the link in the results panel is added", len(plugin.recorder.links) == 1 and panel.links.count() == 1)
panel.enabled_box.setChecked(True)
check("switched on: status says how many links and how often (the Map's I-RECORD-ON)", plugin.recorder.enabled and "Recording on: 1 links every 15 min." in panel.status.text() and "I-RECORD-ON" in panel.status.text(), panel.status.text())
before = store.stats().rows if os.path.exists(store.path) else 0
calls.clear()
plugin._record_tick()
settle()
check("a round ran off the interface thread, without the hourly history request", calls and not calls[0][1] and calls[0][2] is not None)
check("the values were stored", store.stats().rows > before, f"{before} -> {store.stats().rows}; {[x.last_error for x in plugin.recorder.links.values()]}")
newest = max(store.records(), key=lambda r: r.fetched_ts or "")
check("the real fetch time is stored with the values", newest.fetched_ts and abs(history_store.parse_utc(newest.fetched_ts) - time.time()) < 120, newest.fetched_ts)
w = next(iter(plugin.recorder.links.values()))
check("the link shows when it was last recorded", w.last_ok is not None and "last recorded: " in panel.links.item(0).text() and "not yet" not in panel.links.item(0).text())
check("the link is due again in about 15 min", 14 * 60 < w.next_due - time.time() <= 16 * 60 + auto_record.JITTER_S)

print("== 3. a busy source doubles that link's wait; three failures in a row stop that link (as in the Map) ==")
mode["m"] = "busy"
for i in range(3):
    w.next_due = time.time()
    plugin._record_tick()
    settle()
    if i == 0:
        check("busy: the link waits twice as long, the status says so (W-RECORD-BUSY)", w.backoff == 2 and "W-RECORD-BUSY" in panel.status.text()
              and "source busy, waiting longer" in panel.links.item(0).text(), panel.status.text())
check("three failures in a row stop recording of that link and say so (W-RECORD-STOPPED)", w.stopped and "W-RECORD-STOPPED" in panel.status.text()
      and "stopped after 3 failures" in panel.links.item(0).text(), panel.status.text())
check("recording itself stays on; stored values are kept", plugin.recorder.enabled and store.stats().rows > 0)
mode["m"] = "ok"
plugin.recorder.set_enabled(False, time.time())

print("== 4. the user's own link: code only unless ticked; free limit ==")
me.analyze_sites = fake_sites
own = own_result("My Secret Tower")
plugin._shown_result = lambda: own
label_count = len(store.labels())
plugin.add_current(False)
own_w = [x for x in plugin.recorder.links.values() if not x.public][0]
check("own link without the tick: listed under its code, not its name", own_w.label.startswith("Your link (code ") and "My Secret Tower" not in own_w.label)
plugin.recorder.set_enabled(True, time.time())
plugin._record_tick(); settle()
check("own link recorded without storing its names", "My Secret Tower" not in store.labels().values() and len(store.labels()) == label_count)
plugin.add_current(True)
plugin.recorder.next_due = time.time()
plugin._record_tick(); settle()
check("with the tick, the names are stored on this computer", "My Secret Tower" in " ".join(store.labels().values()))
plugin.recorder.max_links = 2
other = own_result("Other", lat_shift=0.5)
plugin._shown_result = lambda: other
check("beyond the free limit a link is refused with the plan message", plugin.add_current(False) == auto_record.LIMIT)

print("== 5. unloading stops everything ==")
plugin.unload()
check("unload: recording off, links forgotten, no timer, no task", not plugin.recorder.enabled and not plugin.recorder.links and plugin._record_timer is None and plugin._record_task is None)

failed = [n for n, ok, _ in RESULTS if not ok]
print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
qgs.exitQgis()
sys.exit(1 if failed else 0)
