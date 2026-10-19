# 08 — Git state before and after this preparation task

Captured with read-only git commands (`branch`, `rev-parse`, `status`, `diff --cached`, `ls-files`, `write-tree`). Nothing was staged, unstaged, reset, stashed, committed, pushed, merged, tagged, published or deployed; branch and worktree were not switched.

| Item | Before | After |
|---|---|---|
| Branch | `integration/qgis-finalization` | same |
| HEAD | `905d9e4119829a122f7cd990e5a3de8d96d2cb66` | same |
| Staged files | 28 (2115 insertions, 62 deletions) | same 28 |
| SHA-256 of `git diff --cached` | `3b9a85b269da1b9c9288f17e81971443cecf7aaa7db0168ca9e8d37835892ad3` | identical |
| Index tree (`git write-tree`) | `fa1e87c627c5410f59464b02ad33b3ffa9e7b0c1` | `fa1e87c627c5410f59464b02ad33b3ffa9e7b0c1` |
| Unstaged changes | none | none |
| Untracked files | none | `docs/acceptance/` (9 new files: README, 01–07 incl. `07_results_template.csv`, and this file, added after the capture) |

`diff before.txt after.txt` differs only by the new untracked files.

Staged files (unchanged): CHANGELOG.md, README.md, core/batch.py, core/imagery.py, core/layers.py, core/presentation/terrain.py, core/presentation/workbook.py, core/processing/{__init__,provider,terrain_batch}.py, docs/{BATCH_TERRAIN,FINALIZATION_STATUS,UI_INTEGRATION_AUDIT}.md, metadata.txt, plugin.py, tests/{README.md,clean_install_smoke.py,qgis_batch_e2e.py,qgis_e2e.py,qgis_selection_sync_e2e.py,qgis_workflow_e2e.py,run_qgis_tests.sh,test_presentation_terrain.py,test_satellite_reliability.py,test_terrain_batch.py,test_workflow_core_semantics.py}, tools/verify_package.py, ui/records_table.py.

No application code, test, metadata or version number was modified. Test reruns used a scratch copy outside the repository and disabled bytecode writing.
