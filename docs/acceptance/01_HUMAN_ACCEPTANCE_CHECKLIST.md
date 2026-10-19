# 01 — Human acceptance checklist (QGIS desktop)

Run in order. Use the clean profile and disposable project from `03_*`. Never use your real projects. Record every result in `07_EVIDENCE_TEMPLATE.md`. Evidence folder (outside the repo): `~/velorona-acceptance/<YYYY-MM-DD>/<TestID>/`.

Severity: **S1** blocks release review (data loss, wrong analytical result, crash, conflicting records shown) · **S2** must be fixed or explicitly accepted by the product owner · **S3** cosmetic/wording, may ship with a recorded note.

Terms: *Records* = the Velorona panel's table (dataset picker, search box, Operator filter). *Details* = the result view in the same panel (Summary / Details / Evidence). Menu: *Plugins ▸ Velorona*. Log: *View ▸ Panels ▸ Log Messages ▸ Velorona* and *Python Error* tab.

Live prerequisites (record whether each was available): internet; Open-Meteo not rate-limited (HTTP 429 gives NO DATA); for SEL-03b/REG-03 a real CelesTrak cache or live access.

---
## A. Installation and startup (details in `03_*`)

### INS-01 Clean install of the candidate ZIP
- **Purpose:** the candidate installs like a release. **Pre:** new QGIS profile (03 §1), ZIP built from the staged tree, SHA-256 recorded.
- **Steps:** Plugins ▸ Manage and Install Plugins ▸ Install from ZIP ▸ choose the ZIP ▸ Install; tick Velorona.
- **Expect:** installs without a dependency prompt beyond what the README states; plugin listed as enabled; version shown equals the candidate's `metadata.txt` version.
- **Fail if:** install error, missing-library message when the libraries are installed, plugin silently not enabled.
- **Evidence:** screenshot of the plugin manager entry; ZIP name + SHA-256. **Severity:** S1.

### INS-02 Startup is clean
- **Steps:** after INS-01 open Log Messages (Velorona and Plugins tabs) and the Python Error tab.
- **Expect:** no traceback, no warning other than the documented dependency/library-range notice.
- **Fail if:** any traceback or "could not be registered". **Evidence:** log export. **Severity:** S1.

### INS-03 Actions, panel and Processing provider present
- **Steps:** open Plugins ▸ Velorona and the toolbar.
- **Expect (8 actions):** Explore: Load Public Data · Explore: Load USA Links in View (FCC ULS) · Explore: USA Data Setup… · Analyze: Terrestrial Path Clearance · Analyze: Microwave Weather Exposure · Analyze: Satellite / Earth-Space · **Analyze: Terrain Clearance for Many Links (batch)** · Show Velorona Panel. Open Processing Toolbox (View ▸ Panels): provider **Velorona** with the algorithm "Terrain clearance for many Fixed Service links".
- **Fail if:** fewer than 8 actions, the provider missing, a duplicate action after Plugins ▸ Reload (do the reload once and re-count). **Evidence:** screenshot of menu + toolbox. **Severity:** S1 (missing), S2 (duplicate).

### INS-04 Existing single-link analysis still works
- **Steps:** Explore: Load Public Data. Zoom to a populated area. In Records pick *Fixed Service links*, click one row. Then Analyze: Terrestrial Path Clearance; accept the pre-filled dialog.
- **Expect:** Details open for that link; Summary shows a status (CLEAR/WATCH/AT RISK/CRITICAL, or NO DATA with a reason); Evidence lists Observed/Assumed values.
- **Fail if:** error, empty result without a reason, wrong link. **Evidence:** screenshot of Summary, Details and Evidence. **Severity:** S1.

### INS-05 Nothing disappeared compared with 1.1.9
- **Pre:** a second clean profile with the published 1.1.9 ZIP (SHA-256 `d255c5f68c98c98e2f5e97446c1942d7172a845f94a2199b96bd4646bd880164`).
- **Steps:** in both profiles run Load Public Data; list menu actions, layer-tree names/groups, Records datasets (picker), Details views, export buttons.
- **Expect:** the candidate has everything 1.1.9 has plus the batch action/provider; the only intended renames: imagery group `USA Imagery (optional)` → `USA Aerial Imagery & Topo (USGS)`; no GeoJSON claim in the plugin description.
- **Fail if:** anything from 1.1.9 is missing or renamed beyond that. **Evidence:** the two screenshots side by side. **Severity:** S1.

---
## B. Selection and layer lifecycle

Invariant to check after **every** step in this section: the highlighted Records row, the map's highlighted feature and the record named in Details are the **same record**. Any disagreement is S1.

### SEL-01 Select a record and verify details (both directions)
- **Steps:** Records ▸ *Fixed Service sites* ▸ click a row; note the name/record id. Then clear (Edit ▸ Select ▸ Deselect All) and, with *Select Features by Area or Single Click* on layer *Fixed Service sites (CAN)*, click a site on the map.
- **Expect:** row click → that feature selected on the map, map zooms to it, Details name it. Map click → Records switches to the dataset, highlights that single row, Details name it. Deselect All → no highlighted row, Details empty state.
- **Fail if:** different record in any of the three places; row stays lit after deselect. **Evidence:** 3 screenshots. **Severity:** S1.

### SEL-02 Refresh, record unchanged → selection kept
- **Steps:** select one Fixed Service link (Records row). Run Explore: Load Public Data again (re-fills the layer with identical bundled records). Note: Load Public Data itself may re-zoom the map; that is existing behaviour.
- **Expect:** the same link is still selected and still shown in Details; the highlighted Records row is that link.
- **Fail if:** selection lost with the record unchanged, or a different record selected. **Evidence:** before/after screenshots. **Severity:** S2 (lost), S1 (different record).

### SEL-03a Refresh, record changed or different → selection cleared (scratch layer)
- **Pre:** disposable project; **do not load USA data in it**. Create the scratch layer in the QGIS Python console:
```python
import qgis.utils
from qgis.core import QgsProject
from velorona.core import layers as L
from velorona.core.countries.usa_fields import US_SITE_FIELDS
plugin = qgis.utils.plugins['velorona']
recs = [{"id": f"ACC-{i}", "name": f"Acceptance site {i}", "source": "acceptance test (synthetic)", "licensee": "Test",
         "latitude": 43.0 + i*0.05, "longitude": -79.5 + i*0.05, "country": "CA"} for i in range(5)]
lyr = L.build_point_layer("ACC scratch sites", recs, US_SITE_FIELDS, "#d4af37")
L.add_to_group(QgsProject.instance(), lyr, plugin._ensure_velorona_groups()[1]["Infrastructure"], True, source_key=L.SOURCE_US_SITES)
plugin._populate_records()
```
  (The Records picker will label it "USA Fixed Service sites (FCC ULS)": a known artefact of borrowing that dataset key; the data is synthetic and the project is disposable.)
- **Steps:** in Records pick that dataset, click the row "Acceptance site 2". Then in the console run each variant, checking Records/map/Details after each:
  1. same records, reversed order: `L.replace_point_features(lyr, list(reversed(recs)), US_SITE_FIELDS)`; `plugin.dock.records.refresh_current()`
  2. same ids, changed content: `L.replace_point_features(lyr, [dict(r, name="CHANGED "+r["name"]) for r in recs], US_SITE_FIELDS)`
  3. different records, ids reissued: `L.replace_point_features(lyr, [dict(r, id="OTHER-"+r["id"]) for r in recs], US_SITE_FIELDS)`
  Before each of 2 and 3 re-select "Acceptance site 2" (restore with the original `recs` first).
- **Expect:** variant 1 → "Acceptance site 2" still selected, same Details. Variant 2 → selection cleared, Details empty, no highlighted row. Variant 3 → selection cleared, nothing selected (in particular no "OTHER-…" record selected by position).
- **Fail if:** any record other than the original stays selected/shown; Details keep showing the old record while the map has none. **Evidence:** screenshots after each variant. **Severity:** S1.

### SEL-03b Refresh with a moving record (live; optional)
- **Pre:** live CelesTrak access or a real orbit cache. **Steps:** Satellites layer on, select one satellite, wait for/trigger a refresh (hide and show the layer after the cache window). **Expect:** the selection is cleared and Details empty (positions changed) — never an old position shown against a new one. **Severity:** S1/S2. **Not-run is allowed if the prerequisite is missing; record why.**

### SEL-04 Remove the selected layer
- **Steps:** in the scratch project select a record in "ACC scratch sites"; in the Layers panel right-click that layer ▸ Remove Layer. Then open the Records dataset picker and pick every remaining dataset.
- **Expect:** dataset disappears from the picker; Details empty; no Python Error; every other dataset still loads.
- **Fail if:** any error/traceback, a frozen panel, Details still showing the removed layer's record. **Evidence:** Python Error tab screenshot (empty) + log. **Severity:** S1.

### SEL-05 Layer added after the plugin has loaded
- **Steps:** re-run the SEL-03a creation snippet (plugin already loaded). Select a record on the map.
- **Expect:** the record is shown in Details exactly once (no double refresh/flicker, no duplicate dock updates); Records lists the dataset.
- **Fail if:** nothing happens on selection (not wired) or the panel updates twice per click. **Evidence:** screen recording of one click. **Severity:** S1 (not wired), S2 (double).

### SEL-06 Switching datasets
- **Steps:** select a site in *Fixed Service sites*; in the picker choose *Fixed Service links*, then *Fixed Service sites* again.
- **Expect:** selection on every layer is unchanged by the switching; returning to sites highlights the same record; the QGIS active layer (Layers panel highlight) follows the picker; nothing becomes selected by itself.
- **Fail if:** a selection appears/disappears, or a different record is highlighted. **Severity:** S1.

### SEL-07 Search vs map selection
- **Steps:** Records ▸ *Fixed Service links*; type an authorization number of link A in the search box; click A's row (selected). Now, with the Select Features tool, click a different link B (not matching the search).
- **Expect:** B is selected on the map and shown in Details; the table shows **no highlighted row** (B is hidden by the search; A must not remain highlighted). Clearing the search then highlights B. Typing a string that matches nothing shows "No records match the search “…”".
- **Fail if:** A's row stays highlighted while Details show B. **Evidence:** 2 screenshots. **Severity:** S1.

### SEL-08 Independent selections on two layers (two-site analysis)
- **Steps:** select one site in *Fixed Service sites (CAN)* (map click). In Records switch to *Cellular / mobile sites* or *Tower structures* (load them: zoom to Ontario, switch the layer on; live) — or use the scratch layer — and click a row. Then Analyze: Microwave Weather Exposure.
- **Expect:** both selections stay (check each layer's selected count in the Layers panel *Show Selected Feature Count*); the analysis dialog opens for those two sites. With 1 or 3 sites selected the plugin warns with the exact count.
- **Fail if:** selecting in the second layer cleared the first. **Severity:** S2.

### SEL-09 Operator filter
- **Steps:** with Canada loaded choose an Operator; select a record of a different operator beforehand.
- **Expect:** map, table count and Details agree; the excluded selection is dropped; clearing restores the full count. Tooltip/hint say the filter covers **Canadian** layers and USA layers are not filtered.
- **Fail if:** counts differ between status line and layer; a record outside the filter stays shown. **Severity:** S2.

---
## C. Saved-project reopening → see `03_CLEAN_INSTALL_AND_PROJECT_REOPEN.md` (PRJ-01 … PRJ-07)

---
## D. Batch Processing

Inputs: candidate links in `02_*` §3. Output layer name "Terrain clearance (batch)". Algorithm parameters: *Fixed Service links* (line layer, optional "selected features only"), *Most links to analyse in one run* (default 100, max 1000), *Fallback frequency (GHz)*, *Pause between links (seconds)*, *CSV export*.

### BAT-01 Algorithm is runnable from three entry points
- **Steps:** (a) Plugins ▸ Velorona ▸ Analyze: Terrain Clearance for Many Links (batch); (b) Processing Toolbox ▸ Velorona; (c) Processing ▸ Graphical Modeler is optional.
- **Expect:** same dialog; help text states "terrain only", Observed/Assumed rule, the NO DATA rule, the limit. **Severity:** S2.

### BAT-02 Multiple valid links
- **Steps:** select links C1–C7 (`02_*` §3) in *Fixed Service links (CAN)*; run with *Selected features only*, limit 100, pause 0, CSV to the evidence folder.
- **Expect:** the dialog runs in the background (QGIS stays responsive; Task Manager shows the task), progress advances; output has exactly one row per selected link with fields from `core/batch.py` (`batch_index, source_fid, link_id, authorization_number, …, status, reason, …`); geometry equals the input link.
- **Fail if:** row count ≠ selected count; a row for an unselected link; QGIS frozen for the whole run. **Evidence:** log tab + output attribute table. **Severity:** S1.

### BAT-03 Progress and cancellation
- **Pre:** at least 30 links selected (Edit selection with a rectangle in a dense area) and **pause 1 s** (so the run takes ≥30 s).
- **Steps:** run; after about 5 rows press **Cancel** in the Processing dialog (and separately in the Task Manager).
- **Expect:** the run stops promptly after the link in flight; the log says it was cancelled; rows already computed are kept; the remaining links are present as **NOT RUN** ("The run was cancelled before this link.") — none silently dropped; no error dialog.
- **Fail if:** hang >30 s after Cancel; fewer rows than inputs without NOT RUN; traceback. **Evidence:** log, output table. **Severity:** S1 (hang/crash), S2 (rows dropped).

### BAT-04 Over the limit
- **Steps:** select 8 links, set limit 5, run.
- **Expect:** refused before running: "The input has 8 links, over the limit of 5 …". **Severity:** S2.

### BAT-05 Invalid and incomplete records do not corrupt other rows
- **Pre:** scratch copy of the link layer (03 §3: Export ▸ Save Selected Features As… GeoPackage in the evidence folder; edit only the copy). In the copy: (i) C1 with `frequencies_mhz` blanked; (ii) one extra row added in the copy's attribute table (Toggle Editing ▸ Add Feature, no geometry drawn) with `id` = NOGEOM, `authorization_number` = NOGEOM-1, `frequencies_mhz` = 7000; (iii) C8 (`010047019-003`, site B height 0.0 in the record); keep C3 and C4 untouched.
- **Steps:** run on the copy, no fallback frequency; then again with **fallback frequency 7**.
- **Expect (no fallback):** (i) NO DATA "no usable frequency … none is assumed", no numbers; (ii) NOGEOM-1: NO DATA "no usable endpoint geometry"; (iii) NO DATA with a reason naming the height; C3, C4 have results **identical** to their rows in BAT-02. **With fallback:** (i) now has a result with `frequency_origin = Assumed`, frequency 7; everything else unchanged.
- **Fail if:** an invalid row gets a status CLEAR/… or invented numbers; a neighbouring row changes. **Evidence:** both output tables + CSVs. **Severity:** S1.

### BAT-06 Row ↔ input correspondence
- **Steps:** in the BAT-02 output compare `link_id`/`authorization_number`/`source_fid` with the input layer for every row, in order; spot-check geometry (identify the output feature, compare with the input).
- **Expect:** 1:1, same order as the input iteration, `source_fid` equals the input feature id, geometry identical. **Severity:** S1.

### BAT-07 CSV export
- **Steps:** open the CSV from BAT-02 in a text editor and in a spreadsheet.
- **Expect:** a `# ` preamble (product, library, convention, meaning of a row, status counts), then a header equal to the output field list, then one row per link; column count constant; statuses counts in the preamble equal counts in the table; numbers un-rounded; no `#` lines inside the table; file opens in a spreadsheet with the right column count. Record the file SHA-256.
- **Fail if:** ragged rows, missing rows, header mismatch, counts differ. **Severity:** S1.

### BAT-08 Repeat run
- **Steps:** run BAT-02 twice more with the same CSV path.
- **Expect:** each run gives a new output layer (identical values to BAT-02) and overwrites the CSV with the same content (no appended/duplicated rows); the input layer and its selection are unchanged; no stale rows from the earlier run. **Severity:** S2.

### BAT-09 Input not modified; other CRS
- **Steps:** compare the input layer's feature count and attributes before/after; run on a copy reprojected to EPSG:3857 (Processing "Reproject layer").
- **Expect:** input unchanged; the 3857 copy gives the same statuses and distances within the display rounding of `distance_km` (the automated test uses < 0.01 km). **Severity:** S2.

### BAT-10 Service outage behaves as NO DATA, not a result
- **Steps:** (optional) run with network off for one link (turn Wi-Fi off after starting) or when Open-Meteo answers 429.
- **Expect:** affected rows NO DATA "elevation data unavailable" (transient = true), run completes. **Severity:** S2.

---
## E. Batch vs single link → `02_BATCH_VS_SINGLE_PARITY_PROTOCOL.md` (PAR-01 … PAR-10)

---
## F. Details and exports

### DET-01 Heights and their source
- **Steps:** analyse C1 as in `02_*` §4 (accept pre-filled values). In Details/Evidence read "Antenna height A/B".
- **Expect:** each states its origin in the same words as Evidence: `observed: <source text of the record>` when the value equals the record's value; `assumed: User, via analysis dialog (default shown, user-confirmed)` when no record value or the default 30 m; `assumed: User override …` when changed. **Never** "entered by the user" for an unchanged link-record value.
- **Then:** change Site A height in the dialog to a different value and re-run: that height must flip to assumed (override text naming the record's own value).
- **Fail if:** Details and Evidence/export disagree. **Severity:** S1.

### DET-02 Frequency and its source
- **Steps:** as DET-01 for "Analysis frequency" (Details) / "Frequency" (Evidence). Check a multi-frequency link (C1): the highest published frequency is used; the note says "Highest of N published frequencies …".
- **Expect:** Observed while unchanged, Assumed after an override (note quotes the record's value). **Severity:** S1.

### DET-03 Excel and CSV exports
- **Steps:** export Excel (.xlsx) and CSV from the result. Open the .xlsx in Excel/Numbers/LibreOffice.
- **Expect:** sheets SUMMARY, LINK ANALYSIS, WEATHER, WEATHER HISTORY, ELEVATION-TERRAIN, EVIDENCE, RAW DATA, DATA DICTIONARY; SUMMARY "Frequency" interpretation states the origin (not a blanket "entered by the user" for a record value); RAW DATA values un-rounded with unit/source; units consistent (km, m, GHz, deg); EVIDENCE rows typed Observed/Calculated/Inferred/Assumed exactly as the Evidence view. The file opens without a repair prompt. **Severity:** S1 (wrong value or provenance), S2 (layout).

### DET-04 Units and values
- **Steps:** compare Details numbers with RAW DATA for distance (km), required/available clearance (m), margin (m), clearance ratio, Fresnel radius (m).
- **Expect:** Details are the rounded display of RAW DATA (difference ≤ half a unit of the last displayed digit); units match. **Severity:** S1.

### DET-05 Missing data is explicit
- **Steps:** analyse C8 (height 0.0) and a blank-frequency copy from BAT-05 via the single-link action.
- **Expect:** a refusal or NO DATA with the reason (C8: "antenna height B outside 0.1-1000 m"); no numbers presented as a result; Ask and exports do not show a status. **Severity:** S1.

---
## G. Existing capabilities and regression

### REG-01 USA setup path
- **Steps:** Explore: USA Data Setup… ▸ choose "Velorona's online USA data" ▸ check ▸ Use this data; zoom to the Dallas area ▸ Explore: Load USA Links in View. Also: Cancel the first-time window once and confirm Canada is unaffected.
- **USA like the Map (product requirement):** with NO USA setting, after Load Public Data: whole-US view ⇒ pale count bubbles (overview layer, not selectable); zoom/pan into a state-sized view without any USA action ⇒ USA links and pale clusters appear by themselves (one message about the online data), follow the pan to another state, Records lists the USA datasets; "Turn USA data off" in the setup window stops it. Headless evidence: `tests/qgis_usa_e2e.py` and images in `~/velorona-acceptance/2026-10-19/usa-default/`.
- **Expect:** window shows Ready with link count and source date, or Problem with a reason; the message bar reports links/sites loaded and attribution; layers *Fixed Service links/sites (USA)*; the setting is stored in the project (not global settings); Operator filter does **not** filter USA layers (stated). **Severity:** S2.

### REG-02 USA link analysis provenance
- **Steps:** select one USA link, run Analyze: Terrestrial Path Clearance (accept).
- **Expect:** frequency Observed ("FCC ULS record …") while unchanged; heights **Assumed 30 m** (FCC heights are not used); source attribution present. **Severity:** S1.

### REG-03 Satellite reliability (needs live data or a real cache)
- **Prerequisite:** `tests/qgis_satellite_feed_e2e.py` and `qgis_satellite_render.py` need `ORBIT_CACHE_DIR`, a directory holding an OrbitCache produced from a real CelesTrak fetch (the `live-orbit-probe.yml` workflow does that). Do not fabricate a cache.
- **Manual (if CelesTrak is reachable):** switch *Satellites (CelesTrak)* on; wait for the status line ("fresh", "stale" with time, "partial", or "unavailable"); select a satellite → regional view (about 3,000 km wide) and Details; hide/show the layer inside the 2-hour cache window → no new request (QGIS Log Messages / network monitor), no duplicate task.
- **Expect when unreachable:** layer empty, the status says unavailable, nothing substituted, no repeated requests. **Severity:** S2.

### REG-04 Weather analysis and Ask
- **Steps:** select a link; read the weather section; ask "Is this link clear?" in the Ask box. **Expect:** answer cites the current result only; declines unknown questions. **Severity:** S2.

### REG-05 Imagery group and layers
- **Steps:** after Load Public Data check the group `USA Aerial Imagery & Topo (USGS)` (two layers, both off). Switch one on over the US, then off.
- **Expect:** nothing requested while off; layer metadata (Layer Properties ▸ Information) says "Off by default …", attribution USGS. **Severity:** S3.

### REG-06 Log hygiene
- **Steps:** after the whole session review Log Messages for Velorona warnings/errors. **Expect:** only service-availability messages (record them). **Severity:** S2.

### BAT-11 Spreadsheet-formula text in CSV exports (mitigation check)
- **Background:** before the fix the raw cells `=1+1`, `+1+2`, `-1+2`, `@SUM(1)` were evaluated by Microsoft Excel 16.114 (results 2, 3, 1, 1) and `=1+1` by Numbers 14.4 on macOS (checked 2026-10-18 with files in the scratch area). Text cells now get a leading apostrophe (`core/csvsafe.py`); calculated numbers are unchanged.
- **Steps:** in a scratch copy of the link layer set `authorization_number` of one link to `=1+1`, another to `+1+2`, `source` of a third to `-1+2`, a fourth to `@SUM(1)`. Run the batch (CSV) and, for one of those links, the single-link analysis then Export CSV. Open each CSV in Excel and Numbers.
- **Expect:** the four cells show their text (with a visible leading apostrophe), none shows a computed value; negative numeric cells such as `margin_m` are still numbers; column count and header unchanged; the Excel (.xlsx) export shows the original text without an apostrophe and no cell is a formula.
- **Fail if:** any such cell is evaluated, or a legitimate negative number gained an apostrophe. **Severity:** S1 (evaluated), S3 (visible apostrophe is documented).
