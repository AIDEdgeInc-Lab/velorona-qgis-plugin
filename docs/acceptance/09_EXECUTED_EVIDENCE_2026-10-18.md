# 09 — What was actually executed on 2026-10-18, and what is still open

Scope: headless real QGIS 4.2.2 (offscreen Qt, a stand-in `iface`, **no desktop session**), real live services where noted, Excel 16.114 and Numbers 14.4 driven by AppleScript. Candidate = the working tree of `integration/qgis-finalization` (28 staged files + the unstaged CSV-safety change), **not built, not committed, version still 1.1.9**. Evidence files (outside the repository): `~/velorona-acceptance/2026-10-18/` with `checksums.txt`.

**None of this replaces the human checklist in `01_*` / `03_*`.** Anything that needs the desktop GUI is listed as *Not run*.

## 1. Batch vs single-link, live elevation (PAR-01…PAR-08, PAR-10) — API level, not GUI
Method (script in the session scratch area, outputs in `parity_live.json`, `batch_run1.csv`, `batch_run2.csv`): the single-link side calls exactly what the plugin runs after its dialog is accepted with the pre-filled values (`terrestrial.build_link_params` → `analyze_link_record`, then `pterrain.terrain_brief`), numbers read from the RAW DATA sheet of the real `result_to_xlsx`; the batch side is the real Processing algorithm `velorona:terrain_clearance_batch` run through `processing.run` on a *selected-features-only* source of the same links of the loaded *Fixed Service links (CAN)* layer, pause 7 s, CSV written. Compared with exact equality (rule in `02_*` §1).

| Test | Link | Single-link | Batch | Fields equal (11) | Decision | Provenance | Repeat batch identical | Status |
|---|---|---|---|---|---|---|---|---|
| PAR-01 | 010895086-001 | CLEAR | CLEAR | 11/11 | match | match (freq Observed 0.96 GHz, heights 13/75 m Observed) | yes | Pass (API level) |
| PAR-02 | 010869233-001 | WATCH | WATCH | 11/11 | match | match (Observed) | yes | Pass |
| PAR-03 | 011076519-002 | CLEAR | CLEAR | 11/11 | match | match | yes | Pass |
| PAR-04 | 010665829-002 | CLEAR | CLEAR | 11/11 | match | match | yes | Pass |
| PAR-05 | 010019479-004 | CLEAR | CLEAR | 11/11 | match | match (6.40479 GHz) | yes | Pass |
| PAR-06 | 010665661-001 | CLEAR | CLEAR | 11/11 | match | match | yes | Pass |
| PAR-07 | 010032181-007 | CLEAR | CLEAR | 11/11 | match | match (85.125 GHz) | yes | Pass |
| PAR-08 | 010047019-003 | NO DATA (height B 0.0 m) | NO DATA | – | same reason: "antenna height B outside 0.1-1000 m" | – | yes | Pass |
| PAR-10a | override (core, live): freq 7 GHz, Site A height 40 m on 010895086-001 | CLEAR | – | – | – | Assumed with "User override … record's own value is 0.96 GHz / 13 m; … entered instead"; Site B stays Observed; Details text says the same | – | Pass (single only) |
| PAR-10b | blank-frequency copy (core) | – | NO DATA "…no usable frequency … none is assumed"; with fallback 7 GHz: CLEAR, frequency 7.0 **Assumed**, heights Observed | – | – | – | – | Pass |
| PAR-09 | USA link WQVU207-4 (FCC ULS, 17.82 GHz) after a live "Load USA Links in View" of the Dallas area (7,232 links, 3,606 sites from `map.velorona.ai/data/us/`) | CLEAR | CLEAR | 6/6 compared | match | match: frequency Observed ("FCC ULS record …"), heights **Assumed 30 m** (FCC heights not used) | – | Pass (API level) |

The 11 fields: distance, bearing, frequency, first Fresnel radius, required clearance, available clearance, margin, clearance ratio, percent Fresnel clear, critical distance, elevation samples (floats compared with `==`).

**Environment finding, kept as evidence:** a first pass with only 1.5 s between requests (`run1_rate_limited/`) gave batch NO DATA, `transient=true`, "the service is rate-limiting requests (HTTP 429); try again in a minute" for 3 of 8 links in one run and 1 of 8 in the repeat — the rows were correctly NO DATA, not a result, and the same links computed normally in the other run. This is Open-Meteo's rate limit, not a product defect; the plugin's default pause is 0 and the algorithm help advises a pause. The pass above used 7 s pauses and 120 s between phases. **Product note for the owner:** a default of 0 s pause will hit 429 on runs of a few links back to back; consider a non-zero default or a stronger hint in the dialog (not changed here).

## 2. CSV / Excel safety on real plugin exports (stage 1)
Files produced by the plugin code with untrusted text (`=1+1`, `+1+2`, `-1+2`, `@SUM(1)`) in `exports/`; the batch file came from a real Processing run on a layer whose attributes were edited to those values. Opened in **Microsoft Excel 16.114** and every cell scanned for formulas:

| File | Result in Excel |
|---|---|
| `batch_plugin_run_untrusted_text.csv` (real algorithm run) | 435 cells, **0** formula cells; text cells show `'=1+1`, `'@SUM(1)`, `'-1+2` |
| `single_link_record.csv`, `single_site_record.csv` | no untrusted cell evaluated (the only hit is the genuine negative longitude, a number) |
| `selection_summary.csv` | no untrusted cell evaluated (only the genuine number −34.5) |
| `single_terrain_analysis.xlsx` | 8 sheets; the cell with the untrusted name is stored as **text** and displayed as text ("=1+1 → Site B"), no apostrophe added, no formula |
| `single_terrain_analysis.csv` | **Not completed in Excel** (AppleScript timed out three times; Numbers likewise timed out on the CSV files). Covered by the 35 automated tests only. |

Earlier, with raw (pre-fix) cells in a scratch file, Excel evaluated all four triggers and Numbers evaluated `=1+1`. Numbers was not re-checked on the plugin's own files. To do by hand: BAT-11.

## 3. Satellites (REG-03, SEL-03b) — **Not run, environment**
The project's own probe (`tools/live_orbit_probe.py`, five requests) ran against `celestrak.org`; the request failed (no answer within the time-out, `curl` HTTP code 000) and the plugin entered its back-off, writing an "unavailable" state; CelesTrak was unreachable from this machine (the 1.1.9 changelog records the same intermittency). No cache existed, so `qgis_satellite_feed_e2e.py` and `qgis_satellite_render.py` could not be run, and no data was fabricated. Retry from another network/time, or take the cache produced by the `live-orbit-probe.yml` workflow.

## 4. Automated suites on the current tree (unchanged since the CSV fix)
unit 458 passed / 3 skipped; `qgis_e2e` 502/502; `qgis_workflow_e2e` 49/49; `qgis_selection_sync_e2e` 58/58; `qgis_batch_e2e` 13/13; `qgis_usa_e2e` 55/55; `qgis_ui_polish_e2e` 91/91; Qt enum check clean (run after the CSV change; the final rerun is recorded at the end of the session report).

## 5. Still open (needs a person at QGIS Desktop, or a service that was unavailable)
| Item | Why open |
|---|---|
| INS-01…05 clean install of the built ZIP, actions, provider, 1.1.9 side-by-side | needs the built candidate ZIP and the GUI |
| SEL-01…SEL-09 | real Select Features tool, Layers panel, Records interaction |
| PRJ-01…PRJ-08 incl. a project saved by 1.1.9 | needs a saved `.qgz` round trip in the GUI |
| BAT-01 (menu/Toolbox entry), BAT-03 real Cancel / Task Manager, BAT-04/05/09 in the dialog | Processing dialog interaction |
| DET-03 opening the real Excel export in Excel for layout/repair prompts | not done (only the formula scan above) |
| REG-03/SEL-03b satellites | CelesTrak unreachable |
| Numbers on plugin CSVs, `single_terrain_analysis.csv` in Excel | automation timed out |
| Candidate build: commit hash, ZIP, SHA-256, `verify_package`, version bump | deliberately deferred until acceptance is complete |

## 6. Automation branch
Unchanged decision (`06_*`): not integrated.
