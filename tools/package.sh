#!/bin/sh
# Builds the installable QGIS plugin ZIP.
#
# QGIS expects the archive to contain exactly one top-level directory whose
# name is the plugin's Python package (here: velorona), so that extracting it
# into the profile's python/plugins/ yields python/plugins/velorona/.
#
#   ./tools/package.sh          -> dist/velorona-<version>.zip
set -e

HERE="$(cd "$(dirname "$0")" && pwd)"
PLUGIN="$(dirname "$HERE")"
NAME="velorona"
VERSION="$(sed -n 's/^version=//p' "$PLUGIN/metadata.txt" | tr -d '[:space:]')"

if [ -z "$VERSION" ]; then
    echo "could not read version= from metadata.txt" >&2
    exit 1
fi

DIST="$PLUGIN/dist"
STAGE="$DIST/stage"
ZIP="$DIST/${NAME}-${VERSION}.zip"

rm -rf "$STAGE" "$ZIP"
mkdir -p "$STAGE/$NAME"

# Runtime content only. tests/, tools/, the internal SESSION_HANDOFF.md and the
# GitHub community files (.github/, CONTRIBUTING.md) are development-only; caches and
# build output never ship.
tar -C "$PLUGIN" -cf - \
    --exclude='.git' \
    --exclude='.gitignore' \
    --exclude='__pycache__' \
    --exclude='*.py[cod]' \
    --exclude='.pytest_cache' \
    --exclude='.DS_Store' \
    --exclude='dist' \
    --exclude='tests' \
    --exclude='tools' \
    --exclude='SESSION_HANDOFF.md' \
    --exclude='.github' \
    --exclude='CONTRIBUTING.md' \
    . | tar -C "$STAGE/$NAME" -xf -

# Bundle the shared workflow core (aei-workflow-runner, Apache-2.0) so the zip runs the exact version it was tested with and needs no
# pip install. Set AEI_WORKFLOW_SRC to the repository checkout (default: a sibling directory). A dirty checkout is refused, so the
# recorded commit always describes the bytes that ship; ALLOW_DIRTY_VENDOR=1 overrides that for local experiments only.
CORE="${AEI_WORKFLOW_SRC:-}"
if [ -z "$CORE" ]; then
    for cand in "$PLUGIN/../aei-workflow-runner" "$PLUGIN/../../aei-workflow-runner"; do
        [ -d "$cand/src/aei_workflow" ] && CORE="$(cd "$cand" && pwd)" && break
    done
fi
if [ -z "$CORE" ] || [ ! -d "$CORE/src/aei_workflow" ]; then
    echo "aei-workflow-runner not found; set AEI_WORKFLOW_SRC to its repository checkout" >&2
    exit 1
fi
if [ -n "$(git -C "$CORE" status --porcelain 2>/dev/null)" ] && [ "${ALLOW_DIRTY_VENDOR:-}" != "1" ]; then
    echo "aei-workflow-runner has uncommitted changes; commit them (or set ALLOW_DIRTY_VENDOR=1 for a throwaway build)" >&2
    exit 1
fi
mkdir -p "$STAGE/$NAME/_vendor"
tar -C "$CORE/src" -cf - --exclude='__pycache__' --exclude='*.py[cod]' aei_workflow | tar -C "$STAGE/$NAME/_vendor" -xf -
cp "$CORE/LICENSE" "$STAGE/$NAME/_vendor/aei_workflow/LICENSE"
CORE_VERSION="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$CORE/src/aei_workflow/__init__.py")"
{
    echo "aei-workflow-runner $CORE_VERSION"
    echo "commit: $(git -C "$CORE" rev-parse HEAD 2>/dev/null || echo unknown)"
    echo "license: Apache-2.0 (see LICENSE)"
} > "$STAGE/$NAME/_vendor/aei_workflow/VENDORED.txt"

(cd "$STAGE" && zip -qr9 "$ZIP" "$NAME")
rm -rf "$STAGE"

echo "built: $ZIP"
ls -lh "$ZIP" | awk '{print "size:", $5}'
