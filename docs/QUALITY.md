# Quality gates for the Velorona QGIS plugin

Follows the AID Edge engineering quality standard
([AIDEdgeInc-Lab/.github `standards/`](https://github.com/AIDEdgeInc-Lab/.github/tree/main/standards)).
Three stages, each with its own workflow. Tests are adapted to what this project is: a QGIS 4 / Qt6 plugin.

| Stage | Workflow | Runs | Blocks merge? |
|---|---|---|---|
| A. Pull-request CI | `ci.yml` | every PR and push to `main` | `unit`, `enums`, `security`, `package` via the single check **`ci-gate`**. `qgis-offline` is advisory until it has been green on `main` 3 times in a row. |
| B. Release validation | `release-validate.yml` | tag `v*` or by hand | Gate for releasing: tag = `metadata.txt` = `CHANGELOG.md`; full Stage A; zip built once, verified, checksummed; that zip installed into a fresh profile in real QGIS 4.0 and 4.2 and the whole workflow run from the installed copy. |
| C. Post-publication | `published-verify.yml` | daily + by hand | Downloads what plugins.qgis.org serves and runs the same structural verification. Opens an issue on failure. |
| (external services) | `qgis-live-e2e.yml` | weekly + by hand | Never. Calls live elevation / weather / CelesTrak; an outage is EXTERNAL, not a code defect. |

## What is and is not covered

- **Covered in CI:** unit tests (Python 3.12, 3.13), Qt6 enum check, bandit (medium+), package contents, the two QGIS
  suites that need no network (USA synthetic pack, UI polish) in the official `qgis/qgis` 4.0 and 4.2 images.
- **Allowed skips:** exactly two tests that need real USA data held in the Velorona Map repo
  (`tools/check_skips.py`). Any other skip fails CI.
- **Not covered in CI:** performance benchmarks, Windows and macOS runtimes (the maintainer's local runs use the macOS app
  bundle via `tests/run_qgis_tests.sh`), and publishing itself.
- **Manual by design:** uploading the verified zip to plugins.qgis.org (needs the maintainer's OSGeo account). After
  upload, `published-verify.yml` is the evidence that users get the right package.

## Known runtime quirk: QGIS 4.0.3 aborts at shutdown

`tests/clean_install_smoke.py` (and `qgis_e2e.py`) end with `qgs.exitQgis()`. On QGIS **4.0.3** (the declared minimum)
the process aborts there (`std::bad_alloc`, exit 134) *after* printing `36/36 passed`; 4.2 exits cleanly. Reproduced
2 of 2 on GitHub runners. `tools/run_qgis_suite.py` tolerates exactly this case (complete N/N pass + abort signal, no
failure lines) with a `::warning::`, and nothing else. Cause is not yet established (hypothesis: widgets still alive at
`exitQgis()`). Remove the tolerance once the harness or QGIS no longer aborts.

## Run the same checks locally

```sh
python3 -m pip install -r requirements-dev.txt
python3 -m pytest tests -q -rs --junitxml=pytest.xml && python3 tools/check_skips.py pytest.xml
python3 tools/check_qt6_enums.py
./tools/package.sh && python3 tools/verify_package.py dist/velorona-<version>.zip <version>
```

## Branch protection (settings, not code)

Require the status check **`ci-gate`** on `main`. Do not require `qgis-offline` until it is promoted.
