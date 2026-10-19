"""Selection / filter / lifecycle synchronisation in a real QGIS runtime (offscreen): Records picker <-> QGIS active layer <-> map selection <->
details panel, the Operator filter and the table search, layer reloads and removal, and plugin reload.

Offline on purpose (basemap, live providers and the per-link weather lookup are doubles that live in this file only). Run like qgis_workflow_e2e.py
(see tests/run_qgis_tests.sh). Every check traces to a defect that was reproduced before it was fixed: stale feature ids after a layer reload,
selection handlers missing (or doubled) after a plugin reload, a crash when a layer was removed from the project, a Records row left highlighted
after the map selection moved on."""
import os
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

from velorona.core import inspector  # noqa: E402
from velorona.core.countries.usa_fields import US_SITE_FIELDS  # noqa: E402


def spin(n=12):
    for _ in range(n):
        qgs.processEvents()


# the per-link weather lookup would call a live service: replace it with a no-network investigation (this file only)
plugin._investigate_link = lambda entry: inspector.LinkInvestigation(entry=entry)
shown = []
_orig_show = plugin._show_result
plugin._show_result = lambda r: (shown.append(r), _orig_show(r))[1]
dock = plugin.dock
rec = dock.records
infra = plugin._ensure_velorona_groups()[1]["Infrastructure"]


def rows_highlighted():
    return [rec.model.feature_id(rec.proxy.mapToSource(i).row()) for i in rec.view.selectionModel().selectedRows()]


def choose_dataset(key):
    rec.dataset_combo.setCurrentIndex(rec.dataset_combo.findData(key))
    spin()


def click_row(fid):
    row = rec.model.row_for_feature(fid)
    rec.view.selectRow(rec.proxy.mapFromSource(rec.model.index(row, 0)).row())
    spin()


# a small synthetic USA site layer (test data in this file only; real USA data is a separate downloadable pack)
us_records = [{"id": f"US-{i}", "name": f"US test site {i}", "source": "synthetic test", "licensee": "Test Licensee", "latitude": 38.0 + i * 0.1,
               "longitude": -97.0 + i * 0.1, "country": "US"} for i in range(5)]
us_sites = plugin._ensure_public_layer(
    L.SOURCE_US_SITES, infra, True, "site",
    build=lambda: L.build_point_layer(PM.NAME_US_SITES, us_records, US_SITE_FIELDS, "#d4af37"))
plugin._populate_records()
spin()

print("== 1. sidebar -> map ==")
choose_dataset(L.SOURCE_FIXED_SITES)
choose_dataset(L.SOURCE_FIXED_LINKS)
check("choosing a dataset makes its layer the QGIS active layer", iface.activeLayer() is links, iface.activeLayer())
choose_dataset(L.SOURCE_US_SITES)
check("choosing the USA dataset makes the USA layer active", iface.activeLayer() is us_sites)
check("... and selects nothing by itself", us_sites.selectedFeatureCount() == 0 and links.selectedFeatureCount() == 0)
target = next(f for f in us_sites.getFeatures() if f["id"] == "US-3")
click_row(target.id())
check("a USA row selects exactly that USA feature on its own layer", us_sites.selectedFeatureIds() == [target.id()], us_sites.selectedFeatureIds())
check("... the details show that record", "US test site 3" in dock.browser.toPlainText() or "US-3" in dock.browser.toPlainText(), dock.browser.toPlainText()[:150])
check("... and the map view contains it", iface.canvas.extent().width() > 0)
check("no other layer gained a selection", links.selectedFeatureCount() == 0 and sites.selectedFeatureCount() == 0)

print("== 2. map -> sidebar and stale state ==")
other = next(f for f in us_sites.getFeatures() if f["id"] == "US-1")
us_sites.selectByIds([other.id()]); spin()
check("a map selection moves the Records highlight to that record only", rows_highlighted() == [other.id()], rows_highlighted())
check("... and the details follow", "US test site 1" in dock.browser.toPlainText() or "US-1" in dock.browser.toPlainText())
us_sites.selectByIds([target.id(), other.id()]); spin()
check("a two-feature map selection highlights exactly those two rows", sorted(rows_highlighted()) == sorted([target.id(), other.id()]), rows_highlighted())
us_sites.removeSelection(); spin()
check("clearing the map selection clears the highlight and the details", rows_highlighted() == [] and dock._result is None)
us_sites.selectByIds([other.id()]); spin()
rec.search_edit.setText("US test site 1"); spin()
check("(setup) the search keeps the selected row visible and highlighted", rows_highlighted() == [other.id()], rows_highlighted())
us_sites.selectByIds([target.id()]); spin()
check("a map selection the search hides leaves NO stale row highlighted", rows_highlighted() == [], rows_highlighted())
rec.search_edit.setText(""); spin()

print("== 3. layer switching keeps identity ==")
sel_site = next(f for f in sites.getFeatures() if f.id() > 100)
iface.setActiveLayer(sites)
sites.selectByIds([sel_site.id()]); spin()
choose_dataset(L.SOURCE_US_SITES)
check("switching dataset shows that dataset's own selection, not the previous one's", rows_highlighted() == [target.id()], rows_highlighted())
choose_dataset(L.SOURCE_FIXED_SITES)
check("switching back highlights the same Canadian record (same identity)", rows_highlighted() == [sel_site.id()], rows_highlighted())
check("... and the active layer followed", iface.activeLayer() is sites)
iface.setActiveLayer(us_sites); spin()
check("picking a layer in the QGIS Layers panel switches the Records dataset", rec.current_source_key() == L.SOURCE_US_SITES, rec.current_source_key())
check("... without changing any selection", sites.selectedFeatureIds() == [sel_site.id()] and us_sites.selectedFeatureIds() == [target.id()])
us_sites.removeSelection(); sites.removeSelection(); spin()

print("== 4. filters ==")
ops = plugin._operator_counts()
top = max(ops, key=lambda k: ops[k])
choose_dataset(L.SOURCE_FIXED_LINKS)
total = links.featureCount()
outside = next(f for f in links.getFeatures() if f["licensee"] and top not in f["licensee"])
links.selectByIds([outside.id()]); spin()
plugin.set_licensee_filter(top); spin()
filtered = links.featureCount()
check("the Operator filter narrows the layer", 0 < filtered < total, (filtered, total))
check("... the table shows the same records (count equal)", rec.model.rowCount() == filtered, (rec.model.rowCount(), filtered))
check("... every remaining record names the operator", all(top in (f["licensee"] or "") for f in links.getFeatures()))
check("... a selection the filter excludes is dropped from the map, the table and the details", links.selectedFeatureCount() == 0 and rows_highlighted() == [] and dock._result is None)
check("... the status line states the filtered count", f"{filtered:,}" in rec.status_label.text(), rec.status_label.text()[:80])
rec.search_edit.setText(top.split()[0]); spin()
check("operator + search combine (search narrows within the operator)", 0 < rec.proxy.rowCount() <= filtered, (rec.proxy.rowCount(), filtered))
rec.search_edit.setText("zzzz-no-such-record"); spin()
check("an empty result says so and names the search", "No records match the search" in rec.status_label.text() and "zzzz-no-such-record" in rec.status_label.text(), rec.status_label.text()[:120])
rec.search_edit.setText(""); spin()
plugin.set_licensee_filter(""); spin()
check("clearing the filter restores every record in layer and table", links.featureCount() == total and rec.model.rowCount() == total, (links.featureCount(), rec.model.rowCount(), total))
for _ in range(3):
    plugin.set_licensee_filter(top); plugin.set_licensee_filter("")
spin()
check("repeated filtering leaves no duplicate or stale records", links.featureCount() == total and rec.model.rowCount() == total)
check("the Operator filter does not touch the USA layer (stated in its tooltip)", us_sites.featureCount() == 5 and "USA layers are not filtered" in rec.licensee_combo.toolTip())

print("== 5. dataset reload ==")
us_pre = [dict(r) for r in us_records]
us_sites.selectByIds([next(f.id() for f in us_sites.getFeatures() if f["id"] == "US-2")]); spin()
shown.clear()
# reload with the order reversed: every QgsFeature id is reissued, the records are the same
L.replace_point_features(us_sites, list(reversed(us_pre)), US_SITE_FIELDS); spin()
sel = [f["id"] for f in us_sites.selectedFeatures()]
check("a reload keeps the SAME record selected (by record id, not by the reissued feature id)", sel == ["US-2"], sel)
check("... the selection did not re-open the details or move the map (silent restore)", not shown, len(shown))
rec.refresh_current(); spin()
check("... and the Records highlight is on that record's new row", [rec.model.feature_id(i) for i in range(rec.model.rowCount()) if False] == []
      and rows_highlighted() == [f.id() for f in us_sites.selectedFeatures()], rows_highlighted())
L.replace_point_features(us_sites, [r for r in us_pre if r["id"] != "US-2"], US_SITE_FIELDS); spin()
check("a reload without the selected record clears the selection and the details", us_sites.selectedFeatureCount() == 0 and dock._result is None)
L.replace_point_features(us_sites, us_pre, US_SITE_FIELDS); spin()
# the SAME feature ids now belong to DIFFERENT records (ids are reissued from the start): the old id must not select the new record
sel_fid = next(f.id() for f in us_sites.getFeatures() if f["id"] == "US-2")
us_sites.selectByIds([sel_fid]); spin()
changed = [dict(r, id="OTHER-" + r["id"], name="other " + r["name"]) for r in us_pre]
L.replace_point_features(us_sites, changed, US_SITE_FIELDS); spin()
check("reissued feature ids never select a different record (selection cleared)", us_sites.selectedFeatureCount() == 0 and dock._result is None,
      [f["id"] for f in us_sites.selectedFeatures()])
same_id_new_content = [dict(r, name="renamed " + r["name"]) for r in us_pre]
L.replace_point_features(us_sites, us_pre, US_SITE_FIELDS); spin()
us_sites.selectByIds([next(f.id() for f in us_sites.getFeatures() if f["id"] == "US-2")]); spin()
L.replace_point_features(us_sites, same_id_new_content, US_SITE_FIELDS); spin()
check("a record whose content changed under the same id is not kept as if unchanged", us_sites.selectedFeatureCount() == 0 and dock._result is None)
L.replace_point_features(us_sites, us_pre, US_SITE_FIELDS); spin()

print("== 6. missing values and empty layers ==")
L.replace_point_features(us_sites, [{"name": "no id", "latitude": 40.0, "longitude": -100.0, "source": "synthetic test"}], US_SITE_FIELDS); spin()
f0 = next(us_sites.getFeatures())
us_sites.selectByIds([f0.id()]); spin()
L.replace_point_features(us_sites, [{"name": "no id", "latitude": 40.0, "longitude": -100.0, "source": "synthetic test"}], US_SITE_FIELDS); spin()
check("a record with no id is never matched by guess after a reload (selection cleared)", us_sites.selectedFeatureCount() == 0)
L.replace_point_features(us_sites, [], US_SITE_FIELDS); spin()
choose_dataset(L.SOURCE_US_SITES)
rec.refresh_current(); spin()
check("an empty layer shows an explicit empty state, no rows", rec.model.rowCount() == 0 and rec.status_label.text().strip() != "", rec.status_label.text())
L.replace_point_features(us_sites, us_pre, US_SITE_FIELDS); spin()

print("== 7. layer removal ==")
rec.refresh_current(); choose_dataset(L.SOURCE_US_SITES)
us_sites.selectByIds([next(f.id() for f in us_sites.getFeatures())]); spin()
check("(setup) a USA record is selected and shown", dock._result is not None)
us_id = us_sites.id()
project.removeMapLayer(us_id); spin()
check("removing the layer removes its dataset from the picker", rec.dataset_combo.findData(L.SOURCE_US_SITES) < 0 and L.SOURCE_US_SITES not in rec._layers)
check("... clears the details of its selection", dock._result is None)
check("... and forgets its selection handler", us_id not in plugin._wired_layers)
choose_dataset(L.SOURCE_FIXED_SITES)
rec.refresh_current(); spin()
check("the remaining datasets still work after the removal (no crash)", rec.model.rowCount() == sites.featureCount())

print("== 8. repeated interaction and plugin reload ==")
calls = []
_orig_sel = plugin._on_feature_selected
plugin._on_feature_selected = lambda lyr, k: (calls.append(lyr.id()), _orig_sel(lyr, k))[1]
for _ in range(3):
    plugin.action_load_public.trigger(); spin(20)
sites, links = lay(L.SOURCE_FIXED_SITES), lay(L.SOURCE_FIXED_LINKS)
calls.clear()
s1 = next(f for f in sites.getFeatures() if f.id() > 200)
sites.selectByIds([s1.id()]); spin()
check("after three Load Public Data runs one selection is handled exactly once", calls == [sites.id()], calls)
check("each layer has exactly one inspector handler", len(plugin._wired_layers) == len({k for k in plugin._wired_layers}) and sites.id() in plugin._wired_layers)
sites.removeSelection(); spin()
plugin._on_feature_selected = _orig_sel
plugin.unload()
shown.clear()
sites.selectByIds([s1.id()]); spin()
check("an unloaded plugin no longer answers selections", not shown, len(shown))
sites.removeSelection(); spin()
plugin2 = PM.VeloronaPlugin(iface)
plugin2._warn = lambda m: None
plugin2._error = lambda m: None
plugin2._basemap_renderer = lambda dark: None
plugin2._investigate_link = plugin._investigate_link
plugin2.initGui()
check("a reloaded plugin adopts the Velorona layers already in the project", sites.id() in plugin2._wired_layers and links.id() in plugin2._wired_layers)
calls2 = []
_o2 = plugin2._on_feature_selected
plugin2._on_feature_selected = lambda lyr, k: (calls2.append(lyr.id()), _o2(lyr, k))[1]
sites.selectByIds([s1.id()]); spin()
check("... and answers a selection exactly once", calls2 == [sites.id()], calls2)
check("... showing that record in the new panel", plugin2.dock is not None and plugin2.dock._result is not None)
sites.removeSelection(); spin()
plugin2.action_load_public.trigger(); spin(20)
calls2.clear()
sites.selectByIds([s1.id()]); spin()
check("re-running Load Public Data after a reload does not double the handler", calls2 == [sites.id()], calls2)
# a Velorona layer arriving in the project after start-up (a reopened project restoring its layers) is adopted through layersAdded
late = L.build_point_layer("late layer", us_records, US_SITE_FIELDS, "#d4af37")
L.add_to_group(project, late, plugin2._ensure_velorona_groups()[1]["Infrastructure"], True, source_key=L.SOURCE_US_SITES)
spin()
check("a layer added to the project later is wired once (layersAdded)", late.id() in plugin2._wired_layers)
calls2.clear()
late.selectByIds([next(f.id() for f in late.getFeatures() if f["id"] == "US-4")]); spin()
check("... and answers a selection exactly once", calls2 == [late.id()], calls2)
late.removeSelection(); spin()
# switching the Records dataset must not change what is selected, on any layer
sites.selectByIds([s1.id()]); late.selectByIds([next(f.id() for f in late.getFeatures() if f["id"] == "US-1")]); spin()
before = (sorted(sites.selectedFeatureIds()), sorted(late.selectedFeatureIds()))
plugin2._populate_records(); spin()
r2 = plugin2.dock.records
for key in (L.SOURCE_FIXED_LINKS, L.SOURCE_US_SITES, L.SOURCE_FIXED_SITES, L.SOURCE_US_SITES):
    r2.dataset_combo.setCurrentIndex(r2.dataset_combo.findData(key)); spin()
check("switching datasets back and forth changes no selection on any layer", (sorted(sites.selectedFeatureIds()), sorted(late.selectedFeatureIds())) == before)
sites.removeSelection(); late.removeSelection(); spin()
late_id = late.id()
project.removeMapLayer(late_id); spin()
check("removing that layer unwires it", late_id not in plugin2._wired_layers)
plugin2.unload()
check("unloading leaves no handler wired and no signal connection to the project", not plugin2._wired_layers and not plugin2._project_wiring_connected)

print("== 9. user-facing wording ==")
import re  # noqa: E402
names = [n.name() for n in project.layerTreeRoot().findGroups(True)] + [l.name() for l in project.mapLayers().values()]
bad = re.compile(r"\b(optional|experimental|placeholder|coming soon|not implemented|todo|demo|beta|temporary|wip)\b", re.I)
check("no layer or group name uses development-oriented wording", not [n for n in names if bad.search(n)], [n for n in names if bad.search(n)])
NEW_GROUP = PM.IMAGERY_GROUP_NAME
check("the imagery group is named for what it holds (USGS aerial imagery and topo, USA)", any(n == NEW_GROUP for n in names) and "optional" not in NEW_GROUP.lower(), names)
_img_before = len(project.layerTreeRoot().findGroup(NEW_GROUP).findLayers())      # 0 where this QGIS build has no 'wms' provider
project.layerTreeRoot().findGroup(NEW_GROUP).setName("USA Imagery (optional)")      # what a project saved by 1.1.9 contains
plugin3 = PM.VeloronaPlugin(iface)
renamed = plugin3._ensure_imagery_group()
check("a project saved with the old group name is renamed in place, not duplicated",
      renamed.name() == NEW_GROUP and project.layerTreeRoot().findGroup("USA Imagery (optional)") is None
      and len([g for g in project.layerTreeRoot().findGroups() if g.name() == NEW_GROUP]) == 1)
check("the renamed group keeps its two imagery layers (user data preserved)", len(renamed.findLayers()) == _img_before)
texts = [a.text() + " " + a.toolTip() for a in plugin2.actions] + [rec.licensee_combo.toolTip(), rec.operator_hint.text(), rec.status_label.text()]
check("no action, tooltip or status text uses development-oriented wording", not [t for t in texts if bad.search(t)], [t for t in texts if bad.search(t)][:3])

failed = [r for r in RESULTS if not r[1]]
print(f"\n===== {len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed =====")
for name, _ok, detail in failed:
    print("FAILED:", name, detail)
os._exit(1 if failed else 0)
