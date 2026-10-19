# 04 — Automated test inventory, verification status, coverage gaps

"Rerun today" = executed during this task (2026-10-18, no source or test edited; scratch copy via rsync, bytecode writing disabled). "Reported" = result stated in `docs/FINALIZATION_STATUS.md` from the previous session and **not** rerun now.

## 1. Environment and commands

- Python venv (3.9) with `pytest skyfield sgp4 numpy requests aei-geo-features openpyxl flake8 bandit`; libraries `aei-link-clearance` 0.2.1 and `aei-microwave-link-exposure` 0.2.0 from `~/Desktop/Video -Velorona/qgis-series-v1.1.9/libs` via `PYTHONPATH`.
- QGIS 4.2.2 `/Applications/QGIS-final-4_2_2.app`, Python 3.12, `QT_QPA_PLATFORM=offscreen`, environment as in `tests/run_qgis_tests.sh`.
- Important trap: the e2e scripts insert the *parent directory* of the checkout on `sys.path` and import `velorona`; inside `_worktrees/` that finds a different branch. They were run from a copy placed under a directory whose only `velorona` is the candidate.
- Commands:
  - `PYTHONPATH=<libs> python -m pytest -q tests` (unit)
  - `python tests/<name>.py` with the QGIS Python for each `qgis_*.py`
  - `sh tests/run_qgis_tests.sh` is the repository's own all-in-one runner (unit + e2e; it uses the QGIS Python's unit step with system pytest).

## 2. Status of each suite

| Suite | Result | Status |
|---|---|---|
| `pytest tests` (no `aei_workflow`) | 423 passed, 3 skipped | **rerun today** |
| `pytest tests/test_terrain_batch.py tests/test_satellite_reliability.py tests/test_presentation_terrain.py` | 52 passed | **rerun today** |
| `qgis_selection_sync_e2e.py` | 58/58 | **rerun today** |
| `qgis_batch_e2e.py` | 13/13 | **rerun today** |
| `qgis_workflow_e2e.py` | 49/49 | **rerun today** |
| `qgis_usa_e2e.py` | 55/55 | **rerun today** |
| `qgis_ui_polish_e2e.py` | 91/91 | **rerun today** |
| `qgis_e2e.py` | 502/502 (live services) | reported, not rerun |
| `clean_install_smoke.py` on a built ZIP | 36/36 | reported, not rerun |
| `pytest` with `aei-workflow-runner` 0.1.1 on the path | 425 passed, 2 skipped | reported |
| `parity/run_parity.sh` against Map `ddb7454` | 96 fixtures, 0 divergences | reported |
| Velorona Map `pytest` | 705 passed, 1 failed (last-digit float, satellite geometry) | reported |
| `bandit -ll` (CI options), `tools/check_qt6_enums.py` | clean | reported |
| `qgis_satellite_feed_e2e.py`, `qgis_satellite_render.py` | not run | need `ORBIT_CACHE_DIR` = a directory with an OrbitCache from a **real** CelesTrak fetch (workflow `live-orbit-probe.yml`). Do not fabricate. |

The 3 skips in the unit run: `tests/test_workflow_core_semantics.py` (needs `aei_workflow`, deliberately absent) and 2 pre-existing.

## 3. The five UI fixes: implementation and automated coverage

| # | Fix | Implementation | Automated tests (`tests/qgis_selection_sync_e2e.py` unless stated) | Real-window check |
|---|---|---|---|---|
| 1 | Selection after refresh | `core/layers.py` `_record_signature`, `_selected_records`, `_restore_selection`, used by `replace_point_features/replace_link_features` | §5 "dataset reload": same record kept after reorder; no re-open/zoom (silent restore); gone record cleared; id-less record cleared; reissued ids select nothing; changed content under same id cleared. `qgis_workflow_e2e.py` scenario 6c (satellite refresh) | SEL-02, SEL-03a/b |
| 2 | Signal connect/disconnect | `plugin.py` `_wire_inspector`, `_unwire_inspector`, `_unwire_all_inspectors`, `_adopt_layer`, `_on_layers_added`, `initGui`, `unload` | §8: one handler call per selection after 3× Load; unloaded plugin silent; reloaded plugin adopts layers and answers once; layer added later wired once; unload leaves `_wired_layers` empty and `_project_wiring_connected` false | SEL-05, PRJ-03, PRJ-07 |
| 3 | Removed-layer cleanup | `plugin.py` `_on_layers_will_be_removed`; `ui/records_table.py` `drop_layers`, `layer_alive` | §7: dataset leaves picker, details cleared, handler forgotten, remaining datasets still load | SEL-04 |
| 4 | Search vs map selection | `ui/records_table.py` `_highlight` (clears first), `_update_status` | §2: map selection hidden by the search leaves no highlighted row; §4 empty-search message | SEL-07 |
| 5 | Picker ↔ active layer | `plugin.py` `_on_active_layer_changed`, `_on_dataset_activated`; `records_table.datasetActivated`, `select_dataset`, `_mirror_layer_selection` | §1 picker → active layer; §3 Layers-panel pick → dataset; no selection changes; switching datasets back and forth changes nothing; independent selections kept | SEL-06, SEL-08 |

Limits of that evidence: `FakeIface` supplies `currentLayerChanged`/`setActiveLayer`; the real Layers-panel and the Select Features tool are never exercised; "project reopening" is simulated with `layersAdded`, not a saved `.qgz`.

## 4. Batch Processing coverage

Implementation: `core/batch.py` (`BatchLink`, `analyze_one`, `run_batch`, `batch_to_csv`), `core/processing/terrain_batch.py` (algorithm `velorona:terrain_clearance_batch`), `core/processing/provider.py`, plugin action `run_batch_terrain`.

| Required area | Covered by | Verdict |
|---|---|---|
| Multiple links | `test_every_parity_fixture_in_one_batch_equals_its_own_single_link_analysis` (all fixtures with terrain, >50) ; e2e "one output feature per input link" (4 links) | covered (offline, synthetic terrain) |
| Empty input | `test_empty_input_is_an_empty_result_and_a_valid_export`; e2e "empty layer gives an empty result" | covered |
| Invalid records | `test_incomplete_input_is_no_data_with_a_reason_never_a_guess` (no geometry, no frequency, bad coordinate, identical endpoints; no invented numbers); e2e covers only a blank-frequency link; `ca-h-height-zero` parity fixture in the all-fixtures test | covered in core; **Processing/layer path covers only blank frequency** |
| Cancellation | `test_the_limit_and_cancel_report_not_run_never_drop_links` (callback `is_canceled`; remaining rows NOT RUN, none dropped) | covered in core; **not through a real `QgsProcessingFeedback`, the dialog's Cancel or the Task Manager** |
| Partial failures | `test_a_failing_elevation_service_for_one_link_…` (NO DATA same reason/transient as single-link), `test_an_unexpected_exception_…` (ERROR row, rest continue), `test_a_library_too_old_…` (whole batch stops) | covered in core only |
| Repeat execution | `test_the_batch_is_deterministic` (two runs equal); no QGIS repeat/overwrite test | **core only** |
| Per-row consistency | `test_one_link_equals_the_independent_single_link_result` (exact `==`), all-fixtures test, e2e "each output row equals the single-link analysis" | covered (offline) |
| CSV export | `test_csv_export_has_the_preamble_one_row_per_link_and_the_counts`; e2e "CSV is written with the preamble and one row per link" | covered; **no special-character / formula-text test** |
| Extras | link limit, pause, input not mutated, reprojected (3857) input, selected-only input, fallback frequency typed Assumed, NaN/inf ratio | covered |

## 5. Coverage gaps and the smallest test that would close each

| ID | Gap | Smallest added test (not written — instructed not to modify tests) |
|---|---|---|
| G1 | Cancel through the Processing layer | In `qgis_batch_e2e.py`: a `QgsProcessingFeedback` subclass whose `isCanceled()` turns true after N `setProgress` calls; run the algorithm; assert output feature count == input count, first N rows have result statuses, the rest `NOT RUN`. |
| G2 | Invalid records from a real QGIS layer | Add to `make_layer`: a feature with null geometry, and C8-like height 0; assert NO DATA with the geometry/height reasons and that neighbouring rows equal their rows in a run without the bad ones. |
| G3 | Repeat run through Processing | Run the algorithm twice with the same CSV path; assert CSV bytes equal and output feature attributes equal. |
| G4 | Partial failure through Processing | Patch `requests.get` in the e2e to raise for one link; assert that row is NO DATA/transient and others unchanged. |
| G5 | CSV text safety | **Closed after this package was written**: `core/csvsafe.py` + `tests/test_csv_safety.py` (35 tests). Remaining: BAT-11 in a real spreadsheet. |
| G6 | Real Layers-panel / map-tool selection, overlapping features | Cannot be automated headlessly; manual SEL-01…SEL-08. |
| G7 | Saved-project reopening | Automated test that saves a `.qgz` with Velorona memory layers and reopens it with `QgsProject.read()` in the QGIS test runtime, then asserts `_wired_layers`, no duplicates after Load Public Data. |
| G8 | Batch vs single with **live** elevation | Manual PAR-01…PAR-10. |
| G9 | Satellite live paths | Need a real orbit cache; see REG-03. |
| G10 | Stale document | **Corrected afterwards** in `docs/BATCH_TERRAIN.md` and `CHANGELOG.md`. |
