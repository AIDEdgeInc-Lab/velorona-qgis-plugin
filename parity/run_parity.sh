#!/bin/sh
# Canada + USA parity: Velorona Map vs Velorona for QGIS on the shared frozen fixtures, against the spec oracle.
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
# The fixtures are the Map workstream's byte-identical files; MANIFEST.sha256 (its) must verify before anything is run.
( cd "$HERE/fixtures" && shasum -a 256 -c MANIFEST.sha256 >/dev/null ) || { echo "fixtures do not match MANIFEST.sha256" >&2; exit 2; }
FIX="$HERE/fixtures/ca-*.json $HERE/fixtures/us-*.json $HERE/fixtures/synthetic-boundary/sb*-*.json"
# The fixtures' weather expectations are the Map workstream's recomputed ones (ITU-R P.838-3 equations, Map commit d2090c3). An installed rain model that fails the
# spot check (aei-microwave-link-exposure <= 0.1.5) would DIVERGE on them by design; say so instead of printing 90+ problems.
"$PY" -c "import sys; sys.path.insert(0, '$HERE/..'); from core import rain_check; sys.exit(0 if rain_check.rain_model_matches_p838_3() else 3)" \
  || { echo "the installed aei-microwave-link-exposure fails the ITU-R P.838-3 spot check (core/rain_check.py): install 0.2.0 or newer (unpublished on PyPI at the time of writing: build it from the library repo)" >&2; exit 3; }
echo "library under test: $($PY -c 'import aei_link_clearance as a;print(a.__version__, a.__file__)')"
node "$MAP_REPO/parity/runner_map.js" $FIX > "$OUT/map.json"
$PY "$HERE/runner_qgis.py" $FIX > "$OUT/qgis.json" 2>/dev/null
$PY "$MAP_REPO/parity/compare.py" "$OUT/map.json" "$OUT/qgis.json" "$HERE/fixtures" "$OUT/PARITY_REPORT.md" 2>/dev/null
$PY "$HERE/check_accepted_divergences.py" "$OUT/PARITY_REPORT.json"
echo "report: $OUT/PARITY_REPORT.md"
