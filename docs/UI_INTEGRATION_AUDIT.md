# UI, selection and filter integration audit

> Historical engineering note written while 1.1.10 was being prepared; the selection and wording fixes it describes are part of 1.1.10 (see `CHANGELOG.md`). Branch and git-state statements describe that moment.

Written on branch `feat/ui-selection-integration` (from `origin/main` 905d9e4, plugin 1.1.9; uncommitted). Carried into `integration/qgis-finalization`, where it was extended: see "Finalization update" at the end, and `FINALIZATION_STATUS.md`. Nothing pushed, merged, tagged or released.

## Root causes found (each reproduced in real QGIS before the fix)

| # | Defect | Cause | Fix |
|---|--------|-------|-----|
| 1 | After a layer's content was replaced (viewport refresh, Load Public Data, USA load) the old selection survived as **stale feature ids** (`selectedFeatureIds()` still `[501]` with 0 features). `QgsFeature` ids are reissued on reload, so a stale id could later point at a different record. | `replace_point_features` / `replace_link_features` truncate and refill without touching the selection. | `core/layers.py`: selection is carried over by the record's own `id` (`_selected_record_ids`, `_restore_selection`). A surviving record is re-selected silently (no re-zoom while panning); a record that is gone, or has no `id`, is cleared and the details panel empties. |
| 2 | **Selecting on the map showed no details** for Velorona layers that already existed in the project after the plugin was reloaded, because the selection handler was connected only when a layer was *created*. The unloaded instance also kept answering (handlers were never disconnected). | `_ensure_public_layer` returned an existing layer without wiring it; `unload()` never disconnected. | `plugin.py`: `_wire_inspector` is idempotent (`_wired_layers`), existing layers are adopted in `initGui` / `layersAdded` / on reuse, and `unload` unwires everything. |
| 3 | **Removing a Velorona layer from the project, then using the Records picker, raised `RuntimeError: wrapped C/C++ object … has been deleted`** (uncaught exception inside a Qt slot). | The Records table held the layer wrapper after QGIS deleted it. | `plugin._on_layers_will_be_removed` unwires the layer, drops its caches and calls `records.drop_layers`; `records_table.layer_alive` guards the model, row handler and picker. Details of the removed layer's selection are cleared. |
| 4 | A Records row stayed highlighted when the map selection moved to a record the search hides, or to one missing from a rebuilt dataset. | `show_feature` returned early without clearing the old highlight. | `records_table._highlight` always clears first. |
| 5 | Switching the Records dataset showed no highlight for the selection the map still held; picking a layer in the QGIS Layers panel did not move the table, and choosing a dataset did not make its layer active. | No link between the picker and the QGIS active layer. | `datasetActivated` → `plugin._on_dataset_activated` (sets the active layer) and `iface.currentLayerChanged` → `_on_active_layer_changed` (selects the dataset). Neither selects anything; both are loop-guarded. |

## Files and functions changed
- `core/layers.py`: `_selected_record_ids`, `_restore_selection`, `replace_point_features`, `replace_link_features`.
- `plugin.py` (also `IMAGERY_GROUP_NAME`, `LEGACY_IMAGERY_GROUP_NAMES`): `_wire_inspector`, `_unwire_inspector`, `_unwire_all_inspectors`, `_adopt_existing_layers`, `_adopt_layer`, `_on_layers_added`, `_on_layers_will_be_removed`, `_on_active_layer_changed`, `_on_dataset_activated`, `_ensure_public_layer`, `_ensure_imagery_group`, `_ensure_imagery_layers`, `initGui`, `unload`, `_ensure_dock`.
- `ui/records_table.py`: `layer_alive`, `datasetActivated`, `drop_layers`, `select_dataset`, `_mirror_layer_selection`, `_highlight`, `show_feature(s)`, `set_layers`, `refresh_current`, `_update_status`, operator tooltip / hint.
- `metadata.txt` (`about`), `README.md` (version line), `tests/qgis_e2e.py` (group name), `tests/run_qgis_tests.sh`, `tests/README.md`, new `tests/qgis_selection_sync_e2e.py`.

## Wording
Searched `plugin.py`, `ui/`, `core/`, `metadata.txt`, README for Optional / Experimental / Placeholder / Coming Soon / Not Implemented / TODO / Demo / Beta / Temporary / WIP.
- Layer group **"USA Imagery (optional)" → "USA Aerial Imagery & Topo (USGS)"** (final name; see the finalization update). Projects saved with the old name are renamed in place, not duplicated.
- Log line "Optional layer … was not added" → "Imagery layer … was not added".
- `metadata.txt` `about` claimed a **GeoJSON** export that does not exist in the code; it now says CSV and Excel (.xlsx), like the README. README version line 1.1.6 → 1.1.9.
- Operator filter tooltip / hint now say the filter covers the **Canadian** layers and that USA layers are searched in the table (previously implied all loaded layers).
- Empty search result now reads "No records match the search “…” (N in this dataset)" instead of "0 of N records".
- Left as is (not user-facing UI): input placeholders ("Search records…") are correct use; internal `Optional[...]` typing; a 0.2.0 changelog line "Experimental local development plugin" is accurate release history.
- No `Optional` label exists on the analysis parameter form (labels come from the engine `PARAM_SPEC`; none contains it). The "Optional" you saw is most likely the imagery group.

## Behaviour verified
Selection: Records row → the correct layer's feature, details, active layer; map → the one correct row (and none when hidden); clearing; switching datasets; panel layer pick; USA and Canadian layers; reload by record id; layer removal; plugin reload; no double handling after repeated Load Public Data.
Filters: Operator filter narrows layer, table, counts and details consistently, drops an excluded selection, combines with the search, clears back to the full set, repeated toggling leaves no stale records; empty results are stated.

## Tests run (this machine, QGIS 4.2.2 offscreen, `aei-link-clearance` 0.2.1 / `aei-microwave-link-exposure` 0.2.0 via PYTHONPATH)
| Suite | Result |
|---|---|
| `tests/qgis_selection_sync_e2e.py` (new) | **50/50** on the fixed code; **fails on `origin/main`** (reload, id-less record, layer removal, handler checks), so it detects the defects |
| `tests/qgis_workflow_e2e.py` | 44/44 |
| `tests/qgis_ui_polish_e2e.py` | 91/91 |
| `tests/qgis_usa_e2e.py` (synthetic pack) | 55/55 |
| `tests/qgis_e2e.py` | 502/502 (talks to live public services) |
| `tools/check_qt6_enums.py` | clean |
| `pytest tests` under system Python 3.9 | 380 pass, **9 fail, the same count (9) and cause as on the untouched branch**: `test_satellite_feed.py` needs `skyfield`/`sgp4`, which are not installed in that interpreter. They were not run under QGIS's Python (no pytest there). |
`tests/test_metadata.py` passes after the `about` edit.
Engineering calculations, thresholds, statuses and exports were not touched; the existing presentation/terrain/weather/status/parity unit tests pass.

## Not changed on purpose / remaining
- **No country selector exists.** USA is a data pack the user sets up (Explore: USA Data Setup) and loads for the current view; "USA" appears as a Records dataset and a layer only after that. Selecting "USA" cannot work before data is loaded, and this is stated rather than faked.
- **Operator filter is Canada-only** (`OPERATOR_SOURCE_KEYS`). Extending it to the FCC layers is a product decision (the operator list and counts are built by scanning every record, and the FCC pack can hold hundreds of thousands of links; I did not check how FCC licensee names are formatted). Gap recorded, wording made accurate.
- **The Records search is a table-only filter** (documented in the tooltip/status); exports use the layer. It does not change the map.
- **Selections on different layers are kept independently** by design: the two-site Microwave analysis gathers selected sites across layers. Selecting a row in another dataset does not clear the other layer's selection.
- Pack coverage (docs/USA.md): Canada is bundled (ISED snapshot, 24,859 sites / 16,956 links, file dated 2026-09-01); Ontario towers and ISED cellular are live viewport queries; the USA FCC ULS pack is **not bundled** (about 14 MB, served at map.velorona.ai/data/us/ or from a folder); satellites and SatNOGS stations are global. Redistribution terms for bundling the FCC data are not established in this repository; no USA data was added.
- Pre-existing, unchanged: terrain Details wording about heights "entered by the user" for link-record runs (owner issue from the 1.1.9 video series); `docs/` rain-coefficient caveat.

## Not verified
- No interactive QGIS GUI session was run. Everything above ran headless (offscreen Qt, a stand-in `iface` that supplies `currentLayerChanged` and `setActiveLayer`). The real Layers-panel click path, map-canvas identify clicks and overlapping features on a real display are untested.
- Panel appearance in light/dark themes and narrow docks was not re-reviewed beyond the existing UI polish suite.
- Live-service behaviour (Open-Meteo, ECCC, CelesTrak) was exercised only by `qgis_e2e.py`.

Manual check in QGIS: load the plugin, Explore: Load Public Data; (1) in Records pick "Fixed Service links" and confirm the Layers panel active layer changes; click a row and confirm the map selects/zooms and Details match; (2) click Fixed Service sites in the Layers panel and confirm the Records dataset follows with nothing selected; (3) pick an Operator, confirm the count and map change and a selected record outside it clears; clear it and confirm the full count returns; (4) remove a Velorona layer in the Layers panel and open the Records picker (no error); (5) Plugins > Reload, select a feature on the map, confirm Details appear once.

## Git state
Branch `feat/ui-selection-integration` in worktree `~/velorona-repos/_worktrees/qgis-ui-integration`; changes uncommitted. The original checkout (`parity/1.1.5-p0`) and all other worktrees were not modified.

## Finalization update (integration/qgis-finalization)

Changes to the above after review against the repository and the other branches:
- **Stale selection rule strengthened.** `core/layers.py` keeps a selected record only if its record `id` exists after the reload **and its attributes and geometry are unchanged** (`_record_signature`). Reissued feature ids can no longer select a different record, a record whose content changed (a moved satellite, an edited licence) is cleared with the details, and a record without an `id` is cleared. This reconciles with `feat/satellite-reliability`, which required a refreshed satellite to leave nothing stale shown; its own one-line `removeSelection()` in the same functions was not applied (superseded).
- **Imagery group name.** Final name `USA Aerial Imagery & Topo (USGS)` (the group holds the USGS aerial imagery and the USGS topographic map; it is not renamed to hide that the layers are optional: both layers are off by default and their metadata says "Off by default: nothing is requested until you switch the layer on"). Projects saved with `USA Imagery (optional)` (1.1.9) or the intermediate `USA Imagery` are renamed in place, no group or layer is duplicated.
- **Terrain Details wording.** `core/presentation/terrain.py` (`_height_origin_text`, `frequency_origin_text`) and `core/presentation/workbook.py`: for a link-record run the Details facts and the Excel Summary state the origin carried by the result (`observed: ISED record -- …` / `assumed: …`), consistent with the Evidence view and exports; runs without origin keep the two-site wording. Tests: `tests/test_presentation_terrain.py`.
- **New checks in `tests/qgis_selection_sync_e2e.py`** (now 58): reissued ids / changed content under the same id clear the selection; a layer arriving later (the mechanism a reopened project uses) is wired exactly once and answers once; switching Records datasets back and forth changes no selection on any layer; removal unwires; unload leaves no handler and no project connection.
- Independent selections on different layers are intentionally preserved (the two-site microwave analysis gathers selected sites across layers).
