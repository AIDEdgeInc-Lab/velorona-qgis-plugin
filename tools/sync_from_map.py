"""Copies the Map's shared registries into the plugin (never edit the copies by hand):

    python tools/sync_from_map.py <Map checkout>

  <Map>/web/messages.json      -> core/messages.json      (message IDs and short texts)
  <Map>/web/data/packs.json    -> core/packs.json         (data packs, verification level)
  <Map>/web/data/entitlements.json -> core/entitlements.json (plan limits)
Then run the tests: the drift tests compare each copy with the Map checkout."""
import json
import os
import shutil
import sys

CORE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core")
FILES = (("web/messages.json", "messages.json", "velorona.messages/1"),
         ("web/data/packs.json", "packs.json", "velorona.packs/1"),
         ("web/data/entitlements.json", "entitlements.json", "velorona.entitlements/1"))

if len(sys.argv) != 2:
    sys.exit(__doc__)
for rel, dest, schema in FILES:
    src = os.path.join(sys.argv[1], rel)
    if not os.path.exists(src):
        print(f"skipped {rel}: not in this Map checkout")
        continue
    data = json.load(open(src, encoding="utf-8"))
    if data.get("schema") != schema:
        sys.exit(f"{rel}: schema {data.get('schema')!r}, expected {schema!r}; not copied")
    shutil.copyfile(src, os.path.join(CORE, dest))
    print(f"copied {rel} -> core/{dest}")
