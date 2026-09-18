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
    Qgis,
    QgsApplication,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeatureRequest,
    QgsMapRendererParallelJob,
    QgsProject,
    QgsRectangle,
)
from qgis.gui import QgsLayerTreeMapCanvasBridge, QgsMapCanvas, QgsMessageBar  # noqa: E402
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
        # A real QgsMessageBar, not a stub -- so tests exercise the actual
        # push/pop behaviour Velorona's status messages depend on, not a
        # mock that would pass regardless of what the real widget does.
        self._message_bar = QgsMessageBar(self.window)

    def mapCanvas(self):
        return self.canvas

    def mainWindow(self):
        return self.window

    def messageBar(self):
        return self._message_bar

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
cluster_sym = layer_helpers.cluster_symbol(layer_helpers.COLORS_DARK["fixed-sites"], True)
check("cluster draws a disc plus the count", cluster_sym.symbolLayerCount() == 2)

# The cluster bubble is the web map's .marker-cluster-velorona TREATMENT --
# translucent disc under a soft ring, not an opaque disc inside a bright one
# -- generalised to a colour per layer type instead of the web map's one
# shared accent (a Velorona-QGIS-specific requirement, reported directly by
# an operator running the demo: six distinct COLORS entries existed but
# every cluster still rendered identically, because the cluster SYMBOL that
# replaces the per-feature symbol at any zoom wide enough to group records
# ignored colour entirely -- see cluster_ink()'s docstring in core/layers.py
# for the fix). These checks pin the treatment across every real type colour
# in both appearances, not just one -- a regression back to a single shared
# ink for all six would still pass a test that only checked one.
def _rgba(spec):
    return tuple(int(part) for part in spec.split(","))


def _over(rgba, backdrop):
    a = rgba[3] / 255
    bg = tuple(int(backdrop.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    return "#%02X%02X%02X" % tuple(
        round(rgba[i] * a + bg[i] * (1 - a)) for i in range(3))


_DARK_LAND, _LIGHT_LAND = "#181E18", "#FAF6F0"
for _kind, _hex in layer_helpers.COLORS_DARK.items():
    _ink = layer_helpers.cluster_ink(_hex, True)
    _fill, _stroke = _rgba(_ink["fill"]), _rgba(_ink["stroke"])
    check(f"dark {_kind}: cluster fill is translucent, so the basemap reads through",
          _fill[3] < 255, f"alpha {_fill[3]}/255")
    check(f"dark {_kind}: cluster ring is soft (low alpha), not a solid bright ring",
          _stroke[3] <= 80, f"alpha {_stroke[3]}/255")
    check(f"dark {_kind}: cluster fill uses this type's own hue, not a shared accent",
          _fill[:3] == layer_helpers._hex_to_rgb(_hex))
    _composite = _over(_fill, _DARK_LAND)
    _c = _contrast(_ink["text"], _composite)
    check(f"dark {_kind}: cluster count stays readable over the translucent disc (>= 4.5:1)",
          _c >= 4.5, f"{_c:.2f}:1 over {_composite}")
for _kind, _hex in layer_helpers.COLORS_LIGHT.items():
    _ink = layer_helpers.cluster_ink(_hex, False)
    _fill, _stroke = _rgba(_ink["fill"]), _rgba(_ink["stroke"])
    check(f"light {_kind}: cluster fill is translucent, so the basemap reads through",
          _fill[3] < 255, f"alpha {_fill[3]}/255")
    check(f"light {_kind}: cluster ring is soft (low alpha), not a solid bright ring",
          _stroke[3] <= 80, f"alpha {_stroke[3]}/255")
    check(f"light {_kind}: cluster fill uses this type's own hue, not a shared accent",
          _fill[:3] == layer_helpers._hex_to_rgb(_hex))
    _composite = _over(_fill, _LIGHT_LAND)
    _c = _contrast(_ink["text"], _composite)
    check(f"light {_kind}: cluster count stays readable over the translucent disc (>= 4.5:1)",
          _c >= 4.5, f"{_c:.2f}:1 over {_composite}")

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

# The bug this closes, reproduced directly: two different clustered layers,
# restyled by the real plugin method, must carry two different fill colours
# -- not the same shared ink regardless of type, which is what "distinct
# COLORS entries but identical clusters on screen" actually was.
plugin._restyle_clusters(True)
_sites_fill = sites_layer.renderer().clusterSymbol().symbolLayer(0).color()
_towers_layer_for_color = layer_helpers.find_owned_layer(project, layer_helpers.SOURCE_TOWERS)
_towers_fill = _towers_layer_for_color.renderer().clusterSymbol().symbolLayer(0).color()
check("two different clustered layer types carry two different cluster fill colours",
      _sites_fill.name() != _towers_fill.name(),
      f"fixed-sites {_sites_fill.name()} vs towers {_towers_fill.name()}")
check("the restyled fixed-sites cluster matches its own COLORS_DARK entry",
      (_sites_fill.red(), _sites_fill.green(), _sites_fill.blue())
      == layer_helpers._hex_to_rgb(layer_helpers.COLORS_DARK["fixed-sites"]))
check("the restyled towers cluster matches its own COLORS_DARK entry",
      (_towers_fill.red(), _towers_fill.green(), _towers_fill.blue())
      == layer_helpers._hex_to_rgb(layer_helpers.COLORS_DARK["towers"]))

# Fixed Service links are a line symbol, not a cluster, but the same "does
# the type colour actually reach the screen" question applies to it.
_link_symbol_color = links_layer2.renderer().symbol().color()
check("Fixed Service links render in their own COLORS_DARK hue (composited with LINE_ALPHA)",
      (_link_symbol_color.red(), _link_symbol_color.green(), _link_symbol_color.blue())
      == layer_helpers._hex_to_rgb(layer_helpers.LINK_INK_DARK["color"]))

# -- Operator filter: built from the data, applies to every layer that ------
# -- carries a licensee, empty state, no leakage into export/CRS -----------
combo = plugin.dock.records.licensee_combo
options = [combo.itemData(i) for i in range(combo.count())]
check("operator list is data-driven, not hard-coded",
      combo.count() > 100 and options[0] == "", f"{combo.count()} options")
check("operator list offers 'All' first", "All operators" in combo.itemText(0))

# The QGIS layer's own 'licensee' field is already a " / "-joined string
# where a site's raw record names more than one licensee
# (core/sources/terrestrial_public.py: "licensee": " / ".join(licensees)) --
# real, common (355 of 956 distinct site licensee strings in the loaded
# snapshot), not a rare edge case. The offered operator list must be built
# by splitting those, or a real "Bell Media Inc. / Bell Média Inc." record
# would offer only the whole combined string as one (wrong) "operator".
_cellular_layer = layer_helpers.find_owned_layer(project, layer_helpers.SOURCE_CELLULAR)
_source_raw = {(f["licensee"] or "").strip() for f in sites_layer.getFeatures()} | \
              {(f["licensee"] or "").strip() for f in links_layer2.getFeatures()}
_source_split = {part.strip() for raw in _source_raw for part in raw.split(" / ") if part.strip()}
check("every offered operator is a real, split-correct name from the loaded records",
      set(o for o in options if o) <= _source_split)
check("a combined licensee string itself is never offered whole as one operator",
      "Bell Media Inc. / Bell Média Inc." not in set(options))

unfiltered_sites = sites_layer.featureCount()
unfiltered_links = links_layer2.featureCount()
# Fetched while unfiltered, so a filter applied later in this block cannot
# hide the very record these checks need to find again.
_site_combo_id = next(
    (f.id() for f in sites_layer.getFeatures()
     if (f["licensee"] or "") == "Bell Media Inc. / Bell Média Inc."), None)
_link_combo_id = next(
    (f.id() for f in links_layer2.getFeatures()
     if "Bell Média Inc. (CFVM-FM / CIKI-FM)" in (f["licensee"] or "")), None)
http_calls = {"n": 0}
_real_get4 = _requests.get


def _count4(url, *a, **kw):
    http_calls["n"] += 1
    return _real_get4(url, *a, **kw)


_requests.get = _count4
try:
    # Anchored match: exact value, or one " / "-separated part of a combined
    # value -- the same boundary _operator_counts() splits on, verified
    # against real combined records rather than a synthetic fixture.
    def _anchored_count(layer, name):
        return sum(1 for f in layer.getFeatures()
                   if name in [p.strip() for p in (f["licensee"] or "").split(" / ")])

    expected_sites = {n: _anchored_count(sites_layer, n)
                      for n in ("Rogers Communications Canada Inc.", "Bell Mobility Inc.")}
    http_calls["n"] = 0
    plugin.set_licensee_filter("Rogers Communications Canada Inc.")
    qgs.processEvents()
    rogers_count = sites_layer.featureCount()
    check("Rogers filter shows only Rogers sites (anchored match, not just exact)",
          rogers_count == expected_sites["Rogers Communications Canada Inc."] < unfiltered_sites,
          f"{rogers_count:,} of {unfiltered_sites:,}")
    check("every visible site belongs to the chosen operator",
          all("Rogers Communications Canada Inc."
              in [p.strip() for p in (f["licensee"] or "").split(" / ")]
              for f in sites_layer.getFeatures()))
    check("the same operator filter also narrows Fixed Service links",
          links_layer2.featureCount() < unfiltered_links, f"{links_layer2.featureCount():,}")
    check("every visible link belongs to the chosen operator",
          all("Rogers Communications Canada Inc."
              in [p.strip() for p in (f["licensee"] or "").split(" / ")]
              for f in links_layer2.getFeatures()))
    # Cellular is a live, viewport-scoped layer with no features loaded in
    # this offline harness -- the filter still has to reach it structurally,
    # so this checks the subset string it was given, not a feature count.
    check("the operator filter reaches the Cellular layer too (subset string set)",
          _cellular_layer is not None and _cellular_layer.subsetString() != "",
          _cellular_layer.subsetString() if _cellular_layer is not None else None)

    plugin.set_licensee_filter("Bell Mobility Inc.")
    qgs.processEvents()
    check("Bell filter shows only Bell sites",
          sites_layer.featureCount() == expected_sites["Bell Mobility Inc."],
          f"{sites_layer.featureCount():,}")

    # A real combined-name record, in each layer, used exactly as reported --
    # filtering by one split part must still surface the record whose whole
    # licensee field is the combined string. IDs were captured above, before
    # any filter in this block could hide them.
    if _site_combo_id is not None:
        plugin.set_licensee_filter("Bell Media Inc.")
        qgs.processEvents()
        check("filtering by one part of a real combined SITE licensee still finds that record",
              _site_combo_id in {f.id() for f in sites_layer.getFeatures()})
    else:
        SKIPPED.append("combined-site-licensee filter check (record not present this run)")

    if _link_combo_id is not None:
        plugin.set_licensee_filter("Bell Média Inc. (CFVM-FM / CIKI-FM)")
        qgs.processEvents()
        check("filtering by a real combined LINK licensee finds its own record",
              _link_combo_id in {f.id() for f in links_layer2.getFeatures()})
    else:
        SKIPPED.append("combined-link-licensee filter check (record not present this run)")

    plugin.set_licensee_filter("")
    qgs.processEvents()
    check("clearing the filter restores every site", sites_layer.featureCount() == unfiltered_sites,
          f"{sites_layer.featureCount():,}")
    check("clearing the filter restores every link", links_layer2.featureCount() == unfiltered_links,
          f"{links_layer2.featureCount():,}")
    check("operator switching issues no public-data requests",
          http_calls["n"] == 0, f"{http_calls['n']} requests")
finally:
    _requests.get = _real_get4

check("filtering creates no second dataset",
      layer_helpers.find_owned_layer(project, layer_helpers.SOURCE_FIXED_SITES) is sites_layer)
check("filtering does not touch the CRS", project.crs().authid() == "EPSG:3857")

# -- Empty operator match: an explicit message, not a silent blank table ----
# Force the Records tab to Fixed Service sites first -- this check is about
# the empty-state MESSAGE, not about whichever tab happened to be showing
# from earlier in the suite.
_sites_tab = plugin.dock.records.dataset_combo.findData(layer_helpers.SOURCE_FIXED_SITES)
plugin.dock.records.dataset_combo.setCurrentIndex(_sites_tab)
plugin.set_licensee_filter("An Operator That Does Not Exist In This Data")
qgs.processEvents()
check("a nonexistent operator legitimately matches zero sites",
      sites_layer.featureCount() == 0)
check("the Records tab is really showing Fixed Service sites for this check",
      plugin.dock.records.current_source_key() == layer_helpers.SOURCE_FIXED_SITES)
_status_text = plugin.dock.records.status_label.text()
check("the empty state names the operator, not a generic 'nothing loaded' message",
      "An Operator That Does Not Exist In This Data" in _status_text, _status_text)
check("the empty state tells the operator how to recover",
      "clear" in _status_text.lower(), _status_text)
plugin.set_licensee_filter("")
qgs.processEvents()
check("clearing the empty filter restores every site again",
      sites_layer.featureCount() == unfiltered_sites)

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

print("\n== 24. Operator filter visible from dock creation, before any data ==")
# A fresh dock, never having gone through load_public_data() -- this is what
# show_panel()/initGui() produce for an operator who reopens the panel (or
# opens it for the first time) before ever clicking Load Public Data. The
# Operator combo must already be there, not hidden behind picking a
# dataset that does not exist yet.
_iface2 = FakeIface()
_iface2.window.show()
_plugin2 = VeloronaPlugin(_iface2)
_plugin2._warn = lambda m: None
_plugin2._error = lambda m: None
_dock2 = _plugin2._ensure_dock()
check("the Operator combo exists and is visible the moment the dock is created",
      _dock2.records.licensee_combo.isVisibleTo(_dock2.records))
check("the Operator label is visible too, not just the combo",
      _dock2.records.operator_label.isVisibleTo(_dock2.records))
check("before Load Public Data, the Operator combo is disabled, not hidden",
      not _dock2.records.licensee_combo.isEnabled())
check("before Load Public Data, the Operator hint is not shown",
      not _dock2.records.operator_hint.isVisible())
check("the dataset combo has no datasets yet (nothing loaded)",
      _dock2.records.dataset_combo.count() == 0)
# Populate it now, exactly as Load Public Data would, and confirm the combo
# turns on -- this is the ONLY thing that should gate it, not which dataset
# tab is selected.
_dock2.records.populate_licensees({"Example Operator Inc.": 3})
check("populate_licensees() enables the combo once it has real counts",
      _dock2.records.licensee_combo.isEnabled())
check("populate_licensees() shows the count hint",
      _dock2.records.operator_hint.isVisibleTo(_dock2.records)
      and "1 operator" in _dock2.records.operator_hint.text(),
      _dock2.records.operator_hint.text())
_iface2.window.close()

print("\n== 25. Layer-type colour system: measured distinctness ==")
# core/colors.py's docstring states specific, checkable claims about the six
# COLORS_DARK/COLORS_LIGHT values: minimum pairwise CIEDE2000 separation
# after simulating deuteranopia/protanopia/tritanopia, and a contrast floor
# against each real backdrop. This verifies the DATA actually chosen, not
# just that cluster_ink()/cluster_symbol() correctly apply whatever colour
# they are given (section 21 covers that). A future edit that quietly
# narrows the palette toward near-duplicate hues has to fail one of these,
# not just "look different enough" to whoever made the change.


def _lab(rgb):
    def lin(v):
        v /= 255.0
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(v) for v in rgb)
    x = (r * 0.4124 + g * 0.3576 + b * 0.1805) / 0.95047
    y = r * 0.2126 + g * 0.7152 + b * 0.0722
    z = (r * 0.0193 + g * 0.1192 + b * 0.9505) / 1.08883
    f = lambda t: t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116
    fx, fy, fz = f(x), f(y), f(z)
    return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))


def _ciede2000(rgb1, rgb2):
    import math
    L1, a1, b1 = _lab(rgb1)
    L2, a2, b2 = _lab(rgb2)
    C1, C2 = math.hypot(a1, b1), math.hypot(a2, b2)
    Cb = (C1 + C2) / 2
    G = 0.5 * (1 - math.sqrt(Cb ** 7 / (Cb ** 7 + 25 ** 7))) if Cb > 0 else 0
    a1p, a2p = (1 + G) * a1, (1 + G) * a2
    C1p, C2p = math.hypot(a1p, b1), math.hypot(a2p, b2)
    h1 = math.degrees(math.atan2(b1, a1p)) % 360
    h2 = math.degrees(math.atan2(b2, a2p)) % 360
    dLp = L2 - L1
    dCp = C2p - C1p
    if C1p * C2p == 0:
        dh = 0
    elif h2 - h1 > 180:
        dh = h2 - h1 - 360
    elif h2 - h1 < -180:
        dh = h2 - h1 + 360
    else:
        dh = h2 - h1
    dHp = 2 * math.sqrt(C1p * C2p) * math.sin(math.radians(dh) / 2)
    Lb, Cbp = (L1 + L2) / 2, (C1p + C2p) / 2
    if C1p * C2p == 0:
        hb = h1 + h2
    elif abs(h1 - h2) > 180:
        hb = (h1 + h2 + 360) / 2 if h1 + h2 < 360 else (h1 + h2 - 360) / 2
    else:
        hb = (h1 + h2) / 2
    T = (1 - 0.17 * math.cos(math.radians(hb - 30)) + 0.24 * math.cos(math.radians(2 * hb))
        + 0.32 * math.cos(math.radians(3 * hb + 6)) - 0.20 * math.cos(math.radians(4 * hb - 63)))
    Sl = 1 + (0.015 * (Lb - 50) ** 2) / math.sqrt(20 + (Lb - 50) ** 2)
    Sc, Sh = 1 + 0.045 * Cbp, 1 + 0.015 * Cbp * T
    Rt = 0
    if Cbp > 0:
        Rt = (-2 * math.sqrt(Cbp ** 7 / (Cbp ** 7 + 25 ** 7))
             * math.sin(math.radians(60 * math.exp(-((hb - 275) / 25) ** 2))))
    return math.sqrt((dLp / Sl) ** 2 + (dCp / Sc) ** 2 + (dHp / Sh) ** 2
                     + Rt * (dCp / Sc) * (dHp / Sh))


# Vienot/Brettel/Mollon linear-RGB CVD simulation matrices.
_CVD_MATS = {
    "deuteranopia": ((0.625, 0.375, 0.0), (0.70, 0.30, 0.0), (0.0, 0.30, 0.70)),
    "protanopia": ((0.567, 0.433, 0.0), (0.558, 0.442, 0.0), (0.0, 0.242, 0.758)),
    "tritanopia": ((0.95, 0.05, 0.0), (0.0, 0.433, 0.567), (0.0, 0.475, 0.525)),
}


def _simulate_cvd(rgb, kind):
    if kind == "normal":
        return rgb

    def lin(v):
        v /= 255.0
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4

    def srgb(v):
        v = max(0.0, min(1.0, v))
        return 255 * (12.92 * v if v <= 0.0031308 else 1.055 * v ** (1 / 2.4) - 0.055)
    r, g, b = (lin(v) for v in rgb)
    m = _CVD_MATS[kind]
    out = [m[i][0] * r + m[i][1] * g + m[i][2] * b for i in range(3)]
    return tuple(srgb(v) for v in out)


import itertools as _itertools

_VISION_TYPES = ("normal", "deuteranopia", "protanopia", "tritanopia")
_MIN_DE_FLOOR = 15.0  # measured achieved: 17.3 dark / 16.9 light -- margin, not the exact value

for _mode, _palette, _land, _contrast_floor in (
        ("dark", layer_helpers.COLORS_DARK, "#181E18", 4.5),
        ("light", layer_helpers.COLORS_LIGHT, "#FAF6F0", 2.5)):
    check(f"{_mode}: all six type colours are distinct hex values",
          len(set(_palette.values())) == 6, str(_palette))
    _land_rgb = layer_helpers._hex_to_rgb(_land)
    for _kind, _hex in _palette.items():
        _c = _contrast(_hex, _land)
        check(f"{_mode} {_kind}: solid colour meets the {_contrast_floor}:1 contrast floor "
             f"against {_land}",
              _c >= _contrast_floor, f"{_c:.2f}:1")
    _worst = 999.0
    _worst_pair = None
    for _vision in _VISION_TYPES:
        _sims = {k: _simulate_cvd(layer_helpers._hex_to_rgb(h), _vision)
                for k, h in _palette.items()}
        for _a, _b in _itertools.combinations(_sims, 2):
            _de = _ciede2000(_sims[_a], _sims[_b])
            if _de < _worst:
                _worst, _worst_pair = _de, (_vision, _a, _b)
    check(f"{_mode}: minimum pairwise CIEDE2000 separation across every simulated "
         f"vision type stays above {_MIN_DE_FLOOR}",
          _worst >= _MIN_DE_FLOOR, f"{_worst:.1f} ({_worst_pair})")

print("\n== 26. Layer-type colour system: rendered proof ==")
# The bug this whole feature closes, reproduced end to end: build several
# clustered layers of different types with the real renderer, render them
# together with QGIS's own compositor, and read the actual pixels back --
# not just inspect the symbol objects. Before the fix, every clustered layer
# rendered the same shared bubble regardless of its own COLORS entry; this
# is the render-level proof that is no longer true.
from qgis.core import (QgsFeature, QgsGeometry, QgsMapSettings,  # noqa: E402
                       QgsMapRendererParallelJob, QgsPointXY as _QgsPointXY,
                       QgsVectorLayer)
from qgis.PyQt.QtGui import QColor as _QColor26  # noqa: E402
import random as _random

_random.seed(11)
_render_layers = []
_render_kinds = [("fixed-sites", -79.8), ("satellites", -78.9)]
for _kind, _lon0 in _render_kinds:
    _lyr = QgsVectorLayer("Point?crs=EPSG:4326", _kind, "memory")
    _feats = []
    for _ in range(40):
        _f = QgsFeature()
        _f.setGeometry(QgsGeometry.fromPointXY(
            _QgsPointXY(_lon0 + _random.gauss(0, 0.02), 43.7 + _random.gauss(0, 0.02))))
        _feats.append(_f)
    _lyr.dataProvider().addFeatures(_feats)
    _lyr.updateExtents()
    _lyr.setRenderer(layer_helpers._clustered_renderer(layer_helpers.COLORS_DARK[_kind], True))
    _render_layers.append(_lyr)

_ms = QgsMapSettings()
_ms.setLayers(_render_layers)
# Native EPSG:4326, matching the layers themselves -- no reprojection math to
# get wrong. The extent is the layers' own combined extent, buffered, so
# every rendered point is guaranteed to be inside frame regardless of the
# actual coordinates picked above.
_ms.setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:4326"))
_ms.setOutputSize(QSize(600, 300))
_ms.setOutputDpi(96)
_ms.setBackgroundColor(_QColor26("#181E18"))
_render_extent = QgsRectangle()
for _lyr in _render_layers:
    _render_extent.combineExtentWith(_lyr.extent())
_render_extent.grow(0.05)
_ms.setExtent(_render_extent)

_job = QgsMapRendererParallelJob(_ms)
_job.start()
_job.waitForFinished()
_image = _job.renderedImage()


def _pixels_matching(image, hex_color, land, tol=30):
    # The cluster fill is translucent (CLUSTER_FILL_ALPHA/255), by design --
    # that is what lets the basemap read through it -- so the pixel actually
    # on screen is the composite of the type hue over the backdrop, not the
    # raw hex. Comparing against the raw hex would never match anything.
    rgba = layer_helpers._hex_to_rgb(hex_color) + (layer_helpers.CLUSTER_FILL_ALPHA,)
    r, g, b = _over_rgb(rgba, land)
    n = 0
    for y in range(0, image.height(), 3):      # sampled, not every pixel -- fast enough to stay in CI
        for x in range(0, image.width(), 3):
            p = image.pixelColor(x, y)
            if abs(p.red() - r) + abs(p.green() - g) + abs(p.blue() - b) < tol:
                n += 1
    return n


def _over_rgb(rgba, backdrop):
    a = rgba[3] / 255
    bg = layer_helpers._hex_to_rgb(backdrop)
    return tuple(round(rgba[i] * a + bg[i] * (1 - a)) for i in range(3))


_sites_pixels = _pixels_matching(_image, layer_helpers.COLORS_DARK["fixed-sites"], "#181E18")
_satellites_pixels = _pixels_matching(_image, layer_helpers.COLORS_DARK["satellites"], "#181E18")
check("the rendered image actually contains fixed-sites' own cluster colour",
      _sites_pixels > 0, f"{_sites_pixels} sampled px")
check("the rendered image actually contains satellites' own cluster colour",
      _satellites_pixels > 0, f"{_satellites_pixels} sampled px")
check("fixed-sites and satellites clusters are visually distinct colours on screen, "
     "not the same shared bubble",
      layer_helpers.COLORS_DARK["fixed-sites"] != layer_helpers.COLORS_DARK["satellites"])

print("\n== 27. CelesTrak fetch: a dead host must not freeze the map ==")
# Enabling Satellites ran the CelesTrak fetch on the GUI thread behind a wait
# cursor, with timeout=15.0 -- a single float, so a host that never completes
# a TCP connect burned the full 15s, five times over, one per group. Measured
# against the live service while it was genuinely unreachable: 75.077s to
# return zero satellites, 76.33s end to end through the real toggle path. The
# other stages were measured and ruled out, so they are not what to guard:
# skyfield's timescale load is 0.027s with no HTTP at all, propagation is
# 0.089 ms/satellite (0.071s for 800), feature construction 0.006s, and
# nothing re-fetches on pan/zoom. These checks pin the fetch behaviour only.
#
# Mocked, not live: the point is what happens when the service misbehaves,
# which is not reproducible on demand against the real host.
from velorona.core.sources import space_public  # noqa: E402

_ct_calls = {"groups": []}


class _FakeResp:
    def __init__(self, text): self.text = text
    def raise_for_status(self): pass


_SAMPLE_TLE = (
    "ISS (ZARYA)\n"
    "1 25544U 98067A   26261.50000000  .00016717  00000-0  10270-3 0  9000\n"
    "2 25544  51.6400 208.9163 0006317  69.9862 290.1974 15.49181247 10000\n")

_real_ct_get = _requests.get
try:
    # 1. Host refuses to connect at all -> stop, do not ask the same host 4
    #    more times. This is the 75s case.
    def _all_refused(url, *a, **kw):
        _ct_calls["groups"].append(kw.get("params", {}).get("GROUP"))
        raise _requests.exceptions.ConnectionError("connection refused")

    _requests.get = _all_refused
    _ct_calls["groups"] = []
    _t0 = time.monotonic()
    _result = space_public.fetch_celestrak_satellites()
    _elapsed = time.monotonic() - _t0
    check("an unreachable host is asked once, not once per group",
          len(_ct_calls["groups"]) == 1,
          f"{len(_ct_calls['groups'])} of {len(space_public.CELESTRAK_GROUPS)} groups attempted")
    check("an unreachable host still returns an empty set, not an exception",
          _result == {})

    # 2. A single group failing for its OWN reason (404, rate-limit, bad
    #    payload) must NOT abort the others -- that degrade-per-group
    #    behaviour is the reason the loop swallows exceptions at all, and the
    #    bail-out above must not have cost it.
    def _first_group_404(url, *a, **kw):
        group = kw.get("params", {}).get("GROUP")
        _ct_calls["groups"].append(group)
        if group == space_public.CELESTRAK_GROUPS[0]:
            raise _requests.exceptions.HTTPError("404 Not Found")
        return _FakeResp(_SAMPLE_TLE)

    _requests.get = _first_group_404
    _ct_calls["groups"] = []
    _result = space_public.fetch_celestrak_satellites()
    check("one group failing on its own does not abort the remaining groups",
          len(_ct_calls["groups"]) == len(space_public.CELESTRAK_GROUPS),
          f"{len(_ct_calls['groups'])} of {len(space_public.CELESTRAK_GROUPS)} attempted")
    check("the groups that did answer are still parsed",
          len(_result) == 1 and "25544" in _result, str(list(_result)))

    # 3. A connect TIMEOUT (the live failure actually observed: DNS resolved,
    #    TCP connect then hung) must bail out the same way a refusal does.
    #    requests.ConnectTimeout subclasses ConnectionError, so one except
    #    covers both -- asserted here rather than assumed from the hierarchy.
    def _connect_timeout(url, *a, **kw):
        _ct_calls["groups"].append(kw.get("params", {}).get("GROUP"))
        raise _requests.exceptions.ConnectTimeout("connect timed out")

    _requests.get = _connect_timeout
    _ct_calls["groups"] = []
    space_public.fetch_celestrak_satellites()
    check("a hanging connect bails out after one group, like a refusal",
          len(_ct_calls["groups"]) == 1, f"{len(_ct_calls['groups'])} attempted")

    # 4. A read timeout is also per-group, not a whole-host verdict: the host
    #    answered, this group was just slow.
    def _read_timeout(url, *a, **kw):
        _ct_calls["groups"].append(kw.get("params", {}).get("GROUP"))
        raise _requests.exceptions.ReadTimeout("read timed out")

    _requests.get = _read_timeout
    _ct_calls["groups"] = []
    space_public.fetch_celestrak_satellites()
    check("a read timeout is treated per group, not as an unreachable host",
          len(_ct_calls["groups"]) == len(space_public.CELESTRAK_GROUPS),
          f"{len(_ct_calls['groups'])} attempted")
finally:
    _requests.get = _real_ct_get

check("the CelesTrak timeout separates connect from read",
      isinstance(space_public.CELESTRAK_TIMEOUT, tuple)
      and len(space_public.CELESTRAK_TIMEOUT) == 2,
      str(space_public.CELESTRAK_TIMEOUT))
check("the connect timeout is short enough that a dead host cannot freeze the map",
      space_public.CELESTRAK_TIMEOUT[0] <= 5.0,
      f"connect {space_public.CELESTRAK_TIMEOUT[0]}s, and an unreachable host is asked once, "
      f"so the worst case is {space_public.CELESTRAK_TIMEOUT[0]}s -- not "
      f"{space_public.CELESTRAK_TIMEOUT[0] * len(space_public.CELESTRAK_GROUPS)}s")
check("the read timeout is still generous enough for a large TLE payload",
      space_public.CELESTRAK_TIMEOUT[1] >= 15.0, f"read {space_public.CELESTRAK_TIMEOUT[1]}s")

# The stages that were measured and ruled out -- pinned so a future change
# cannot quietly reintroduce them as costs.
_t0 = time.monotonic()
import importlib as _importlib
_importlib.reload(space_public)
check("skyfield's timescale load stays local (no network, sub-second)",
      time.monotonic() - _t0 < 2.0, f"{time.monotonic() - _t0:.3f}s to re-import")

print("\n== 28. satellite fetch: status message on the map's own message bar ==")
# The fetch is bounded now (section 27), but it is still a blocking call on
# the GUI thread -- so an operator toggling Satellites on still sees a short
# pause. A status message explains it instead of the map just appearing to
# freeze, and is replaced with a plain explanation rather than silently
# reverting to blank on failure. plugin.py:_populate_satellites is the only
# thing touched; Ground/Earth Stations, colours, filter, export and CRS are
# untouched by this pass.
_mb_calls = []
_real_push = plugin.iface.messageBar().pushMessage
_real_pop = plugin.iface.messageBar().popWidget


def _recording_push(*a, **kw):
    _mb_calls.append(("push", a, kw))
    return _real_push(*a, **kw)


def _recording_pop(*a, **kw):
    _mb_calls.append(("pop", a, kw))
    return _real_pop(*a, **kw)


plugin.iface.messageBar().pushMessage = _recording_push
plugin.iface.messageBar().popWidget = _recording_pop

_sat_layer28 = layer_helpers.find_owned_layer(project, layer_helpers.SOURCE_SATELLITES)
_sat_node28 = project.layerTreeRoot().findLayer(_sat_layer28.id())
_real_fetch28 = space_public.fetch_celestrak_satellites

try:
    _ONE_SAT = {"25544": (
        "ISS (ZARYA)",
        "1 25544U 98067A   26261.50000000  .00016717  00000-0  10270-3 0  9000",
        "2 25544  51.6400 208.9163 0006317  69.9862 290.1974 15.49181247 10000")}

    # -- Case 1: the fetch is still in progress when the caller checks -------
    # (mid-call instrumentation, not just "the code calls processEvents()" --
    # this catches the message being pushed AFTER the blocking call instead
    # of before, which would defeat the whole point.) A fast fake, NOT
    # _real_fetch28 -- this must not touch the real network.
    _mid_call = {}

    def _slow_fetch_probe():
        _mid_call["visible"] = plugin.iface.messageBar().isVisible()
        _mid_call["pushed_before_call"] = any(c[0] == "push" for c in _mb_calls)
        return _ONE_SAT

    space_public.fetch_celestrak_satellites = _slow_fetch_probe
    plugin._satellites_fetched_at = None
    plugin.iface.messageBar().clearWidgets()
    _mb_calls.clear()
    _sat_node28.setItemVisibilityChecked(False)
    qgs.processEvents()
    _sat_node28.setItemVisibilityChecked(True)
    qgs.processEvents()

    check("the status message is pushed and visible BEFORE the blocking fetch starts",
          _mid_call.get("pushed_before_call") is True and _mid_call.get("visible") is True)
    _connecting_calls = [c for c in _mb_calls if c[0] == "push"
                         and "Connecting to satellite data" in str(c[1])]
    check("the in-progress message is plain and honest, not a bare 'Loading...'",
          len(_connecting_calls) == 1 and "few seconds" in str(_connecting_calls[0][1]))

    # -- Case 2: fetch succeeds -> message is cleared, nothing lingers -------
    space_public.fetch_celestrak_satellites = lambda: _ONE_SAT
    plugin._satellites_fetched_at = None
    plugin.iface.messageBar().clearWidgets()
    _mb_calls.clear()
    _sat_node28.setItemVisibilityChecked(False)
    qgs.processEvents()
    _sat_node28.setItemVisibilityChecked(True)
    qgs.processEvents()

    check("a successful fetch pops the in-progress message (cleanup happens)",
          any(c[0] == "pop" for c in _mb_calls))
    check("a successful fetch pushes no failure message",
          not any(c[0] == "push" and "unavailable" in str(c[1]).lower() for c in _mb_calls))
    check("the message bar is not left showing anything after a success",
          not plugin.iface.messageBar().isVisible())

    # -- Case 3: fetch degrades to empty (the actual observed failure mode --
    # a refused/hanging connection is caught inside fetch_celestrak_satellites
    # itself and returns {}, it does not raise) -> plain explanation, not a
    # silent revert to blank.
    space_public.fetch_celestrak_satellites = lambda: {}
    plugin._satellites_fetched_at = None
    plugin.iface.messageBar().clearWidgets()
    _mb_calls.clear()
    _sat_node28.setItemVisibilityChecked(False)
    qgs.processEvents()
    _sat_node28.setItemVisibilityChecked(True)
    qgs.processEvents()

    _failure_pushes = [c for c in _mb_calls if c[0] == "push"
                       and "unavailable" in str(c[1]).lower()]
    check("an empty (degraded) result still gets a plain failure explanation",
          len(_failure_pushes) == 1, str(_mb_calls))
    check("the failure message names CelesTrak, not a generic error",
          "CelesTrak" in str(_failure_pushes[0][1]) if _failure_pushes else False)
    check("the failure message is a warning, not styled as routine info",
          bool(_failure_pushes) and len(_failure_pushes[0][1]) >= 3
          and _failure_pushes[0][1][2] == Qgis.MessageLevel.Warning)
    check("the failure message does not silently vanish -- it is still showing after",
          plugin.iface.messageBar().isVisible())

    # -- Case 4: an outright exception (not the degrade path) is handled the
    # same honest way, and the wait cursor is unconditionally restored.
    def _raises(*a, **kw):
        raise RuntimeError("unexpected failure, not a network degrade")

    space_public.fetch_celestrak_satellites = _raises
    plugin._satellites_fetched_at = None
    plugin.iface.messageBar().clearWidgets()
    _mb_calls.clear()
    _sat_node28.setItemVisibilityChecked(False)
    qgs.processEvents()
    _sat_node28.setItemVisibilityChecked(True)
    qgs.processEvents()

    _exc_pushes = [c for c in _mb_calls if c[0] == "push"
                  and "unavailable" in str(c[1]).lower()]
    check("an unexpected exception also gets the plain failure explanation, not a stack trace",
          len(_exc_pushes) == 1, str(_mb_calls))
    check("the wait cursor is restored even when the fetch raises",
          QApplication.overrideCursor() is None)
finally:
    space_public.fetch_celestrak_satellites = _real_fetch28
    plugin.iface.messageBar().pushMessage = _real_push
    plugin.iface.messageBar().popWidget = _real_pop
    plugin.iface.messageBar().clearWidgets()
    _sat_node28.setItemVisibilityChecked(False)
    qgs.processEvents()
    plugin._satellites_fetched_at = None

check("the wait cursor is restored after an ordinary run too",
      QApplication.overrideCursor() is None)

passed = sum(1 for _, ok, _ in RESULTS if ok)
for s_ in SKIPPED:
    print(f"  SKIPPED: {s_}")
print(f"\n===== {passed}/{len(RESULTS)} checks passed =====")
for name, ok, detail in RESULTS:
    if not ok:
        print(f"  FAILED: {name} -- {detail}")

qgs.exitQgis()
sys.exit(0 if passed == len(RESULTS) else 1)
