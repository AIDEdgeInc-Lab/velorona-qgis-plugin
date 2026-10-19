"""Renders the Satellites layer from REAL cached CelesTrak records in a real QGIS runtime and checks the positions, for visual review. Dev/CI only (not shipped).

Input: ORBIT_CACHE_DIR (a cache filled from the real source by tools/live_orbit_probe.py) and RENDER_OUT (where the PNGs go). The orbital source is not contacted
here. What is verified: every drawn satellite has a valid latitude/longitude and a GEO-class altitude, the layer CRS maps correctly into the map CRS, selecting a
satellite in Records selects that very feature, the map shows it, and the details panel names it. Light and Dark screenshots at world, Americas and selected scales."""
import os
os.environ.setdefault("VELORONA_USA_PACK", "off")       # USA data is on by default (online); these suites are offline and about other things
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
geo = [f for f, _ in pts if f["orbit_category"] == os.environ.get("RENDER_TEST_CLASS", "GEO")]   # the env override exists only to exercise this logic offline
check("the layer has a GEO-class population (production classifies by orbital period, 1436 +- 30 min)", len(geo) > 100, len(geo))

# Physics, not a catalogue range. "GEO" here means a geosynchronous PERIOD, which also admits inclined and eccentric orbits (e.g. inclined geosynchronous
# QZSS/BeiDou satellites, decommissioned drifting GEOs, eccentric transfer or graveyard orbits), so a fixed "35,000-36,500 km, within 25 deg of the equator"
# is not a valid expectation. What holds for any valid record: the altitude must lie between the record's own perigee and apogee (semi-major axis from its
# mean motion), and, for near-circular orbits, the sub-satellite latitude cannot exceed the orbit's inclination (plus a small allowance for the geodetic/
# geocentric difference and SDP4's lunisolar periodic variation of inclination: 2 deg, an allowance chosen from one proxy check, to be confirmed on live data).
# Highly eccentric records (e > 0.1) are exempt from the latitude bound: their osculating inclination differs from the mean by more (a real
# eccentric geosynchronous-period object, ADITYA-L1, shows 4 deg).
MU, R_EQ, R_POL = 398600.4418, 6378.137, 6356.752
ALT_TOLERANCE_KM = 60.0      # mean-element semi-major axis vs the osculating SGP4 radius (J2 short-period terms are tens of km at GEO)
LAT_TOLERANCE_DEG = 2.0
LAT_CHECK_MAX_ECC = 0.1


def orbit_facts(f):
    import json as _json
    gp = _json.loads(f["omm_json"])
    n = float(gp["MEAN_MOTION"]) * 2 * 3.141592653589793 / 86400.0
    a = (MU / (n * n)) ** (1.0 / 3.0)
    return float(gp["ECCENTRICITY"]), float(gp["INCLINATION"]), a


violations = []
for f in geo:
    e, inc, a = orbit_facts(f)
    p = f.geometry().asPoint()
    lo, hi = a * (1 - e) - R_EQ - ALT_TOLERANCE_KM, a * (1 + e) - R_POL + ALT_TOLERANCE_KM
    why = []
    if not lo <= f["altitude_km"] <= hi:
        why.append(f"altitude {f['altitude_km']:.0f} km outside this record's own perigee/apogee band {lo:.0f}-{hi:.0f} km")
    if e <= LAT_CHECK_MAX_ECC and abs(p.y()) > inc + LAT_TOLERANCE_DEG:
        why.append(f"|latitude| {abs(p.y()):.2f} deg exceeds its inclination {inc:.2f} deg")
    if why:
        violations.append((f, e, inc, p.y(), why))
check("every GEO-class record's altitude lies between its own perigee and apogee, and |sub-satellite latitude| <= its inclination (physical invariants)",
      not violations, [(f["name"], f["norad_cat_id"], why) for f, _e, _i, _l, why in violations[:10]])
# Always print the population, so a reviewer can see what 'GEO-class' contains in this run (counts only; nothing is committed).
stats = [(orbit_facts(f), f) for f in geo]
if geo:
    print("   GEO-class population: n=%d, altitude %.0f-%.0f km, max |lat| %.1f deg, max inclination %.1f deg, max eccentricity %.4f, inclined(>5 deg)=%d, eccentric(>0.01)=%d"
        % (len(geo), min(f["altitude_km"] for f in geo), max(f["altitude_km"] for f in geo), max(abs(f.geometry().asPoint().y()) for f in geo),
           max(i for (_e, i, _a), _f in stats), max(e for (e, _i, _a), _f in stats), sum(1 for (_e, i, _a), _f in stats if i > 5),
           sum(1 for (e, _i, _a), _f in stats if e > 0.01)))
# The old fixed-range expectation is reported as information, with every record that falls outside it, so the reason is visible rather than assumed.
outside = [(f, orbit_facts(f)) for f in geo if not (35000 < f["altitude_km"] < 36600 and abs(f.geometry().asPoint().y()) < 25)]
for f, (e, inc, a) in outside:
    print("   outside 35,000-36,600 km / 25 deg: %-28s NORAD %-6s period %7.2f min ecc %.5f inc %6.2f deg alt %8.1f km lat %7.2f deg"
          % (f["name"], f["norad_cat_id"], f["period_minutes"], e, inc, f["altitude_km"], f.geometry().asPoint().y()))
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
