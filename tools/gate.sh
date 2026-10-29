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
    cat > "$HOOKS/pre-push" <<HOOK
#!/bin/sh
# Installed by tools/gate.sh --install-hook. Bypass only deliberately: git push --no-verify
exec "$ROOT/tools/gate.sh"
HOOK
    chmod +x "$HOOKS/pre-push"
    echo "pre-push hook installed at $HOOKS/pre-push (runs $ROOT/tools/gate.sh)"
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
