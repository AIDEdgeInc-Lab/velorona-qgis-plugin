# Accepted interface divergences (Map vs QGIS)

> **Status 2026-10-08: no divergence is accepted.** AID-1 below is CLOSED for the harness (Canada and USA): the QGIS terrain flow can now start from one selected
> link record and types the record's frequency (and, for US records that carry them, antenna heights) Observed only while unchanged (`core/record_source.py`).
> It remains true of the two-free-sites flow, where the user types the value and Assumed is correct in both products. `check_accepted_divergences.py` now fails
> on ANY divergence and names an AID-1 pattern as a regression. The original text is kept for the record.

## (historical) Canada parity

Every other stage of the parity run must MATCH. This file lists the only differences that are accepted, why, and how the parity run keeps them
from growing. `parity/check_accepted_divergences.py` fails the run if anything else differs.

## AID-1 — terrain-flow frequency is typed Assumed in QGIS (provenance, row `Frequency`)
| | Velorona Map | Velorona for QGIS |
|---|---|---|
| Where the frequency comes from in the terrain analysis | pre-filled from the selected ISED link record (highest published frequency) | the analysis dialog only (default 7.0 GHz); `core/engines/terrestrial.py` `build_params()` reads only antenna heights from a feature, never a frequency |
| Evidence type | **Observed** (a record's own value) | **Assumed** (user-provided; never Observed — owner decision P9) |

**Why it is not a correctness defect.** In QGIS the value really is entered by the user, so Assumed is the accurate, conservative label for what
that flow does. The parity fixtures feed the record's frequency to both products; that is a *Map* behaviour (pre-fill) QGIS does not have, not a
QGIS mis-label. Typing the record's value by hand does not make it a record-sourced observation.
**Cost.** The two products label that one row differently for the same link; QGIS under-claims.
**Not in scope here.** Giving the QGIS terrain flow a record binding (so it could type the frequency Observed) is a feature, not a fix: it needs
a "this is the link" concept for the two selected sites, dialog pre-fill and e2e coverage. Deferred, not rejected.
**Scope of the exception.** Only the `Frequency` row, only Observed (Map) vs Assumed (QGIS), only in the terrain evidence. Weather evidence
(Fixed Service link flow) types frequency by its origin in both products and matches.
