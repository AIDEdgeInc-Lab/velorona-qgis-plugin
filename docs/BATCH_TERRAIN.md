# Batch terrain clearance (Processing algorithm)

`velorona:terrain_clearance_batch` -- "Terrain clearance for many Fixed Service links" (Processing Toolbox > Velorona, or the menu item Analyze: Terrain Clearance for Many Links).
It runs the existing single-link Terrestrial Path Clearance for every link of a layer (or its selected links) and writes one row per link.

## What a row is
Each row is **the same calculation** as selecting that link and running Analyze: Terrestrial Path Clearance with the dialog's pre-filled values accepted: the record's own highest published
frequency (typed Observed), the record's own antenna heights where the record carries them (Observed; Canada), otherwise 30 m (Assumed). `core/batch.py` calls
`terrestrial.build_link_params` and `terrestrial.analyze_link_record` -- there is no second calculation. Batch-only fields: `batch_index`, `source_fid`, and the statuses of links that were not attempted.

## Statuses (every row has one, with a reason)
| status | meaning |
|---|---|
| CLEAR / WATCH / AT RISK / CRITICAL | the terrain result, as in the single-link flow. WATCH (clearance ratio below 1.3) is a provisional threshold, not physics- or operator-validated. |
| NO DATA | a required input is missing or invalid, or elevation data could not be retrieved. The reason is in `reason`; `transient` is true when a retry may help. Nothing is guessed. |
| ERROR | an unexpected failure for that link (`error_type` and the message are given). The batch continues. |
| NOT RUN | not attempted: over the run limit, or the run was cancelled. |

A library too old for the corrected earth-curvature convention stops the whole batch (it would be wrong for every link); it is never reported row by row.

## One deliberate difference from the single-link flow
The single-link dialog always shows a frequency (the record's, else 7 GHz) and the user confirms it. A batch has no confirmation step, so **a record that publishes no usable frequency is NO DATA**
unless you enter a fallback frequency (then it is typed Assumed). Layers that are not Velorona Fixed Service layers carry no record frequency or heights: give a fallback frequency or every link is NO DATA.

## Parameters
Input line layer (only selected features if chosen); most links per run (default 100, at most 1000); optional fallback frequency (0.1-100 GHz); pause between links (0-30 s); output layer; optional CSV.
Each link makes one Open-Meteo elevation request (50 points). The provider rate-limits (HTTP 429 after a few thousand points in a short time was seen in the Map's parity work), which is why a run is capped,
refused up front when the input is larger than the limit, and has an optional pause.

## Output
A line layer with each link's own geometry and the columns in `core/batch.COLUMNS` (ids, status, reason, terrain class, distance/bearing, frequency and its origin, both heights and their origins, Fresnel radius,
required/available clearance, margin, ratio, percent Fresnel clear, critical distance, elevation samples and source). The optional CSV has the same rows under a `# ` header with the product, library versions,
curvature convention, what a row means and the counts. Input geometry and attributes are never modified; endpoints are reprojected to EPSG:4326 for the calculation only.

## How it is checked
* `tests/test_terrain_batch.py` (QGIS-free, runs anywhere): each batch row equals an independently written single-link analysis on all 58 shared Map/QGIS parity fixtures that carry terrain (real engine and library; only the
  elevation HTTP edge is replaced, with the fixtures' synthetic terrain); a failing link does not stop the batch; incomplete input, fallback frequency, empty input, limit, cancel, no input mutation, determinism, CSV.
* `tests/qgis_batch_e2e.py` (needs QGIS 4; part of `tests/run_qgis_tests.sh`): the Processing layer in a real QGIS -- provider registration, parameter validation, reading features (EPSG:4326 and a reprojected layer),
  selected-only input, output table, CSV, empty input, and row-equals-single-link on real `QgsFeature`s.
  **At the time of writing it had not been run**: the environment that produced it had no QGIS. Until it has passed on a Mac, treat the Processing wrapper (`core/processing/`) and the menu action as untested.

## Limits
Terrain only (no weather exposure in this algorithm). 90 m surface model that may include canopy and rooftops. Not an outage prediction, not a field measurement. Results at the elevation provider's mercy: a transient failure
is NO DATA for that link, not a retry loop. Record antenna heights are licensee-reported (ISED column 29); FCC heights are not used (see `parity/` HEIGHTS_CONTRACT in the Map repo).
