# 02 — Batch Processing vs single-link analysis: controlled comparison

Claim under test (from `core/batch.py` and `docs/BATCH_TERRAIN.md`): *each batch row is the same calculation as selecting that link and running Analyze: Terrestrial Path Clearance with the dialog's pre-filled values accepted untouched.* Automated evidence exists only offline with synthetic terrain (`tests/test_terrain_batch.py`, `tests/qgis_batch_e2e.py`); this protocol checks it in the real application with real elevation data.

No production data is changed: the analysis only reads layers. Scratch edits are made on GeoPackage copies in the evidence folder.

## 1. Tolerance rules (not invented — where they come from)

| Field group | Rule | Basis |
|---|---|---|
| Any number, batch CSV vs single-link **RAW DATA sheet / single-link CSV** | **Exact equality** (same decimal string / `float ==`) | The automated comparison asserts `==` on distance, bearing, frequency, available/required clearance, margin, Fresnel radius, and compares status, reason, terrain class, frequency origin, sample count (`tests/test_terrain_batch.py` `test_one_link_equals_…`, `test_every_parity_fixture_…`). Both paths run the same code on the same inputs; the batch CSV writes `repr(float)` (full precision, `core/batch.py _cell`) and RAW DATA is un-rounded (`core/presentation/workbook.py raw_rows`). |
| Number read from the **Details/Summary screen** vs batch | Equal after rounding the batch value to the digits the screen shows (difference ≤ ½ unit of the last displayed digit) | Details is a rounded display of the same values; this is display rounding, not an engineering tolerance. |
| Same link, same session, but the elevation provider answered differently between the two runs | **Not a pass and not a fail**: re-run both once; if still different record the elevation samples (`elevation_samples`, ELEVATION-TERRAIN sheet) and classify as environment until explained | Terrain input is a live external service; rows must be compared on identical elevation. |
| Decision (status, terrain class, near-threshold flag, reason text), provenance (frequency/height Observed/Assumed and source text), identity (link id, authorization number, endpoints) | **Exact match** | Required by the batch contract. |
| Velorona **Map** vs QGIS (out of scope here) | Per-field tolerances live in `aei-link-clearance/parity/compare.py` `TOL` (e.g. metres 1e-6 abs, ratio 1e-9 rel). Not used for this protocol. | |

Anything outside these rules is a **difference to explain before classifying**; if it cannot be explained as a documented display-rounding or provider effect it is a defect (S1 when the status or a clearance differs).

## 2. Field map (single-link ↔ batch column)

| Compare | Single-link source | Batch CSV column |
|---|---|---|
| Link identity | Details heading, `terrain.link_id` in RAW DATA, Evidence "Link" | `link_id`, `authorization_number`, `source_fid`, `batch_index` |
| Endpoints | Evidence rows Site A/B latitude, longitude | output feature geometry (first/last vertex); identify tool |
| Status & reason | Summary status line + reason | `status`, `reason`, `transient` |
| Terrain class, near threshold | `terrain.los_status`, `terrain.near_threshold` | `terrain_class`, `near_threshold` |
| Distance, bearing | `terrain.distance_km`, `terrain.bearing_deg` | `distance_km`, `bearing_deg` |
| Frequency + provenance | `terrain.frequency_ghz`; Evidence "Frequency" row (Observed/Assumed + source) | `frequency_ghz`, `frequency_origin` |
| Heights + provenance | Evidence "Antenna height A/B" rows; Details "Antenna height A/B" | `site_a_height_m`, `site_a_height_origin`, `site_b_height_m`, `site_b_height_origin` |
| Clearance | `terrain.first_fresnel_radius_m`, `terrain.required_clearance_m`, `terrain.terrain_clearance_m`, `terrain.margin_m`, `terrain.clearance_ratio`, `terrain.percent_fresnel_clear` | `first_fresnel_radius_m`, `required_clearance_m`, `available_clearance_m`, `margin_m`, `clearance_ratio`, `percent_fresnel_clear` |
| Critical point | `terrain.critical_distance_from_a_km` | `critical_distance_from_a_km` |
| Samples & source | `terrain.samples`; Evidence "Elevation source" | `elevation_samples`, `elevation_source` |
| Missing data | NO DATA panel with reasons | `status` = NO DATA, `reason`, numeric columns empty |

Units: km, m, GHz, degrees, ratio dimensionless — identical on both sides; a unit difference is a defect.

## 3. Candidate links (Canada, bundled snapshot dated 2026-09-01; confirm each id exists in your layer first)

| Code | Authorization | Why | Source facts (snapshot) |
|---|---|---|---|
| C1 | 010895086-001 | multi-frequency; record heights both ends | 11.3 km; 953.0 / 960.0 MHz; heights 13 / 75 m |
| C2 | 010869233-001 | multi-frequency; record heights | 8.0 km; 956.25 / 959.875 MHz; 20 / 54 m |
| C3 | 011076519-002 | single frequency | 11.6 km; 959.9375 MHz; 6.1 / 12.2 m |
| C4 | 010665829-002 | single frequency, tall A end | 12.7 km; 959.9375 MHz; 107 / 12 m |
| C5 | 010019479-004 | ~6 GHz band (rain-model range) | 19.0 km; four published frequencies, highest 6404.79 MHz; 31 / 22 m |
| C6 | 010665661-001 | long path | 44.5 km; 959.875 MHz; 90 / 70 m |
| C7 | 010032181-007 | highest frequency 85.125 GHz (upper part of the 0.1–100 GHz bound) | 4.4 km; four published frequencies, highest 85125 MHz; 39 / 44 m |
| C8 | 010047019-003 | **invalid height**: site B height 0.0 m (below the 0.1 m lower bound) | 0.1 km; heights 68 / 0.0 m → expected NO DATA. Offline check run for this document: batch core returns `NO DATA | antenna height B outside 0.1-1000 m` before any elevation request. In the single-link dialog expect either a refusal message at OK or a NO DATA panel with that reason — record which; the reason must match the batch row |
| C9 | (scratch copy of C1) | frequency blank in the copy | expected NO DATA; with fallback 7 GHz → Assumed |
| C10 | any USA link (REG-01) | heights not used → Assumed 30 m; frequency Observed from "FCC ULS record" | needs the USA pack |
| C11 | (scratch copy of C1, edited) | override: in the single-link dialog change frequency to 7 and Site A height to 40; in batch use fallback only for blank records, so C11 is **single-link only** and proves the Assumed/override wording | |

Statuses are not predicted: terrain is live. The test is agreement, not a particular status. Record the statuses obtained; at least one result should be something other than CLEAR across C1–C7 if the area allows (if every link is CLEAR add a longer/obstructed path of your choosing and record its id).

## 4. Procedure per link (PAR-01…PAR-10 = C1…C8, C10, C11; PAR for C9 uses batch only)

1. **Record inputs.** Open the layer attribute table (*Fixed Service links (CAN)*), filter `"authorization_number" = '<id>'`; record `frequencies_mhz`, `site_a_height_m`, `site_b_height_m`, `height_source`, endpoints (Identify). Note provenance as the record states it.
2. **Single-link run.** Edit ▸ Select ▸ Deselect All (all layers). Select **only** that link (Records row). Confirm no sites are selected anywhere (Layers panel selected-count). Analyze: Terrestrial Path Clearance; **accept the pre-filled dialog without editing** (except C11 where the override is the point). Wait for the result.
3. **Capture single-link evidence:** screenshots of Summary, Details, Evidence; export **Excel** (RAW DATA sheet = un-rounded values) and the single-result **CSV**; save both under `<TestID>/single/`.
4. **Batch run, same session, within a few minutes:** select the same link(s) (the whole set C1–C7 together is fine) → Terrain Clearance for Many Links ▸ *Selected features only*, limit 100, pause 0, CSV `<TestID>/batch/batch.csv`.
5. **Compare** with the field map in §2 using the results table below (use a spreadsheet; paste both RAW sources). Compute numeric difference as batch − single in the field's unit.
6. **Explain every difference** (display rounding / provider answered differently / defect) in *Notes* before setting *Status*.
7. Repeat step 4 once for repeatability; the second batch must equal the first exactly (BAT-08).

## 5. Pass rule
A link passes only if: identity and endpoints match; every numeric field is within the §1 rule; status, reason, terrain class and near-threshold flag match; frequency and both heights agree in value **and** in provenance kind and source text; missing-data links are NO DATA with the same reason on both sides and no numbers. One unexplained difference fails the link.

## 6. Results table (copy into the evidence workbook)

| Test ID | Link ID | Single-link result (status; key numbers) | Batch result (status; key numbers) | Numeric difference (per field, unit) | Decision match | Provenance match | Status (Pass/Fail/Not run) | Notes (explanation of any difference) |
|---|---|---|---|---|---|---|---|---|
| PAR-01 | 010895086-001 | | | | | | | |
| PAR-02 | 010869233-001 | | | | | | | |
| PAR-03 | 011076519-002 | | | | | | | |
| PAR-04 | 010665829-002 | | | | | | | |
| PAR-05 | 010019479-004 | | | | | | | |
| PAR-06 | 010665661-001 | | | | | | | |
| PAR-07 | 010032181-007 | | | | | | | |
| PAR-08 | 010047019-003 (NO DATA expected) | | | | | | | |
| PAR-09 | USA link ____ | | | | | | | |
| PAR-10 | scratch C11 (override, single only) / C9 (blank frequency, batch with and without fallback) | | | | | | | |

Per-field detail sheet (one per link): columns `Field | Unit | Single (RAW/CSV) | Batch CSV | Difference | Rule applied | Match`, rows = every line of §2.

## 7. Evidence collection without changing production data
- Work in the disposable project and clean profile only; never edit `fixed_service_snapshot.json` or the layers of a real project. Scratch edits only in `<evidence>/scratch/*.gpkg`.
- Keep downloads, exports and screenshots under `~/velorona-acceptance/<date>/<TestID>/`; record SHA-256 of each exported file.
- If Open-Meteo rate-limits (NO DATA "elevation data unavailable", transient), wait and repeat both runs; note the time.
