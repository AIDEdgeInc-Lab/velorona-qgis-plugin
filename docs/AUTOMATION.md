# Velorona automation: batch workflows, run history, comparison

Status: Terrestrial Path Clearance only. Branch `feat/automation-workflow-runs`, not released.

**Update:** the workflow/run logic described below no longer lives in this repository. It is the product-neutral package
`aei-workflow-runner` (`aei_workflow`), also used by the headless `velorona-run` CLI for unattended scheduled runs. This plugin keeps only
the QGIS parts (`core/automation/qgis_task.py`, `ui/automation_dialog.py`), bundles the package into the release zip under `_vendor/`
(`tools/package.sh`), takes the same per-workflow lock as the CLI so both can share one store folder, and works without Velorona Web
or the CLI installed. Design, contract and scheduling docs are in the aei-workflow-runner repository. The module table below names the old
locations; read `core/automation/*` as `aei_workflow/*`.

## What it does

```
links CSV -> validate -> saved workflow -> background run -> saved run -> reopen / compare / export
```

In QGIS: **Velorona menu > Automate: Batch Path Clearance Runs**.

## Design

| Concern | Where | Notes |
|---|---|---|
| Input schema and row parsing | `aei_link_clearance.batch` (`REQUIRED_COLUMNS`, `parse_links_csv`) | Called, not copied. `core/automation/inputs.py` adds only: non-finite numbers, the plugin's own height/frequency bounds (`PARAM_SPEC`), same-point sites, duplicate `link_id`. |
| Analysis | `aei_link_clearance.analyze_link`, `explain` | Unmodified. `core/automation/engine.py` only adapts and serialises. |
| Execution | `core/automation/runner.py` | Per-link isolation, retries, cancel, checkpoints. No QGIS imports. |
| Background task | `core/automation/qgis_task.py` | `QgsTask` on QGIS's task manager; worker touches no widgets. |
| Storage | `core/automation/store.py` | JSON files under `<QGIS profile>/velorona/automation/`. Atomic writes. Backup/restore zip with SHA-256 manifest. |
| Comparison | `core/automation/compare.py` | See below. |
| Export | `core/automation/report.py`, `csvsafe.py` | Package folder per run. |
| UI | `ui/automation_dialog.py` | Only wiring. |

Only `qgis_task.py`, the dialog and `inputs.default_bounds()` need QGIS. Everything else is stdlib and runs under plain Python, so a CLI or worker can reuse it.

## Shared contract (for Velorona Map and any worker)

Two versioned JSON documents, integer `schema_version`, refused (never rewritten) when newer than the reader knows:

* `velorona.workflow/1`: id, name, engine, input, params + units, execution (attempts, retry delay, pause between links), output (`retain_runs`).
* `velorona.run/1`: run id, workflow id + full workflow snapshot, status, timestamps, input file name + SHA-256, rejected rows, per-link `{input, status, result | error, warnings, analyzed_at}`, counts, provenance, assumptions and limitations, versions (plugin, QGIS, Python, engine, schemas).

`tests/fixtures/*_v1.json` are committed v1 records. A future schema change that breaks reading them needs a migration; the fixtures are not to be regenerated.

Run status: `completed` (every input row analysed), `partial`, `failed` (no link produced a result), `canceled`, `interrupted` (found in `running` after a crash; finished links kept).

## Data provenance

| Source | Kind | Used in this slice |
|---|---|---|
| Open-Meteo Elevation (Copernicus DEM GLO-90, 90 m) | Static surface model. **Not an observation**: no observation time is provided, none is recorded. Retrieval time is recorded per link. | Yes |
| Open-Meteo current weather, ECCC station and radar (via `aei_mw_exposure`) | Current observations. Historical replay not available from these calls. | No (next engine) |

A stored run is a record of what was calculated. Re-running later re-queries the service and is a new analysis, never a reconstruction of past conditions. `provenance.historical_replay_supported` is `false`. A historical provider can be added as another entry in `provenance.data_sources` without changing the run schema.

## Comparison semantics

Differences are grouped as parameters / input file, data source, versions, and per-link results. `comparable` is false (with reasons) when engine, parameters or data source differ, or a run failed. Per link: a changed input is named as the likely cause; identical inputs and versions with a different result is reported as **unexplained** (the elevation service may have changed, which cannot be observed); an engine-version change is offered as a possible cause, not asserted.

## Known limits

* Cancel takes effect between links; a request already in flight finishes first (library HTTP timeout 15 s).
* Retry is a fixed delay, not adaptive backoff. No rate-limit figures are assumed; use "Pause between links" if the service throttles.
* `results.csv` follows the Evidence-CSV `#` preamble convention: for spreadsheets and people. It is neutralised against spreadsheet formula injection with the Web Map's rule. Load `links.geojson` into QGIS, not the CSV.
* Only `input_links.csv` (canonical input schema) and `run.json` (via backup restore) are claimed re-importable, and both are tested.
* Retention moves old runs to `_pruned/`; nothing is deleted. Default keeps everything.
* Checkpoints are written at most every 2 s; a crash loses at most that window.
* No scheduling yet.

## Scheduling: recommendation (not built)

Smallest reliable design: a small CLI (`run --workflow <file> --links <csv> --store <dir>`) over the same `core/automation` modules, started by the customer's own OS scheduler (cron / launchd / Task Scheduler). Exit code from run status; runs land in the same store, so QGIS History shows them. Needed first: move the terrestrial bounds out of the QGIS-dependent `engines/terrestrial.py` so validation runs without QGIS. Browser tabs cannot run unattended and are not proposed for it. Pause/resume/retry-policy for a schedule belong in that CLI, not in a service.

## Velorona Map (not yet integrated)

Plan: implement the same two JSON documents in `web/` (IndexedDB store; export/import of the same backup zip layout; a JS reader/comparer) and run the plugin's `tests/fixtures/*_v1.json` through it in the Map's Node test harness, as `test_web_mwexposure_parity.py` already does for the weather port. Analysis reuses `linkmath.js`, the existing parity-tested port. Browser storage can be cleared or evicted, so the Map must offer backup export/import and say it is per-browser.
