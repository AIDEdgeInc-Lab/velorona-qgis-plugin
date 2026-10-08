#!/usr/bin/env python3
"""Fails unless EVERY stage of the parity report is MATCH (pairwise Map vs QGIS, and each product vs the spec oracle).

    python3 parity/check_accepted_divergences.py <PARITY_REPORT.json>

AID-1 (the terrain flow typing a record's frequency Assumed) was CLOSED in 1.1.5 by the link-record terrain flow and the frequency-origin channel
(core/record_source.py), and the same channel types record antenna heights; the harness therefore accepts NO divergence any more. The AID-1
pattern is still recognised below only so that a regression is reported by name ("AID-1 REGRESSION") instead of as a bare provenance mismatch.
See ACCEPTED_INTERFACE_DIVERGENCES.md.
"""
import json
import re
import sys

report = json.load(open(sys.argv[1]))
fixtures = report["fixtures"]
problems, accepted = [], 0
for fid, v in fixtures.items():
    for s in v["pairwise"]:
        if s["result"] != "DIVERGE":
            continue
        if s["stage"] != "provenance.pairwise":
            problems.append("%s: pairwise %s DIVERGE (Map %s | QGIS %s)" % (fid, s["stage"], s["a"], s["b"]))
            continue
        diffs = [d for d in str(s["b"]).split("; ") if d and d != "same types"]
        aid1 = [d for d in diffs if re.match(r"^frequency: Map \['Observed'\] vs QGIS \[.*'Assumed'.*\]$", d)]
        problems.append("%s: provenance differs%s: %s" % (fid, " (AID-1 REGRESSION: record frequency typed Assumed)" if aid1 else "", diffs))
    for who in ("map_vs_spec", "qgis_vs_spec"):
        for s in v[who]:
            if s["result"] == "DIVERGE":
                problems.append("%s: %s %s DIVERGE (%s | %s)" % (fid, who, s["stage"], s["a"], s["b"]))
print("fixtures: %d | accepted divergences: %d | problems: %d" % (len(fixtures), accepted, len(problems)))
for p in problems:
    print("  PROBLEM", p)
sys.exit(1 if problems else 0)
