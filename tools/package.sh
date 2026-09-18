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

# Runtime content only. tests/ and tools/ are development-only; caches and
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
    . | tar -C "$STAGE/$NAME" -xf -

(cd "$STAGE" && zip -qr9 "$ZIP" "$NAME")
rm -rf "$STAGE"

echo "built: $ZIP"
ls -lh "$ZIP" | awk '{print "size:", $5}'
