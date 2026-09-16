# Evidence export audit

Verified against the actual current code (`core/export.py`, `ui/results_dock.py`)
on this date, not assumed. Canonical target structure:

```
Evidence | Type | Source | Observation-Input | Calculated result | Interpretation
```
with `Type` restricted to `Observed | Calculated | Inferred`.

## 1. Does the current export match the canonical structure?

**No.** Every export is currently wide-format (one row per link/site, many
columns), not the canonical long-format (one row per evidence item, typed).
None of the four export functions in `core/export.py` emit a `Type` column.

This is **not an engine-data gap** — every field the canonical structure
would need (source citation, timestamp, method/formula string) already
exists on the result objects `aei_mw_exposure`/`aei_link_clearance` return,
confirmed unmodified. It is a gap in this plugin's own export-serialization
code. No analysis engine change would be required to close it.

### Per-kind findings

**`_terrestrial_to_csv`** — columns: `Link ID, Site A, Site B, Distance,
First Fresnel Radius, Required Clearance, Terrain Clearance, Clearance
Ratio, LOS Status, Near Threshold, Obstruction Distance, Explanation`.
- No `Type` column.
- No `Source` column at all — `TerrestrialAnalysisResult.site_a_source` /
  `.site_b_source` exist (already used in the dock's source note) but are
  never written to this export.
- No `Observation-Input` — the underlying elevation samples (source:
  `aei_link_clearance`'s own `elevation.py` `SOURCE` constant, Open-Meteo
  Elevation API / Copernicus DEM GLO-90) are available via `result.result.profile`
  but never exported at all, in any form.

**`_microwave_to_csv`** — main row: `Link ID, Site A, Site B, Length,
Frequency, Polarization, Fade Margin, Rain Rate Used, Rain Rate Source
Site, Predicted Attenuation, Exposure Ratio, Severity, Provenance`.
- Has a provenance value and a "source site" identifier, but **not**
  `attenuation.method` / `attenuation.assumption` — both of which the dock
  *does* now show (added in the previous pass) and the export does not.
  Concrete dock/export mismatch.
- Weather Evidence sub-table: `Site, Nearest ECCC Station, Station Time,
  Station Distance, Model Reading, Model Source, Representativeness, Note`.
  This is the closest of the four to the canonical spirit (has source +
  timestamp), but still missing two fields the dock now shows: **radar
  reading** and **station-vs-model difference** are both rendered in
  `ui/results_dock.py`'s `_render_weather_evidence_site()` but absent from
  this export.

**`feature_to_csv` / `link_feature_to_csv`** (site/link raw-record export)
— has `Source` and `Retrieved/Generated` consistently. These are raw
records, not analysis results, so "Calculated result"/"Interpretation"
columns don't semantically apply the same way — this export's mismatch
against the canonical structure is expected/appropriate, not a gap.

**Satellite/Earth-Space** — not exportable at all, by disclosed design
(a computed geometry snapshot, not a raw record). No gap; already correct
and consistent with the same judgment call already made in
`aei-link-clearance/web/space.js`.

### Verdict

Closing this gap is an export-code task (`core/export.py`), not an engine
change — flagged per instruction, not implemented this pass.

## 2. UI contradictions of the Observed/Calculated/Inferred separation

Checked every renderer in `ui/results_dock.py` for numbers shown without an
attached source/method/type label.

- **Microwave** (`_render_microwave`): explicitly sectioned "Observed
  weather (LIVE)" / "Calculated exposure (DERIVED)" / "Inferred
  implication" — correctly typed.
- **Terrestrial** (`_render_terrestrial`): sections are labeled "Path",
  "Result", "Terrain / Elevation (critical point)" — **none of these carry
  an Observed/Calculated/Inferred label**, unlike microwave's sections.
  Distance/Fresnel radius/clearance are calculated values shown with no
  "Calculated" label; the LOS status badge is an inferred classification
  shown with no "Inferred" label. This is a real, direct inconsistency
  with the microwave section's own established pattern in the same dock.
  Also: the elevation data's own source (Open-Meteo Elevation API /
  Copernicus DEM GLO-90, per `aei_link_clearance/elevation.py`'s `SOURCE`
  constant) is not mentioned anywhere in this renderer at all.
- **Satellite-earth-space** (`_render_satellite_analysis`): "Geometry"
  section is also unlabeled by type (calculated), though a "Method:"
  caveat immediately follows explaining the computation — a partial
  mitigation the terrestrial renderer doesn't have at all.
- **Site/link/satellite/ground-station feature drawers**: not applicable
  in the same sense — these render raw records (all "Observed" by nature),
  and already carry a Provenance section with Source for each.

**A regression found in the same pass**: an earlier version of the
terrestrial renderer had a bottom caveat identifying the calculation
method ("Calculated via `aei_link_clearance` (ITU-R P.530 Fresnel-zone/
earth-curvature terrain clearance), unmodified"). The current renderer no
longer has this sentence anywhere — dropped during the dock's later
restructuring pass, not deliberately removed. Worth restoring.

## 3. "Not determined" status — current behavior

Two different situations exist under this heading, and they're in
different states right now:

**(a) Per-record optional-field gaps** (a specific station/tower/site just
doesn't have a value for one field) — inconsistent:
- Weather evidence fields already do this correctly: `"not published by
  this station"`, `"unavailable"`, `"not available for this location/time"`,
  `"not calculable (see note)"` are all explicit strings, not silent
  omissions.
- Several feature-attribute fields do **not** follow this pattern: e.g.
  `_render_ground_station_feature`'s SatNOGS `success_rate` passes `None`
  to `_field_row()` when the value isn't a real number, and `_field_row()`
  silently drops any row whose value is `None`/empty — the row simply
  doesn't appear, with no "Not determined" text. Same pattern for
  `height_above_ground_m`, `purpose`, `service_bands`, etc. across the
  site/link/satellite feature drawers.

**(b) Structural/out-of-scope categories** (the engine never determines
this for *any* input — the user's own example, hardware condition) —
currently **prose-only, not a rendered status line**. "Hardware condition"
and "outage prediction" appear exactly once, as a disclaimer sentence at
the bottom of the microwave section ("It does not determine hardware
condition, and it is not an outage prediction.") — never as an explicit
`Evidence: Hardware condition | Status: Not determined` line item the way
the instruction describes. No such line exists anywhere in the dock or
export for any analysis kind.

### Verdict

Needs a change to match the described behavior — not present today for
case (b), and inconsistent for case (a). Not implemented this pass per
instruction (report only); a candidate fix would be a shared helper
(e.g. `_field_row_or_not_determined()`) used consistently in place of the
current bare `_field_row(label, value_or_None)` calls, plus one explicit
static "Scope" section per analysis kind listing what it does not
determine, each rendered as `Not determined` rather than left as prose.
