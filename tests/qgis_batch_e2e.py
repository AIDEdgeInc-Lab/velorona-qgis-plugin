"""Velorona QGIS plugin -- runtime test of the batch terrain-clearance Processing algorithm. NEEDS a real QGIS 4 (run via tests/run_qgis_tests.sh). No network: the elevation
HTTP edge is replaced, everything else (the provider, the algorithm, the sink, core/batch.py, the library) is real.

It checks the Processing layer of the batch (provider registration, parameter validation, reading features incl. a reprojected layer and selected-only input, the output
table, the optional CSV, empty input) and that each output row equals the single-link analysis of the same link run through the plugin's own entry points.
"""

import csv
import os
import sys
import tempfile

PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(PLUGIN_DIR))

from qgis.core import (  # noqa: E402
    NULL,
    QgsApplication,
    QgsCoordinateReferenceSystem,
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsProcessingContext,
    QgsProcessingFeatureSourceDefinition,
    QgsProcessingFeedback,
    QgsProject,
    QgsVectorLayer,
)

qgs = QgsApplication([], False)
qgs.initQgis()

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    return ok


import requests  # noqa: E402

from velorona.core import batch as B  # noqa: E402
from velorona.core.engines import terrestrial  # noqa: E402
from velorona.core.inspector import feature_to_entry  # noqa: E402
from velorona.core.processing.provider import VeloronaProcessingProvider  # noqa: E402
from velorona.core.processing.terrain_batch import (  # noqa: E402
    CSV, FALLBACK_FREQUENCY, INPUT, MAX_LINKS, OUTPUT, PAUSE, TerrainClearanceBatch)

# ---- a synthetic elevation service: flat 100 m with a hump, 50 samples, so no network and a known obstruction --------------
HUMP = 60.0


class _Resp:
    def __init__(self, body):
        self.body = body

    def raise_for_status(self):
        pass

    def json(self):
        return self.body


def fake_get(url, params=None, timeout=None):
    n = len(params["latitude"].split(","))
    return _Resp({"elevation": [100.0 + HUMP * (1 - abs(2 * i / (n - 1) - 1)) for i in range(n)]})


requests.get = fake_get

LINKS = [  # id, A (lat, lon), B (lat, lon), frequencies_mhz
    ("L-1", (44.00, -79.00), (44.20, -79.10), "6000"),
    ("L-2", (44.50, -79.50), (44.55, -79.60), "5945.2, 6226.89"),
    ("L-3", (45.00, -80.00), (45.30, -80.20), "11000"),
    ("L-NOFREQ", (44.00, -79.50), (44.10, -79.60), ""),
]


def make_layer(crs="EPSG:4326", links=LINKS, name="links"):
    layer = QgsVectorLayer(f"LineString?crs={crs}&field=id:string&field=authorization_number:string&field=frequencies_mhz:string&field=source:string", name, "memory")
    transform = None
    if crs != "EPSG:4326":
        from qgis.core import QgsCoordinateTransform
        transform = QgsCoordinateTransform(QgsCoordinateReferenceSystem("EPSG:4326"), QgsCoordinateReferenceSystem(crs), QgsProject.instance())
    feats = []
    for link_id, a, b, freq in links:
        pa, pb = QgsPointXY(a[1], a[0]), QgsPointXY(b[1], b[0])
        if transform is not None:
            pa, pb = transform.transform(pa), transform.transform(pb)
        f = QgsFeature(layer.fields())
        f.setGeometry(QgsGeometry.fromPolylineXY([pa, pb]))
        f.setAttributes([link_id, link_id, freq, "ISED Fixed Service record"])
        feats.append(f)
    layer.dataProvider().addFeatures(feats)
    QgsProject.instance().addMapLayer(layer)
    return layer


def run(params):
    alg = TerrainClearanceBatch()
    alg.initAlgorithm()
    context, feedback = QgsProcessingContext(), QgsProcessingFeedback()
    context.setProject(QgsProject.instance())
    results, ok = alg.run(params, context, feedback)
    out = context.getMapLayer(results.get(OUTPUT)) if ok and results.get(OUTPUT) else None
    return ok, results, out, context


def rows_of(layer):
    return {f["link_id"]: {n: f[n] for n in layer.fields().names()} for f in layer.getFeatures()}


def single(feature):
    entry = feature_to_entry(feature, "link")
    params, _g, _n = terrestrial.build_link_params(entry.data)
    return terrestrial.analyze_link_record(entry.data, entry.site_a_point, entry.site_b_point, params)


print("\n== provider and parameter validation ==")
provider = VeloronaProcessingProvider()
QgsApplication.processingRegistry().addProvider(provider)
alg = QgsApplication.processingRegistry().algorithmById("velorona:terrain_clearance_batch")
check("the provider registers and the algorithm is found by id", alg is not None and alg.displayName().startswith("Terrain clearance"))
check("the help text tells the user about the HTTP 429 rate limit and the pause", "429" in alg.shortHelpString() and "pause" in alg.shortHelpString().lower()
      and "HTTP 429" in alg.parameterDefinition(PAUSE).description(), alg.parameterDefinition(PAUSE).description())
layer = make_layer()
alg2 = TerrainClearanceBatch()
alg2.initAlgorithm()
ctx = QgsProcessingContext()
ctx.setProject(QgsProject.instance())
ok, msg = alg2.checkParameterValues({INPUT: layer.id(), MAX_LINKS: 3}, ctx)
check("an input over the limit is refused before running, with a reason", (not ok) and "over the limit of 3" in msg, msg)
ok, msg = alg2.checkParameterValues({INPUT: layer.id(), MAX_LINKS: 100}, ctx)
check("an input within the limit is accepted", ok, msg)

print("\n== a run on an EPSG:4326 layer ==")
ok, results, out, _ = run({INPUT: layer.id(), MAX_LINKS: 100, PAUSE: 0, OUTPUT: "memory:"})
check("the algorithm runs", ok and out is not None)
rows = rows_of(out)
check("one output feature per input link, keeping the geometry type", out.featureCount() == 4 and out.geometryType() == layer.geometryType())
nd = rows["L-NOFREQ"]
check("the NO DATA link says why and carries no invented numbers",
      nd["status"] == "NO DATA" and "no usable frequency" in nd["reason"] and all(nd[c] is None or nd[c] == NULL for c in ("distance_km", "frequency_ghz", "available_clearance_m")))
equal = True
detail = []
for f in layer.getFeatures():
    if f["id"] == "L-NOFREQ":
        continue
    res = single(f)
    r = res.result
    row = rows[f["id"]]
    ok_row = (row["distance_km"] == r.distance_km and row["available_clearance_m"] == r.terrain_clearance_m and row["required_clearance_m"] == r.required_clearance_m
              and row["frequency_ghz"] == r.frequency_ghz and row["terrain_class"] == r.los_status and row["frequency_origin"] == res.frequency_origin[0])
    equal &= ok_row
    detail.append(f"{f['id']}:{row['status']}")
check("each output row equals the single-link analysis of the same link", equal, ", ".join(detail))
check("the input layer is unchanged", layer.featureCount() == 4 and [f["frequencies_mhz"] for f in layer.getFeatures()][-1] == "")

print("\n== fallback frequency, selected-only input, reprojected input, CSV, empty input ==")
ok, results, out_fb, _ = run({INPUT: layer.id(), MAX_LINKS: 100, FALLBACK_FREQUENCY: 7.0, PAUSE: 0, OUTPUT: "memory:"})
fb = rows_of(out_fb)["L-NOFREQ"]
check("a fallback frequency makes the no-frequency link run, typed Assumed", ok and fb["status"] != "NO DATA" and fb["frequency_ghz"] == 7.0 and fb["frequency_origin"] == "Assumed", str(fb["status"]))
layer.selectByIds([f.id() for f in layer.getFeatures() if f["id"] in ("L-1", "L-3")])
ok, results, out_sel, _ = run({INPUT: QgsProcessingFeatureSourceDefinition(layer.id(), True), MAX_LINKS: 100, PAUSE: 0, OUTPUT: "memory:"})
check("selected features only", ok and sorted(rows_of(out_sel)) == ["L-1", "L-3"])
layer.removeSelection()
proj = make_layer("EPSG:3857", name="links3857")
ok, results, out_p, _ = run({INPUT: proj.id(), MAX_LINKS: 100, PAUSE: 0, OUTPUT: "memory:"})
rp = rows_of(out_p)
same = all(abs(rp[k]["distance_km"] - rows[k]["distance_km"]) < 0.01 for k in ("L-1", "L-2", "L-3"))
check("a layer in another CRS gives the same results (endpoints reprojected to EPSG:4326)", ok and same)
with tempfile.TemporaryDirectory() as tmp:
    path = os.path.join(tmp, "batch.csv")
    ok, results, out_c, _ = run({INPUT: layer.id(), MAX_LINKS: 100, PAUSE: 0, OUTPUT: "memory:", CSV: path})
    text = open(path, encoding="utf-8").read() if os.path.exists(path) else ""
    table = list(csv.reader([ln for ln in text.splitlines() if not ln.startswith("#")]))
    check("the CSV is written with the preamble and one row per link", ok and "batch export" in text and len(table) == 1 + 4 and table[0] == B.COLUMNS)
empty = make_layer(links=[], name="empty")
ok, results, out_e, _ = run({INPUT: empty.id(), MAX_LINKS: 100, PAUSE: 0, OUTPUT: "memory:"})
check("an empty layer gives an empty result, not a failure", ok and out_e is not None and out_e.featureCount() == 0)

qgs.exitQgis()
print(f"\n{sum(RESULTS)}/{len(RESULTS)} checks passed")
sys.exit(0 if all(RESULTS) else 1)
