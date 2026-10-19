# Finalization status (2026-10-18)

> Historical engineering note written while 1.1.10 was being prepared (2026-10-18/19); its statements about the working tree, commits and open items describe that moment. The user-facing description of 1.1.10 is in `CHANGELOG.md` and `README.md`.

Worktree `~/velorona-repos/_worktrees/qgis-finalize`, branch `integration/qgis-finalization`, created from `origin/main` = tag `v1.1.9` = `905d9e4`. Nothing is committed, pushed, merged, tagged, published or deployed; all changes are in the working tree / index. The earlier worktree `qgis-ui-integration` (branch `feat/ui-selection-integration`, uncommitted) was left exactly as it was; its changes were copied here (they were against the same base).

## 1. What v1.1.9 actually contains (verified)

| Check | Evidence |
|---|---|
| GitHub release `v1.1.9` (published 2026-10-15, not draft) | asset `velorona-1.1.9.zip` 2,590,744 bytes, sha256 `d255c5f6…880164` (GitHub's digest and my download agree) |
| Official QGIS repository lists it | `plugins.qgis.org/plugins/plugins.xml?qgis=4.0` lists *Velorona 1.1.9* (file `velorona.1.1.9.zip`, QGIS 4.0–4.99, updated 2026-10-15T01:34Z, not experimental). The zip downloaded from `plugins.qgis.org/plugins/velorona/version/1.1.9/download/` has the **same sha256** as the GitHub asset |
| Zip equals tagged source | file-by-file diff of the extracted zip against `git archive v1.1.9`: no content differences; the zip omits only `.github`, `.gitignore`, `CONTRIBUTING.md`, `examples`, `parity`, `tests`, `tools` |
| Batch / workflow / history code in the zip | none: no `core/batch.py`, `core/processing/`, `core/automation/`, `ui/automation_dialog.py` |
| Tag | annotated tag `v1.1.9` (object `762777e`) → commit `905d9e4` |

## 2. Reconciliation of the development branches

| Branch | Relation to `origin/main` | Decision | Evidence |
|---|---|---|---|
| `feat/selection-visibility-zoom-hit-target`, `feat/ui-polish`, `feat/usa-setup-ux` | already ancestors of main (0 commits ahead) | superseded, nothing to do | `git merge-base --is-ancestor` |
| `feat/satellite-reliability` (1 commit) | 1 ahead, 2 behind | **integrated (tests); its `layers.py` change superseded** | Its test matrix (`tests/test_satellite_reliability.py`, scenario 6c in `qgis_workflow_e2e.py`) is applied unchanged and passes. Its fix for stale selection (`removeSelection()` before a refresh) is replaced by the stronger rule in `core/layers.py` (see UI audit): same record id and unchanged content is kept, anything else cleared. Satellites move, so a refreshed satellite is "changed" and is cleared exactly as that branch required |
| `feat/batch-terrain-processing` (2 commits) | 2 ahead, 31 behind | **integrated** (3-way apply, 3 trivial conflicts resolved: CHANGELOG, `run_qgis_tests.sh`, `verify_package.py`) | Reuses `terrestrial.build_link_params` / `analyze_link_record` and the presentation status model, so a batch row equals the single-link result (`tests/test_terrain_batch.py` compares every shared parity fixture that has terrain (more than 50) with an independent single-link analysis: 13 tests pass); first run of `tests/qgis_batch_e2e.py` in QGIS 4.2.2: 13/13. Runs as a Processing algorithm, so QGIS executes it in a background task with progress and cancel (`feedback.isCanceled`, `setProgress`) |
| `feat/automation-workflow-runs` (6 commits) | 6 ahead, **109 behind** | **NOT integrated – blocked decision** (see §3) | `core/automation/`, `ui/automation_dialog.py`, vendored `aei_workflow` |

One consequence of integrating batch: `tests/qgis_e2e.py` had the check "Velorona never references the Processing Toolbox" implemented as a substring ban on "processing" in `plugin.py`. Its intent is "Velorona must not own native QGIS panels". It now forbids reaching into the Toolbox panel (find/show/hide/re-parent) and allows a registered Processing provider. This is a deliberate change of an invariant, made visible here. `tests/clean_install_smoke.py` now expects 8 actions (7 + the batch action).

## 3. Why the automation branch is held back

1. **Decision vocabulary differs from the plugin.** `aei_workflow.engine.analyze_link_row` calls `analyze_link` and returns the library's three line-of-sight classes. The plugin decides with `core/presentation/terrain.py` (CLEAR / WATCH / AT RISK / CRITICAL, near-threshold rule, NO DATA boundary, Observed/Assumed provenance). `tests/test_workflow_core_semantics.py` runs all comparable parity fixtures through both with the same offline elevation: **numbers are identical** (clearance, required clearance, Fresnel radius, distance), but of 50 comparable links the plugin says WATCH for 2 where the workflow core says `clear`; the inputs the plugin refuses (NO DATA) have no equivalent in the workflow core. A run history built on it would show a different decision than the Results panel for the same link.
2. **Stale base.** It predates the 1.1.5 decision contract (owner decision D-Q7: "branch predates every P0 change"), is 109 commits behind, and rewrites `PARAM_SPEC` in `core/engines/terrestrial.py` to come from the external package (the values are textually identical to main's today, but the source of truth would move out of the repository).
3. **New runtime dependency and release step.** `aei_workflow` (Apache-2.0, `aei-workflow-runner` 0.1.1 on its `origin/main`, not on PyPI per the branch) must be vendored by `tools/package.sh` from a sibling checkout; that changes how releases are built.
4. **Overlap.** It and the Processing batch both run terrain batches; shipping both without a decision would give users two different batch tools.

Smallest safe path (not done, needs owner approval D-Q7): rebase the branch, give `WorkflowTask` an analyzer that wraps `core.batch.analyze_one` so rows carry the plugin's statuses and provenance, store the plugin status next to the library class, then re-run `qgis_automation_e2e.py` and the smoke test. Until then run history, comparison and saved workflows are not available in the plugin; the Map has its own (browser-local) implementation.

## 4. Capability status

States: 1 released · 2 in source, not exposed · 3 partial · 4 unmerged branch only · 5 not implemented · 6 blocked · 7 unverified.

| Capability | Before (v1.1.9) | After this work (integration branch, unreleased) | Evidence |
|---|---|---|---|
| Batch execution | 5 – none | 3 – **terrain clearance only**, Fixed Service link layer or its selection, via Processing (also Processing Toolbox / modeler / `qgis_process`); one row per link, per-link status/reason, optional CSV, cancel, progress, link limit 100 (hard 1000). Weather exposure and satellite are not batched | `core/batch.py`, `core/processing/`, `docs/BATCH_TERRAIN.md`, `test_terrain_batch.py`, `qgis_batch_e2e.py` |
| Saved workflow definitions | 5 | 4 – automation branch only | §3 |
| Workflow execution | 5 | 4 | §3 |
| Run history / comparison | 5 | 4 | §3 |
| Export of batch results | 5 | 3 – CSV from the batch algorithm only (no Excel for a batch) | `batch_to_csv` |
| Persistence of workflows/results | 5 (USA pack source in the QGIS project; satellite element-set cache on disk) | unchanged; nothing persists batch results except the CSV the user writes | `plugin.py` project entry, `orbit_data.py` |
| Scheduling / unattended | 5 in the plugin; separate `velorona-run` CLI | unchanged. The runner documents macOS launchd as verified (2026-09-26); Linux cron/systemd text is untested; Windows unsupported | `aei-workflow-runner/docs/SCHEDULING.md` |
| Remote / cloud storage | 5 | 5 – none, and none is justified by a stated requirement | audit docs |
| USA setup | 1 | 1, unchanged. `qgis_usa_e2e.py` 55/55 on a synthetic pack. The online pack answers (`map.velorona.ai/data/us/index.json`, HTTP 200, generated 2026-10-03, source file 2026-09-27); a live load into QGIS was **not** run here. Operator filter still Canada-only (see §6) | tests, curl |
| Satellite reliability | 1 (1.1.8/1.1.9) | 1 + the branch's failure/cache matrix and refresh scenario as regression tests | `test_satellite_reliability.py` (19 tests), workflow scenario 6c |
| Calculation parity (Map vs QGIS) | 7 | verified now: `parity/run_parity.sh` against Map `ddb7454`, library `aei-link-clearance` 0.2.1: **96 fixtures, 0 divergences, 0 problems**; the report's independent exact-chord check agrees with the oracle within 0.0166 m; convention `bulge-added-to-terrain` is enforced by `core.validation.require_corrected_clearance` and `tests/test_terrain_curvature.py` | `PARITY_REPORT.md` (scratch run) |

## 5. Tests (Python 3.9 venv with pytest, skyfield, sgp4, requests, aei-geo-features, openpyxl; libraries `aei-link-clearance` 0.2.1 and `aei-microwave-link-exposure` 0.2.0 from the 1.1.9 video-series `libs/`; QGIS 4.2.2 at `/Applications/QGIS-final-4_2_2.app`, offscreen)

| Suite | Result |
|---|---|
| `pytest tests` (no `aei_workflow`) | 423 passed, 3 skipped (the skips: the workflow-core comparison, which needs `aei_workflow`, plus 2 pre-existing) |
| `pytest tests` with `aei-workflow-runner` 0.1.1 on the path | 425 passed, 2 skipped |
| `qgis_e2e.py` (live public services) | 502/502 |
| `qgis_ui_polish_e2e.py` | 91/91 |
| `qgis_usa_e2e.py` (synthetic pack) | 55/55 |
| `qgis_workflow_e2e.py` | 49/49 |
| `qgis_selection_sync_e2e.py` | 58/58 (fails on `origin/main`) |
| `qgis_batch_e2e.py` | 13/13 |
| `clean_install_smoke.py` on a package built by `tools/package.sh` and verified with `tools/verify_package.py` | 36/36 |
| `tools/check_qt6_enums.py`, `bandit -ll` (CI settings) | clean |
| `qgis_satellite_feed_e2e.py`, `qgis_satellite_render.py` | **not run**: they need `ORBIT_CACHE_DIR`, a cache of real CelesTrak data (the live-orbit-probe workflow) |
| Velorona Map `pytest tests` (read-only, same machine) | 705 pass, 1 fail: `tests/js/satgeo.test.js` compares floats with `deepStrictEqual` and differs in the last digit (e.g. `-44.65782879507985` vs `-44.657828795079844`). It is satellite geometry, not terrain; a tolerance-free golden comparison in the Map repo, not touched here |

## 6. Operator filter and US data

The filter covers `OPERATOR_SOURCE_KEYS` (Canadian Fixed Service sites/links, Cellular). US layers do carry `licensee` (sites: names joined with " / " like ISED; links: one string, `core/countries/usa.py`), so extending it is structurally possible, but the FCC name forms and the effect of 250k-link scans were not verified; it is not extended and the UI says so.

## 7. Not verified / blockers

- No interactive QGIS desktop session (clicks in the Layers panel, canvas identify with overlapping features, theme/narrow-dock appearance). Headless runs use a stand-in `iface` that supplies `currentLayerChanged`/`setActiveLayer`. Manual steps: `docs/UI_INTEGRATION_AUDIT.md`.
- Project reopening is exercised through `layersAdded` (a layer arriving after start-up), not by saving and reopening a `.qgz` (Velorona's layers are memory layers).
- Live CelesTrak, Open-Meteo rate limits and ECCC were not stressed.
- FCC redistribution rights are not established anywhere in the repository: the USA pack stays an external download.
- Windows and Linux were not tested.
