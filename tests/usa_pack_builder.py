"""SYNTHETIC USA pack builder shared by the provider unit tests and the QGIS-side USA end-to-end test. Pure stdlib (no pytest, no QGIS).
Everything here is test data labelled as such; none of it is an analysis fixture and none of it is a real FCC record."""

import copy
import gzip
import json
import os

ATTRIBUTION = ("Source: U.S. Federal Communications Commission, Universal Licensing System (ULS) public access database, microwave "
               "services (l_micro). Data as published; not endorsed by the FCC.")


def site(lat, lon, call, name=""):
    return {"i": f"fcc-site-{lat:.5f},{lon:.5f}", "la": lat, "lo": lon, "n": name, "c": [call], "s": "CO", "l": ["Test Licensee"]}


def link(lid, call, k, a, b, freqs, **extra):
    d = {"i": lid, "u": lid.split("-")[2], "k": k, "c": call, "a": a, "b": b, "l": "Test Licensee", "f": freqs,
         "t": ["Fixed Point-to-Point"], "np": 1, "g": "2021-01-26", "x": "2031-02-01"}
    d.update(extra)
    return d


# SYNTHETIC geometry: the link L1 crosses the 40/41 degree edge, so it is written into both tiles (as the real builder does).
S_LOW = site(40.5, -105.5, "WAAA001")
S_HIGH = site(41.5, -105.5, "WAAA001")
S_FAR = site(40.7, -105.2, "WBBB002")
L1 = link("fcc-link-1-1", "WAAA001", 1, 0, 1, [11245.0, 6078.625])
L2 = link("fcc-link-2-1", "WBBB002", 1, 0, 1, [18700.0])


def tiles():
    return copy.deepcopy({
        "40_-106": {"sites": [S_LOW, S_HIGH, S_FAR], "links": [L1, link("fcc-link-2-1", "WBBB002", 1, 0, 2, [18700.0])]},
        "41_-106": {"sites": [S_LOW, S_HIGH], "links": [L1]},
        "10_10": {"sites": [site(10.5, 10.5, "WCCC003"), site(10.6, 10.6, "WCCC003")], "links": [link("fcc-link-3-1", "WCCC003", 1, 0, 1, [7000])]},
    })


def index(tile_map, **over):
    d = {"pack": "us-fcc-uls-micro", "schema": "velorona.us-fcc-uls-micro/1", "builder_version": "1.0.0", "generated_date": "2026-10-03",
         "source_file_updated": "2026-09-27", "source": {"agency": "Federal Communications Commission", "system": "Universal Licensing System (ULS)"},
         "attribution": ATTRIBUTION, "tile_degrees": 1, "min_zoom_hint": 8, "counts": {"links": 3},
         "tiles": {k: [len(t["sites"]), len(t["links"])] for k, t in tile_map.items()}}
    d.update(over)
    return d


def write_pack(root, tile_map=None, idx=None):
    tile_map = tile_map if tile_map is not None else tiles()
    os.makedirs(os.path.join(root, "tiles"), exist_ok=True)
    with open(os.path.join(root, "index.json"), "w") as fh:
        json.dump(idx if idx is not None else index(tile_map), fh)
    for key, tile in tile_map.items():
        with open(os.path.join(root, "tiles", f"{key}.json.gz"), "wb") as fh:
            fh.write(gzip.compress(json.dumps(tile).encode(), mtime=0))
    return str(root)
