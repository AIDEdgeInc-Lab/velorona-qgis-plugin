# 05 — Criteria for advancing the candidate to release review

Advancing means "the owner may review a release"; it is not a release approval. Automated green results are necessary, never sufficient.

## 1. Gate (all must hold)

| # | Criterion | Evidence | Tests |
|---|---|---|---|
| R1 | **No regression in existing single-link analysis**: Summary/Details/Evidence and exports for Canada (and USA if tested) match 1.1.9 for the same link and inputs, except the intended wording change (Details/Excel state origin instead of "entered by the user") | side-by-side with the 1.1.9 profile | INS-04, INS-05, DET-01…05, REG-02 |
| R2 | **No conflicting selection/details state**: map selection, highlighted Records row and Details never name different records; stale details cleared | screenshots at every step | SEL-01…SEL-09, PRJ-04 |
| R3 | **No data loss on layer/project reopen**: reopening neither duplicates nor drops layers/settings beyond what QGIS itself does; USA source setting and imagery group survive; a 1.1.9-saved project upgrades in place | PRJ log + screenshots | PRJ-01…PRJ-08 |
| R4 | **Batch agrees with single-link**: for every candidate link, within the §1 rules of `02_*`, decisions and provenance equal; any difference explained as display rounding or a documented provider effect | filled results table + both exports | PAR-01…PAR-10 |
| R5 | **CSV is valid and maps each result to its link**: header = field list, one row per input link, counts consistent, identity/geometry correspond; repeat run identical | CSV + SHA-256 | BAT-02, BAT-06, BAT-07, BAT-08 |
| R6 | **Cancellation and invalid input are safe**: Cancel stops promptly, remaining links are NOT RUN, nothing dropped; bad records are NO DATA with a reason and do not alter other rows | logs + tables | BAT-03, BAT-05 |
| R7 | **Existing capabilities remain available**: all 1.1.9 actions, layers, panels, datasets, exports present; the 8 actions and the Processing provider appear; USA setup; satellites behave per REG-03 or are recorded not-run with the reason | INS-03, INS-05, REG-* | |
| R8 | **Mandatory tests pass** (below), or each exception is written down with owner acceptance (name, date, reason) | evidence template §3 | |
| R9 | **Environment limits distinguished from defects**: every NO DATA caused by a rate-limit/outage is labelled environment and repeated later; a test that could not run (e.g. no live CelesTrak) is "Not run", never "Pass" | evidence template | |
| R10 | **Version bumped** in `metadata.txt` and the changelog for any release containing these changes (the published 1.1.9 must not be re-used); the ZIP built from a committed tree, `tools/verify_package.py` PASS, SHA-256 recorded | release engineer | not part of this package |

## 2. Mandatory tests
All S1 tests in `01_*`, `03_*` and the PAR set must be Pass. S2 failures need a recorded decision (fix now / accept with note). S3 may ship with a note. A "Not run" S1 test blocks the gate unless the owner records an accepted exception.

## 3. Automatic stop conditions (any one → NOT READY)
- Any traceback in the Python Error tab or Velorona log during the session.
- A wrong analytical result (status or clearance differing between batch and single-link without an explanation).
- Conflicting records shown (R2) even once.
- Loss or duplication of user layers after reopening.
- A missing 1.1.9 capability.

## 4. Known limitations that are *not* defects of this candidate (record, do not fail)
- Live-service outages or rate limits; CelesTrak intermittency.
- The Operator filter covers Canadian layers only (stated in the UI).
- Terrain data is a 90 m surface model; statuses are decision support, not field measurement.
- Run history/comparison/saved workflows are not in this candidate (`06_*`).
- Windows/Linux untested.

## 5. Decision record
Reviewer, date, candidate commit, ZIP SHA-256, outcome (Advance / Do not advance), accepted exceptions list, owner signature — fields in `07_EVIDENCE_TEMPLATE.md` §4.
