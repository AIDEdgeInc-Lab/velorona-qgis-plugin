# Operational output layer

The engineering calculations are unchanged. This layer changes how their results are
presented: what is said first, what each number is compared against, where the weather
came from, what changed, and what the Excel export contains.

Code: `core/presentation/` (QGIS-free) and `ui/operational_view.py`, `ui/charts.py`.

## 1. Audit: what is calculated

The authoritative table is `core/presentation/registry.py` (also exported as the workbook's
DATA DICTIONARY sheet). Summary:

| Area | Calculation | Formula / method | Unit | Threshold | Lives in |
|---|---|---|---|---|---|
| Terrain | Path distance | haversine(A, B) | km | none | aei_geo_features |
| Terrain | Bearing | initial great-circle bearing | deg | none | aei_link_clearance |
| Terrain | Earth bulge | h = d1·d2 / (2·k·R), k = 4/3 | m | none | aei_link_clearance |
| Terrain | First Fresnel radius | r1 = 17.3·√(d1·d2 / (f·(d1+d2))) | m | none | aei_link_clearance |
| Terrain | Clearance at a sample | LOS height − (ground − bulge) | m | none | aei_link_clearance |
| Terrain | Critical point | interior sample with lowest clearance / r1 | – | endpoints excluded | aei_link_clearance |
| Terrain | Required clearance | 0.60 · r1 at the critical point | m | 0.60 (standard practice, not an ITU-R figure) | aei_link_clearance |
| Terrain | Clearance ratio | available / required | ratio | 1.0 = minimum | aei_link_clearance |
| Terrain | LOS class | clear ≥ 0.60, marginal ≥ 0.30, else obstructed (fraction of r1) | class | 0.30 is the project's own judgment | aei_link_clearance |
| Terrain | Near threshold | 15 m / r1 swing straddles 0.60 or 0.30 | flag | 15 m DEM uncertainty | aei_link_clearance |
| Weather | Rain rate used | max(site A, site B) model rain rate | mm/h | none | aei_mw_exposure |
| Weather | Specific attenuation | γ = k·R^α (ITU-R P.838-3) | dB/km | 1–100 GHz | aei_mw_exposure |
| Weather | Effective path | d / (1 + d/d0), d0 = 35·e^(−0.015R) (ITU-R P.530) | km | R capped at 100 | aei_mw_exposure |
| Weather | Predicted rain fade | γ · d_eff | dB | none | aei_mw_exposure |
| Weather | Exposure ratio / severity | fade / fade margin; moderate ≥ 0.3, high ≥ 0.7 | ratio | library conventions, "not a validated risk model" | aei_mw_exposure |
| Weather | Station distance, representativeness | haversine; 50 km, 2.0 mm/h conventions | km | stated conventions | aei_mw_exposure |
| Satellite | Look angles | SGP4, topocentric alt/az/range; visible if elevation ≥ 10° | deg, km | 10° mask | skyfield |

Nothing in this table was changed.

## 2. Previous output architecture

```
engine result object (aei_*)
        │
        ├── ui/results_dock.py   _render_terrestrial / _render_microwave / _render_link_investigation
        │                        one HTML report: Observed → Calculated → Inferred sections
        └── core/export.py       result_to_csv → Evidence | Type | Source | Observation-Input |
                                 Calculated result | Interpretation (CSV only, no Excel)
```

### Confusing fields

| Field (where) | Why it was hard to read |
|---|---|
| "Clearance ratio 5.22" and "422% above minimum" (dock, CSV, `explain()`) | A ratio and a derived percentage the reader must convert back into metres. |
| "Exposure ratio 13%" (dock `:.0f`, CSV `:.1f`) | A percentage of what? Dock and CSV also disagreed on precision. |
| "Terrain clearance" next to "Required clearance" with no margin | The reader had to subtract. |
| "NEAR THRESHOLD" status | Not a state an operator can act on; it hid the underlying class. |
| "Severity: Moderate" | Different vocabulary from terrain status. |
| "Nearest ECCC weather station: ECCC SWOB-Realtime -- BRAMPTON" | Source and name fused; no statement of why that station. |
| "Observed" on Open-Meteo precipitation | It is a weather-model value at the site's coordinates, not a measurement. **Fixed**: Model-derived. |
| Weather values with no history | No way to tell whether conditions were improving or worsening. |
| Frequency `:.1f`, heights `:.0f` (dock) | Truncated operator input: 7.25 GHz showed as 7.2, 30.5 m as 30. **Fixed** (exact formatting, as the CSV already did). |

## 3. New output schema

Every important result is a `Brief` (`core/presentation/model.py`), rendered identically in
the dock, the Ask answers and the workbook:

```
status + reason   CLEAR | WATCH | AT RISK | CRITICAL | NO DATA, with one factual line
answer            plain-language sentence
key_facts         value (with unit) · what it is compared against · what it means
technical         ratios, Fresnel radius, k, coefficients, input origins
evidence          sample count, sources, calculation id
changes           value, arrow, delta, explicit baseline ("vs 1 hour ago")
sites             weather source, kind, time, why selected, station, distance
caveats           limits and assumptions
data              the un-rounded numbers behind the text
```

Three depths in the dock (selector above the report): **Summary** (technician),
**Details** (planner), **Evidence** (the original Observed / Calculated / Inferred report,
unchanged apart from the display fixes above). Excel carries the analyst view.

### Status mapping (a presentation of existing classifications, no new thresholds)

| Terrain (library result) | Status | | Weather (library result) | Status |
|---|---|---|---|---|
| obstructed | CRITICAL | | predicted fade ≥ fade margin | CRITICAL |
| marginal | AT RISK | | severity high | AT RISK |
| clear and (near_threshold or ratio < 1.3) | WATCH | | severity moderate | WATCH |
| clear | CLEAR | | severity low | CLEAR |
| no elevation profile | NO DATA | | no weather result | NO DATA |

1.3 is the library's own `COMFORTABLE_MARGIN_RATIO`. "Fade ≥ margin" is the definition of the
margin being used up. Both are checked against the library by the tests.

### Weather provenance

Each site shows source, kind (**Model-derived**, **Observed** station, **Derived** radar),
observation time, how it was selected, the nearest station with coordinates, distance and
time, whether the sources agree, and why. Station selection text mirrors
`find_nearest_station`'s defaults (50 km, 90 min); a test fails if the library's defaults change.

### History

Open-Meteo hourly model data (`past_hours=6`) at each site's coordinates. Hourly values are
compared with hourly values only. ↑ / ↓ mean the value differs at 0.1 precision; → means it
does not. That is a display rule, not a physical threshold.

### Ask

Rule-based intent matching over the current Brief. No language model; unanswerable questions
get "could not match" plus the list of what can be asked. Each answer cites its evidence.
Terrain questions on a weather result (and the reverse) say the analysis is not part of this result.

### Workbook (`.xlsx`, standard library writer, no openpyxl needed)

SUMMARY · LINK ANALYSIS · WEATHER · WEATHER HISTORY · ELEVATION-TERRAIN · EVIDENCE · RAW DATA ·
DATA DICTIONARY. ("ELEVATION / TERRAIN" is not a legal Excel sheet name; `/` is replaced.)
Numbers are numeric cells at full precision. EVIDENCE is read back from the CSV export, so the
two cannot disagree. Sheets that do not apply say so in one line.

## 4. Corrections and remaining questions

### Fixed in this pass

1. **Rain-rate fallback (snow shown as rain).** The library's `OpenMeteoProvider` uses
   `current.rain or current.precipitation`. Open-Meteo's `precipitation` is rain + showers +
   snowfall water equivalent, so a snow-only hour (rain 0, precipitation > 0) was fed to the
   rain-attenuation model as rain, and `showers` (liquid) was ignored. The plugin now uses
   `core/sources/open_meteo_rain.py` (a subclass; the published library is untouched):
   liquid rain = `rain + showers`, frozen part = total − liquid, shown as "not counted as rain".
   If the response reports neither `rain` nor `showers`, the value is labelled **total
   precipitation (may include snow)**; nothing is guessed. The only numeric effect is on hours
   with snow or showers; dry and rain-only hours are identical to before. The hourly history
   uses the same rule. Tests: `tests/test_presentation_provenance.py` (rain, snow, mixed,
   showers, zero rain with non-zero total, type not reported, and a test showing the library
   provider's defect).
2. **"Observed" on model data.** Open-Meteo values are typed **Model-derived** in the CSV, the
   Evidence view, the Summary / Details views, the workbook (RAW DATA kind, WEATHER, WEATHER
   HISTORY) and Ask. Station and radar rows keep their own types. The Type vocabulary is now
   Observed / Model-derived / Calculated / Inferred. "Observation time" for a model value is
   "Model value time". Source, timestamp, station-vs-model distinction and selection method are kept.
3. **Critical point.** Calculation unchanged. Defined wherever it appears: the critical
   (tightest) point is where the **Fresnel-zone clearance fraction** (clearance / first Fresnel
   radius) is lowest, **not necessarily** where absolute clearance in metres is lowest. A test
   finds a profile where the two differ.
4. **History** is labelled model-derived, "not station observations", in every view and sheet.

### Resolved in the follow-up pass

5. **Negative clearance ratio is valid, not a defect.** `terrain_clearance_m` is the line-of-sight
   height minus the curvature-adjusted terrain at the critical point, and the library divides it by
   the required clearance without clamping. It is below zero exactly when the terrain is above the
   line of sight; every such case is classed obstructed and shown as CRITICAL. The calculation is
   unchanged. The wording is now explicit: "Terrain is inside the required clearance envelope by
   X m (and Y m above the line of sight)", the ratio is labelled "Negative: the terrain is above the
   line of sight", and the Fresnel-zone share carries the same note.
6. **Old percentage wording.** The library's `explain()` text ("427% above minimum") is still
   produced by the engine and is kept only in RAW DATA (`terrain.library_explanation`) for audit.
   Every human-facing place (Evidence view, CSV, Excel, Ask) now uses one shared sentence:
   "16.0 m available vs 6.8 m required at the critical point: 9.3 m of margin (2.37× the required
   minimum)". The CSV exposure ratio reads "5.1% of the fade margin (1.64 dB of 32.0 dB)".

### Still open (not changed)

- **Library wording in `operational_note`** (weather severity text) still quotes its own band
  ("at or above 70% of this link's stated fade margin"). It states its baseline, so it was left alone.
- **The rain rate comes from the model; the station is corroboration only.** The 2 mm/h
  disagreement convention affects the "do the sources agree" label, not the status. ECCC
  station precipitation is a gauge total and is not split by type either.
- **Open-Meteo free tier is non-commercial.** History adds two requests per analysis.

## 5. What this does not do

- One workbook covers one analysis. A terrain run and a weather run on the same pair are two
  workbooks; there is no combined link verdict.
- Satellite / Earth-space has no Summary view or export (unchanged).
- History is model data, not station history.
- The `.xlsx` was verified by loading it with openpyxl and by the tests' own reader, not in Excel itself.
- Ask understands a fixed set of intents, not free language.

## 6. Acceptance check

- Technician: the Summary opens with the status word, one reason line and a plain sentence.
- Planner: Details shows each value with its comparison and meaning, plus sources and changes.
- Analyst: RAW DATA is un-rounded with unit, source and calculation id; DATA DICTIONARY defines
  every field, calculation and status; ELEVATION-TERRAIN has every sample.
- Non-technical reader: no ratio, Fresnel radius or percentage is needed to read the Summary.
  The ratio sits under Details → Engineering detail, next to what it means.
