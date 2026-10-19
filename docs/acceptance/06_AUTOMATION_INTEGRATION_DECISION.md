# 06 — Decision record: `feat/automation-workflow-runs` is not integrated

Source of truth: `docs/FINALIZATION_STATUS.md` §3 and `tests/test_workflow_core_semantics.py` (both in the staged tree), the branch itself (`b10edd2`), `aei-workflow-runner` `origin/main` (0.1.1). **Nothing in the automation branch was rebased, merged, cherry-picked, wrapped or edited by this task.** The discrepancy below is reported as found; no test was weakened to hide it.

## Decision
Keep it **unintegrated**. It is not part of the candidate; the candidate contains only the terrain-only Processing batch.

## Facts that justify it
1. **Decision vocabulary differs from the plugin.** The workflow core (`aei_workflow.engine.analyze_link_row`) calls `analyze_link` and reports the library's three line-of-sight classes (`clear` / `marginal` / `obstructed`). The plugin decides with `core/presentation/terrain.py`: CLEAR / WATCH / AT RISK / CRITICAL with the near-threshold WATCH rule. On the same inputs and the same offline elevation, **the numbers are identical** (distance, clearance, required clearance, Fresnel radius), but of the 50 comparable parity links the plugin says WATCH for 2 where the workflow core says `clear`. (36 CLEAR/clear, 9 CRITICAL/obstructed, 3 AT RISK/marginal, 2 WATCH/clear.)
2. **NO DATA behaviour differs.** The plugin refuses invalid input (height outside 0.1–1000 m, frequency missing/outside range, unusable endpoints, unavailable elevation) as NO DATA with a reason and no numbers; the workflow core has no equivalent boundary — inputs the plugin refuses were excluded from the comparison for that reason.
3. **Provenance differs.** The plugin types frequency and heights Observed/Assumed (record value vs default/override, with source text); the workflow core's result carries no such typing.
4. **Stale base.** 6 commits ahead, 109 behind main when inspected; it predates the 1.1.5 decision contract (owner decision D-Q7). It also replaces `PARAM_SPEC` in `core/engines/terrestrial.py` with an import from the external package (values textually equal today, source of truth would move).
5. **Build/release process change.** It needs `aei_workflow` vendored into the ZIP by `tools/package.sh` from a sibling checkout (clean tree required); `aei-workflow-runner` is a separate package at 0.1.1 and is not a dependency of the released plugin.
6. **Overlap.** It and the Processing batch both run terrain batches.

## Evidence required before reconsidering integration
| Requirement | What must be shown |
|---|---|
| Shared decision semantics | A single mapping from the analysis result to CLEAR/WATCH/AT RISK/CRITICAL/NO DATA used by both single-link and workflow runs (the plugin's `terrain_status` or an extracted shared function); workflow rows store and display that status. A fixture test where **no** fixture differs (today: 2 of 50 do). |
| Matching missing-data behaviour | The workflow path applies the same input validation (bounds, frequency, endpoints, elevation availability) and produces NO DATA with the same reasons and `transient` flag as `core/batch.py`; a test over the parity NO DATA fixtures (e.g. `ca-h-height-zero`, elevation error fixtures). |
| Matching provenance | Frequency/height origin (Observed/Assumed + source text) recorded per row and equal to the single-link Evidence; test on fixtures with record heights, defaults and overrides. |
| Numeric and decision parity fixtures | All shared parity fixtures with terrain (more than 50) run through workflow, batch and single-link; exact equality on numbers (existing rule), identical decisions; results committed as a test, no tolerance added to make it pass. |
| Release/build compatibility | Reproducible `tools/package.sh` build with the vendored package at a recorded commit/version; `tools/verify_package.py` updated and PASS; `clean_install_smoke.py` passes on that ZIP; licence notice for the vendored Apache-2.0 code; a single batch UX story (Processing batch vs Automate dialog) approved by the owner. |
| Rebased automation tests | `tests/qgis_automation_e2e.py` rerun on current main, plus selection/lifecycle suites unchanged (all green). |

Smallest path (needs owner approval, not started): rebase, wrap `core.batch.analyze_one` as the workflow analyzer, store the plugin status next to the library class, rerun the above.
