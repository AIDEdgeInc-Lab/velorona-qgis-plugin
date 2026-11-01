#!/bin/sh
# Local release gate (no GitHub Actions needed). Runs the same blocking lanes as .github/workflows/ci.yml:
#   unit tests + documented-skips check, Qt6 enum check, ruff (pyflakes-class errors), bandit (medium+), package build + verify,
#   and the Map/QGIS parity harness when its sibling Map checkout is present (otherwise reported as SKIPPED, never as passed).
# Appends one line {date, repo, SHA, result} to ~/velorona-repos/_private/GATE_LOG.md (override with GATE_LOG=...).
#
#   tools/gate.sh                 run the gate
#   tools/gate.sh --install-hook  install a pre-push hook that runs it (shared by all worktrees of this clone)
# Python: $GATE_PYTHON, else ~/.venvs/velorona-release/bin/python (the pinned libraries: aei-link-clearance 0.3.x, aei-history-contract 0.2.x, aei-microwave-link-exposure 0.2.x), else python3.
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

PY="${GATE_PYTHON:-$HOME/.venvs/velorona-release/bin/python}"
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
    # Any DIVERGE fails the gate unless it is exactly one of the owner-decided entries of parity/KNOWN_DIVERGENCES.json (printed every time).
    "$PY" - "$TMP/gate-parity/PARITY_REPORT.json" parity/KNOWN_DIVERGENCES.json <<'PYEOF'
import json, sys
report, known = json.load(open(sys.argv[1])), json.load(open(sys.argv[2]))
allowed = {(k["stage"], k["detail"]): k for k in known}
unexpected, tolerated = [], {}
for fixture, parts in report["fixtures"].items():
    for section, rows in parts.items():
        for row in rows if isinstance(rows, list) else []:
            if isinstance(row, dict) and row.get("result") == "DIVERGE":
                key = (row.get("stage"), row.get("b"))
                if key in allowed:
                    tolerated.setdefault(key, []).append(fixture)
                else:
                    unexpected.append((fixture, section, row.get("stage"), row.get("a"), row.get("b")))
for key, fixtures in tolerated.items():
    print(f"   KNOWN DIVERGENCE ({len(fixtures)} fixtures, owner-decided {allowed[key]['decided']}): {key[0]}: {key[1]}")
for item in unexpected[:10]:
    print("   UNEXPECTED DIVERGENCE:", *item)
sys.exit(1 if unexpected else 0)
PYEOF
}

# QGIS lane: the offline real-QGIS suites (no network). The suites import "velorona.*", so run them through a link named velorona.
QGIS_APP="${QGIS_APP:-/Applications/QGIS-final-4_2_2.app}"
qgis_check() {
    link="$TMP/gate-qgis-link"; rm -rf "$link"; mkdir -p "$link"; ln -s "$ROOT" "$link/velorona"
    RES="$QGIS_APP/Contents/Resources"; rc=0
    for t in qgis_ui_polish_e2e qgis_workflow_e2e qgis_batch_e2e qgis_usa_e2e qgis_selection_sync_e2e qgis_local_dem_e2e qgis_history_e2e qgis_link_weather_e2e; do
        QGIS_PREFIX_PATH="$QGIS_APP/Contents/MacOS" DYLD_FRAMEWORK_PATH="$QGIS_APP/Contents/Frameworks" PROJ_DATA="$RES/qgis/proj" PROJ_LIB="$RES/qgis/proj" \
        QT_QPA_PLATFORM=offscreen PYTHONPATH="${GATE_LIBS:-$HOME/.venvs/velorona-release-libs}:$RES/python3.12:$RES/python3.12/lib-dynload:$RES/python3.12/site-packages" \
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
