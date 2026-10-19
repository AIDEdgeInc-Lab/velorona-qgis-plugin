# Changelog — Velorona for QGIS

Canonical human-readable version history. (The plugin manager shows the shorter `changelog=` text in `metadata.txt`; this file is the detailed record.)
Compare any two releases: https://github.com/AIDEdgeInc-Lab/velorona-qgis-plugin/compare/v1.1.4...v1.1.5

## 1.1.10 — 2026-10-19 (compared with 1.1.9)

Why it matters: terrain clearance can now be run for many links at once with the same result as the single-link analysis; a selected record can no longer be left selected, or shown, against a different record after a layer reloads, a layer is removed or the plugin is reloaded; and exported CSV files can no longer run formulas in a spreadsheet. No terrain, weather, status or threshold calculation changed.

### Added
- **Terrain clearance for many links**: a native Processing algorithm (`velorona:terrain_clearance_batch`, Processing Toolbox > Velorona, and Analyze: Terrain Clearance for Many Links) runs the existing single-link analysis for every link of a layer or its selected links. One row per link, each equal to the single-link result; per-row status and reason (CLEAR / WATCH / AT RISK / CRITICAL / NO DATA / ERROR / NOT RUN); one failing link never stops the run; optional CSV. See `docs/BATCH_TERRAIN.md`.
- Batch terrain clearance: the pause parameter and help now explain the elevation provider's HTTP 429 limit (rate-limited links are NO DATA, transient, never a result) and advise several seconds of pause for more than a handful of links; the default stays 0.

### Fixed
- **USA clusters now appear, and follow the map, like Velorona Map.** USA sites were drawn with the same clustered, subtle style as Canada's, but US records only ever entered the map through the manual Load USA Links in View action, for the view at that moment: pan or zoom elsewhere and no USA clusters were drawn there, and the Records table stayed on a Canadian dataset. Once USA data has been loaded and a pack source is set, the USA layers now load the 1-degree tiles of the view as you pan and zoom (nothing is asked and nothing is fetched for a user who has not set USA up; a view too large to draw keeps what is loaded and says so in the Records note, as the Map hides US records below its minimum zoom). An explicit USA load also shows the USA links in Records. The cluster look is unchanged and pixel-identical to Canada's for the same points.
- **Selection after a layer reload.** A selected record is kept by its record id and unchanged content (never by a reissued feature id); a record that is gone, changed, or has no id is deselected and the details panel empties. Resolves the 1.1.9 known issue "after a live layer refresh a previous selection can remain while the details panel still shows the earlier record".
- **Layer lifecycle.** The selection handler is connected once per Velorona layer, also for layers already in the project after a plugin reload or when a project restores its layers; it is disconnected on unload and when a layer is removed.
- **Removed layers.** Removing a Velorona layer no longer breaks the Records picker (an uncaught "object has been deleted" error); its details are cleared.
- **Records table.** No row stays highlighted when the map selection moved to a record the search hides; switching dataset shows that layer's own selection; the Records dataset and the QGIS active layer follow each other without selecting anything.
- **Terrain Details wording.** Antenna heights and the analysis frequency now say where each value came from (the link record's own value is Observed; a default or override is Assumed), as the Evidence view and the exports already did. The Excel Summary says the same. Previously Details said "entered by the user" even for link-record runs.

### Changed
- The imagery group `USA Imagery (optional)` is now `USA Aerial Imagery & Topo (USGS)` (projects saved with the old name are renamed in place; the layers are still off by default and the layer metadata says so). The plugin description no longer claims a GeoJSON export (CSV and Excel only). The Operator filter text says it covers the Canadian layers; an empty search says which search matched nothing.

### Security
- **CSV formula injection.** Exported CSV text cells that begin with `=`, `+`, `-`, `@`, tab or CR (identifiers, names, licensees, source and reason text from imported or public records) are prefixed with an apostrophe so Excel and Numbers do not evaluate them; calculated numbers (negative ones too) are unchanged. Applies to the single-link, single-record, selection-summary and Batch CSV exports (`core/csvsafe.py`); the Excel export stores plain strings and is unaffected. The apostrophe is visible when a CSV is opened.

### Tests
- New `tests/test_csv_safety.py` (35 tests), `tests/qgis_selection_sync_e2e.py` (58 checks), `tests/test_satellite_reliability.py`, a satellite refresh scenario in `tests/qgis_workflow_e2e.py`, terrain-origin wording tests, and `tests/test_workflow_core_semantics.py` (compares the unmerged shared workflow core with the plugin flow; skipped when that package is absent). `tests/qgis_e2e.py` now forbids reaching into the Processing Toolbox panel instead of forbidding any mention of Processing, because the batch algorithm registers a Processing provider.
- `tests/test_terrain_batch.py` (QGIS-free) compares every batch row with an independent single-link analysis on all shared parity fixtures. `tests/qgis_batch_e2e.py` is the QGIS runtime test of the Processing layer; it passes 13/13 headless in QGIS 4.2.2 (offscreen, stand-in `iface`). It is not an interactive desktop test: the Processing dialog, Cancel, Task Manager and project reopening are still to be verified by hand.

### Verified, and known limits
- Headless QGIS 4.2.2 runs (offscreen), live Open-Meteo for Batch-versus-single-link parity (7 Canadian links, 11 numeric fields each, exact equality; one USA link) and Excel 16.114 for the CSV and .xlsx exports. **Not run:** the live-satellite end-to-end tests (CelesTrak was unreachable from the test machine, so no orbit cache existed; nothing was substituted). Open-Meteo rate-limits requests made closer together than a few seconds (see the pause parameter).

## 1.1.9 — 2026-10-15 (compared with 1.1.8)

Why it matters: the map is readable in the light theme in the field, the layer list says what each layer is and where its data comes from, and every live or bundled data source now states its status (live, cached with a time, empty, unavailable, or a dated snapshot) instead of failing silently.

### Changed
- **Light map readability.** Roads, rail, buildings and waterways are retinted for the light basemap only (minor roads were white on cream, about 1.07:1); street-name labels appear in both themes at neighbourhood scale; city and town names no longer vanish when zoomed past tile zoom 14.
- **Layers panel.** Names are short and carry the country (`Fixed Service sites (CAN)`, `... (USA)`, `Satellites (CelesTrak)`); the group `Space` is now `Satellite / Orbital Data` (a project saved with the old group or old names is renamed in place, a layer you renamed keeps your name); the public-records disclosure moved from the layer names to each layer's metadata and the Records status line.
- **Optional USA imagery** (off by default, own group): USGS aerial imagery and USGS topographic map, United States only, zoom 0-16. These are aerial photography and a map, not the orbital data; the Satellites layer shows satellite positions, not imagery.
- **Records.** The sort arrow no longer clips the header; columns are fitted by priority (coordinates are never squeezed) at 1024-1920 px windows and refit on resize unless you sized a column; a selected row is readable on the light theme; the dock opens at 37 percent of the window; full values stay in cell tooltips.
- **Evidence view.** Labels line up in one column; a NO DATA panel for a link names the link (it was blank); NO DATA is shown once.

### Data integrity (what is shown is real, or says why not)
- **Ontario towers and ISED cellular sites (live services).** Each layer's status is stated in the Records status line and, for an outage, once on the message bar: live (just retrieved), cached (retrieved within the last 5 minutes, with that time), empty (the service answered with no records for this view) or unavailable (the request failed). After a failed request the layer is emptied rather than keeping the previous view's records; the service's 1,000-record limit is reported instead of ignored.
- **Satellites.** The status line says fresh, stale (with the retrieval time), partial or unavailable; positions are described as calculated (SGP4) from the provider's element sets.
- **Invalid coordinates.** A record whose coordinates are missing, not finite or outside the valid range is not drawn, on any layer, and is counted; a selected feature without usable geometry no longer moves the map.
- **SatNOGS ground stations.** 206 of 4,461 stations in the bundled snapshot are reported by the source at latitude 0, longitude 0 (an unset location). They were drawn in the Gulf of Guinea; they are no longer drawn, and the layer says how many and why.
- **Snapshots are dated.** Canada Fixed Service records state the ISED file date and bundle date; ground stations state the snapshot retrieval date.
- **Selection.** Clearing a map selection also clears the highlighted Records row (a stale highlight remained).
- **Selecting a satellite** now shows a regional view (about 3,000 km wide) around its sub-satellite point instead of a 1 km box over empty ocean.

### Internal
- New cross-component workflow test (`tests/qgis_workflow_e2e.py`: Records row to map to details, map to Records, filters, sort, dataset change, provider outages with test doubles, no fabricated records), a Records layout/header test set, a satellite render test and a dev-only live probe workflow.

### Verified, and known limits
- Real sources reached from this machine on 2026-10-14: ISED snapshot checked against the raw ISED file (300 of 300 sampled links identical in endpoints and frequencies), SatNOGS snapshot checked against the live API (397 of 400 sampled stations identical, 3 moved since), live ISED cellular (453 sites in one view), live Open-Meteo and ECCC weather for a real link, the USA pack from map.velorona.ai (7,232 links and 3,606 sites in one view). Ontario towers: the service answered (278 in a wide Ontario view, none in downtown Toronto).
- **Live CelesTrak, on the code in this release.** Workflow run 38661544311 (GitHub-hosted runner, real QGIS 4.0, 2026-10-15 00:43 UTC, commit e85c28e): HTTP 200 for all five GEO groups, 599 unique real records retrieved and parsed, 599 positions computed with SGP4 (TLE and OMM paths agree to 0.005 km), all coordinates valid and finite, and the render and selection checks (Records row to map to details) passed 10/10, including physical-invariant checks on all 564 geosynchronous-period records (inclined BeiDou, QZSS and IRNSS satellites included). CelesTrak is intermittently unreachable: the same source timed out at 21:13 UTC and returned HTTP 500 at 22:12 UTC on 2026-10-14, and was unreachable from the maintainer's machine; in those cases the layer stayed empty, said so, and made no further requests (verified live).
- **Package provenance.** The first validated package (SHA-256 630863132e2d71fb1b310a0188e66445de8b6975f159b37f0a0b6ebcdf235cfe) was built from commit 05f9a3a. The live probe above ran on e85c28e, a test-only child of 05f9a3a (it changes only a development test that the package excludes). This release was rebuilt after a documentation-only change (this changelog); all packaged code is byte-identical to that first package.
- Known and planned for 1.1.10: after a live layer refresh a previous selection can remain while the details panel still shows the earlier record (a stale, not a wrong, record).
- Not verified: Windows and Linux; a real user's desktop session (the checks ran in the real QGIS application with an offscreen display).

## 1.1.8 — 2026-10-14 (compared with 1.1.7)

Why it matters: the Satellites layer no longer asks the orbital source every ten minutes, no longer repeats a request that just failed, can show satellites with catalog numbers above 99999, and says how old its element sets are. Nothing about terrain clearance, weather exposure, statuses, exports or Canada/USA data changes.

### Changed
- **Satellites layer data path.** Element sets are cached for 2 hours, a failed request is not repeated until its back-off passes (previously the source was asked every 10 minutes and again on each layer toggle after a failure), decayed element sets are no longer drawn or analysed, satellites with catalog ids above 99999 are now supported (from their OMM record) instead of being unsupported, and each satellite records when its element set was retrieved and whether it is fresh or stale. The new path was exercised in a real QGIS 4.0.3 runtime against the live CelesTrak response on 2026-10-14 (28/28 checks; details and limits in docs/ORBIT_DATA.md), and the load now runs in a background task so the map stays responsive.
- **Satellite analysis.** The satellite-to-station analysis rejects an element set that cannot be propagated (SGP4 error) with an explanation instead of returning a number; an OMM-only satellite is analysed from its OMM record (agrees with the TLE path within 0.05 degrees in the real-QGIS test).
- **Source text.** The CelesTrak source line now links the provider's usage policy instead of calling the data "Public Domain" (no source for that claim).

### Internal
- Narrower error handling where an unreadable provider response body is classified by its HTTP status (Bandit B608/B110); `metadata.txt` escapes a literal percent sign (plugins.qgis.org rejected 1.1.7 for it); the tests read the expected version from `metadata.txt`; CI gates (unit, Qt6 enums, security, package, real-QGIS offline suites on 4.0 and 4.2) and a release-validation workflow.

### Verified, and known limits
- Real CelesTrak data through this feed (five GEO groups, 599 unique records, 3 only representable as OMM) and a real QGIS 4.0.3 runtime test of the Satellites layer (28/28 checks), on this code, 2026-10-14; details in docs/ORBIT_DATA.md. The source is intermittently unreachable (seen from several networks); when it is, the layer stays empty, says so, and backs off, and nothing is substituted.
- Not changed and not part of this release: two QGIS 4.0 layer-group-order checks in the live end-to-end suite fail the same way on 1.1.7; a provider connection error can be shown to the user as raw text (existing behaviour).

## 1.1.7 — UI polish (compared with 1.1.6; 1.1.6 was never published separately, so 1.1.7 also carries the 1.1.6 guided USA data setup below)

### Changed (appearance only)
- **Calmer USA map.** Cluster discs and link lines now fade with map scale: more transparent and slightly smaller at regional zoom (so dense areas read as a soft density cue instead of a solid blue mass), progressively stronger at medium and close zoom. Hues, cluster logic, counts, tolerance and selection symbols are unchanged; no data is hidden.
- **Records tab.** The "Operator" label is readable on the dark theme; the operator list no longer shows a record count that contradicts the table footer (the total moved into the hint line); cells have full-value tooltips.
- **Evidence view.** Endpoint name and coordinates no longer run together ("Site A49.16072").
- **Link title.** The on-screen title leads with the authorization number when the record carries one ("<authorization> · Site A ↔ Site B"); a missing or placeholder value shows the plain endpoint pair. The exported location text is unchanged.
- **NO DATA.** The status line gives the reason once; the repeated plain-language answer is dropped for NO DATA only. Status semantics are unchanged.
- **What changed.** Hourly comparisons are grouped by baseline (each baseline in its own table) instead of interleaved.
- **Narrow windows.** Records tab: search on its own row, wrapping hints, size-adjusting dropdowns, accessible names.
- **Records columns.** A *Columns* menu (and header right-click) shows or hides columns per dataset for the session. Display only: search, sorting, selection and exports still use every column; the last visible column cannot be hidden.

### Not changed
Calculations, five-level status contract, provenance, parity fixtures, exports, data limits.

## 1.1.6 — 2026-10-09 (compared with 1.1.5)

Why it matters: setting up USA data no longer starts with an unexplained box asking you to type a folder path or web address. Nothing about calculations, statuses, data or Canada changes.

### Changed (user experience)
- **Guided USA data setup.** *Explore: USA Data Setup…* opens a window that says what the USA data is (a separate download, not included in the plugin; Canada works without it) and offers *Use Velorona's online USA data*, *Choose a folder…* (the normal folder picker) or an https address, with a built-in "How do I get the data?" guide. Previously, pressing *Load USA Links in View* with nothing set up opened a bare text box ("Folder on this computer, or https address…").
- **Honest status.** *Not set up yet* / *Ready* (link count and dates read from the data itself, after the index and one real tile were validated) / *Problem* (what is wrong and what to do: missing folder, `index.json` not found, incomplete or damaged tiles, a newer data version, unreachable address, plain http). *Use this data* is enabled only after a successful check.
- **Safe to back out.** Cancel changes nothing; *Forget the saved setting* removes it; a cancelled first-time window ends with a calm note that Canada is unaffected. Small slips are forgiven (typing `index.json`, quotes, choosing the folder above the pack).
- **Never unprompted.** The window opens only when you ask for US data; starting Velorona, loading Canada and every Canadian analysis never open it (covered by an end-to-end test).
- The action *Explore: Set USA Data Pack Source* is now *Explore: USA Data Setup…*. The setting is still saved in the QGIS project (never global QGIS settings), with `VELORONA_USA_PACK` as the fallback; existing projects keep working.

### Not changed
Calculations, the five-level status contract, parity fixtures, Canadian data and heights, US antenna heights (30 m, Assumed), data limits (20,000 links / 36 tiles per view), the required library versions.

## 1.1.5 — 2026-10-09 (compared with 1.1.4)

Why it matters: 1.1.5 changes numbers. Terrain clearance on long paths is lower, weather rain loss is higher (mostly 6–10 GHz), many Canadian terrain statuses move because real antenna heights replace a 30 m assumption, and anything that cannot be decided now says NO DATA instead of guessing. Re-run saved analyses.

### Calculation corrections (results change)
- **Earth curvature.** `aei-link-clearance` 0.1.x applied the earth's bulge in the wrong direction (it added clearance). From 0.2.0 it is subtracted: clearance at mid-path is lower by about D²/(4·k·R) metres (k = 4/3, R = 6371 km): ~1 m at 6 km, 5 m at 13 km, 43 m at 38 km. The plugin refuses to run terrain analysis against an older library.
- **Rain attenuation (ITU-R P.838-3).** `aei-microwave-link-exposure` up to 0.1.5 used a 24-row coefficient table that differed from the Recommendation's Table 5 in 21 rows (rain loss understated, most at 6–10 GHz). 0.2.0 evaluates the Recommendation's equations. The plugin requires `>=0.2.0,<0.3` and shows an open-issue notice on weather results if an older model is installed.
- **Rain rate is per hour.** Open-Meteo reports millimetres per 15 minutes; 1.1.4 used that as mm/h. It is now ×4. Snow, freezing and mixed precipitation are no longer counted as rain; showers are. If the source does not split precipitation by type, the weather result is NO DATA.
- **Near threshold is a flag, not WATCH.** In 1.1.4 "near threshold" turned a result WATCH; now it is a verification note beside the status. Terrain WATCH means clearance ratio < 1.3, a provisional threshold, neither physics- nor operator-validated.

### Decision contract (shared with Velorona Map)
- The five levels CLEAR / WATCH / AT RISK / CRITICAL / NO DATA and "overall = worst of terrain and weather" already appeared in 1.1.4's Summary. 1.1.5 makes them a contract: same frozen input → same status, evidence, provenance and NO DATA as Velorona Map, checked on 96 shared fixtures (2,026 comparisons, 0 divergences; agreement between two implementations, not proof of correct physics).
- **NO DATA only through explicit validation**: invalid coordinates, identical endpoints, missing/null elevation (never 0 m), unusable weather interval, provider unreachable, weather frequency outside 1–100 GHz, antenna height outside 0.1–1000 m. A rate limit or outage is reported with its cause (bounded retry, never a status of its own); a data-pack problem is reported as a pack problem, never as a link's NO DATA.
- **Provenance.** Observed / Model-derived / Calculated / Inferred / Assumed. Anything you type or change is Assumed. Terrain can now start from one selected link: its highest published frequency is Observed while unchanged (in 1.1.4 the terrain dialog always typed frequency Assumed).

### New
- **USA (FCC ULS microwave links).** Explore: Set USA Data Pack Source, then Load USA Links in View. The dataset is **not bundled** (size, weekly refresh): you point Velorona at a pack folder or https address; only the 1° tiles under the map view are read; views over 20,000 links are refused. Source, source-file date, pack date and attribution travel with the layer and every export; it is licensee-reported record data, not a field measurement. US antenna heights stay 30 m (Assumed): the FCC's field documentation gives no unit or reference for its height field. See `docs/USA.md`. Not validated.
- **Canadian antenna heights.** The bundled Canada snapshot is schema 1.1 (shared byte-for-byte with Velorona Map): each link carries the heights its licensee reported (ISED column 29, "Height above ground level [m]"). They replace the 30 m assumption: Observed while unchanged, Assumed once you change them, 30 m Assumed when missing, terrain NO DATA when outside 0.1–1000 m (never clamped). ISED does not say whether the height is to the antenna centre or tip; an endpoint with several values uses the first row in the file (5.8 % of endpoints). Citation: `parity/contract/ISED_COLUMN29_CITATION.md`.
- **Exports** carry product/spec/library versions, the earth-curvature convention and the data source as `#` comment lines above the evidence table (table unchanged).
- **Start-up warning** when `aei-link-clearance` / `aei-microwave-link-exposure` is outside the supported range; install messages now give the exact line to run in QGIS's Python Console.

### Fixed
- The analysis dialog rounded a published frequency (6.22689 GHz → 6.23); an untouched field now returns its exact value.
- A deterministic NO DATA (e.g. a sub-GHz link) was remembered as "unavailable a moment ago"; it is now reported as what it is, every time.
- README claimed a GeoJSON export that the plugin does not have (CSV and Excel).
- Wording that said "ISED" for every record now follows the record's source.

### Dependencies and installation
- Requires `aei-link-clearance>=0.2.0,<0.3` (was unpinned) and `aei-microwave-link-exposure>=0.2.0,<0.3` (was `>=0.1.4`), `aei-geo-features`, `skyfield`, in QGIS's own Python. **QGIS does not install Python packages for plugins**; see the README for the one-line install from the Python Console.

### Documentation and development (no effect on results)
- New: `docs/USA.md`, `docs/RAIN_COEFFICIENTS_CAVEAT.md`, this file; `parity/` harness and handoff notes; `tools/verify_package.py`; USA end-to-end test and loading benchmark.

### Not changed
Thresholds, the Fresnel/clearance formulas, the earth-model constants (k = 4/3), the satellite engine.

## 1.1.4 — 2026-10 (reference)
Operational output: plain-language Summary / Details / Evidence, Ask box, Excel export, hourly weather history; Bandit/Flake8 cleanups. Earlier versions: see `metadata.txt`.
