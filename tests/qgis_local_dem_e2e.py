"""Local DEM as elevation source, in real QGIS (offscreen, no network): a WGS84 raster, a projected raster, a raster that does not cover the
path, a raster with no CRS, the dialog's selector. Needs the elevation-provider seam (aei-link-clearance >= 0.3). Run like qgis_ui_polish_e2e.py."""
import os
os.environ.setdefault("VELORONA_USA_PACK", "off")
import sys
import tempfile

PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(PLUGIN_DIR))

from osgeo import gdal, osr  # noqa: E402
from qgis.core import QgsApplication, QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsPointXY, QgsProject, QgsRasterLayer  # noqa: E402
from qgis.PyQt.QtWidgets import QApplication  # noqa: E402

qgs = QgsApplication([], True)
qgs.initQgis()
RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  -- {detail}" if detail and not ok else ""))


from velorona.core import elevation_source, local_dem  # noqa: E402
from velorona.core.engines import terrestrial as TR  # noqa: E402
from velorona.core.validation import NoDataError  # noqa: E402

PARAMS = {"site_a_height_m": 30.0, "site_b_height_m": 30.0, "frequency_ghz": 7.0}
A, B = (43.70, -79.40), (43.80, -79.20)
TMP = tempfile.mkdtemp(prefix="velorona-dem-")


def write_raster(name, epsg, west, north, res, cols, rows, fn, nodata=-9999.0):
    path = os.path.join(TMP, name)
    ds = gdal.GetDriverByName("GTiff").Create(path, cols, rows, 1, gdal.GDT_Float32)
    ds.SetGeoTransform((west, res, 0, north, 0, -res))
    if epsg:
        srs = osr.SpatialReference(); srs.ImportFromEPSG(epsg); ds.SetProjection(srs.ExportToWkt())
    band = ds.GetRasterBand(1); band.SetNoDataValue(nodata)
    band.WriteArray(__import__("numpy").array([[fn(r, c) for c in range(cols)] for r in range(rows)], dtype="float32"))
    ds.FlushCache(); ds = None
    return path


# 1. WGS84 raster covering the path, constant 250 m
p1 = write_raster("wgs84.tif", 4326, -79.6, 43.9, 0.01, 60, 30, lambda r, c: 250.0)
l1 = QgsRasterLayer(p1, "wgs84dem"); QgsProject.instance().addMapLayer(l1)
prov = local_dem.make_provider(l1)
res = TR.analyze_endpoints(*A, *B, PARAMS, "t", prov)
check("WGS84 raster: result uses the raster heights", all(abs(p.ground_elevation_m - 250.0) < 1e-6 for p in res.profile))
check("WGS84 raster: source names the file", res.elevation_source == "Local DEM: wgs84.tif", res.elevation_source)

# 2. Projected raster (UTM 17N) covering the path: the sampler must reproject
tr = QgsCoordinateTransform(QgsCoordinateReferenceSystem("EPSG:4326"), QgsCoordinateReferenceSystem("EPSG:32617"), QgsProject.instance().transformContext())
sw = tr.transform(QgsPointXY(-79.6, 43.6)); ne = tr.transform(QgsPointXY(-79.1, 43.9))
cols, rows = 200, 130
res_m = max((ne.x() - sw.x()) / cols, (ne.y() - sw.y()) / rows)
p2 = write_raster("utm.tif", 32617, sw.x(), sw.y() + rows * res_m, res_m, cols, rows, lambda r, c: 180.0)
l2 = QgsRasterLayer(p2, "utmdem"); QgsProject.instance().addMapLayer(l2)
res2 = TR.analyze_endpoints(*A, *B, PARAMS, "t", local_dem.make_provider(l2))
check("projected raster is reprojected correctly", all(abs(p.ground_elevation_m - 180.0) < 1e-6 for p in res2.profile))

# 3. Raster that covers only part of the path -> explicit NO DATA, nothing substituted
p3 = write_raster("small.tif", 4326, -79.6, 43.9, 0.01, 22, 30, lambda r, c: 250.0)   # covers lon -79.6..-79.38 only
l3 = QgsRasterLayer(p3, "small"); QgsProject.instance().addMapLayer(l3)
try:
    TR.analyze_endpoints(*A, *B, PARAMS, "t", local_dem.make_provider(l3)); ok, msg = False, "no error"
except NoDataError as e:
    ok, msg = ("does not cover this path" in e.reasons[0] and not e.transient), e.reasons[0]
check("partial coverage is NO DATA (not transient), never a result", ok, msg)

# 4. nodata cell inside the path
p4 = write_raster("holes.tif", 4326, -79.6, 43.9, 0.01, 60, 30, lambda r, c: -9999.0 if c == 30 else 250.0)
l4 = QgsRasterLayer(p4, "holes"); QgsProject.instance().addMapLayer(l4)
try:
    TR.analyze_endpoints(*A, *B, PARAMS, "t", local_dem.make_provider(l4)); ok = False
except NoDataError:
    ok = True
check("a nodata cell on the path is NO DATA, not 0 m", ok)

# 5. raster without a CRS is refused before reading
p5 = write_raster("nocrs.tif", None, -79.6, 43.9, 0.01, 60, 30, lambda r, c: 250.0)
l5 = QgsRasterLayer(p5, "nocrs"); QgsProject.instance().addMapLayer(l5)
try:
    local_dem.make_provider(l5); ok = False
except Exception as e:
    ok = "coordinate reference system" in str(e)
check("raster without CRS is refused with the reason", ok)

# 6. candidate list + dialog selector
labels = [l for l, _ in local_dem.candidate_layers()]
check("candidate layers are the project's single-band rasters", set(labels) >= {"wgs84dem", "utmdem", "small", "holes", "nocrs"}, str(labels))
# 6b. the candidate list itself: only valid single-band rasters, sorted by name, two layers with one name told apart by their id tail
dup_a = QgsRasterLayer(write_raster("dup_a.tif", 4326, -79.6, 43.9, 0.01, 4, 4, lambda r, c: 10.0), "twin"); QgsProject.instance().addMapLayer(dup_a)
dup_b = QgsRasterLayer(write_raster("dup_b.tif", 4326, -79.6, 43.9, 0.01, 4, 4, lambda r, c: 20.0), "twin"); QgsProject.instance().addMapLayer(dup_b)
bad = QgsRasterLayer(os.path.join(TMP, "not_a_raster.tif"), "broken"); QgsProject.instance().addMapLayer(bad)
cands = local_dem.candidate_layers()
labels2 = [name for name, _ in cands]
check("candidate list is sorted by layer name", [lyr.name().lower() for _, lyr in cands] == sorted(lyr.name().lower() for _, lyr in cands), str(labels2))
check("an invalid raster is not offered", "broken" not in labels2 and all(lyr.isValid() for _, lyr in cands))
twins = [name for name, lyr in cands if lyr.name() == "twin"]
tails = {dup_a.id()[-8:], dup_b.id()[-8:]}
check("two layers with one name get distinct labels ending in their own id tail",
      len(twins) == 2 and twins[0] != twins[1] and all(t.startswith("twin  [") for t in twins)
      and {t[-9:-1] for t in twins} == tails, str(twins))
check("a name used once stays plain", "wgs84dem" in labels2 and "small" in labels2)
QgsProject.instance().removeMapLayer(dup_a.id()); QgsProject.instance().removeMapLayer(dup_b.id()); QgsProject.instance().removeMapLayer(bad.id())

app = QApplication.instance()
from velorona.ui.param_dialog import ParamDialog  # noqa: E402
d = ParamDialog(None, "t", TR.PARAM_SPEC, {p["key"]: p["default"] for p in TR.PARAM_SPEC}, elevation_layers=local_dem.candidate_layers())
check("dialog defaults to online (no layer)", d.elevation_layer() is None)
d._elevation_combo.setCurrentIndex(d._elevation_combo.findText("Local raster: wgs84dem"))
check("dialog returns the chosen layer", d.elevation_layer() is not None and d.elevation_layer().name() == "wgs84dem")
check("choice is not a parameter value", "elevation_source" not in d.values())
d2 = ParamDialog(None, "t", TR.PARAM_SPEC, {p["key"]: p["default"] for p in TR.PARAM_SPEC}, elevation_layers=[], elevation_note="needs 0.3")
check("old library: choice shown disabled with the reason", not d2._elevation_combo.isEnabled() and d2._elevation_combo.toolTip() == "needs 0.3")
d3 = ParamDialog(None, "t", TR.PARAM_SPEC, {p["key"]: p["default"] for p in TR.PARAM_SPEC})
check("microwave dialog has no elevation row", d3.elevation_layer() is None)

failed = [n for n, ok, _ in RESULTS if not ok]
print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
qgs.exitQgis()
sys.exit(1 if failed else 0)
