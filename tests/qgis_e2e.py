"""Velorona QGIS plugin -- end-to-end runtime regression test.

Drives the REAL plugin through a real QgsProject + QgsMapCanvas + layer
tree bridge: new blank project, real QAction, CRS/extent assertions, real
rendering, pan/zoom, then the analysis engines, inspector, dock and export.
"""

import os
import sys
import time

# Repo-local: tests/ lives directly under the plugin package.
PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(PLUGIN_DIR))

from qgis.core import (  # noqa: E402
    QgsApplication,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeatureRequest,
    QgsMapRendererParallelJob,
    QgsProject,
    QgsRectangle,
)
from qgis.gui import QgsLayerTreeMapCanvasBridge, QgsMapCanvas  # noqa: E402
from qgis.PyQt.QtCore import QSize, Qt  # noqa: E402
from qgis.PyQt.QtWidgets import QMainWindow  # noqa: E402

qgs = QgsApplication([], True)
qgs.initQgis()

RESULTS = []
SKIPPED = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    return ok


class FakeIface:
    def __init__(self):
        self.window = QMainWindow()
        self.window.resize(1680, 1000)
        self.canvas = QgsMapCanvas()
        self.window.setCentralWidget(self.canvas)
        self.canvas.resize(1280, 800)
        self.docks = []

    def mapCanvas(self):
        return self.canvas

    def mainWindow(self):
        return self.window

    def addToolBarIcon(self, a):
        pass

    def addPluginToMenu(self, m, a):
        pass

    def removePluginMenu(self, m, a):
        pass

    def removeToolBarIcon(self, a):
        pass

    def setActiveLayer(self, layer):
        self.active_layer = layer

    def activeLayer(self):
        return getattr(self, "active_layer", None)

    def addDockWidget(self, area, dock):
        self.docks.append(dock)
        self.window.addDockWidget(area, dock)

    def removeDockWidget(self, dock):
        if dock in self.docks:
            self.docks.remove(dock)
        self.window.removeDockWidget(dock)


iface = FakeIface()
iface.window.show()
canvas = iface.canvas
project = QgsProject.instance()
# Left at QGIS's own default: the bridge adopts the first added layer's CRS for
# an empty project. Disabling it here would hide exactly the regression that put
# the workspace back on EPSG:4326 in real QGIS.
bridge = QgsLayerTreeMapCanvasBridge(project.layerTreeRoot(), canvas)

crs_events = []
project.crsChanged.connect(lambda: crs_events.append(("project", project.crs().authid(), time.monotonic())))
canvas.destinationCrsChanged.connect(
    lambda: crs_events.append(("canvas", canvas.mapSettings().destinationCrs().authid(), time.monotonic()))
)

from velorona.core import export, inspector  # noqa: E402
from velorona.core.engines import microwave_exposure, satellite_earth_space, terrestrial  # noqa: E402
from velorona.core.inspector import feature_to_entry  # noqa: E402
from aei_mw_exposure import physics as mw_physics  # noqa: E402
from velorona.ui.param_dialog import ParamDialog  # noqa: E402
import velorona.plugin as plugin_module  # noqa: E402
from velorona.plugin import BASEMAP_NAME, VeloronaPlugin  # noqa: E402

plugin = VeloronaPlugin(iface)
warnings = []
plugin._warn = lambda m: warnings.append(m)
plugin._error = lambda m: warnings.append("ERROR: " + m)

print("\n== 1. blank project -> real Load Public Data QAction ==")
plugin.initGui()
check("blank project starts with no Velorona CRS forced", project.crs().authid() in ("", "EPSG:4326"),
      f"start CRS={project.crs().authid() or '(unset)'}")
t0 = time.monotonic()
plugin.action_load_public.trigger()
for _ in range(30):
    qgs.processEvents()   # let QGIS's queued layer-tree handling settle
load_seconds = time.monotonic() - t0

check("project CRS is EPSG:3857", project.crs().authid() == "EPSG:3857", project.crs().authid())
check("canvas destination CRS is EPSG:3857",
      canvas.mapSettings().destinationCrs().authid() == "EPSG:3857",
      canvas.mapSettings().destinationCrs().authid())
# QGIS transiently adopts a layer's CRS for an empty project from a queued
# handler; Velorona re-asserts the workspace CRS before anything is rendered,
# so what matters is where it lands, not that QGIS never touched it.
check("workspace settles on EPSG:3857, not EPSG:4326",
      project.crs().authid() == "EPSG:3857"
      and canvas.mapSettings().destinationCrs().authid() == "EPSG:3857",
      f"crs events: {[(w, a) for w, a, _ in crs_events]}")
print(f"  load took {load_seconds:.2f}s; warnings: {warnings or 'none'}")

print("\n== 2. initial extent ==")
ext = canvas.extent()
to_wgs = QgsCoordinateTransform(QgsCoordinateReferenceSystem("EPSG:3857"),
                                QgsCoordinateReferenceSystem("EPSG:4326"), project)
geo = to_wgs.transformBoundingBox(ext)
check("extent is not a whole-world view", ext.width() < 0.6 * 40075016.7,
      f"width={ext.width():,.0f} m (world=40,075,017)")
check("extent is not a degenerate sliver", ext.width() > 100000.0, f"width={ext.width():,.0f} m")
check("extent covers Canadian Fixed Service data",
      geo.xMinimum() < -60 and geo.xMaximum() > -100 and geo.yMinimum() < 50 and geo.yMaximum() > 60,
      f"lon {geo.xMinimum():.1f}..{geo.xMaximum():.1f}, lat {geo.yMinimum():.1f}..{geo.yMaximum():.1f}")

print("\n== 3. layers, visibility hierarchy, basemap ==")
by_name = {lyr.name(): lyr for lyr in project.mapLayers().values()}
root = project.layerTreeRoot()


def vis(fragment):
    for name, lyr in by_name.items():
        if fragment in name:
            node = root.findLayer(lyr.id())
            return node is not None and node.isVisible()
    return None


check("Fixed Service sites ON by default", vis("Fixed Service sites") is True)
check("Fixed Service links ON by default", vis("Fixed Service links") is True)
check("Ontario Towers OFF by default", vis("Ontario Towers") is False)
check("Cellular Sites OFF by default", vis("Cellular Sites") is False)
check("Satellites OFF by default", vis("Satellites") is False)
check("Ground/Earth Stations OFF by default", vis("Ground/Earth Stations") is False)

basemap = by_name.get(BASEMAP_NAME)
check("Velorona basemap present", basemap is not None)
check("basemap layer is valid", basemap is not None and basemap.isValid())
check("basemap has a converted renderer", basemap is not None and basemap.renderer() is not None)
check("basemap CRS is EPSG:3857 (no runtime reprojection)",
      basemap is not None and basemap.crs().authid() == "EPSG:3857",
      basemap.crs().authid() if basemap else "n/a")
qgs.processEvents()  # let the layer-tree bridge push visible layers onto the canvas
check("hidden layers excluded from render", len(canvas.mapSettings().layers()) == 3,
      f"renderer sees {len(canvas.mapSettings().layers())} of {len(by_name)} layers")

disclosed = [n for n in by_name if "not a coverage guarantee" in n]
check("public-records disclosure still on the raw-record layer names", len(disclosed) == 4,
      f"{len(disclosed)} layers carry it")
check("layer abstract/metadata disclosure intact",
      all("public infrastructure records" in by_name[n].metadata().abstract().lower()
          for n in disclosed if by_name[n].metadata().abstract()),
      "abstracts checked")

print("\n== 4. real render ==")


def render(tag):
    qgs.processEvents()
    ms = canvas.mapSettings()
    ms.setOutputSize(QSize(1280, 800))
    job = QgsMapRendererParallelJob(ms)
    t = time.monotonic()
    job.start()
    job.waitForFinished()
    dt = time.monotonic() - t
    img = job.renderedImage()
    colours = {img.pixel(x, y) for x in range(0, 1280, 64) for y in range(0, 800, 40)}
    return dt, img, colours, job.errors()


dt, img, colours, errs = render("initial")
check("render produced an image", not img.isNull(), f"{img.width()}x{img.height()} in {dt:.2f}s")
check("render reported no errors", not errs, str(errs))
check("rendered map is not blank/uniform", len(colours) > 3, f"{len(colours)} distinct sampled colours")

print("\n== 5. pan / zoom ==")
crs_events_before_nav = len(crs_events)
base = QgsRectangle(canvas.extent())
nav_times = []
for i, (dx, f) in enumerate([(0.25, 1.0), (0.0, 0.5), (0.0, 2.0), (-0.25, 1.0), (0.15, 0.7), (-0.1, 1.4)]):
    e = QgsRectangle(base)
    e = QgsRectangle(e.xMinimum() + e.width() * dx, e.yMinimum(), e.xMaximum() + e.width() * dx, e.yMaximum())
    e.scale(f)
    t = time.monotonic()
    canvas.setExtent(e)
    qgs.processEvents()
    handler = time.monotonic() - t
    rdt, _, _, rerr = render(f"nav{i}")
    nav_times.append((handler, rdt))

worst_handler = max(h for h, _ in nav_times)
worst_render = max(r for _, r in nav_times)
check("no CRS change during navigation", len(crs_events) == crs_events_before_nav,
      f"{len(crs_events) - crs_events_before_nav} new CRS events")
check("navigation handler does not block the GUI", worst_handler < 0.5,
      f"worst handler {worst_handler * 1000:.0f} ms over {len(nav_times)} moves")
check("navigation render stays interactive", worst_render < 1.5, f"worst render {worst_render:.2f}s")

print("\n== 6. feature selection / inspector / dock ==")
sites_layer = next(lyr for name, lyr in by_name.items() if "Fixed Service sites" in name)
links_layer = next(lyr for name, lyr in by_name.items() if "Fixed Service links" in name)
feats = list(sites_layer.getFeatures())
check("Fixed Service sites layer has real features", len(feats) > 1000, f"{len(feats)} features")

entry = feature_to_entry(feats[0], "site")
check("inspector builds a site entry", entry.kind == "site" and entry.latitude is not None,
      f"lat={entry.latitude:.3f} lon={entry.longitude:.3f}")
link_entry = feature_to_entry(next(links_layer.getFeatures()), "link")
check("inspector builds a link entry", link_entry.site_a_point is not None and link_entry.site_b_point is not None)

sites_layer.selectByIds([feats[0].id()])
qgs.processEvents()
check("selection opens the Results Dock", plugin.dock is not None and len(iface.docks) == 1)
if plugin.dock is not None:
    plugin.dock.show_result(entry)
    check("dock renders the site entry", bool(plugin.dock.browser.toHtml().strip()))
    plugin.dock.show_result(link_entry)
    check("dock renders the link entry", bool(plugin.dock.browser.toHtml().strip()))

print("\n== 7. analysis engines (unchanged code paths) ==")
# Two real endpoints of one real Fixed Service link, matched back to site features.
link_feat = next(links_layer.getFeatures())
le = feature_to_entry(link_feat, "link")
(lat_a, lon_a), (lat_b, lon_b) = le.site_a_point, le.site_b_point


def nearest_site(lat, lon):
    best, bestd = None, 1e9
    for f in feats:
        p = f.geometry().centroid().asPoint()
        d = (p.y() - lat) ** 2 + (p.x() - lon) ** 2
        if d < bestd:
            best, bestd = f, d
    return best


entries = [(sites_layer, nearest_site(lat_a, lon_a)), (sites_layer, nearest_site(lat_b, lon_b))]

try:
    tparams = terrestrial.build_params(entries)
    tresult = terrestrial.analyze(entries, tparams)
    globals()['tresult'] = tresult
    check("terrestrial engine analyze() runs", tresult is not None, type(tresult).__name__)
    plugin.dock.show_result(tresult)
    check("dock renders terrestrial result", bool(plugin.dock.browser.toHtml().strip()))
    csv = export.result_to_csv(tresult)
    check("terrestrial evidence export produces CSV",
          "Evidence" in csv and len(csv.splitlines()) > 3, f"{len(csv.splitlines())} lines")
except Exception as exc:
    check("terrestrial engine analyze() runs", False, f"{type(exc).__name__}: {exc}")

try:
    mparams = microwave_exposure.build_params(entries)
    mresult = microwave_exposure.analyze(entries, mparams)
    globals()['mresult'] = mresult
    check("microwave engine analyze() runs", mresult is not None, type(mresult).__name__)
    plugin.dock.show_result(mresult)
    check("dock renders microwave result", bool(plugin.dock.browser.toHtml().strip()))
    csv = export.result_to_csv(mresult)
    check("microwave evidence export produces CSV",
          "Evidence" in csv and len(csv.splitlines()) > 3, f"{len(csv.splitlines())} lines")
except Exception as exc:
    check("microwave engine analyze() runs", False, f"{type(exc).__name__}: {exc}")

try:
    gs_layer = next(lyr for name, lyr in by_name.items() if "Ground/Earth Stations" in name)
    sat_layer = next(lyr for name, lyr in by_name.items() if name == "Satellites")
    if sat_layer.featureCount() == 0 or gs_layer.featureCount() == 0:
        # CelesTrak is a live public service and rate-limits; an empty layer is
        # the plugin's intended degrade path, not a defect. Report it as skipped
        # rather than passing a check that never ran.
        SKIPPED.append("satellite/earth-space engine (CelesTrak returned no elements this run)")
        print("  [SKIP] satellite/earth-space engine -- CelesTrak unavailable "
              f"(satellites={sat_layer.featureCount()}, stations={gs_layer.featureCount()})")
    else:
        gs_feat = next(gs_layer.getFeatures())
        sat_feat = next(sat_layer.getFeatures())
        sresult = satellite_earth_space.analyze((gs_layer, gs_feat), (sat_layer, sat_feat))
        check("satellite/earth-space engine analyze() runs", sresult is not None, type(sresult).__name__)
        plugin.dock.show_result(sresult)
        check("dock renders satellite result", bool(plugin.dock.browser.toHtml().strip()))
except Exception as exc:
    check("satellite/earth-space engine analyze() runs", False, f"{type(exc).__name__}: {exc}")

print("\n== 8. feature CSV export (provenance/disclosure) ==")
try:
    fcsv = export.feature_to_csv(entry.data, entry.latitude, entry.longitude)
    check("feature export produces CSV", len(fcsv.splitlines()) >= 2, f"{len(fcsv.splitlines())} lines")
    check("export carries source provenance and coverage note",
          "Open Government Licence" in fcsv and "snapshot, not a live query" in fcsv,
          "Source + Retrieved/Generated columns populated")
except Exception as exc:
    check("feature export produces CSV", False, f"{type(exc).__name__}: {exc}")

print("\n== 9. Qt6 / PyQt6 compatibility ==")
import subprocess  # noqa: E402

checker = subprocess.run(
    [sys.executable, os.path.join(PLUGIN_DIR, "tools", "check_qt6_enums.py")],
    capture_output=True, text=True)
check("unscoped-enum checker passes on the current tree", checker.returncode == 0,
      checker.stdout.strip().splitlines()[0] if checker.stdout else "")

try:
    from velorona.ui.param_dialog import ParamDialog  # noqa: E402
    dlg = ParamDialog(iface.mainWindow(), "probe", terrestrial.PARAM_SPEC,
                      terrestrial.build_params(entries))
    check("ParamDialog constructs under Qt6", dlg is not None,
          f"{len(terrestrial.PARAM_SPEC)} params")
    check("ParamDialog exposes the scoped accept code",
          dlg.exec is not None and dlg.DialogCode.Accepted is not None)
    check("ParamDialog.values() returns every param",
          set(dlg.values()) == {p["key"] for p in terrestrial.PARAM_SPEC}, str(list(dlg.values())))
    dlg.deleteLater()
except Exception as exc:
    check("ParamDialog constructs under Qt6", False, f"{type(exc).__name__}: {exc}")

print("\n== 10. ownership markers ==")
from velorona.core import layers as layer_helpers  # noqa: E402

owned = [lyr for lyr in project.mapLayers().values() if layer_helpers.is_velorona_owned(lyr)]
check("every plugin-created layer carries the ownership marker",
      len(owned) == len(project.mapLayers()), f"{len(owned)} of {len(project.mapLayers())}")
check("basemap carries the ownership marker",
      basemap is not None and layer_helpers.is_velorona_owned(basemap))
check("public data layers are marked persistent",
      all(layer_helpers.layer_lifecycle(lyr) == layer_helpers.LIFECYCLE_PERSISTENT
          for lyr in owned), "all persistent before analysis overlays")

# Build the evidence overlays the way an analysis run does.
plugin._update_terrain_layer(tresult)
plugin._update_weather_evidence_layers(mresult)
evidence = [lyr for lyr in project.mapLayers().values()
            if layer_helpers.layer_lifecycle(lyr) == layer_helpers.LIFECYCLE_EVIDENCE]
check("evidence overlays are marked evidence", len(evidence) == 3,
      f"{len(evidence)} evidence layers: {[l.name() for l in evidence]}")

print("\n== 11. unload lifecycle ==")
persistent_before = {lid for lid, lyr in project.mapLayers().items()
                     if layer_helpers.layer_lifecycle(lyr) == layer_helpers.LIFECYCLE_PERSISTENT}
try:
    plugin.unload()
    check("unload() completes without error", True)
except Exception as exc:
    check("unload() completes without error", False, f"{type(exc).__name__}: {exc}")

after = set(project.mapLayers())
check("persistent public-data layers survive unload",
      persistent_before <= after, f"{len(persistent_before & after)}/{len(persistent_before)} kept")
check("evidence overlays are removed on unload",
      not any(layer_helpers.layer_lifecycle(lyr) == layer_helpers.LIFECYCLE_EVIDENCE
              for lyr in project.mapLayers().values()))
check("viewport cache is cleared on unload", len(plugin._viewport_cache) == 0)

try:
    plugin.unload()  # idempotent: bare disconnects would raise here
    check("unload() is safe to call twice (defensive disconnects)", True)
except Exception as exc:
    check("unload() is safe to call twice (defensive disconnects)", False,
          f"{type(exc).__name__}: {exc}")


# ---------------------------------------------------------------------
# Velorona investigation workflow: idempotent loading, Records table,
# selection sync, and Fixed Service link -> weather evidence.
# ---------------------------------------------------------------------
print("\n== 12. idempotent Load Public Data ==")
from qgis.core import QgsVectorLayer  # noqa: E402

user_layer = QgsVectorLayer("Point?crs=EPSG:4326", "User's own sites", "memory")
project.addMapLayer(user_layer)
before = len(project.mapLayers())
plugin.action_load_public.trigger()
after_second = len(project.mapLayers())
plugin.action_load_public.trigger()
after_third = len(project.mapLayers())
check("repeat Load Public Data creates no duplicate layers",
      before == after_second == after_third, f"{before} -> {after_second} -> {after_third}")

from collections import Counter  # noqa: E402

counts = Counter(lyr.name() for lyr in project.mapLayers().values())
check("no Velorona layer name appears twice",
      not [n for n, k in counts.items() if k > 1], str([n for n, k in counts.items() if k > 1]))
check("unrelated user layer untouched by reload",
      any(lyr.name() == "User's own sites" for lyr in project.mapLayers().values()))
check("every Velorona layer has a stable source key",
      all(layer_helpers.layer_source_key(lyr)
          for lyr in project.mapLayers().values() if layer_helpers.is_velorona_owned(lyr)))

print("\n== 13. Records table ==")
records = plugin.dock.records
link_layer = layer_helpers.find_owned_layer(project, layer_helpers.SOURCE_FIXED_LINKS)
check("Records lists every loaded Velorona dataset", records.dataset_combo.count() == 6,
      f"{records.dataset_combo.count()} datasets")
check("Records opens on Fixed Service links", records.dataset_combo.currentData() == layer_helpers.SOURCE_FIXED_LINKS)
check("Records rows match the layer's features",
      records.model.rowCount() == link_layer.featureCount(),
      f"{records.model.rowCount()} rows vs {link_layer.featureCount()} features")
headers = [records.model.headerData(c, Qt.Orientation.Horizontal) for c in range(records.model.columnCount())]
check("Records exposes the link engineering columns",
      {"Authorization", "Licensee", "Frequency (MHz)", "In service", "Source"} <= set(headers), str(headers))
check("Records is a view, not a copy -- rows map back to feature ids",
      records.model.feature_id(0) in set(link_layer.allFeatureIds()))

records.search_edit.setText("CTV INC")
qgs.processEvents()
filtered = records.proxy.rowCount()
check("Records search filters rows", 0 < filtered < records.model.rowCount(),
      f"{filtered} of {records.model.rowCount()}")
records.search_edit.setText("")
qgs.processEvents()

print("\n== 14. selection synchronisation ==")
records.view.selectRow(0)
qgs.processEvents()
check("table row selects the QGIS feature", link_layer.selectedFeatureCount() == 1,
      f"{link_layer.selectedFeatureCount()} selected")
check("table row activates the owning layer", iface.activeLayer() is link_layer)
check("table row opens the evidence drawer",
      getattr(plugin.dock._result, "kind", None) == "link-investigation")

some_fid = sorted(link_layer.allFeatureIds())[30]
link_layer.selectByIds([some_fid])
qgs.processEvents()
selected_rows = records.view.selectionModel().selectedRows()
synced_fid = (records.model.feature_id(records.proxy.mapToSource(selected_rows[0]).row())
              if selected_rows else None)
check("map selection highlights the matching table row", synced_fid == some_fid,
      f"table fid {synced_fid} vs map fid {some_fid}")

link_layer.removeSelection()
qgs.processEvents()
check("clearing selection shows the empty state",
      "Select a Velorona feature" in plugin.dock.browser.toPlainText())

print("\n== 15. Fixed Service link -> weather evidence ==")
link_layer.selectByIds([some_fid])
qgs.processEvents()
investigation = plugin.dock._result
check("link selection produces a link investigation",
      getattr(investigation, "kind", None) == "link-investigation")
check("investigation keeps the real link endpoints",
      investigation.entry.site_a_point is not None and investigation.entry.site_b_point is not None
      and investigation.entry.site_a_point != investigation.entry.site_b_point)

if investigation.exposure is None:
    SKIPPED.append(f"link weather evidence (live provider unavailable: {investigation.weather_error})")
    print(f"  [SKIP] live weather unavailable -- {investigation.weather_error}")
else:
    reps = list(investigation.exposure.representativeness.values())
    check("weather evidence is resolved for both endpoints", len(reps) == 2, f"{len(reps)} endpoints")
    check("Site A and Site B weather are distinct records",
          reps[0].site.id != reps[1].site.id and reps[0].site.latitude != reps[1].site.latitude)
    check("frequency came from the public record, not a default",
          investigation.param_origins.get("frequency_ghz", ("", ""))[0] == "Observed",
          str(investigation.param_origins.get("frequency_ghz")))
    check("polarization and fade margin are declared assumptions",
          investigation.param_origins["polarization"][0] == "Assumed"
          and investigation.param_origins["fade_margin_db"][0] == "Assumed")

    panel = plugin.dock.browser.toPlainText()
    for needed in ("Weather evidence", "Observed", "Independent evidence", "Representativeness",
                   "Calculated exposure", "Assessment", "Site A", "Site B",
                   "Temperature", "Wind", "Provenance and limitations"):
        check(f"evidence panel shows {needed}", needed in panel)
    check("humidity/pressure report Not determined rather than a value",
          "Humidity" in panel and "Pressure" in panel and "Not determined" in panel)
    check("hardware condition is never inferred from weather",
          "Hardware condition" in panel and "no hardware telemetry input to this analysis" in panel)
    check("pairing provenance preserved", "not inferred from proximity" in panel)
    check("weather disclaimer preserved", "not an outage prediction" in panel)

    print("\n== 16. evidence export matches the panel ==")
    link_csv = export.result_to_csv(investigation)
    import csv as _csv  # noqa: E402
    import io as _io  # noqa: E402
    body = [ln for ln in link_csv.splitlines() if not ln.startswith("#")]
    rows = list(_csv.reader(_io.StringIO("\n".join(body))))
    check("export uses the canonical evidence header", rows[0] == export.EVIDENCE_HEADER)
    vocab = sorted({r[1] for r in rows[1:] if len(r) > 1})
    check("export Type vocabulary stays Observed/Calculated/Inferred",
          vocab == ["Calculated", "Inferred", "Observed"], str(vocab))
    weather_rows = [r[0] for r in rows[1:] if "(Site A)" in r[0] or "(Site B)" in r[0]]
    check("export carries per-endpoint weather evidence", len(weather_rows) >= 10,
          f"{len(weather_rows)} endpoint weather rows")
    check("export records the hardware-condition limitation",
          any(r[0] == "Hardware condition" and "no hardware telemetry" in r[5] for r in rows[1:]))
    check("export records the pairing provenance",
          any(r[0] == "Link pairing" and "Not inferred from proximity" in r[5] for r in rows[1:]))

print("\n== 17. information architecture regressions ==")
import re as _re  # noqa: E402

from qgis.PyQt.QtWidgets import QTextBrowser  # noqa: E402

check("Velorona workspace CRS is EPSG:3857 under QGIS's own layer-tree behaviour",
      project.crs().authid() == "EPSG:3857", project.crs().authid())
check("canvas follows the workspace CRS",
      canvas.mapSettings().destinationCrs().authid() == "EPSG:3857")
check("initial extent computed in the workspace CRS, not a world view",
      1e6 < canvas.extent().width() < 0.6 * 40075016.7, f"{canvas.extent().width():,.0f} m")

# Satellites are off by default -- CelesTrak must not be contacted at load.
sat_layer = layer_helpers.find_owned_layer(project, layer_helpers.SOURCE_SATELLITES)
sat_node = project.layerTreeRoot().findLayer(sat_layer.id()) if sat_layer else None
check("Satellites layer exists but stays off by default",
      sat_layer is not None and sat_node is not None and not sat_node.isVisible())
check("no satellite fetch while the layer is hidden",
      sat_layer is not None and sat_layer.featureCount() == 0,
      f"{sat_layer.featureCount() if sat_layer else 'n/a'} features")

probe = QTextBrowser()
probe.setHtml(plugin.dock.browser.toHtml())
visible_text = probe.toPlainText()
leaked = _re.findall(r"<[a-zA-Z/][^>\n]{0,60}>", visible_text)
check("no raw HTML is shown to the user", not leaked, str(leaked[:3]))
check("parameter provenance renders as text, not markup",
      "span class" not in visible_text and "caveat" not in visible_text)

dock_w = plugin.dock.width()
win_w = iface.mainWindow().width()
check("investigation dock leaves the map the majority of the workspace",
      0.22 <= dock_w / win_w <= 0.42, f"dock {dock_w}px of {win_w}px ({dock_w / win_w * 100:.0f}%)")
check("dock stays user-resizable after its initial sizing",
      plugin.dock.maximumWidth() > 5000, f"max width {plugin.dock.maximumWidth()}")

if getattr(investigation, "exposure", None) is not None:
    reps_ = list(investigation.exposure.representativeness.values())
    check("Site A and Site B weather stay separate in the panel",
          visible_text.count("Observed") >= 2 and reps_[0].site.id != reps_[1].site.id)
    check("evidence hierarchy present in order",
          visible_text.find("Endpoints") < visible_text.find("Weather evidence")
          < visible_text.find("Calculated exposure") < visible_text.find("Assessment"))

print("\n== 18. layer hierarchy, selection scale, dock ==")
import requests as _requests  # noqa: E402

root_children = [c.name() for c in project.layerTreeRoot().children()]
check("basemap stays at the bottom of the stack",
      root_children and root_children[-1] == BASEMAP_NAME, str(root_children))
velorona_group = next((c for c in project.layerTreeRoot().children() if c.name() == "Velorona"), None)
group_order = [c.name() for c in velorona_group.children()] if velorona_group else []
check("Infrastructure comes before Space",
      group_order.index("Infrastructure") < group_order.index("Space") if
      {"Infrastructure", "Space"} <= set(group_order) else False, str(group_order))
check("Velorona groups are Infrastructure, Space, My Data, Evidence in order",
      group_order == ["Infrastructure", "Space", "My Data", "Evidence"], str(group_order))

check("exactly one Velorona dock exists",
      sum(1 for d in iface.docks if d.objectName() == "VeloronaDock") == 1,
      f"{len(iface.docks)} docks registered")
check("dock has a stable object name so QGIS can reopen it",
      plugin.dock.objectName() == "VeloronaDock")
plugin.dock.hide()
plugin.show_panel()
check("Show Velorona Panel reopens the same dock without creating another",
      plugin.dock.isVisible() and sum(1 for d in iface.docks if d.objectName() == "VeloronaDock") == 1)

link_ids = sorted(link_layer.allFeatureIds())
_real_get = _requests.get
http_calls = {"n": 0}


def _counting_get(url, *a, **kw):
    http_calls["n"] += 1
    return _real_get(url, *a, **kw)


_requests.get = _counting_get
try:
    http_calls["n"] = 0
    link_layer.selectByIds(link_ids[:4])
    qgs.processEvents()
    summary = plugin.dock._result
    check("two or more links produce a selection summary, not repeated investigations",
          summary.kind == "selection-summary", getattr(summary, "kind", "?"))
    check("summary counts the selection", summary.count == 4, str(summary.count))
    check("summary lists the selected records", len(summary.rows) == 4, f"{len(summary.rows)} rows")
    check("summary aggregates licensees from the records", len(summary.licensees) >= 1)
    check("multi-selection issues no weather requests", http_calls["n"] == 0, f"{http_calls['n']} requests")
    multi_text = plugin.dock.browser.toPlainText()
    check("summary offers endpoint evidence only for a single link",
          "single link is selected" in multi_text)
    check("summary renders no per-link weather sections",
          "Independent evidence" not in multi_text)

    http_calls["n"] = 0
    t_large = time.monotonic()
    link_layer.selectAll()
    qgs.processEvents()
    large_seconds = time.monotonic() - t_large
    large = plugin.dock._result
    check("whole-layer selection stays a summary", large.kind == "selection-summary")
    check("whole-layer selection counts every record", large.count == link_layer.featureCount(),
          f"{large.count:,}")
    check("whole-layer selection issues no weather requests", http_calls["n"] == 0,
          f"{http_calls['n']} requests")
    # These two used to assert the opposite: that a whole-layer selection was
    # scan-capped at 2,000 and captured no rows at all. Both were consequences
    # of one shared cap sized for the Records *widget* (25.5s to draw 16,956
    # rows), not for reading them (0.31s). The budgets are separate now, so the
    # whole layer is both fully scanned and fully exportable -- what must still
    # hold is that none of it is *drawn*.
    check("whole-layer selection captures every record for export",
          len(large.rows) == large.count, f"{len(large.rows):,} rows of {large.count:,}")
    check("whole-layer selection scans every record for the aggregates",
          large.scanned == large.count, f"scanned {large.scanned:,} of {large.count:,}")
    check("whole-layer selection is still never drawn into the evidence table",
          large.count > plugin_module.SELECTION_TABLE_LIMIT
          and "<table class='grid'>" not in plugin.dock.browser.toHtml(),
          f"count {large.count:,} > table cap {plugin_module.SELECTION_TABLE_LIMIT}")
    check("whole-layer selection does not freeze the UI", large_seconds < 3.0,
          f"{large_seconds:.2f}s")
    check("whole-layer selection tells the user to narrow it",
          "too large" in plugin.dock.browser.toPlainText())
finally:
    _requests.get = _real_get

link_layer.selectByIds(link_ids[:3])
qgs.processEvents()
sel_rows = plugin.dock.records.view.selectionModel().selectedRows()
check("map multi-selection highlights the matching Records rows", len(sel_rows) == 3,
      f"{len(sel_rows)} rows highlighted")

link_layer.selectByIds([link_ids[0]])
qgs.processEvents()
check("returning to one link restores the detailed investigation",
      plugin.dock._result.kind == "link-investigation")

from velorona.ui import theme as _theme  # noqa: E402

check("Velorona theme uses the product's own accent blue", _theme.ACCENT == "#5F98D1")
check("dock chrome is themed, not left to a light default",
      "veloronaRoot" in plugin.dock.widget().objectName() or
      plugin.dock.widget().objectName() == "veloronaRoot")
check("evidence report paints its own dark surface",
      _theme.BG in _theme.report_stylesheet() and "background" in _theme.report_stylesheet())
check("no hard-coded light background in Velorona widgets",
      "#fff" not in _theme.widget_stylesheet().lower())

print("\n== 19. map readability, theme, network context ==")
from qgis.PyQt.QtGui import QPalette  # noqa: E402
from qgis.PyQt.QtWidgets import QApplication  # noqa: E402

from velorona.core import basemap_labels, network_context  # noqa: E402
from velorona.plugin import BASEMAP_NAME  # noqa: E402

# 1. the host theme is the user's, never written by Velorona
plugin_source = open(os.path.join(PLUGIN_DIR, "plugin.py")).read()
theme_source = open(os.path.join(PLUGIN_DIR, "ui", "theme.py")).read()
check("Velorona never writes a QGIS setting",
      "QgsSettings" not in plugin_source and "setValue" not in theme_source)
check("Velorona never switches the QGIS UI theme",
      "setUITheme" not in plugin_source and "UITheme" not in theme_source)

# 2/3. readable in both host themes
dark_tokens = _theme.tokens(True)
light_tokens = _theme.tokens(False)


def _lum(hex_color):
    """WCAG relative luminance -- sRGB channels must be linearised first."""
    hex_color = hex_color.lstrip("#")
    channels = []
    for i in (0, 2, 4):
        c = int(hex_color[i:i + 2], 16) / 255
        channels.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def _contrast(fg, bg):
    l1, l2 = sorted((_lum(fg), _lum(bg)), reverse=True)
    return (l1 + 0.05) / (l2 + 0.05)


check("dark ramp keeps body text readable",
      _contrast(dark_tokens["text"], dark_tokens["bg"]) >= 7.0,
      f"contrast {_contrast(dark_tokens['text'], dark_tokens['bg']):.1f}:1")
check("light ramp keeps body text readable",
      _contrast(light_tokens["text"], light_tokens["bg"]) >= 7.0,
      f"contrast {_contrast(light_tokens['text'], light_tokens['bg']):.1f}:1")
check("muted text stays legible in both ramps",
      _contrast(dark_tokens["text_muted"], dark_tokens["bg"]) >= 4.5
      and _contrast(light_tokens["text_muted"], light_tokens["bg"]) >= 4.5,
      f"dark {_contrast(dark_tokens['text_muted'], dark_tokens['bg']):.1f}:1, "
      f"light {_contrast(light_tokens['text_muted'], light_tokens['bg']):.1f}:1")
check("faintest text still meets AA in both ramps",
      _contrast(dark_tokens["text_faint"], dark_tokens["bg"]) >= 4.5
      and _contrast(light_tokens["text_faint"], light_tokens["bg"]) >= 4.5,
      f"dark {_contrast(dark_tokens['text_faint'], dark_tokens['bg']):.1f}:1, "
      f"light {_contrast(light_tokens['text_faint'], light_tokens['bg']):.1f}:1")
check("brand accent is identical in both host themes",
      dark_tokens["accent"] == light_tokens["accent"] == _theme.ACCENT)
check("map appearance is Velorona's own control, not a QGIS theme",
      hasattr(plugin, "set_map_appearance") and hasattr(plugin.dock, "appearance_combo"))

# 4/5. geographic orientation at sensible scales, without flooding
basemap = next(l for l in project.mapLayers().values() if l.name() == BASEMAP_NAME)
check("basemap carries geographic labels", basemap.labelsEnabled())
styles = basemap.labeling().styles()
check("labels are scale-tiered", len(styles) == len(basemap_labels.TIERS), f"{len(styles)} tiers")
by_name = {st.styleName(): st for st in styles}
check("countries label at continental zoom only",
      by_name["country"].minZoomLevel() == 0 and by_name["country"].maxZoomLevel() <= 4)
check("provinces label at wide zoom", by_name["province"].maxZoomLevel() <= 6)
check("lakes and seas are labelled", "water" in by_name
      and by_name["water"].layerName() == basemap_labels.WATER_LAYER)
check("towns only appear when zoomed in", by_name["town"].minZoomLevel() >= 10)
check("city tiers are rank-limited so labels cannot flood",
      '"rank" <=' in by_name["city-wide"].filterExpression()
      and '"rank" <=' in by_name["city"].filterExpression())
check("only place and water names are labelled, not roads or POIs",
      {st.layerName() for st in styles} == {basemap_labels.PLACE_LAYER, basemap_labels.WATER_LAYER})
check("duplicate labels across tile seams are removed",
      all(st.labelSettings().thinningSettings().allowDuplicateRemoval() for st in styles))

# 6. selected link stays dominant: context is a softer, separate overlay
hub_index = network_context.build_endpoint_index(link_layer)
hub_key, hub_fids = max(hub_index.items(), key=lambda kv: len(kv[1]))
http_calls = {"n": 0}
_real_get2 = _requests.get


def _count_get(url, *a, **kw):
    http_calls["n"] += 1
    return _real_get2(url, *a, **kw)


_requests.get = _count_get
try:
    link_layer.selectByIds([hub_fids[0]])
    qgs.processEvents()
    weather_calls = http_calls["n"]
    investigation2 = plugin.dock._result
    check("shared-endpoint links are found from the record",
          (investigation2.connected_site_a + investigation2.connected_site_b) > 0,
          f"A={investigation2.connected_site_a} B={investigation2.connected_site_b}")
    context_layer = plugin.network_context_layer
    check("connected links are drawn as a separate context overlay",
          context_layer is not None and context_layer.featureCount() > 0,
          f"{context_layer.featureCount() if context_layer else 0} features")
    check("context overlay is an evidence layer, cleaned with the rest",
          layer_helpers.layer_lifecycle(context_layer) == layer_helpers.LIFECYCLE_EVIDENCE)
    check("selected link is not redrawn by the context overlay",
          context_layer.featureCount() <= network_context.MAX_CONNECTED)

    http_calls["n"] = 0
    link_layer.selectByIds([hub_fids[1]])
    qgs.processEvents()
    check("connected-link context issues no extra weather requests",
          http_calls["n"] <= weather_calls,
          f"{http_calls['n']} requests for one link's weather, none per connected link")
finally:
    _requests.get = _real_get2

# 8. proximity must never create a connection
near_a = network_context.endpoint_key(50.410560, -104.617220)
near_b = network_context.endpoint_key(50.410999, -104.617220)   # ~49 m away
check("endpoints ~49 m apart are not treated as shared", near_a != near_b, f"{near_a} vs {near_b}")
probe_feature = next(link_layer.getFeatures())
probe_ends = network_context._feature_endpoints(probe_feature)
nudged = (round(probe_ends[0][0] + 0.0005, 6), probe_ends[0][1])   # ~55 m away
nearby_only_index = {nudged: [probe_feature.id() + 99999]}
nearby_result = network_context.connected_links(nearby_only_index, probe_feature)
check("a link 55 m away is not reported as connected",
      not nearby_result["site_a"] and not nearby_result["site_b"],
      f"{nearby_result}")

panel2 = plugin.dock.browser.toPlainText()
check("network context states it is spatial context only",
      "No fault propagation is inferred" in panel2)
lowered = panel2.lower()
check("the outage disclaimer is present and only ever negated",
      "not an outage prediction" in lowered
      and lowered.count("outage") == lowered.count("not an outage prediction"))
check("no causality or cascade claims in the panel",
      not any(word in lowered for word in ("root cause", "cascad", "will fail", "caused by")))

print("\n== 20. Velorona map appearance control ==")
check("light and dark styles come from the same tile source, different styles",
      "carto" in plugin_module.BASEMAP_STYLE_URL_LIGHT
      and "carto" in plugin_module.BASEMAP_STYLE_URL_DARK
      and plugin_module.BASEMAP_STYLE_URL_LIGHT != plugin_module.BASEMAP_STYLE_URL_DARK)
check("light style is Voyager, not the washed-out Positron",
      "voyager" in plugin_module.BASEMAP_STYLE_URL_LIGHT)
check("the appearance control offers exactly Dark and Light",
      [plugin.dock.appearance_combo.itemData(i) for i in range(plugin.dock.appearance_combo.count())]
      == ["dark", "light"])
check("Velorona defaults to its dark presentation",
      plugin_module.DEFAULT_MAP_APPEARANCE == "dark")

# switching must be free of side effects
layers_before = set(project.mapLayers())
crs_before = project.crs().authid()
records_before = plugin.dock.records.model.rowCount()
basemap_layer = layer_helpers.find_owned_layer(project, layer_helpers.SOURCE_BASEMAP)

plugin.set_map_appearance("light")
qgs.processEvents()
check("switching to light changes the map appearance", plugin.map_is_dark() is False)
check("panel follows the same appearance as the map", plugin.dock._dark is False)

http_calls = {"n": 0}
_real_get3 = _requests.get


def _count3(url, *a, **kw):
    http_calls["n"] += 1
    return _real_get3(url, *a, **kw)


_requests.get = _count3
try:
    plugin.set_map_appearance("dark")
    qgs.processEvents()
    plugin.set_map_appearance("light")
    qgs.processEvents()
    check("switching between cached styles issues no network requests",
          http_calls["n"] == 0, f"{http_calls['n']} requests")
finally:
    _requests.get = _real_get3

check("switching rebuilds no layers", set(project.mapLayers()) == layers_before)
check("switching does not touch the project CRS", project.crs().authid() == crs_before == "EPSG:3857")
check("switching does not reload records",
      plugin.dock.records.model.rowCount() == records_before)
check("basemap keeps its labels through an appearance switch",
      basemap_layer.labelsEnabled()
      and len(basemap_layer.labeling().styles()) == len(basemap_labels.TIERS))
check("label ink flips with the appearance",
      basemap_labels.DARK_INK["place"] != basemap_labels.LIGHT_INK["place"])
check("labels stay capped against a zoom-out flood",
      basemap_labels.MAX_LABELS_PER_TIER <= 60, str(basemap_labels.MAX_LABELS_PER_TIER))
check("labels prefer a Latin name to avoid slow font fallback",
      "name:latin" in basemap_labels.NAME_EXPRESSION)

# selection stays visible on whichever basemap is active
plugin.set_map_appearance("light")
qgs.processEvents()
light_selection = project.selectionColor().name().lower()
plugin.set_map_appearance("dark")
qgs.processEvents()
dark_selection = project.selectionColor().name().lower()
check("selected feature stays visible on the light map",
      light_selection == plugin_module.SELECTION_COLOR_LIGHT.lower(), light_selection)
check("dark map keeps the high-contrast selection colour",
      dark_selection == plugin_module.SELECTION_COLOR_DARK.lower(), dark_selection)
check("selection colours are brand or QGIS values, not invented",
      plugin_module.SELECTION_COLOR_LIGHT == "#224B75")

check("Velorona still never writes a QGIS setting or switches the UI theme",
      "QgsSettings" not in plugin_source and "setUITheme" not in plugin_source)

print("\n== 21. Fixed Service site clustering and licensee filter ==")
from qgis.core import (QgsPointClusterRenderer, QgsSingleSymbolRenderer,  # noqa: E402
                       QgsUnitTypes)

sites_layer = layer_helpers.find_owned_layer(project, layer_helpers.SOURCE_FIXED_SITES)
links_layer2 = layer_helpers.find_owned_layer(project, layer_helpers.SOURCE_FIXED_LINKS)

check("Fixed Service sites are clustered",
      isinstance(sites_layer.renderer(), QgsPointClusterRenderer))
check("Fixed Service links are never clustered",
      not isinstance(links_layer2.renderer(), QgsPointClusterRenderer))
check("cluster grouping radius matches the web map's maxClusterRadius",
      sites_layer.renderer().tolerance() == layer_helpers.CLUSTER_TOLERANCE_PX == 50)
check("cluster size tiers match the web map (32/40/48, capped)",
      (layer_helpers.CLUSTER_SIZE_SMALL_PX, layer_helpers.CLUSTER_SIZE_MEDIUM_PX,
       layer_helpers.CLUSTER_SIZE_LARGE_PX) == (32, 40, 48))
check("cluster count comes from the represented record count",
      "@cluster_size" in layer_helpers.CLUSTER_SIZE_EXPRESSION)
cluster_sym = layer_helpers.cluster_symbol(True)
check("cluster draws a disc plus the count", cluster_sym.symbolLayerCount() == 2)
check("cluster ink differs between light and dark",
      layer_helpers.CLUSTER_INK_DARK != layer_helpers.CLUSTER_INK_LIGHT)

# The cluster bubble is the web map's .marker-cluster-velorona, measured rather
# than approximated: a translucent accent disc under a low-alpha ring, not an
# opaque disc inside a bright one. These pin the properties that carry that --
# a regression to a solid fill or a full-alpha ring is the exact thing that
# made the QGIS bubble read heavier than the web map's.
def _rgba(spec):
    return tuple(int(part) for part in spec.split(","))


for _theme, _ink in (("dark", layer_helpers.CLUSTER_INK_DARK),
                     ("light", layer_helpers.CLUSTER_INK_LIGHT)):
    _fill, _stroke = _rgba(_ink["fill"]), _rgba(_ink["stroke"])
    check(f"{_theme}: cluster fill is translucent, so the basemap reads through",
          _fill[3] < 255, f"alpha {_fill[3]}/255")
    check(f"{_theme}: cluster ring is soft (low alpha), not a solid bright ring",
          _stroke[3] <= 80, f"alpha {_stroke[3]}/255")

check("cluster fill is the web map's own accent at its composited alpha",
      _rgba(layer_helpers.CLUSTER_INK_DARK["fill"])[:3] == (95, 152, 209)
      and _rgba(layer_helpers.CLUSTER_INK_DARK["fill"])[3] == 93,
      "rgba(95,152,209,0.12) over rgba(95,152,209,0.28) -> 0.366 = 93/255")
check("cluster ring is the web map's --accent-line at its own 0.24 alpha",
      _rgba(layer_helpers.CLUSTER_INK_DARK["stroke"]) == (153, 198, 243, 61))
check("cluster ring width matches the web map's 2px border",
      layer_helpers.CLUSTER_STROKE_WIDTH_PX == 2)
check("cluster count size matches the web map's 12px, not a larger point size",
      layer_helpers.CLUSTER_COUNT_SIZE_PX == 12)

# Disc, ring and count must share one unit, or the count drifts out of
# proportion to the bubble under DPI scaling instead of holding the web map's
# fixed 12px-in-32/40/48px ratio.
_disc, _count = cluster_sym.symbolLayer(0), cluster_sym.symbolLayer(1)
check("disc size, ring width and count size are all in screen pixels",
      _disc.sizeUnit() == _disc.strokeWidthUnit() == _count.sizeUnit()
      == QgsUnitTypes.RenderPixels)
check("the count is still bold, as the web map's font-weight: 700 is",
      "bold" in _count.fontStyle().lower(), _count.fontStyle())

# Translucency must not cost legibility: check the count against the fill as it
# actually composites over each basemap's land, not against the raw accent.
def _over(rgba, backdrop):
    a = rgba[3] / 255
    bg = tuple(int(backdrop.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    return "#%02X%02X%02X" % tuple(
        round(rgba[i] * a + bg[i] * (1 - a)) for i in range(3))


for _theme, _ink, _land in (("dark", layer_helpers.CLUSTER_INK_DARK, "#181E18"),
                            ("light", layer_helpers.CLUSTER_INK_LIGHT, "#FAF6F0")):
    _composite = _over(_rgba(_ink["fill"]), _land)
    _c = _contrast(_ink["text"], _composite)
    check(f"{_theme}: cluster count stays readable over the translucent disc (>= 4.5:1)",
          _c >= 4.5, f"{_c:.2f}:1 over {_composite}")

# licensee filter is built from the data, not hard-coded
combo = plugin.dock.records.licensee_combo
options = [combo.itemData(i) for i in range(combo.count())]
check("licensee list is data-driven, not hard-coded",
      combo.count() > 100 and options[0] == "", f"{combo.count()} options")
check("licensee list offers 'All' first", "All licensees" in combo.itemText(0))
source_licensees = {(f["licensee"] or "").strip() for f in sites_layer.getFeatures()}
check("every offered licensee exists in the loaded records",
      set(o for o in options if o) <= source_licensees)

unfiltered_total = sites_layer.featureCount()
http_calls = {"n": 0}
_real_get4 = _requests.get


def _count4(url, *a, **kw):
    http_calls["n"] += 1
    return _real_get4(url, *a, **kw)


_requests.get = _count4
try:
    expected = {}
    for name in ("Rogers Communications Canada Inc.", "Bell Mobility Inc."):
        expected[name] = sum(1 for f in sites_layer.getFeatures()
                             if (f["licensee"] or "").strip() == name)
    http_calls["n"] = 0
    plugin.set_licensee_filter("Rogers Communications Canada Inc.")
    qgs.processEvents()
    rogers_count = sites_layer.featureCount()
    check("Rogers filter shows only Rogers records",
          rogers_count == expected["Rogers Communications Canada Inc."] < unfiltered_total,
          f"{rogers_count:,} of {unfiltered_total:,}")
    check("every visible record belongs to the chosen licensee",
          all((f["licensee"] or "").strip() == "Rogers Communications Canada Inc."
              for f in sites_layer.getFeatures()))

    plugin.set_licensee_filter("Bell Mobility Inc.")
    qgs.processEvents()
    check("Bell filter shows only Bell records",
          sites_layer.featureCount() == expected["Bell Mobility Inc."],
          f"{sites_layer.featureCount():,}")

    plugin.set_licensee_filter("")
    qgs.processEvents()
    check("clearing the filter restores every record",
          sites_layer.featureCount() == unfiltered_total, f"{sites_layer.featureCount():,}")
    check("licensee switching issues no public-data requests",
          http_calls["n"] == 0, f"{http_calls['n']} requests")
finally:
    _requests.get = _real_get4

check("filtering creates no second dataset",
      layer_helpers.find_owned_layer(project, layer_helpers.SOURCE_FIXED_SITES) is sites_layer)
check("filtering leaves the links layer alone", links_layer2.subsetString() == "")
check("filtering does not touch the CRS", project.crs().authid() == "EPSG:3857")

# clustering must not leak into the evidence model
check("clustering adds no evidence kind",
      "cluster" not in str(sorted(getattr(export, "EVIDENCE_HEADER", []))).lower())
site_feature = next(sites_layer.getFeatures())
site_csv = export.feature_to_csv(
    {f.name(): site_feature[f.name()] for f in site_feature.fields()}, 0.0, 0.0)
check("raw site export is unchanged by clustering",
      "cluster" not in site_csv.lower() and "Open Government Licence" in site_csv)

# -- Multi-record selection export -------------------------------------------
# The workflow is EXPLORE -> SELECT -> ANALYZE -> EVIDENCE -> EXPORT, and it
# used to dead-end at EXPORT: a selection-summary had no branch in
# result_to_csv(), so it fell through to the satellite/earth-space
# NotExportable and the operator was refused with a message about an analysis
# they never ran. These pin the fix and the message that was wrong.
_sel = inspector.SelectionSummary(
    kind_label="Fixed Service sites", feature_kind="site", count=3, scanned=3,
    licensees=["Bell Mobility Inc.", "Rogers Communications Canada Inc."],
    frequency_range=(6175.0, 959.9375),
    extent_wgs84=(-79.9512, 43.1043, -78.8501, 44.2011),
    columns=["Site", "Licensee"],
    rows=[["Toronto A", "Bell Mobility Inc."], ["Toronto B", "Bell Mobility Inc."]],
    licensee_filter="Bell Mobility Inc.")

try:
    _sel_csv = export.result_to_csv(_sel)
    _sel_ok = True
except Exception as _exc:
    _sel_csv, _sel_ok = str(_exc), False

check("a multi-record selection exports at all (was NotExportable)", _sel_ok, _sel_csv[:90])
check("the selection export never claims to be a satellite result",
      "Earth-Space" not in _sel_csv and "geometry snapshot" not in _sel_csv)
check("preamble carries the active licensee filter",
      "Licensee filter: Bell Mobility Inc." in _sel_csv)
check("preamble states the filter is off when there is none",
      "Licensee filter: None -- all licensees" in export.result_to_csv(
          inspector.SelectionSummary(kind_label="sites", feature_kind="site", count=1,
                                     scanned=1, columns=["Site"], rows=[["A"]])))
check("preamble carries the selection extent in WGS84",
      "-79.95120, 43.10430, -78.85010, 44.20110" in _sel_csv)
check("preamble carries the record count", "Records selected: 3" in _sel_csv)
check("preamble carries a UTC generation timestamp",
      "Generated: " in _sel_csv and "+00:00" in _sel_csv)
check("preamble carries the distinct licensees", "Distinct licensees: 2" in _sel_csv)
check("frequency range keeps ISED's 4-decimal precision (not %g-rounded)",
      "959.9375" in _sel_csv and "959.938 " not in _sel_csv)
check("one row per selected record, under the Records table's own columns",
      "Site,Licensee" in _sel_csv and "Toronto A,Bell Mobility Inc." in _sel_csv)
check("the selection export states that O/C/I typing does not apply",
      "not applicable" in _sel_csv and "nothing here is inferred" in _sel_csv.lower())
check("the O/C/I evidence header is NOT imposed on a raw-record selection",
      ",".join(export.EVIDENCE_HEADER) not in _sel_csv)

# Above the listing limit the rows are never captured. The file must say so
# rather than shipping a header with no rows under it.
_sel_big = inspector.SelectionSummary(
    kind_label="Fixed Service sites", feature_kind="site", count=30000, scanned=25000,
    columns=["Site", "Licensee"], rows=[], listing_limit=25000)
_big_csv = export.result_to_csv(_sel_big)
check("an over-limit selection still exports", bool(_big_csv))
check("an over-limit selection says the listing was omitted and why",
      "Per-record listing: Not determined" in _big_csv and "25,000-record export limit" in _big_csv)
check("the omission message names the export cap, not the on-screen cap",
      "25,000-record export limit" in _big_csv and "200-record" not in _big_csv)
check("a partially scanned selection does not let its aggregates imply completeness",
      "describe the scanned subset only" in _big_csv)

# The genuinely-unexportable case must still refuse, with its own message.
class _SatResult:
    kind = "satellite-earth-space"


try:
    export.result_to_csv(_SatResult())
    _sat_refused, _sat_msg = False, ""
except export.NotExportable as _exc:
    _sat_refused, _sat_msg = True, str(_exc)
check("satellite/earth-space export still refuses", _sat_refused)
check("and still refuses with its own correct message",
      "Earth-Space" in _sat_msg and "geometry snapshot" in _sat_msg)

# Single-record export must be untouched by this change: the same feature,
# routed through result_to_csv()'s "site" branch, must produce byte-identical
# output to the direct feature_to_csv() call above, modulo its timestamp line.
_site_entry = inspector.feature_to_entry(site_feature, "site")
_site_entry.latitude, _site_entry.longitude = 0.0, 0.0
_routed = export.result_to_csv(_site_entry)


def _drop_generated(text):
    return "\n".join(line for line in text.splitlines()
                      if not line.startswith("# Generated:"))


check("single-record site export is unchanged by the selection-export branch",
      _drop_generated(_routed) == _drop_generated(site_csv))
check("single-record export still uses the wide record header, not O/C/I",
      "Name / Licensee" in _routed and ",".join(export.EVIDENCE_HEADER) not in _routed)

# -- The three selection budgets are genuinely separate ----------------------
# They used to be one constant, which tied the export to the *rendering*
# budget: a 1,455-link regional selection could be summarised but not exported.
# Measured on the full dataset, capturing every row costs 0.31s while drawing
# them into the Records widget costs 25.5s -- so the caps must not be shared.
check("the export cap is far larger than the on-screen cap",
      plugin_module.SELECTION_LISTING_LIMIT > plugin_module.SELECTION_TABLE_LIMIT * 10,
      f"listing={plugin_module.SELECTION_LISTING_LIMIT:,} table={plugin_module.SELECTION_TABLE_LIMIT:,}")
check("the on-screen cap stays small enough to draw instantly",
      plugin_module.SELECTION_TABLE_LIMIT <= 200, plugin_module.SELECTION_TABLE_LIMIT)
# The capture happens inside the scan loop, so a scan cap below the listing cap
# would silently truncate the listing without anything saying so.
check("the scan cap cannot silently truncate the export listing",
      plugin_module.SELECTION_SCAN_LIMIT >= plugin_module.SELECTION_LISTING_LIMIT,
      f"scan={plugin_module.SELECTION_SCAN_LIMIT:,} listing={plugin_module.SELECTION_LISTING_LIMIT:,}")
check("the export cap clears the whole loaded dataset",
      plugin_module.SELECTION_LISTING_LIMIT >= sites_layer.featureCount(),
      f"cap={plugin_module.SELECTION_LISTING_LIMIT:,} sites={sites_layer.featureCount():,}")

# A real regional selection must now come back with every row.
_region = QgsRectangle(-80.10, 43.20, -79.10, 43.95)
_region_fids = [f.id() for f in links_layer2.getFeatures(QgsFeatureRequest().setFilterRect(_region))]
links_layer2.selectByIds(_region_fids)
_t0 = time.monotonic()
_region_summary = plugin._summarize_selection(links_layer2, "link", len(_region_fids))
_region_seconds = time.monotonic() - _t0
check("a regional selection is well past the old 200 cap",
      len(_region_fids) > 1000, f"{len(_region_fids):,} links")
check("a regional selection now captures every row for export",
      len(_region_summary.rows) == len(_region_fids),
      f"{len(_region_summary.rows):,} of {len(_region_fids):,}")
check("capturing a regional selection does not block the UI",
      _region_seconds < 1.0, f"{_region_seconds:.3f}s")
_region_csv = export.result_to_csv(_region_summary)
check("the regional export carries one data row per selected link",
      len([ln for ln in _region_csv.splitlines()
           if ln and not ln.startswith("#")]) == len(_region_fids) + 1,
      f"{len(_region_fids):,} rows + header")
check("the regional export no longer claims the listing was omitted",
      "Per-record listing: Not determined" not in _region_csv)
links_layer2.removeSelection()

# -- Licensees preamble line is readable, and the count stays exact ----------
_many = [f"Licensee Number {i:02d} Communications Limited" for i in range(46)]
_many_csv = export.result_to_csv(inspector.SelectionSummary(
    kind_label="Fixed Service links", feature_kind="link", count=1455, scanned=1455,
    licensees=_many, columns=["Authorization"], rows=[["x"]]))
_lic_line = [ln for ln in _many_csv.splitlines() if ln.startswith("# Licensees:")][0]
check("the distinct-licensee count is never truncated",
      "Distinct licensees: 46" in _many_csv)
check("the licensee names line is truncated to a readable length",
      len(_lic_line) < 520, f"{len(_lic_line)} chars")
check("the truncated licensee line states the exact remainder",
      "... and " in _lic_line and "more" in _lic_line)
check("the shown-plus-remainder always reconciles to the exact total",
      _lic_line.count(" | ") + 1 + int(_lic_line.split("... and ")[1].split(" more")[0].replace(",", ""))
      == 46)
check("a short licensee list is not truncated at all",
      "... and " not in export.result_to_csv(inspector.SelectionSummary(
          kind_label="links", feature_kind="link", count=2, scanned=2,
          licensees=["Bell Mobility Inc.", "TeraGo Networks Inc."],
          columns=["Authorization"], rows=[["x"]])))

# -- Numeric precision in the preamble: no silent truncation anywhere --------
_prec_csv = export.result_to_csv(inspector.SelectionSummary(
    kind_label="links", feature_kind="link", count=1, scanned=1,
    frequency_range=(933.5125, 85125.0), extent_wgs84=(-80.49605, 43.05111, -78.39844, 44.09472),
    columns=["Authorization"], rows=[["x"]]))
check("preamble frequencies keep ISED's full published precision",
      "933.5125" in _prec_csv and "85125.0" in _prec_csv)
check("preamble extent keeps 5 decimal places, matching the source records",
      "-80.49605, 43.05111, -78.39844, 44.09472" in _prec_csv)

# -- Operator inputs must survive into the evidence rows intact --------------
# Precision is set by whoever produced the number: an input is reproduced
# exactly, a calculated value is rounded to what its method justifies. These
# four previously lost precision on ordinary values in ordinary use, inside
# the typed O/C/I rows -- the one part of the file an operator can check
# against what they typed.
for _value, _was in ((0.9599375, "1.0"), (7.25, "7.2"), (30.5, "30"), (32.5, "32")):
    check(f"an input of {_value} is reproduced exactly, not as {_was}",
          export._exact(_value) == repr(float(_value)), export._exact(_value))
check("an ordinary whole value does not gain spurious digits",
      export._exact(18.0) == "18.0", export._exact(18.0))
check("no operator-input quantity is rounded in export.py any more",
      not _re.search(r"(site_[ab]_height_m|frequency_ghz|fade_margin_db):\.[0-9]",
                    open(os.path.join(PLUGIN_DIR, "core", "export.py")).read()))
check("lat/lon keep their source-matched :.5f (the rule this generalises)",
      ":.5f" in open(os.path.join(PLUGIN_DIR, "core", "export.py")).read())
# Calculated values keep explicit rounding -- they must NOT use _exact().
check("calculated attenuation is still explicitly rounded, not round-tripped",
      "predicted_attenuation_db:.2f" in open(os.path.join(PLUGIN_DIR, "core", "export.py")).read())
check("exposure ratio resolves which side of the fade margin it sits on",
      "exposure_ratio * 100:.1f" in open(os.path.join(PLUGIN_DIR, "core", "export.py")).read())

# -- Parameter bounds, each with a recorded basis ----------------------------
for _mod, _name in ((terrestrial, "terrestrial"), (microwave_exposure, "microwave")):
    for _p in _mod.PARAM_SPEC:
        if _p["type"] != "float":
            continue
        check(f"{_name}: {_p['key']} carries an explicit envelope",
              _p.get("min") is not None and _p.get("max") is not None,
              f"{_p.get('min')} to {_p.get('max')}")
        check(f"{_name}: {_p['key']}'s bound states where it comes from",
              len(_p.get("basis", "")) > 40)
        check(f"{_name}: {_p['key']}'s default sits inside its own envelope",
              _p["min"] <= _p["default"] <= _p["max"], f"{_p['default']}")

check("the microwave frequency bound is the rain model's own tabulated range",
      (microwave_exposure.PARAM_SPEC[0]["min"], microwave_exposure.PARAM_SPEC[0]["max"])
      == (mw_physics.MIN_FREQ_GHZ, mw_physics.MAX_FREQ_GHZ),
      f"{mw_physics.MIN_FREQ_GHZ}-{mw_physics.MAX_FREQ_GHZ} GHz (ITU-R P.838-3)")
def _basis_is_honest(basis: str) -> bool:
    """A bound either names where it is derived from, or admits it is an
    engineering judgment. What it must never do is read as derived without a
    source."""
    b = basis.lower()
    if "not a derived bound" in b or "conservative engineering limit" in b:
        return True                                    # labelled as judgment
    return "derived" in b and any(src in b for src in ("itu-r", "raise", "aei_"))


check("every bound either names its source or admits it is a judgment call",
      all(_basis_is_honest(_p["basis"])
          for _m in (terrestrial, microwave_exposure) for _p in _m.PARAM_SPEC
          if _p["type"] == "float"),
      str([(_p["key"], _basis_is_honest(_p["basis"]))
           for _m in (terrestrial, microwave_exposure) for _p in _m.PARAM_SPEC
           if _p["type"] == "float"]))
check("the unbounded 0.1-100000.0 range is gone from the dialog",
      "setRange(0.1, 100000.0)" not in
      open(os.path.join(PLUGIN_DIR, "ui", "param_dialog.py")).read())

# The dialog must REFUSE an out-of-range value, never clamp it: a clamped
# value is a number the operator did not choose, reported back as if they had.
_dlg = ParamDialog(iface.mainWindow(), "bounds probe",
                   microwave_exposure.PARAM_SPEC,
                   {"frequency_ghz": 18.0, "polarization": "V", "fade_margin_db": 32.0})
check("a valid parameter set reports nothing out of range", not _dlg.out_of_range())
_dlg._widgets["fade_margin_db"].setValue(100000.0)
_clamped = _dlg._widgets["fade_margin_db"].value()
check("the spin box cannot silently clamp an entry onto the limit itself",
      _clamped != microwave_exposure.PARAM_SPEC[2]["max"], f"clamped to {_clamped:g}")
_bad = _dlg.out_of_range()
check("an out-of-range fade margin is detected, not accepted", len(_bad) == 1, str(_bad[:1]))
check("the refusal names the offending value and its envelope",
      _bad[0][1] > _bad[0][3] and _bad[0][2] == 0.1 and _bad[0][3] == 100.0)
check("the refusal carries the basis, not just the numbers", "derived" in _bad[0][4])
_dlg._widgets["fade_margin_db"].setValue(32.0)
_dlg._widgets["frequency_ghz"].setValue(0.5)   # below ITU-R P.838-3's floor
check("a sub-1 GHz frequency is refused for the rain model",
      len(_dlg.out_of_range()) == 1 and _dlg.out_of_range()[0][2] == mw_physics.MIN_FREQ_GHZ)
_dlg.deleteLater()

# normal links stay subordinate to the selection in both appearances
check("normal link ink differs per appearance",
      layer_helpers.LINK_INK_DARK != layer_helpers.LINK_INK_LIGHT)
check("normal links never use the selection colour",
      layer_helpers.LINK_INK_LIGHT["color"] != plugin_module.SELECTION_COLOR_LIGHT)

# Velorona must not own native QGIS panels
check("Velorona never references the Processing Toolbox",
      "processing" not in plugin_source.lower() and "toolbox" not in plugin_source.lower())

# No risk/health/outage *claim* introduced by clustering. Whole-word matching,
# because "fault" is a substring of "default"; and the one line that names
# those concepts is the disclaimer saying none of them are implied.
cluster_source = open(os.path.join(PLUGIN_DIR, "core", "layers.py")).read()
claim_lines = [
    line for line in cluster_source.splitlines()
    if _re.search(r"\b(risk|health|outage|fault)\b", line, _re.IGNORECASE)
    and "is implied" not in line
]
check("clustering makes no risk/health/outage claim", not claim_lines, str(claim_lines[:2]))
check("the cluster count is explicitly disclaimed as a record count",
      "nothing" in cluster_source.lower() and "is implied by it" in cluster_source)

print("\n== 22. basemap vegetation retint (map polish pass 1) ==")
from qgis.core import QgsMapBoxGlStyleConverter as _Conv, QgsSymbolLayer as _SL  # noqa: E402
import requests as _rq  # noqa: E402
from velorona.core import layers as _L  # noqa: E402

for _dark, _url, _label in (
    (True, plugin_module.BASEMAP_STYLE_URL_DARK, "dark"),
    (False, plugin_module.BASEMAP_STYLE_URL_LIGHT, "light"),
):
    _conv = _Conv()
    _conv.convert(_rq.get(_url, timeout=25).text)
    _renderer = _conv.renderer()
    _n = _L.retint_basemap_vegetation(_renderer, _dark)
    check(f"{_label}: retint touches the landcover/park style rules", _n >= 3, f"{_n} rules")

    _target = _L.BASEMAP_VEGETATION_FILL_DARK if _dark else _L.BASEMAP_VEGETATION_FILL_LIGHT
    _seen_layers = set()
    for _st in _renderer.styles():
        if _st.layerName() not in _L.BASEMAP_VEGETATION_LAYERS:
            continue
        _seen_layers.add(_st.layerName())
        _sym = _st.symbol()
        _sl = _sym.symbolLayer(0)
        check(f"{_label}: {_st.layerName()} static fill matches the target colour",
              _sl.fillColor().name() == _target.name(),
              f"{_sl.fillColor().name()} vs {_target.name()}")
        # This is the actual bug this pass fixed: CARTO's converted style holds
        # PropertyFillColor/PropertyStrokeColor as *data-defined* zoom-interpolated
        # expressions, which QGIS evaluates instead of the static colour at paint
        # time -- a static-only fix was verified (by an isolated render test with
        # an extreme colour) to leave the map completely unchanged.
        _ddp = _sl.dataDefinedProperties()
        check(f"{_label}: {_st.layerName()} data-defined fill colour is neutralised",
              not _ddp.isActive(_SL.PropertyFillColor)
              or _ddp.property(_SL.PropertyFillColor).expressionString() == "",
              "checked via evaluated value below")
        _ctx_val = _ddp.value(_SL.PropertyFillColor, __import__("qgis.core", fromlist=["QgsExpressionContext"]).QgsExpressionContext(), _target)
        check(f"{_label}: {_st.layerName()} data-defined property now evaluates to the target",
              _ctx_val == _target or (hasattr(_ctx_val, "name") and _ctx_val.name() == _target.name()),
              str(_ctx_val))
    check(f"{_label}: both landcover and park were reached",
          {"landcover", "park"} <= _seen_layers, str(_seen_layers))

check("vegetation retint does not touch water/boundary/waterway/transportation",
      not any(name in cluster_source for name in
              ("retint_basemap_vegetation(renderer, water", "retint water", "retint boundary")))
check("vegetation retint adds no new HTTP dependency",
      "requests.get" not in open(os.path.join(PLUGIN_DIR, "core", "layers.py")).read())

print("\n== 23. label restraint, calibrated to the Velorona Web Map ==")
# The Web Map renders OSM raster under a CSS invert/contrast filter; pushing a
# real tile through that same chain numerically puts its brightest label text at
# rgb(174,174,174). These checks keep Velorona's labels in that quiet register
# instead of drifting back toward the near-white, 16.3:1 city ink they had.
from qgis.PyQt.QtGui import QColor as _QC  # noqa: E402

def _lin(c):
    c = c / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

def _lum(hexs):
    c = _QC(hexs)
    return 0.2126 * _lin(c.red()) + 0.7152 * _lin(c.green()) + 0.0722 * _lin(c.blue())

def _contrast(a, b):
    l1, l2 = sorted((_lum(a), _lum(b)), reverse=True)
    return (l1 + 0.05) / (l2 + 0.05)

# Compared by relative luminance, not by channel value: the Web Map's text is a
# neutral grey while Velorona's ink is blue-tinted, so a per-channel comparison
# would reject a correctly-muted blue purely for its blue channel (it did).
_WEB_MAP_LUM = 0.4233   # rgb(174,174,174), the Web Map's brightest label text

def _lum_ratio(hexs):
    return _lum(hexs) / _WEB_MAP_LUM

check("every tier carries its own label cap (no single flat ceiling)",
      all(len(t) == 9 and isinstance(t[8], int) for t in basemap_labels.TIERS))
check("no tier may draw as many labels as the old flat cap of 40",
      all(t[8] < 40 for t in basemap_labels.TIERS),
      str([(t[0], t[8]) for t in basemap_labels.TIERS]))
_caps = {t[0]: t[8] for t in basemap_labels.TIERS}
check("the province tier is the most tightly capped of the wide-zoom tiers",
      _caps["province"] <= _caps["city"], f"province={_caps['province']} city={_caps['city']}")
check("label point sizes stay restrained (<= 9 pt)",
      all(t[3] <= 9.0 for t in basemap_labels.TIERS),
      str([(t[0], t[3]) for t in basemap_labels.TIERS]))
check("dark label ink sits in the Web Map's brightness register, not above it",
      all(_lum_ratio(basemap_labels.DARK_INK[k]) <= 1.35
          for k in ("place", "place_muted", "water")),
      str({k: f"{_lum_ratio(basemap_labels.DARK_INK[k]):.2f}x"
           for k in ("place", "place_muted", "water")}))
check("the previous near-white city ink would now be rejected",
      _lum_ratio("#E4EDF5") > 1.35, f"{_lum_ratio('#E4EDF5'):.2f}x")
check("the muted tiers sit below the Web Map's brightest text, not above it",
      _lum_ratio(basemap_labels.DARK_INK["place_muted"]) < 1.0
      and _lum_ratio(basemap_labels.DARK_INK["water"]) < 1.0)
check("dark city ink is muted well below its former 16.3:1",
      _contrast(basemap_labels.DARK_INK["place"], "#0E0E0E") < 12.0,
      f"{_contrast(basemap_labels.DARK_INK['place'], '#0E0E0E'):.2f}:1")
for _k in ("place", "place_muted", "water"):
    check(f"light-theme {_k} ink stays readable (>= 4.5:1)",
          _contrast(basemap_labels.LIGHT_INK[_k], "#FBF8F3") >= 4.5,
          f"{_contrast(basemap_labels.LIGHT_INK[_k], '#FBF8F3'):.2f}:1")
    check(f"dark-theme {_k} ink stays readable (>= 4.5:1)",
          _contrast(basemap_labels.DARK_INK[_k], "#0E0E0E") >= 4.5,
          f"{_contrast(basemap_labels.DARK_INK[_k], '#0E0E0E'):.2f}:1")
# The QgsTextFormat must stay referenced: buffer() hands back a reference into
# it, so calling _text_format(...).buffer() on a temporary reads freed memory
# and segfaults the interpreter -- it did, before this was split in two.
_fmt = basemap_labels._text_format(9.0, "#B4C2D0", "#05090C")
_buf = _fmt.buffer()
check("the label halo is thinned, not a heavy collar", _buf.size() <= 0.7, f"{_buf.size()} mm")
check("the label halo is still enabled (names cross water and roads)", _buf.enabled())
check("duplicate removal survives this pass",
      all(st.labelSettings().thinningSettings().allowDuplicateRemoval()
          for st in basemap_labels.place_labeling(True).styles()))
check("geographic coverage is unchanged (same six tiers, same source layers)",
      {t[0] for t in basemap_labels.TIERS} == {"country", "province", "water",
                                               "city-wide", "city", "town"})

passed = sum(1 for _, ok, _ in RESULTS if ok)
for s_ in SKIPPED:
    print(f"  SKIPPED: {s_}")
print(f"\n===== {passed}/{len(RESULTS)} checks passed =====")
for name, ok, detail in RESULTS:
    if not ok:
        print(f"  FAILED: {name} -- {detail}")

qgs.exitQgis()
sys.exit(0 if passed == len(RESULTS) else 1)
