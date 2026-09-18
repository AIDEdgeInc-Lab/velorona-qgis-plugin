"""Clean-profile install smoke test.

Loads Velorona from a FRESH QGIS profile's python/plugins directory -- the
installed copy from the release ZIP, with the development repo deliberately
kept off sys.path -- and runs the whole Explore -> Select -> Analyze ->
Evidence -> Export workflow, plus enable/disable/re-enable.
"""

import os
import sys

PROFILE = os.environ.get("VELORONA_TEST_PROFILE", os.path.expanduser(
    "~/Library/Application Support/QGIS/QGIS4/profiles/velorona_release_test"))
PLUGINS = os.path.join(PROFILE, "python", "plugins")
sys.path.insert(0, PLUGINS)

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:] = [p for p in sys.path if not p.startswith(REPO)]

from qgis.core import QgsApplication, QgsProject  # noqa: E402
from qgis.gui import QgsLayerTreeMapCanvasBridge, QgsMapCanvas  # noqa: E402
from qgis.PyQt.QtWidgets import QMainWindow  # noqa: E402

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
        self.canvas.resize(1280, 800)
        self.docks = []

    def mapCanvas(self):
        return self.canvas

    def mainWindow(self):
        return self.window

    def addToolBarIcon(self, a):
        self.window.addAction(a)

    def addPluginToMenu(self, m, a):
        pass

    def removePluginMenu(self, m, a):
        pass

    def removeToolBarIcon(self, a):
        self.window.removeAction(a)

    def addDockWidget(self, area, dock):
        self.docks.append(dock)

    def removeDockWidget(self, dock):
        if dock in self.docks:
            self.docks.remove(dock)


print("== install location ==")
import velorona  # noqa: E402

origin = os.path.dirname(os.path.abspath(velorona.__file__))
check("velorona imports from the clean profile, not the repo",
      origin.startswith(PROFILE), origin)
check("no development repo path leaked into sys.path",
      not any(p.startswith(REPO) for p in sys.path))
check("classFactory is exposed", callable(velorona.classFactory))

print("\n== bundled assets ==")
for rel in ("data/fixed_service_snapshot.json", "data/satnogs_snapshot.json",
            "metadata.txt", "__init__.py", "plugin.py"):
    check(f"shipped: {rel}", os.path.exists(os.path.join(origin, rel)))

from velorona.core.sources import space_public, terrestrial_public  # noqa: E402

check("Fixed Service snapshot path resolves inside the install",
      terrestrial_public.FIXED_SERVICE_SNAPSHOT_PATH.startswith(origin),
      terrestrial_public.FIXED_SERVICE_SNAPSHOT_PATH.replace(origin, "<plugin>"))
check("SatNOGS snapshot path resolves inside the install",
      space_public.GROUND_STATIONS_SNAPSHOT_PATH.startswith(origin),
      space_public.GROUND_STATIONS_SNAPSHOT_PATH.replace(origin, "<plugin>"))

print("\n== enable plugin (classFactory + initGui) ==")
iface = FakeIface()
project = QgsProject.instance()
bridge = QgsLayerTreeMapCanvasBridge(project.layerTreeRoot(), iface.canvas)
bridge.setAutoSetupOnFirstLayer(False)

plugin = velorona.classFactory(iface)
warnings = []
plugin._warn = lambda m: warnings.append(m)
plugin._error = lambda m: warnings.append("ERROR: " + m)
plugin.initGui()
check("plugin enables without traceback", True)
check("toolbar/menu actions registered", len(plugin.actions) == 5,
      f"{len(plugin.actions)} actions: {[a.text() for a in plugin.actions]}")
check("no duplicate action labels",
      len({a.text() for a in plugin.actions}) == len(plugin.actions))

print("\n== Explore ==")
plugin.action_load_public.trigger()
for _ in range(30):
    qgs.processEvents()   # the workspace CRS + initial extent settle on the event loop
check("Load Public Data ran", True, f"warnings: {warnings or 'none'}")
check("project CRS is EPSG:3857", project.crs().authid() == "EPSG:3857", project.crs().authid())
check("canvas CRS is EPSG:3857",
      iface.canvas.mapSettings().destinationCrs().authid() == "EPSG:3857")

by_name = {lyr.name(): lyr for lyr in project.mapLayers().values()}
sites = next((l for n, l in by_name.items() if "Fixed Service sites" in n), None)
check("Fixed Service sites loaded from bundled snapshot",
      sites is not None and sites.featureCount() > 20000,
      f"{sites.featureCount() if sites else 0} features")
from velorona.plugin import BASEMAP_NAME  # noqa: E402

check("Velorona basemap present and valid",
      BASEMAP_NAME in by_name and by_name[BASEMAP_NAME].isValid())
check("basemap carries geographic orientation labels",
      by_name[BASEMAP_NAME].labelsEnabled())
ext = iface.canvas.extent()
check("initial extent is the data, not the world", 1e6 < ext.width() < 0.6 * 40075016.7,
      f"{ext.width():,.0f} m")

print("\n== Select + Evidence ==")
from velorona.core.inspector import feature_to_entry  # noqa: E402

feats = list(sites.getFeatures())[:2]
entry = feature_to_entry(feats[0], "site")
sites.selectByIds([feats[0].id()])
qgs.processEvents()
check("selection opens the Results Dock", plugin.dock is not None)
check("dock renders a feature entry",
      plugin.dock is not None and bool(plugin.dock.browser.toHtml().strip()))

print("\n== Analyze ==")
from velorona.core.engines import microwave_exposure, terrestrial  # noqa: E402
from velorona.ui.param_dialog import ParamDialog  # noqa: E402

entries = [(sites, feats[0]), (sites, feats[1])]
dlg = ParamDialog(iface.mainWindow(), "probe", terrestrial.PARAM_SPEC,
                  terrestrial.build_params(entries))
check("parameter dialog constructs (Qt6)", dlg is not None)
dlg.deleteLater()

tres = terrestrial.analyze(entries, terrestrial.build_params(entries))
check("Terrestrial Path Clearance runs", tres is not None, type(tres).__name__)
plugin._update_terrain_layer(tres)
plugin.dock.show_result(tres)
check("dock renders terrestrial evidence", bool(plugin.dock.browser.toHtml().strip()))

try:
    mres = microwave_exposure.analyze(entries, microwave_exposure.build_params(entries))
    check("Microwave Weather Exposure runs", mres is not None, type(mres).__name__)
    plugin._update_weather_evidence_layers(mres)
except Exception as exc:
    check("Microwave Weather Exposure runs", False, f"{type(exc).__name__}: {exc}")

print("\n== Export ==")
from velorona.core import export  # noqa: E402

csv = export.result_to_csv(tres)
check("evidence CSV exports", "Evidence" in csv and len(csv.splitlines()) > 3,
      f"{len(csv.splitlines())} lines")
check("evidence CSV uses the canonical Type vocabulary",
      all(t in csv for t in ("Observed", "Calculated", "Inferred")))
fcsv = export.feature_to_csv(entry.data, entry.latitude, entry.longitude)
check("raw feature CSV exports", len(fcsv.splitlines()) >= 2)
check("raw export carries source provenance", "Open Government Licence" in fcsv)

print("\n== disable / re-enable ==")
persistent = {lid for lid, lyr in project.mapLayers().items()
              if lyr.customProperty("velorona_lifecycle") != "evidence"}
plugin.unload()
check("plugin disables without traceback", True)
check("public data layers survive disable",
      persistent <= set(project.mapLayers()),
      f"{len(persistent & set(project.mapLayers()))}/{len(persistent)} kept")
check("analysis overlays cleaned on disable",
      not any(l.customProperty("velorona_lifecycle") == "evidence"
              for l in project.mapLayers().values()))

plugin2 = velorona.classFactory(iface)
plugin2._warn = lambda m: warnings.append(m)
plugin2.initGui()
check("plugin re-enables without traceback", True)
check("no duplicate actions after re-enable", len(plugin2.actions) == 5
      and len({a.text() for a in plugin2.actions}) == 5, f"{len(plugin2.actions)} actions")
plugin2.unload()
check("second unload is clean", True)

passed = sum(1 for _, ok, _ in RESULTS if ok)
print(f"\n===== clean-install smoke: {passed}/{len(RESULTS)} passed =====")
for name, ok, detail in RESULTS:
    if not ok:
        print(f"  FAILED: {name} -- {detail}")

qgs.exitQgis()
sys.exit(0 if passed == len(RESULTS) else 1)
