# 07 — Evidence template (fill in during the session)

Companion file `07_results_template.csv` has one pre-filled line per test ID with the same columns as §2. Evidence lives outside the repository: `~/velorona-acceptance/<date>/<TestID>/`.

## 1. Session header
| Field | Value |
|---|---|
| Test date / start–end time (with time zone) | |
| Test operator | |
| QGIS version (Help ▸ About, copy "QGIS version" and build) | |
| Operating system and version, CPU architecture | |
| Python version in QGIS; library versions (`aei-link-clearance`, `aei-microwave-link-exposure`, `aei-geo-features`, `skyfield`) | |
| QGIS profile used (candidate / baseline) | |
| Candidate branch | `integration/qgis-finalization` |
| Candidate commit hash | *(not yet existing — fill in after the owner commits; or "uncommitted staged tree" + `git diff --cached \| shasum -a 256`)* |
| Plugin ZIP file name | *(fill in after build)* |
| Plugin ZIP SHA-256 | *(fill in after build; `shasum -a 256 <zip>`)* |
| `tools/verify_package.py` result | |
| Baseline ZIP (1.1.9) SHA-256 | `d255c5f68c98c98e2f5e97446c1942d7172a845f94a2199b96bd4646bd880164` (published; verify yours matches) |
| Test project identifier / path (disposable) | |
| Dataset identifiers (snapshot date 2026-09-01 for Canada; USA pack `generated_date`/`source_file_updated` from the setup window; candidate link ids used) | |
| Network conditions / live services reachable (Open-Meteo, ECCC, CelesTrak, GeoHub, map.velorona.ai) | |

## 2. Per-test result (one row per Test ID; copy as needed)
| Test ID | Status (Pass / Fail / Not run) | Expected result | Actual result | Evidence location (screenshot / log / export + SHA-256) | Defect severity (S1/S2/S3/—) | Reproduction steps (if not Pass) | Follow-up action / owner |
|---|---|---|---|---|---|---|---|
| INS-01 | | | | | | | |

Rules: *Pass* only when the expected result is observed in full; *Not run* needs the reason (missing prerequisite, service down) and never counts as Pass; a difference you cannot explain is a Fail.

## 3. Exceptions accepted by the product owner
| Test ID | Reason it cannot pass / is not run | Risk | Accepted by (name) | Date |
|---|---|---|---|---|

## 4. Gate decision (from `05_*`)
| Criterion R1…R10 | Met (Y/N) | Evidence / test IDs |
|---|---|---|
| R1 … R10 | | |

Outcome: ☐ Advance to release review ☐ Do not advance. Reviewer / date / signature: ______

## 5. Defect record
| Defect ID | Test ID | Severity | Title | Environment (QGIS, OS, profile) | Steps to reproduce | Expected | Actual | Evidence | Environment issue or product defect? | Status |
|---|---|---|---|---|---|---|---|---|---|---|

## 6. Batch-vs-single table
Use the table and per-field sheets in `02_BATCH_VS_SINGLE_PARITY_PROTOCOL.md` §6.
