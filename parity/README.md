# parity/ (QGIS side) — see the Map repo parity/README.md for the full description; run_all.sh, compare.py, canonical.py live there

Canada AND USA (54 fixtures). The US fixtures, `schema.json` and `MANIFEST.sha256` are byte-identical copies of the Map workstream's files (verified by `run_parity.sh` against that manifest). Changes **no product behaviour**. Everything here is new; no existing source file is edited.

    QGIS_REPO=~/velorona-repos/velorona OUT=/tmp/parity-out sh parity/run_all.sh     # no network, no writes outside OUT

| file | role |
|---|---|
| `fixtures/schema.json`, `fixtures/ca-*.json` | 16 frozen inputs (identical copy in the QGIS repo's `parity/fixtures/`) |
| `build_fixtures.py` | how the fixtures were made (run once; the JSON is the artefact) |
| `runner_map.js` | loads `web/*.js` into a vm context, calls `getElevations` (failure path), `analyzeLinkFromElevations`, `explainResult`, `terrestrialEvidenceRows`, `analyzeMicrowaveLink`; `fetch` serves frozen data |
| `canonical.py` | the spec as an oracle (`CANONICAL_DECISION_SPEC.md`), constants tagged SOURCED / CARRIED OVER / PROPOSED |
| `compare.py` | per-stage MATCH/DIVERGE with tolerances → `PARITY_REPORT.md` |
| (QGIS repo) `parity/runner_qgis.py` | calls `analyze_link`, `analyze_sites`, `terrain_brief`, `exposure_brief`, `export.result_to_csv` |

## How links were chosen
From `web/fixed_service_snapshot.json` (sha256 in each fixture): haversine distance and highest published frequency computed for all 16,956 links; one link per role picked from that table by attribute (short ≈0.6–0.7 km near 7 GHz; long 203 km; highest frequency 85 GHz; three ≈38 km links at 6–7 GHz). The link with a latitude typo (`010312035-007`) was deliberately not used. Each fixture's `note` states why it was chosen; `build_fixtures.py` holds the list.

## What is real and what is synthetic
REAL: link id, endpoint coordinates, published frequencies. SYNTHETIC: terrain (flat 100 m + triangular hump sized to hit a stated Fresnel-clearance target), the Open-Meteo `current` block, `fade_margin_db` (not published by ISED), polarization, antenna heights (product default 30 m). One fixture (`ca-low-headroom`) overrides frequency to 1.0 GHz (user-entered, Assumed). Each fixture lists its synthetic blocks.

## Known couplings
* QGIS runner registers an empty stand-in `qgis.core` (three placeholder classes) so the real `core/engines/microwave_exposure.py` imports without QGIS.
* QGIS runner uses the sibling `aei-*/src` checkouts (as `tests/conftest.py` does), not the PyPI wheels a shipped plugin loads.
* Map runner takes sample points from the fixture instead of `app.js`'s own sampling (DOM-bound).
* ECCC station/radar are stubbed as "none found" in both products; hourly history is not exercised.

## Rain-stage requirement (2026-10-09)
The weather expectations in the fixtures were recomputed by the Map workstream from the ITU-R P.838-3 equations (Map commit `d2090c3`: new `ca-rain-{6,7,8,11}ghz`, `us-rain-*`, `sb2-*` fixtures). They match only an
`aei-microwave-link-exposure` that reproduces the Recommendation (0.2.0+). `run_parity.sh` refuses to run against an older one (exit 3). Negative control (OBSERVED): with 0.1.5 the harness reports 96 problems;
with 0.2.0 built from the library repo (`4b13f64`): 68 fixtures, 1,414 stage comparisons, 0 non-MATCH.
