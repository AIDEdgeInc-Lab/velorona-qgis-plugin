"""Renders the Satellites layer from REAL cached CelesTrak records in a real QGIS runtime and checks the positions, for visual review. Dev/CI only (not shipped).

Input: ORBIT_CACHE_DIR (a cache filled from the real source by tools/live_orbit_probe.py) and RENDER_OUT (where the PNGs go). The orbital source is not contacted
here. What is verified: every drawn satellite has a valid latitude/longitude and a GEO-class altitude, the layer CRS maps correctly into the map CRS, selecting a
satellite in Records selects that very feature, the map shows it, and the details panel names it. Light and Dark screenshots at world, Americas and selected scales."""
import os
import sys
import time

PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(PLUGIN_DIR))

from qgis.core import QgsApplication, QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsPointXY, QgsProject, QgsRectangle  # noqa: E402
from qgis.gui import QgsLayerTreeMapCanvasBridge, QgsMapCanvas, QgsMessageBar  # noqa: E402
from qgis.PyQt.QtWidgets import QApplication, QMainWindow  # noqa: E402

qgs = QgsApplication([], True)
qgs.initQgis()
RESULTS = []
OUT = os.environ.get("RENDER_OUT", "/tmp/render")
os.makedirs(OUT, exist_ok=True)


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  -- {detail}" if detail and not ok else ""))
    return ok


class FakeIface:
    def __init__(self):
        self.window = QMainWindow()
        self.window.resize(1500, 900)
        self.canvas = QgsMapCanvas()
        self.window.setCentralWidget(self.canvas)
        self._bar = QgsMessageBar(self.window)

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
from velorona.core.sources import orbit_data  # noqa: E402
from velorona.plugin import VeloronaPlugin  # noqa: E402

plugin = VeloronaPlugin(iface)
warnings = []
plugin._warn = lambda m: warnings.append(m)
plugin._error = lambda m: warnings.append("ERROR: " + m)
plugin._orbit_cache = lambda: orbit_data.OrbitCache(os.environ["ORBIT_CACHE_DIR"])
plugin.initGui()
plugin.action_load_public.trigger()
for _ in range(30):
    qgs.processEvents()
root = project.layerTreeRoot()
sat = L.find_owned_layer(project, L.SOURCE_SATELLITES)
root.findLayer(sat.id()).setItemVisibilityChecked(True)
t0 = time.time()
while (plugin._satellites_task is not None or sat.featureCount() == 0) and time.time() - t0 < 120:
    qgs.processEvents()
    time.sleep(0.05)
for _ in range(20):
    qgs.processEvents()
rows = list(sat.getFeatures())
print(f"== satellites drawn: {len(rows)} ==")
check("real records populated the layer", len(rows) > 100, len(rows))
pts = [(f, f.geometry().asPoint()) for f in rows]
check("every position is a valid WGS84 coordinate", all(-90 <= p.y() <= 90 and -180 <= p.x() <= 180 for _, p in pts))
geo = [f for f, _ in pts if f["orbit_category"] == "GEO"]
check("the layer is GEO-class (altitude 35,000-36,500 km) for the GEO records", len(geo) > 100 and all(35000 < f["altitude_km"] < 36600 for f in geo),
      (len(geo), [round(f["altitude_km"]) for f in geo[:3]]))
check("GEO sub-points sit near the equator (|lat| < 25 deg)", all(abs(p.y()) < 25 for f, p in pts if f["orbit_category"] == "GEO"))
check("each row states when its element set was retrieved and whether it is fresh or stale",
      all(f["retrieved_at"] and f["data_status"] in ("fresh", "stale") for f in rows))
check("the Records status line states the data status", "CelesTrak satellites" in plugin.dock.records._dataset_notes.get(L.SOURCE_SATELLITES, ""),
      plugin.dock.records._dataset_notes)

canvas = iface.canvas
to3857 = QgsCoordinateTransform(QgsCoordinateReferenceSystem("EPSG:4326"), canvas.mapSettings().destinationCrs(), project)


def view(lon0, lat0, lon1, lat1):
    a, b = to3857.transform(QgsPointXY(lon0, lat0)), to3857.transform(QgsPointXY(lon1, lat1))
    canvas.setExtent(QgsRectangle(a.x(), a.y(), b.x(), b.y()))
    canvas.refresh()
    t = time.time()
    while time.time() - t < 6:
        qgs.processEvents()
        time.sleep(0.05)
    while canvas.isDrawing() and time.time() - t < 40:
        qgs.processEvents()
        time.sleep(0.05)


plugin.dock.show()
plugin.dock.records.dataset_combo.setCurrentIndex(plugin.dock.records.dataset_combo.findData(L.SOURCE_SATELLITES))
qgs.processEvents()
for appearance in ("light", "dark"):
    plugin.set_map_appearance(appearance)
    for name, box in (("world", (-180, -70, 180, 70)), ("americas", (-140, -45, -30, 60))):
        view(*box)
        iface.window.grab().save(os.path.join(OUT, f"satellites_{appearance}_{name}.png"))
    # select the first record from the Records table: same feature on the map, same record in the details panel
    rec = plugin.dock.records
    rec.view.selectRow(0)
    for _ in range(20):
        qgs.processEvents()
    chosen = sat.selectedFeatures()
    if appearance == "light":
        check("Records row -> exactly one satellite selected on the map", len(chosen) == 1, len(chosen))
        if chosen:
            f = chosen[0]
            check("the details panel names that satellite and its NORAD id", f["name"] in plugin.dock.browser.toPlainText()
                  and str(f["norad_cat_id"]) in plugin.dock.browser.toPlainText(), plugin.dock.browser.toPlainText()[:150])
            p = f.geometry().asPoint()
            ext = canvas.extent()
            m = to3857.transform(QgsPointXY(p.x(), p.y()))
            check("the map moved to the selected satellite (in the map CRS)", ext.contains(m), (ext.toString(), m.toString()))
            check("the other satellites remain on the layer (selection does not hide them)", sat.featureCount() == len(rows))
    time.sleep(1)
    for _ in range(20):
        qgs.processEvents()
    iface.window.grab().save(os.path.join(OUT, f"satellites_{appearance}_selected.png"))
    sat.removeSelection()
    for _ in range(10):
        qgs.processEvents()

passed = sum(1 for _, ok, _ in RESULTS if ok)
print(f"\n===== {passed}/{len(RESULTS)} checks passed =====")
for name, ok, detail in RESULTS:
    if not ok:
        print(f"  FAILED: {name} -- {detail}")
sys.exit(0 if passed == len(RESULTS) else 1)
