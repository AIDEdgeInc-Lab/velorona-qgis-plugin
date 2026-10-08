"""Velorona QGIS plugin -- USA pack loading benchmark (needs QGIS; no network when the pack is a local folder).

Measures, for a real USA pack: reading the index, then for five scenarios the provider load (cold cache, then warm), the in-memory layer build, and an
offscreen render of the links. Nothing here is a claim about analysis speed: terrain/weather analysis is bound by live public services and is not
measured by this script.

    python3.12 tests/benchmark_usa.py <pack-folder> [label]          # writes tests/bench_usa_<label>.json (git-ignored)

Scenarios (all chosen from the pack's own index, not invented):
  1 link          the smallest non-empty tile
  ~100 links      the tile closest to 100 links
  regional batch  a 2 x 2 degree view over Los Angeles (touches 9 tiles, the densest part of the pack)
  large viewport  a 12 x 12 degree view over the central US -- expected to be REFUSED by the budget; the time to refuse is measured
  regional max    the largest centred window around Los Angeles that fits the budget
Peak RSS is the process's high-water mark after each scenario (it never decreases), so scenarios run smallest first.
"""
import json
import os
import resource
import sys
import time
import tracemalloc

PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(PLUGIN_DIR))

from qgis.core import QgsApplication, QgsCoordinateReferenceSystem, QgsMapRendererSequentialJob, QgsMapSettings, QgsRectangle  # noqa: E402
from qgis.PyQt.QtCore import QSize  # noqa: E402

qgs = QgsApplication([], False)
qgs.initQgis()

from velorona.core import layers as layer_helpers  # noqa: E402
from velorona.core.countries import usa  # noqa: E402
from velorona.core.countries.base import ViewTooLargeError  # noqa: E402
from velorona.core.countries.usa_fields import US_LINK_FIELDS, US_SITE_FIELDS  # noqa: E402

PACK = sys.argv[1]
LABEL = sys.argv[2] if len(sys.argv) > 2 else "run"


def rss_mb():
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return round(peak / (1024 * 1024 if sys.platform == "darwin" else 1024), 1)    # macOS reports bytes, Linux kilobytes


def timed(fn):
    t = time.perf_counter()
    out = fn()
    return out, round(time.perf_counter() - t, 4)


report = {"label": LABEL, "pack": PACK, "python": sys.version.split()[0], "budget": {"max_links": usa.MAX_LINKS_PER_LOAD, "max_tiles": usa.MAX_TILES_PER_LOAD},
          "scenarios": []}

provider, t_index = timed(lambda: usa.UsaPackProvider(PACK))
index, t_index2 = timed(provider.index)
report["index"] = {"seconds": t_index2, "links_in_pack": index.link_count, "tiles": len(index.tiles)}

tiles = index.tiles
smallest = min((k for k, v in tiles.items() if v[1] >= 1), key=lambda k: tiles[k][1])
nearest_100 = min(tiles, key=lambda k: abs(tiles[k][1] - 100))


def tile_bbox(key):
    la, lo = (int(x) for x in key.split("_"))
    return (lo + 0.1, la + 0.1, lo + 0.9, la + 0.9)


def window(lat, lon, half):
    return (lon - half, lat - half, lon + half, lat + half)


def run(name, bbox):
    p = usa.UsaPackProvider(PACK)
    p.index()
    tiles_n, bound = p.estimate(bbox)
    entry = {"name": name, "bbox": bbox, "tiles": tiles_n, "links_upper_bound": bound}
    tracemalloc.start()
    try:
        loaded, entry["provider_cold_s"] = timed(lambda: p.load_bbox(bbox))
    except ViewTooLargeError as exc:
        entry["refused"] = str(exc)
        _, entry["refusal_s"] = timed(lambda: _refuse(p, bbox))
        tracemalloc.stop()
        entry["peak_rss_mb"] = rss_mb()
        report["scenarios"].append(entry)
        return
    entry["provider_python_peak_mb"] = round(tracemalloc.get_traced_memory()[1] / 1e6, 1)
    tracemalloc.stop()
    _, entry["provider_warm_s"] = timed(lambda: p.load_bbox(bbox))
    entry.update(links=len(loaded.links), sites=len(loaded.sites), duplicate_links_dropped=loaded.duplicate_links_dropped)
    links_layer, entry["build_links_layer_s"] = timed(lambda: layer_helpers.build_link_layer("bench", loaded.links, US_LINK_FIELDS, "#7aa2f7"))
    sites_layer, entry["build_sites_layer_s"] = timed(lambda: layer_helpers.build_point_layer("bench", loaded.sites, US_SITE_FIELDS, "#7aa2f7"))
    ms = QgsMapSettings()
    ms.setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:4326"))
    ms.setLayers([links_layer])
    ms.setExtent(QgsRectangle(*bbox))
    ms.setOutputSize(QSize(1280, 800))

    def render():
        job = QgsMapRendererSequentialJob(ms)
        job.start()
        job.waitForFinished()
        return job.renderedImage().width()
    _, entry["render_links_s"] = timed(render)
    entry["peak_rss_mb"] = rss_mb()
    report["scenarios"].append(entry)


def _refuse(p, bbox):
    try:
        p.load_bbox(bbox)
    except ViewTooLargeError:
        pass


run("1 link", tile_bbox(smallest))
run("~100 links", tile_bbox(nearest_100))
run("regional batch (2 x 2 degree view over Los Angeles)", (-119.0, 33.0, -117.0, 35.0))
run("large viewport (12 x 12 degrees, central US)", window(38.0, -97.0, 6.0))

best = None
for half in (0.5, 1.0, 1.5, 2.0, 2.5, 3.0):
    bbox = window(34.0, -118.0, half)
    n, bound = usa.UsaPackProvider(PACK).estimate(bbox)
    if bound <= usa.MAX_LINKS_PER_LOAD and n <= usa.MAX_TILES_PER_LOAD:
        best = (half, bbox)
if best:
    run(f"regional max (largest LA-centred window within budget: {best[0] * 2:g} x {best[0] * 2:g} degrees)", best[1])

out = os.path.join(PLUGIN_DIR, "tests", f"bench_usa_{LABEL}.json")
with open(out, "w") as fh:
    json.dump(report, fh, indent=1)
print(json.dumps(report, indent=1))
print("written", out)
