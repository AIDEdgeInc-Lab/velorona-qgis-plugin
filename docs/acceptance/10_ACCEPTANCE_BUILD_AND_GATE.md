# 10 — Acceptance build and the single remaining gate (2026-10-19)

## 1. State
Real QGIS Desktop interaction is **not possible in this agent environment** (no desktop-control tools; AppleScript automation of Excel/Numbers is flaky and cannot drive QGIS). Nothing in `01_*`/`03_*` that needs the GUI was performed or simulated. The release steps (version bump, commit, push, tag, publish) were therefore **not** done, as instructed.

## 2. Acceptance build (temporary; NOT a release artifact)
| Item | Value |
|---|---|
| ZIP | `~/velorona-acceptance/2026-10-19/velorona-1.1.9-ACCEPTANCE-CANDIDATE-NOT-A-RELEASE.zip` |
| SHA-256 | `f3ad5f04eada555651def7f3ec4517b0d1d88e515be52c6a42dc3b9cdaf98f72` |
| Built | 2026-10-19 with `tools/package.sh` (it names the file velorona-1.1.9.zip; copied to the name above and the repo's `dist/` removed); `tools/verify_package.py`: PASS (86 files, 17.1 MB uncompressed, 2.7 MB zip) |
| Source | branch `integration/qgis-finalization`, HEAD `905d9e4119829a122f7cd990e5a3de8d96d2cb66` **plus uncommitted changes**: staged diff (28 files) SHA-256 `3b9a85b269da1b9c…` (index tree `fa1e87c627c5410f59464b02ad33b3ffa9e7b0c1`); unstaged diff SHA-256 `981d24595510a0bd…`; 13 untracked files incl. `core/csvsafe.py`, `tests/test_csv_safety.py`, `docs/acceptance/*`. There is no candidate commit hash. |
| Version inside | `1.1.9` (unchanged; it has the same version number as the published plugin, so install it in a **clean/dedicated profile only**, never over the published install) |
| Install path | Plugins ▸ Manage and Install ▸ Install from ZIP, in profile `velorona_acceptance` → `<profile>/python/plugins/velorona/` |
| Installed-copy test | `tests/clean_install_smoke.py` against this ZIP in a fresh profile (repo off `sys.path`): **36/36** |
| Tree match | Verified by byte comparison: every `.py`, `metadata.txt`, `requirements.txt` and `.json` file in the ZIP is identical to the working tree. Only documentation differs: `CHANGELOG.md` (the pause line was added after the build), `docs/acceptance/README.md`, and `docs/acceptance/10_*` (written after the build). |
| Note | the ZIP contains `docs/acceptance/` (12 entries) because the packager ships `docs/`. Decide before the release build whether internal acceptance evidence should ship (suggest excluding it from the release ZIP). |

## 3. Automated results on this exact tree (2026-10-19, rerun, not historical)
Unit `pytest tests` (Python 3.9 venv): **458 passed, 3 skipped**; `tests/test_csv_safety.py`: 35 passed. QGIS 4.2.2 offscreen: `qgis_e2e` 502/502 · `qgis_workflow_e2e` 49/49 · `qgis_selection_sync_e2e` 58/58 · `qgis_batch_e2e` **14/14** (was 13; one new check) · `qgis_usa_e2e` 55/55 · `qgis_ui_polish_e2e` 91/91. Qt enum check clean; bandit (CI settings) clean; flake8 `F`: only 2 warnings that already exist at HEAD (`COLORS`, `theme` unused imports in `plugin.py`); one duplicate `QgsApplication` import introduced by the batch merge was removed. Skipped: 3 (workflow-core comparison needs `aei_workflow`; 2 pre-existing). **Not run:** `qgis_satellite_feed_e2e`, `qgis_satellite_render`.

Changes made in this pass: batch pause guidance for HTTP 429 (label, help, `docs/BATCH_TERRAIN.md`, CHANGELOG; default left at 0 because only 1.5 s (failed) and 7 s (passed) were measured); duplicate import removed; one new e2e check. No engineering calculation was touched.

## 4. Satellites
CelesTrak was still unreachable on 2026-10-19 (HTTP code 000 after 20 s). The only orbit cache on this machine (`~/Library/Application Support/QGIS/QGIS4/profiles/default/velorona/orbit_cache/orbit_geo.json`, 74 bytes) is a back-off marker from earlier test runs, not data. Satellite end-to-end: **Not run (environment)**. No data fabricated.

## 5. The single gate — what a person must do (about 1–2 hours)
Use the profile `velorona_acceptance` and the ZIP above. Record in `07_EVIDENCE_TEMPLATE.md` / `07_results_template.csv`.
1. **INS-01…05** (`01_*` A): install; no errors in Log Messages / Python Error; 8 actions + Processing provider "Velorona"; single-link analysis works; compare with a second profile holding the published 1.1.9 ZIP.
2. **SEL-01, 02, 04, 05, 06, 07, 08** (`01_*` B): the real Select Features tool and Layers panel; refresh unchanged (Load Public Data again); remove the selected layer then open the Records picker; add a layer later (console snippet in SEL-03a); switch datasets; search vs map selection; two layers selected for Microwave Weather Exposure. SEL-03a variants 1–3 via the console snippet.
3. **PRJ-01…07** (`03_*`): save the disposable `.qgz`, close, reopen, Load Public Data again; no duplicates, no stale details, handlers wired once; **also open a `.qgz` saved by the published 1.1.9** (group `USA Imagery (optional)` must be renamed in place).
4. **BAT-01, 03, 05** (`01_*` D): launch from the menu and from the Toolbox; run 30+ links with pause 1 s and press **Cancel** (dialog and Task Manager); invalid-record copy (blank frequency, no-geometry row, 010047019-003) with and without fallback.
5. **DET-03**: open the real .xlsx export in Excel; no repair prompt; EVIDENCE sheet has no apostrophes. **BAT-11**: open a plugin-made batch CSV with `=1+1`/`@SUM(1)` in text fields (the Excel check on plugin files is already done for 5 of 6 files, see `09_*`).
6. **REG-01/02** with the online USA pack through the setup dialog (headless live load already worked); **REG-03** only if CelesTrak answers.

Everything else in `01_*` is covered by headless evidence in `09_*` or is S3.

## 6. After the gate passes (what I will do in one pass)
1. Fix any defect found, rebuild the acceptance ZIP, repeat only the affected checks.
2. One version bump (proposal: **1.1.10**, the version the 1.1.9 changelog already names for the stale-selection fix) in `metadata.txt`, `CHANGELOG.md` (rename "Unreleased"), README; exclude `docs/acceptance/` from the release ZIP or decide to ship it.
3. Stage all, review the staged diff, one commit, rerun unit + QGIS suites + `verify_package` + smoke on the committed tree, build the ZIP from that commit, record SHA-256.
4. Repository facts for the release: `main` is **not** branch-protected and I have push/maintain rights; CI (`ci.yml`) runs on PR and on pushes to main; `release-validate.yml` runs on a `v*` tag and publishes nothing; **uploading to plugins.qgis.org is a manual step with your OSGeo account**. I would open a PR (so CI runs before merge), merge only on green CI, tag `v1.1.10` once, let the validation workflow run, then hand you the verified ZIP and checksum for the plugins.qgis.org upload and create the GitHub release with the same ZIP.
