"""Kept for old instructions: same as tools/sync_from_map.py <Map checkout> (accepts the Map's web/messages.json path too)."""
import os
import runpy
import sys

if len(sys.argv) == 2 and sys.argv[1].endswith("messages.json"):
    sys.argv[1] = os.path.dirname(os.path.dirname(os.path.abspath(sys.argv[1])))
runpy.run_path(os.path.join(os.path.dirname(os.path.abspath(__file__)), "sync_from_map.py"), run_name="__main__")
