#!/bin/sh
# Local release gate (no GitHub Actions needed). Runs the same blocking lanes as .github/workflows/ci.yml:
#   unit tests + documented-skips check, Qt6 enum check, ruff (pyflakes-class errors), bandit (medium+), package build + verify,
#   and the Map/QGIS parity harness when its sibling Map checkout is present (otherwise reported as SKIPPED, never as passed).
# Appends one line {date, repo, SHA, result} to ~/velorona-repos/_private/GATE_LOG.md (override with GATE_LOG=...).
#
#   tools/gate.sh                 run the gate
#   tools/gate.sh --install-hook  install a pre-push hook that runs it (shared by all worktrees of this clone)
# Python: $GATE_PYTHON, else ~/.venvs/velorona-gate/bin/python, else python3.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$HERE")"
cd "$ROOT" || exit 2

if [ "${1:-}" = "--install-hook" ]; then
    HOOKS="$(git rev-parse --git-common-dir)/hooks"
    mkdir -p "$HOOKS"
    cat > "$HOOKS/pre-push" <<'HOOK'
#!/bin/sh
# Installed by tools/gate.sh --install-hook. Runs the gate of the worktree being pushed from.
# Bypass only deliberately: git push --no-verify
TOP="$(git rev-parse --show-toplevel)"
if [ -x "$TOP/tools/gate.sh" ]; then exec "$TOP/tools/gate.sh"; fi
echo "pre-push: no tools/gate.sh in $TOP, gate not run" >&2
HOOK
    chmod +x "$HOOKS/pre-push"
    echo "pre-push hook installed at $HOOKS/pre-push"
    exit 0
fi

PY="${GATE_PYTHON:-$HOME/.venvs/velorona-gate/bin/python}"
[ -x "$PY" ] || PY="python3"
LOG="${GATE_LOG:-$HOME/velorona-repos/_private/GATE_LOG.md}"
REPO="$(basename "$(git remote get-url origin 2>/dev/null | sed 's/\.git$//')")"
[ -n "$REPO" ] || REPO="$(basename "$ROOT")"
SHA="$(git rev-parse --short HEAD)"
DIRTY=""; [ -z "$(git status --porcelain)" ] || DIRTY="+dirty"
FAILED=""; SKIPPED=""

step() {   # step <name> <command...>
    name="$1"; shift
    printf '\n== %s\n' "$name"
    if "$@"; then echo "-- $name: ok"; else echo "-- $name: FAILED"; FAILED="$FAILED $name"; fi
}

TMP="${TMPDIR:-/tmp}"
VERSION="$(sed -n 's/^version=//p' metadata.txt | tr -d '[:space:]')"
package_check() { ./tools/package.sh >/dev/null && "$PY" tools/verify_package.py "dist/velorona-$VERSION.zip" "$VERSION"; }
parity_check() {
    QGIS_REPO="$ROOT" OUT="$TMP/gate-parity" PATH="$(dirname "$PY"):$PATH" sh "$MAP_REPO/parity/run_all.sh" || return 1
    ! grep -q DIVERGE "$TMP/gate-parity/PARITY_REPORT.md"
}

# Seam lane: the same suite against the UNRELEASED library (aei-link-clearance 0.3, local checkout installed editable in a second venv),
# where tests/test_elevation_seam.py must RUN (not skip). Only the pin test differs: the plugin still pins the released 0.2 line until approval.
SEAM_PY="${GATE_SEAM_PYTHON:-$HOME/.venvs/velorona-seam/bin/python}"
seam_check() {
    "$SEAM_PY" -m pytest tests -q -rs --deselect tests/test_dependencies.py::test_installed_link_clearance_is_inside_the_declared_range \
        --junitxml="$TMP/gate-seam.xml" || return 1
    "$SEAM_PY" - "$TMP/gate-seam.xml" <<'PYEOF'
import sys, xml.etree.ElementTree as ET
cases = [tc for tc in ET.parse(sys.argv[1]).getroot().iter("testcase") if "test_elevation_seam" in (tc.get("classname") or "")]
ran = [tc for tc in cases if tc.find("skipped") is None]
print(f"   test_elevation_seam: {len(ran)} ran, {len(cases) - len(ran)} skipped")
sys.exit(0 if ran and len(ran) == len(cases) else 1)
PYEOF
}
# QGIS lane: the offline real-QGIS suites (no network). The suites import "velorona.*", so run them through a link named velorona.
QGIS_APP="${QGIS_APP:-/Applications/QGIS-final-4_2_2.app}"
qgis_check() {
    link="$TMP/gate-qgis-link"; rm -rf "$link"; mkdir -p "$link"; ln -s "$ROOT" "$link/velorona"
    RES="$QGIS_APP/Contents/Resources"; rc=0
    for t in qgis_ui_polish_e2e qgis_workflow_e2e qgis_batch_e2e qgis_usa_e2e qgis_selection_sync_e2e qgis_local_dem_e2e; do
        QGIS_PREFIX_PATH="$QGIS_APP/Contents/MacOS" DYLD_FRAMEWORK_PATH="$QGIS_APP/Contents/Frameworks" PROJ_DATA="$RES/qgis/proj" PROJ_LIB="$RES/qgis/proj" \
        QT_QPA_PLATFORM=offscreen PYTHONPATH="${GATE_LIB_SRC:-$HOME/velorona-repos/_worktrees/lc-seam/src}:$RES/python3.12:$RES/python3.12/lib-dynload:$RES/python3.12/site-packages" \
        "$QGIS_APP/Contents/MacOS/python3.12" "$link/velorona/tests/$t.py" >"$TMP/gate-$t.log" 2>&1 && echo "   $t ok" || { echo "   $t FAILED (see $TMP/gate-$t.log)"; rc=1; }
    done
    return $rc
}

step unit "$PY" -m pytest tests -q -rs --junitxml="$TMP/gate-pytest.xml"
step skips "$PY" tools/check_skips.py "$TMP/gate-pytest.xml"
step enums "$PY" tools/check_qt6_enums.py
if "$PY" -m ruff --version >/dev/null 2>&1; then
    # Real-error classes only (syntax, undefined names, invalid comparisons); style cleanup of existing code is not a release gate.
    step lint "$PY" -m ruff check --select E9,F63,F7,F82 --exclude dist,parity .
else echo "-- lint: ruff not installed"; FAILED="$FAILED lint(ruff-missing)"; fi
if "$PY" -m bandit --version >/dev/null 2>&1; then
    step security "$PY" -m bandit -q -r . -ll --exclude ./tests,./tools,./parity,./dist,./.git
else echo "-- security: bandit not installed"; FAILED="$FAILED security(bandit-missing)"; fi
step package package_check
if [ -x "$SEAM_PY" ]; then step seam seam_check; else echo "-- seam: SKIPPED (no $SEAM_PY)"; SKIPPED="$SKIPPED seam"; fi
if [ -x "$QGIS_APP/Contents/MacOS/python3.12" ]; then step qgis-offline qgis_check; else echo "-- qgis-offline: SKIPPED (no QGIS at $QGIS_APP)"; SKIPPED="$SKIPPED qgis-offline"; fi

MAP_REPO="${MAP_REPO:-$HOME/velorona-repos/aei-link-clearance}"
if [ -f "$MAP_REPO/parity/run_all.sh" ] && [ -f parity/runner_qgis.py ]; then
    step parity parity_check
else
    echo "-- parity: SKIPPED (no Map checkout at $MAP_REPO)"; SKIPPED="$SKIPPED parity"
fi

if [ -z "$FAILED" ]; then RESULT="PASS"; else RESULT="FAIL:${FAILED# }"; fi
[ -z "$SKIPPED" ] || RESULT="$RESULT (skipped:${SKIPPED# })"
mkdir -p "$(dirname "$LOG")"
[ -s "$LOG" ] || printf '# Local gate log\n\n| date (UTC) | repo | SHA | result |\n|---|---|---|---|\n' > "$LOG"
printf '| %s | %s | %s%s | %s |\n' "$(date -u +%Y-%m-%dT%H:%MZ)" "$REPO" "$SHA" "$DIRTY" "$RESULT" >> "$LOG"
printf '\nGATE %s  (%s %s%s)\n' "$RESULT" "$REPO" "$SHA" "$DIRTY"
[ -z "$FAILED" ]
