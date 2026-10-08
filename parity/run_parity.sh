#!/bin/sh
# Canada P0 parity: Velorona Map vs Velorona for QGIS on the shared frozen fixtures, against the spec oracle.
# The two products are run through their OWN entry points; nothing is copied between repos. The oracle (canonical.py) and comparator
# (compare.py) live in the Map repo's parity/ folder and are used from there.
#
#   PY=/path/to/venv/bin/python MAP_REPO=~/velorona-repos/aei-link-clearance sh parity/run_parity.sh [OUT_DIR]
#
# PY must be a Python with the RELEASED libraries installed (requirements.txt), so QGIS is exercised against aei-link-clearance 0.2.x.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
PY="${PY:-python3}"
MAP_REPO="${MAP_REPO:-$HOME/velorona-repos/aei-link-clearance}"
OUT="${1:-$HERE/out}"; mkdir -p "$OUT"
[ -f "$MAP_REPO/parity/compare.py" ] || { echo "MAP_REPO=$MAP_REPO has no parity/compare.py (needs the Map parity branch)" >&2; exit 2; }
FIX="$HERE/fixtures/ca-*.json $HERE/fixtures/synthetic-boundary/sb-*.json"
echo "library under test: $($PY -c 'import aei_link_clearance as a;print(a.__version__, a.__file__)')"
node "$MAP_REPO/parity/runner_map.js" $FIX > "$OUT/map.json"
$PY "$HERE/runner_qgis.py" $FIX > "$OUT/qgis.json" 2>/dev/null
$PY "$MAP_REPO/parity/compare.py" "$OUT/map.json" "$OUT/qgis.json" "$HERE/fixtures" "$OUT/PARITY_REPORT.md" 2>/dev/null
$PY "$HERE/check_accepted_divergences.py" "$OUT/PARITY_REPORT.json"
echo "report: $OUT/PARITY_REPORT.md"
