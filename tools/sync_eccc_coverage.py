"""Copies the Map's ECCC radar coverage outline into the plugin: python tools/sync_eccc_coverage.py <Map checkout>  (then run the tests).
Reads <Map>/web/eccc_coverage.js (generated there by scripts/build_eccc_coverage.py from Natural Earth) and writes core/eccc_coverage.json
with the same rings, longitude/latitude. The plugin never edits the outline; tests/test_eccc_coverage.py checks it against the Map's file."""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEST = os.path.join(HERE, "core", "eccc_coverage.json")


def read_rings(map_repo: str):
    text = open(os.path.join(map_repo, "web", "eccc_coverage.js"), encoding="utf-8").read()
    m = re.search(r"^const ECCC_RADAR_AREA = (\[.*\]);$", text, re.M)
    if not m:
        sys.exit("web/eccc_coverage.js: ECCC_RADAR_AREA not found")
    return json.loads(m.group(1))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    rings = read_rings(sys.argv[1])
    note = ("Outline of Canada where ECCC radar may be used (Natural Earth 1:50m, public domain), copied from Velorona Map web/eccc_coverage.js. "
            "Rings of [longitude, latitude]. Do not edit by hand: tools/sync_eccc_coverage.py.")
    with open(DEST, "w", encoding="utf-8") as fh:
        json.dump({"note": note, "rings": rings}, fh, separators=(",", ":"))
        fh.write("\n")
    print(f"wrote {len(rings)} rings, {sum(len(r) for r in rings)} vertices to {DEST}")
