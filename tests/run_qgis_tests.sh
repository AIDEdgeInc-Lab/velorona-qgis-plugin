#!/bin/sh
# Runs the Velorona test suite against the installed QGIS 4.x Python.
#
# The QGIS.app bundle ships a Python whose compiled-in prefix points at the
# build machine, so PYTHONHOME/PYTHONPATH have to be pointed at the bundle's
# own stdlib, lib-dynload and site-packages before `import qgis` works
# headlessly. QT_QPA_PLATFORM=offscreen lets the real QgsMapCanvas render
# without a display.
#
#   ./tests/run_qgis_tests.sh              # unit + QGIS end-to-end
#   ./tests/run_qgis_tests.sh --bench      # also run the performance benchmark
#
# Override QGIS_APP for a different install location or version.
set -e

QGIS_APP="${QGIS_APP:-/Applications/QGIS-final-4_2_2.app}"
RES="$QGIS_APP/Contents/Resources"
QGISPY="$QGIS_APP/Contents/MacOS/python3.12"

if [ ! -x "$QGISPY" ]; then
    echo "QGIS Python not found at $QGISPY" >&2
    echo "Set QGIS_APP to your QGIS.app, e.g. QGIS_APP=/Applications/QGIS.app $0" >&2
    exit 1
fi

export QGIS_PREFIX_PATH="$QGIS_APP/Contents/MacOS"
export PYTHONPATH="$RES/python3.12:$RES/python3.12/lib-dynload:$RES/python3.12/site-packages"
export DYLD_FRAMEWORK_PATH="$QGIS_APP/Contents/Frameworks"
export PROJ_DATA="$RES/qgis/proj"
export PROJ_LIB="$PROJ_DATA"
export QT_QPA_PLATFORM=offscreen

HERE="$(cd "$(dirname "$0")" && pwd)"
PLUGIN="$(dirname "$HERE")"

echo "== unscoped Qt enum / removed-idiom check =="
/usr/bin/env -u PYTHONPATH -u DYLD_FRAMEWORK_PATH python3 "$PLUGIN/tools/check_qt6_enums.py"

echo
echo "== unit tests (no QGIS needed) =="
/usr/bin/env -u PYTHONPATH -u DYLD_FRAMEWORK_PATH python3 -m pytest "$HERE" -q

echo
echo "== QGIS end-to-end runtime test =="
"$QGISPY" "$HERE/qgis_e2e.py"

if [ "$1" = "--bench" ]; then
    echo
    echo "== performance benchmark =="
    "$QGISPY" "$HERE/benchmark_viewport.py" "${2:-run}"
fi
