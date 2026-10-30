"""Copies the Map's message registry into the plugin: python tools/sync_messages.py <Map>/web/messages.json  (then run the tests)."""
import json
import os
import shutil
import sys

DEST = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core", "messages.json")
if len(sys.argv) != 2:
    sys.exit(__doc__)
data = json.load(open(sys.argv[1], encoding="utf-8"))
assert data.get("schema") == "velorona.messages/1" and data["messages"], "not a velorona.messages/1 registry"
shutil.copyfile(sys.argv[1], DEST)
print(f"copied {len(data['messages'])} messages to {DEST}")
