#!/usr/bin/env python3
"""Fails unless the parity report contains NOTHING except the accepted interface divergence AID-1 (see ACCEPTED_INTERFACE_DIVERGENCES.md).

    python3 parity/check_accepted_divergences.py <PARITY_REPORT.json>

Accepted: `provenance.pairwise` differing ONLY in the `frequency` row, Map ['Observed'] vs QGIS containing 'Assumed'.
Everything else must be MATCH, and each product must match the spec oracle on every stage (no `*_vs_spec` DIVERGE).
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
        bad = [d for d in diffs if not re.match(r"^frequency: Map \['Observed'\] vs QGIS \[.*'Assumed'.*\]$", d)]
        if bad:
            problems.append("%s: provenance differs beyond AID-1: %s" % (fid, bad))
        else:
            accepted += 1
    for who in ("map_vs_spec", "qgis_vs_spec"):
        for s in v[who]:
            if s["result"] == "DIVERGE":
                problems.append("%s: %s %s DIVERGE (%s | %s)" % (fid, who, s["stage"], s["a"], s["b"]))
print("fixtures: %d | AID-1 occurrences accepted: %d | problems: %d" % (len(fixtures), accepted, len(problems)))
for p in problems:
    print("  PROBLEM", p)
sys.exit(1 if problems else 0)
