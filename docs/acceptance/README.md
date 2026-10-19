# Human acceptance package — Velorona for QGIS candidate

Prepared 2026-10-18. Documentation only: no application code, test or staged file was changed to produce it (see `08_GIT_STATE_COMPARISON.md`). These files are **untracked** on purpose.

**Update 2026-10-19:** the candidate is now version 1.1.10 on branch `integration/qgis-finalization` (one consolidated commit on top of `905d9e4`); the release ZIP is built from that commit (`~/velorona-acceptance/release-1.1.10/`, commit hash and SHA-256 in the pull request). Desktop acceptance (`11_*`) has still not been performed; merge, tag and release wait for it. The text below was written for the earlier 1.1.9 acceptance candidate and is kept as the audit trail.

Originally: baseline tag `v1.1.9` (`905d9e4119829a122f7cd990e5a3de8d96d2cb66`), 28 staged files, not committed, not built, not released.

| File | Content |
|---|---|
| `01_HUMAN_ACCEPTANCE_CHECKLIST.md` | Ordered test cases A–G (install, selection/lifecycle, batch, details/exports, regression) |
| `02_BATCH_VS_SINGLE_PARITY_PROTOCOL.md` | Controlled batch-vs-single-link comparison, tolerance rules, candidate links, results table |
| `03_CLEAN_INSTALL_AND_PROJECT_REOPEN.md` | Clean-profile install and saved-project reopening, step by step |
| `04_TEST_INVENTORY_AND_COVERAGE_GAPS.md` | Existing automated tests, what was rerun today vs only reported earlier, coverage gaps with the smallest added test |
| `05_RELEASE_ACCEPTANCE_CRITERIA.md` | Gate for advancing to release review |
| `06_AUTOMATION_INTEGRATION_DECISION.md` | Why `feat/automation-workflow-runs` is not integrated and what evidence would change that |
| `07_EVIDENCE_TEMPLATE.md` | Session header, per-test result table, defect template |
| `08_GIT_STATE_COMPARISON.md` | Git state before and after the preparation task (a later session changed CSV safety and docs; see 09) |
| `12_PROFILE_SETUP_FA.md` | راه‌اندازی پروفایل جداگانه QGIS (فارسی) |
| `11_DESKTOP_ACCEPTANCE_PACK.md` | One ordered 1–2 hour desktop checklist (start here) |
| `10_ACCEPTANCE_BUILD_AND_GATE.md` | Temporary acceptance ZIP (SHA-256), reruns of 2026-10-19, the one remaining human gate, and the release plan after it |
| `09_EXECUTED_EVIDENCE_2026-10-18.md` | What was actually executed (live batch-vs-single parity, real-export CSV checks in Excel, USA live load, satellite attempt) and what is still open |

## Main acceptance risks
1. **Nothing here has been seen in a real QGIS window.** All 5 UI fixes and the batch tool were verified headless (offscreen Qt, stand-in `iface`). The Layers-panel click path, the Select Features map tool, overlapping features, the Processing dialog's Cancel button and the Task Manager are the first things a human must confirm.
2. **Batch cancellation and invalid-record handling through the real Processing framework** are not automated (only through the core callback): see gap list.
3. **Live services** (Open-Meteo elevation and weather, ECCC, CelesTrak, Ontario GeoHub, the online USA pack) may rate-limit (HTTP 429) or be down; that produces NO DATA, which is an environment result, not a defect, but must be recorded and retried.
4. **Project reopening**: Velorona's layers are in-memory layers; QGIS only restores them if the project is saved with the memory layer content (a QGIS prompt). Expect to test what QGIS actually restores, not a design assumption.
5. **Candidate not built**: the ZIP under test must be built from the staged tree (`tools/package.sh`, then `tools/verify_package.py`) and its SHA-256 recorded before testing.
6. (Resolved after this package was written) the stale "had not been run" statements in `docs/BATCH_TERRAIN.md` and `CHANGELOG.md` were corrected, and CSV formula injection was fixed (`core/csvsafe.py`); both changes are unstaged. See BAT-11.
