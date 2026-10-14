"""Cross-component workflow regression tests in a real QGIS runtime (offscreen): Records <-> map selection <-> details panel <-> map navigation,
the status of live providers when they fail, and the guarantee that an unavailable provider never produces fabricated records.

Offline on purpose: the basemap and the live providers are replaced by test doubles so a provider outage can be SIMULATED. These doubles live in this
test file only; nothing here ships. Run like qgis_e2e.py (see tests/run_qgis_tests.sh). A pass here is NOT proof of a live integration: the live checks
are the real-provider smoke test (tools/live_orbit_probe.py and the real-QGIS session notes in the release notes)."""
import os
import sys

PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(PLUGIN_DIR))

from qgis.core import (QgsApplication, QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsFeature, QgsGeometry,  # noqa: E402
                       QgsPointXY, QgsProject, QgsRectangle)
from qgis.gui import QgsLayerTreeMapCanvasBridge, QgsMapCanvas, QgsMessageBar  # noqa: E402
from qgis.PyQt.QtCore import QMetaType, Qt  # noqa: E402
from qgis.PyQt.QtWidgets import QApplication, QMainWindow  # noqa: E402

qgs = QgsApplication([], True)
qgs.initQgis()
RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  -- {detail}" if detail and not ok else ""))


class FakeIface:
    def __init__(self):
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
    def setActiveLayer(self, layer): self.active = layer
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

print("== 1. startup: nothing synthetic, nothing heavy on by default ==")
plugin.initGui()
plugin.action_load_public.trigger()
for _ in range(20):
    qgs.processEvents()
root = project.layerTreeRoot()


def lay(key):
    return L.find_owned_layer(project, key)


def visible(key):
    return root.findLayer(lay(key).id()).isVisible()


sites, links = lay(L.SOURCE_FIXED_SITES), lay(L.SOURCE_FIXED_LINKS)
check("Canada sites/links come from the bundled ISED snapshot and are on", sites.featureCount() > 20000 and links.featureCount() > 15000
      and visible(L.SOURCE_FIXED_SITES) and visible(L.SOURCE_FIXED_LINKS), (sites.featureCount(), links.featureCount()))
check("towers, cellular, satellites and ground stations are off by default",
      not any(visible(k) for k in (L.SOURCE_TOWERS, L.SOURCE_CELLULAR, L.SOURCE_SATELLITES, L.SOURCE_GROUND_STATIONS)))
check("the live layers start EMPTY (no stand-in records)", lay(L.SOURCE_TOWERS).featureCount() == 0 and lay(L.SOURCE_CELLULAR).featureCount() == 0
      and lay(L.SOURCE_SATELLITES).featureCount() == 0)
check("every Canada site record carries a snapshot date in its coverage text",
      all("ISED file dated" in (f["coverage"] or "") for f in list(sites.getFeatures())[:50]))
gs = lay(L.SOURCE_GROUND_STATIONS)
check("ground-station records carry the snapshot retrieval date", all(f["retrieved_at"] for f in list(gs.getFeatures())[:50]))

_stats = {}
_stations = space_public.load_ground_station_snapshot(stats=_stats)
check("SatNOGS stations the source reports at exactly 0,0 (no recorded location) are not drawn",
      _stats["unlocated"] > 0 and gs.featureCount() == _stats["total"] - _stats["unlocated"]
      and not any(f.geometry().asPoint().x() == 0 and f.geometry().asPoint().y() == 0 for f in gs.getFeatures()), _stats)
check("... and the layer says how many and why", "no recorded location" in plugin.dock.records._dataset_notes.get(L.SOURCE_GROUND_STATIONS, "")
      and "retrieved" in plugin.dock.records._dataset_notes.get(L.SOURCE_GROUND_STATIONS, ""), plugin.dock.records._dataset_notes.get(L.SOURCE_GROUND_STATIONS))

print("== 2. a failing live provider: empty, stated, nothing substituted ==")
tow = lay(L.SOURCE_TOWERS)
root.findLayer(tow.id()).setItemVisibilityChecked(True)
plugin._refresh_viewport_layers()
qgs.processEvents()
st = plugin._viewport_status.get(L.SOURCE_TOWERS) or {}
check("provider down -> the layer has no features", tow.featureCount() == 0, tow.featureCount())
check("provider down -> status is 'unavailable'", st.get("state") == "unavailable", st)
check("provider down -> the user is told on the message bar", any("unavailable" in str(m) for m in iface.pushed), iface.pushed[-2:])
plugin.dock.records.dataset_combo.setCurrentIndex(plugin.dock.records.dataset_combo.findData(L.SOURCE_TOWERS))
qgs.processEvents()
check("provider down -> the Records status line says unavailable (not 'no records')",
      "unavailable" in plugin.dock.records.status_label.text(), plugin.dock.records.status_label.text())

print("== 3. the provider recovers: live data, truncation and invalid coordinates stated ==")
state["mode"] = "truncated"
plugin._viewport_cache.clear()
plugin._last_viewport_bbox.clear()
plugin._refresh_viewport_layers()
qgs.processEvents()
st = plugin._viewport_status.get(L.SOURCE_TOWERS) or {}
check("recovered -> only the valid record is drawn", tow.featureCount() == 1 and [f["id"] for f in tow.getFeatures()] == ["t1"], tow.featureCount())
check("recovered -> status 'live' with a retrieval time", st.get("state") == "live" and st.get("retrieved_at") is not None, st)
check("3 invalid-coordinate records are counted, not drawn", st.get("skipped") == 3 and tow.customProperty(L.VELORONA_SKIPPED_PROPERTY) == 3, st)
check("the 1,000-record limit is reported", st.get("truncated") is True and "1,000-record limit" in plugin.dock.records.status_label.text(),
      plugin.dock.records.status_label.text())
plugin._last_viewport_bbox.clear()
plugin._refresh_viewport_layers()
st = plugin._viewport_status.get(L.SOURCE_TOWERS) or {}
check("the same view again is labelled cached (with its original time), not live", st.get("state") == "cached", st)
state["mode"] = "empty"
plugin._viewport_cache.clear()
plugin._last_viewport_bbox.clear()
plugin._refresh_viewport_layers()
st = plugin._viewport_status.get(L.SOURCE_TOWERS) or {}
check("the service answering with nothing is 'empty', distinct from 'unavailable'", st.get("state") == "empty" and tow.featureCount() == 0, st)
state["mode"] = "down"
plugin._viewport_cache.clear()
plugin._last_viewport_bbox.clear()
state["mode"] = "truncated"
plugin._refresh_viewport_layers()
before_ids = [f["id"] for f in tow.getFeatures()]
state["mode"] = "down"
plugin._viewport_cache.clear()
plugin._last_viewport_bbox.clear()
plugin._refresh_viewport_layers()
check("an outage after a good load does not keep the old records on screen", before_ids == ["t1"] and tow.featureCount() == 0, (before_ids, tow.featureCount()))
root.findLayer(tow.id()).setItemVisibilityChecked(False)

print("== 4. satellites: an unavailable provider cannot produce records ==")
class Cache:
    def __init__(self): self.d = {}
    def read(self, g): return self.d.get(g)
    def write(self, g, v): self.d[g] = v
from datetime import datetime, timezone  # noqa: E402
import tempfile  # noqa: E402
cache = orbit_data.OrbitCache(tempfile.mkdtemp())
now = datetime.now(timezone.utc)
for label, fetch in (("timeout", lambda u: orbit_data.FetchResult(status=None, error="timeout")),
                     ("HTTP 503", lambda u: orbit_data.FetchResult(status=503, text=None)),
                     ("HTTP 200 with garbage", lambda u: orbit_data.FetchResult(status=200, text="<html>not json</html>")),
                     ("HTTP 200 with an empty list", lambda u: orbit_data.FetchResult(status=200, text="[]"))):
    cache2 = orbit_data.OrbitCache(tempfile.mkdtemp())
    feed = satellite_feed.load_groups(satellite_feed.GEO_GROUPS, cache2, now, fetch=fetch)
    built = satellite_feed.build_rows(feed["records"], now)
    check(f"provider {label}: no records, status unavailable", feed["records"] == [] and feed["status"] == "unavailable" and built["rows"] == [],
          (feed["status"], len(feed["records"])))
bad = [{"OBJECT_NAME": "BAD", "NORAD_CAT_ID": 12345, "EPOCH": "2026-10-14T00:00:00", "MEAN_MOTION": 0, "ECCENTRICITY": 0.0001,
        "INCLINATION": 0.01, "RA_OF_ASC_NODE": 0, "ARG_OF_PERICENTER": 0, "MEAN_ANOMALY": 0, "BSTAR": 0, "MEAN_MOTION_DOT": 0,
        "MEAN_MOTION_DDOT": 0, "ELEMENT_SET_NO": 999, "REV_AT_EPOCH": 1, "CLASSIFICATION_TYPE": "U", "EPHEMERIS_TYPE": 0}]
import json as _json  # noqa: E402
feed = satellite_feed.load_groups(("geo",), orbit_data.OrbitCache(tempfile.mkdtemp()), now,
                                  fetch=lambda u: orbit_data.FetchResult(status=200, text=_json.dumps(bad)))
check("an element set with zero mean motion is rejected, not drawn", feed["records"] == [] or satellite_feed.build_rows(feed["records"], now)["rows"] == [],
      feed["status"])
plugin._satellites_loaded(RuntimeError("simulated outage"), None)
check("a failed satellite load leaves the layer empty and says so",
      lay(L.SOURCE_SATELLITES).featureCount() == 0 and "unavailable" in plugin.dock.records._dataset_notes.get(L.SOURCE_SATELLITES, ""),
      plugin.dock.records._dataset_notes)
text = PM.VeloronaPlugin._satellite_status_text({"status": "stale", "per_group": {"geo": {"retrieved_at_utc": "2026-10-14T10:00:00+00:00"}}}, 5, 0)
check("a stale feed is labelled STALE with its retrieval time, never as live", "STALE" in text and "2026-10-14 10:00:00 UTC" in text, text)

print("== 5. USA: no pack configured means no records, not a fallback ==")
from velorona.core.countries import usa as usa_pack  # noqa: E402
from velorona.core.countries.base import PackError  # noqa: E402
try:
    usa_pack.make_provider("")
    check("no pack source raises", False)
except PackError:
    check("no pack source raises a PackError instead of producing records", True)
check("no USA layer exists until a pack is loaded", lay(L.SOURCE_US_LINKS) is None and lay(L.SOURCE_US_SITES) is None)

print("== 6. selection workflow: Records row -> map -> details ==")
canvas = iface.canvas
dock = plugin.dock
rec = dock.records
rec.dataset_combo.setCurrentIndex(rec.dataset_combo.findData(L.SOURCE_FIXED_LINKS))
qgs.processEvents()
target = None
for f in links.getFeatures():
    if f["authorization_number"] and f.id() > 40:
        target = f
        break
fid = target.id()
row = rec.model.row_for_feature(fid)
proxy_row = rec.proxy.mapFromSource(rec.model.index(row, 0)).row()
rec.view.selectRow(proxy_row)
for _ in range(10):
    qgs.processEvents()
check("(1)(2) the clicked Records row selects exactly that feature on the map layer", links.selectedFeatureIds() == [fid], links.selectedFeatureIds())
res = dock._result
check("(5) the details panel shows that record's attributes", res is not None and target["authorization_number"] in dock.browser.toPlainText(),
      dock.browser.toPlainText()[:120])
bbox = target.geometry().boundingBox()
crs = canvas.mapSettings().destinationCrs()
t = QgsCoordinateTransform(QgsCoordinateReferenceSystem("EPSG:4326"), crs, project)
ext = canvas.extent()
check("(3)(9) the map moved so the record is in view, in the map CRS", ext.contains(t.transformBoundingBox(bbox)) and crs.authid() == "EPSG:3857",
      (ext.toString(), crs.authid()))
dock.view_combo.setCurrentIndex(dock.view_combo.findData("evidence"))
qgs.processEvents()
_a = target.geometry().asPolyline()[0]
check("(4) the Evidence view shows the selected feature's own endpoint coordinates",
      f"{_a.y():.5f}" in dock.browser.toPlainText() and f"{_a.x():.5f}" in dock.browser.toPlainText(), dock.browser.toPlainText()[:200])
# change selection
other = None
for f in links.getFeatures():
    if f.id() != fid and f["authorization_number"] and f.id() > 400:
        other = f
        break
row2 = rec.model.row_for_feature(other.id())
rec.view.selectRow(rec.proxy.mapFromSource(rec.model.index(row2, 0)).row())
for _ in range(10):
    qgs.processEvents()
check("(6) changing the selection replaces the old one on the map", links.selectedFeatureIds() == [other.id()], links.selectedFeatureIds())
check("(6) ... and in the details panel", other["authorization_number"] in dock.browser.toPlainText() and target["authorization_number"] not in dock.browser.toPlainText())
# map -> table
site = next(f for f in sites.getFeatures() if f.id() > 100)
links.removeSelection()
iface.setActiveLayer(sites)
sites.selectByIds([site.id()])
for _ in range(10):
    qgs.processEvents()
sel = rec.view.selectionModel().selectedRows()
check("map -> table: Records switches to the site dataset and highlights that row",
      rec.current_source_key() == L.SOURCE_FIXED_SITES and len(sel) == 1
      and rec.model.feature_id(rec.proxy.mapToSource(sel[0]).row()) == site.id(), (rec.current_source_key(), len(sel)))
check("map -> table: the details panel is that site", (site["name"] or "") in dock.browser.toPlainText() or site["record_id"] in dock.browser.toPlainText())
# clear
sites.removeSelection()
for _ in range(10):
    qgs.processEvents()
check("(7) clearing the selection empties the details panel", dock._result is None)
check("(7) ... and leaves no highlighted Records row", len(rec.view.selectionModel().selectedRows()) == 0,
      len(rec.view.selectionModel().selectedRows()))
# dataset change keeps the map selection, filter does not leave a mismatched panel
sites.selectByIds([site.id()])
for _ in range(10):
    qgs.processEvents()
rec.dataset_combo.setCurrentIndex(rec.dataset_combo.findData(L.SOURCE_FIXED_LINKS))
qgs.processEvents()
check("(7) switching the Records dataset does not change the map selection", sites.selectedFeatureIds() == [site.id()])
rec.dataset_combo.setCurrentIndex(rec.dataset_combo.findData(L.SOURCE_FIXED_SITES))
qgs.processEvents()
licensee = site["licensee"]
plugin.set_licensee_filter("An Operator That Is Not This One")
for _ in range(10):
    qgs.processEvents()
check("(7) an operator filter that removes the selected record leaves no selection and no stale details",
      sites.selectedFeatureCount() == 0 and dock._result is None and len(rec.view.selectionModel().selectedRows()) == 0,
      (sites.selectedFeatureCount(), dock._result is not None))
plugin.set_licensee_filter("")
for _ in range(10):
    qgs.processEvents()
check("clearing the operator filter restores every record", sites.featureCount() > 20000, sites.featureCount())
# search filter + sort keep Records and map selection in sync
rec.dataset_combo.setCurrentIndex(rec.dataset_combo.findData(L.SOURCE_FIXED_LINKS))
qgs.processEvents()
links.selectByIds([fid])
for _ in range(10):
    qgs.processEvents()
rec.search_edit.setText(target["authorization_number"][:9])
rec.view.sortByColumn(0, Qt.SortOrder.DescendingOrder)
for _ in range(10):
    qgs.processEvents()
sel = rec.view.selectionModel().selectedRows()
check("(7) after search + sort the selected record is still the highlighted row (or hidden), never a different one",
      all(rec.model.feature_id(rec.proxy.mapToSource(i).row()) == fid for i in sel) and links.selectedFeatureIds() == [fid],
      (links.selectedFeatureIds(), len(sel)))
rec.search_edit.setText("")

print("== 7. invalid or missing coordinates never navigate ==")
mem = L.build_point_layer("bad", [{"id": "b", "latitude": 12.0, "longitude": 30.0, "name": "n"}], [("id", QMetaType.Type.QString), ("name", QMetaType.Type.QString)], "#ffffff")
bad_f = QgsFeature(mem.fields())
bad_f.setAttributes(["nogeom", "n"])
mem.dataProvider().addFeatures([bad_f])
nogeo = next(f for f in mem.getFeatures() if f["id"] == "nogeom")
project.addMapLayer(mem, False)
ext_before = canvas.extent().toString()
mem.selectByIds([nogeo.id()])
plugin._zoom_to_selection(mem)
check("a selected feature with no geometry does not move the map", canvas.extent().toString() == ext_before)
check("point/link builders skip invalid coordinates and count them",
      L.build_point_layer("v", [{"latitude": 95, "longitude": 0}, {"latitude": 1, "longitude": 1}], [], "#ffffff").featureCount() == 1
      and L.build_link_layer("v", [{"site_a": {"latitude": 1, "longitude": 1}, "site_b": {"latitude": None, "longitude": 3}}], [], "#ffffff").featureCount() == 0)

passed = sum(1 for _, ok, _ in RESULTS if ok)
print(f"\n===== {passed}/{len(RESULTS)} checks passed =====")
for name, ok, detail in RESULTS:
    if not ok:
        print(f"  FAILED: {name} -- {detail}")
sys.exit(0 if passed == len(RESULTS) else 1)
