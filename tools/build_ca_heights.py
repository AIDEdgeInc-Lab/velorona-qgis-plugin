#!/usr/bin/env python3
"""Builds the Canadian antenna-height sidecar (velorona.ca-heights/1) from ISED's raw Fixed Service extract. Offline, stdlib only.

    python3 tools/build_ca_heights.py <TAFL_LTAF_Fixe.zip|.csv> <source-file-date YYYY-MM-DD> <out.json>

Reads by column position with a per-row layout check (core/countries/ised_heights.py); a mismatch aborts with an explicit message and writes nothing.
The output is NOT shipped with the plugin by default (owner decision D-Q11)."""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.countries import ised_heights  # noqa: E402
from core.countries.base import PackError  # noqa: E402

if len(sys.argv) != 4 or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", sys.argv[2]):
    sys.exit(__doc__)
try:
    data = ised_heights.build_sidecar(sys.argv[1], sys.argv[2])
except PackError as exc:
    sys.exit(f"REFUSED: {exc}")
tmp = sys.argv[3] + ".tmp"
with open(tmp, "w", encoding="utf-8") as fh:
    json.dump(data, fh, separators=(",", ":"), sort_keys=True)
os.replace(tmp, sys.argv[3])
print("wrote", sys.argv[3], data["counts"], "from", data["source"]["rows"], "rows")
