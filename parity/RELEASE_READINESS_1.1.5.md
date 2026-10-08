# P0_RELEASE_READINESS — Velorona 1.1.5 (Map + QGIS) and the `aei-link-clearance` dependency

Review date 2026-10-08. Read-only review: no product behaviour changed, no commits, nothing pushed, tagged, packaged, published or deployed. Tags: **PASS** (evidence shown) · **OPEN** (unresolved, not blocked by an approval) · **BLOCKED** (cannot proceed without an external step or owner approval) · **DEFERRED** (consciously out of the P0 scope).
Evidence labels: OBSERVED (read in code/data/run), INFERRED (reasoning), UNKNOWN. Three online *read-only* queries were made and are named where used (PyPI JSON API, GitHub release list, plugins.qgis.org `plugins.xml`, Open-Meteo pricing page). No upload, no install into any environment, no registry write.

---

## QGIS 1.1.5 RELEASE-CANDIDATE STATUS (updated 2026-10-08, supersedes the QGIS rows below where they differ)
Repo `aei-microwave-link-exposure`-side plugin, branch `release/1.1.5` (pushed). Library `aei-link-clearance` **0.2.0 is published and verified on PyPI**. Not merged, tagged, packaged for release, published or deployed.

| Gate | Tag | Evidence |
|---|---|---|
| Plugin consumes released library | **PASS** | `requirements.txt` `aei-link-clearance>=0.2.0,<0.3`; sibling-checkout fallback removed from tests/parity; first terrain analysis refuses an older library (`LibraryOutOfDateError`) |
| Unit suite (clean venv, released 0.2.0) | **PASS** | 186 passed |
| QGIS E2E (real QGIS 4.2.2, released 0.2.0) | **PASS** | 483/483, 1 skip (CelesTrak, live service). Supersedes "BLOCKED" in §D |
| Canada P0 parity (shared fixtures, Map as oracle) | **PASS** | 34 fixtures, 0 problems |
| Provenance divergence (frequency Observed in Map vs Assumed in QGIS terrain flow) | **PASS, accepted limitation** | `parity/ACCEPTED_INTERFACE_DIVERGENCES.md` AID-1; checker fails on any other divergence (29 occurrences, all AID-1) |
| Clean install from the 1.1.5 zip, fresh profile, repo off sys.path | **PASS** | 36/36; zip excludes parity/tests/tools |
| Defect found and fixed in this phase | **PASS** | deterministic NO DATA (e.g. sub-GHz link) was cached as a transient "unavailable a moment ago"; now `transient` flag, unit + E2E tests |
| Flake8 / Bandit | **PASS vs baseline** | flake8 28 findings = release/1.1.4 baseline (no new); Bandit clean |
| Version / changelog | **PASS** | `metadata.txt` 1.1.5, README updated |
| Plausibility (167 real links, assumed 30 m heights) | **OPEN, NOT a validation** | CRITICAL 17/167 (10.2 %) vs 5.4 % before correction; placeholder heights; ISED column 29 height-like but meaning unverified. No severity claim made |
| Physics beyond curvature sign (Fresnel, k, thresholds, DEM, rain model, WATCH 1.3) | **OPEN** | provisional; README validation table predates correction, not re-run |
| P10 wording, signed fade-remaining, spec §G export fields | **DEFERRED** | |
| R1, R2, R6, R7, R8 | **DEFERRED** | unapproved, inert |
| Map: xss second-badge regression, stale public text (index.html, faq.json, app.html), data_flow/csp pre-existing failures, Map deploy | **OPEN** (Map side) | not part of QGIS 1.1.5 |
| flake8 baseline findings (28) | **OPEN** (pre-existing) | |
| plugins.qgis.org lists 1.1.2 while README says GitHub Release distribution | **OPEN** | owner decision on channel |
| Optional startup version check (guard fires at first analysis only) | **DEFERRED** | |
| Merge `release/1.1.5`, tag `v1.1.5`, GitHub Release, zip upload, plugins.qgis.org | **BLOCKED** | needs owner approval; none done |

---


## A. P0 implementation status
Branches `parity/1.1.5-p0` (Map `f65609c`, QGIS `b8a7368`), local only.

| Item | Map | QGIS | Tag |
|---|---|---|---|
| Fixture recalibration, independent check, synthetic-boundary set | `fa4cd1e` | `dd5cb00` | **PASS** |
| P11 earth-curvature sign | `808c84e` (in-tree library `terrain.py` + `web/linkmath.js`) | `b2e59ec` (guard; library untouched) | **PASS** in Map; **BLOCKED** for QGIS (needs a published library, §G) |
| NO DATA (R3, R4, R5, R9, T1–T3, frequency) | `7c1fd4d` | `3faf148` | **PASS** |
| Precipitation classes + frozen ×4 conversion | `e4466e7` | `1bfb3a8` | **PASS** (R1/R2 deliberately inert) |
| Provenance five classes | `abcdf9d` | `22b0805` | **PASS** (R6 untouched) |
| Status model, near-threshold as a flag, worst-of | `bfb1efc` | `b8a7368` | **PASS** for status; P10 wording and margin display **DEFERRED** (§I) |
| Browser-check stubs + plausibility script | `f65609c` | – | PASS |

## B. Canonical parity status — **PASS**
OBSERVED (`results/PARITY_REPORT.md`, 34 fixtures = 21 real-link + 13 synthetic-boundary): both products match the spec oracle on **every stage** (clearance, terrain status, precipitation rate and class, weather status, overall, NO DATA) for all 34. The only Map-vs-QGIS difference is pairwise provenance on 29 fixtures: QGIS's terrain flow cannot carry "frequency came from the record" and types it Assumed (§4, option table). Oracle validity: independent spherical-chord check, largest per-sample disagreement **0.0101 m** (203 km); frozen `expected` blocks equal the oracle on all 34; input hashes unchanged.

## C. Test status
| Suite | Baseline (Step 0) | Final | Tag |
|---|---|---|---|
| Map (pytest incl. node-run JS tests, `PYTHONPATH` sibling libs) | 626 passed | **665 passed** | PASS |
| QGIS unit tests (no QGIS) | 107 passed | **181 passed** | PASS |
| `tools/check_qt6_enums.py` | – | "no unscoped Qt/QGIS enum access found" | PASS |
| Pre-existing failures at baseline | none in either suite | | – |
| `tests/qgis_e2e.py` (real QGIS) | not run | **not run** | **BLOCKED** (see D) |
| `tests/benchmark_viewport.py`, `tests/clean_install_smoke.py` | not run | not run | OPEN (release-time) |
| Flake8 / Bandit (the plugin repository scan used them for 1.1.1, 1.1.4) | – | **not installed here, not run** | OPEN |

Tests I changed because the behaviour they encoded was superseded by an owner decision (not to make them pass): old curvature sign (2 QGIS tests), total-as-rain and near-threshold-as-WATCH (QGIS), four-type enumerations and the single `Rain rate along the path` row (Map), `interval` added to Open-Meteo stubs (R3), documented-row count in the output spec.

## D. Browser-check status (Map, real Chromium via the Playwright copy under `Downloads/aidedge-velorona-web`)
| Check | Result | Tag |
|---|---|---|
| integration 57/57 · history 33/33 · context 15/15 · remediation 101/101 · llm 28/28 · us_pack 24/24 · ca_provenance 3/3 | pass (context, remediation, llm, us_pack only after adding `interval` to their Open-Meteo stubs — R3) | PASS |
| **xss_browser_check** | **42/43. FAIL "sample import: drawer title shows id and badge".** The check requires exactly one `.status-badge` in the drawer title; my change adds a second badge ("Near threshold: verify") for near-threshold results. **Baseline passes 43/43** (run from `git archive 974b882`). A regression caused by P0, decision needed: relax the assertion or change the design. Not changed (no new implementation cycle). | **OPEN** |
| data_flow_check | `TypeError … reading '__note'` — **identical on the baseline**. Pre-existing, cause UNKNOWN (not investigated). Needs `python3 -m http.server --directory web` + `PLAYWRIGHT_MODULE=…`; earlier "not run" was my wrong env var. | OPEN (pre-existing) |
| csp_browser_check | same `__note` TypeError on current **and** baseline. Needs `wrangler pages dev` (run from a `git archive` copy so no `.wrangler` state touched the repo; `.wrangler/` in the repo predates me, Sep 25, and is git-ignored). | OPEN (pre-existing) |
| **qgis_e2e.py** | Not run. Needs the QGIS 4.2.2 app (present) + live public services + **a QGIS Python that has the corrected library**. The QGIS Python here has `aei-link-clearance 0.1.0` from `file://…/velorona-repos/aei-link-clearance` without the marker (OBSERVED: `CLEARANCE_CONVENTION` absent, `~/.local/lib/python3.12/site-packages`), so `terrestrial.analyze()` at `tests/qgis_e2e.py:282` would raise `LibraryOutOfDateError`. Also line 667–668 asserts the export Type vocabulary is exactly Observed/Model-derived/Calculated/Inferred; the link export now also contains Assumed (INFERRED from reading — not run). | **BLOCKED** (release-blocking: it is the only test of the real plugin) |

## E. Physics validation status
* **PASS (scope: the sign of the earth-curvature term only).** Independent straight-chord geometry vs corrected code: 9 cases (38.1 km review case + 8 real-link fixtures, 0.6–203 km); critical-sample difference ≤ 2 mm; all-sample maximum 10.1 mm at 203 km (parabolic bulge vs exact trigonometry). Reproducible: `stage1/earth_bulge_review.py`, `parity/independent_check.py`.
* **OPEN (not validated, stated plainly):** Fresnel formula, k = 4/3, the 0.60/0.30 thresholds, the DEM (GLO-90 is a surface model), the ±15 m near-threshold basis, the rain model, and the provisional 1.3 threshold. No external-standard citation for the sign was obtained. The README's uptowhere.com validation table was produced **before** the correction (cases 2 and 3 are on a 14 km path; the bulge there is ≈3 m so their verdicts could shift by up to ≈6 m); it carries a note but was not re-run. Recommended before any "validated" wording: re-run those three cases against the external tool.

## F. Plausibility status — **OPEN (gate not passed, not failed)**
OBSERVED facts, recorded without spin:
* Sample: seeded `random.Random(20261008)`, 200 of 16,956 links; real elevations for **167** (33 unresolved, §3d). Terrain only, **assumed 30 m antenna heights** at both ends, highest published frequency.
* Corrected distribution (167): CLEAR 141 · WATCH 2 · AT RISK 7 · CRITICAL 17 (10.2 %); near-threshold flag on 53. Same elevations, pre-correction: CRITICAL 9 (5.4 %), AT RISK 1, WATCH 1, CLEAR 156.
* **The 10.2 % is NOT a validated real-world severity rate.** It depends on a placeholder height that is not in the data used by either product. No code, fixture or elevation was altered to move it.
* Section 3 below: heights *do* exist upstream; a pilot with them (semantics unverified) gives CRITICAL 4 of 167 (2.4 %). That is also not a severity claim.

## G. Library dependency (section 1 of the brief, all from the repos)

### G.1 What `aei-link-clearance` is — OBSERVED
There are **two source trees with the same package name**, functionally identical but not the same repo:
| | Map repo (`velorona-map`, remote `AIDEdgeInc-Lab/velorona-map`) | Standalone repo (`AIDEdgeInc-Lab/aei-link-clearance`, local `aei-link-clearance-standalone`) |
|---|---|---|
| Path | `src/aei_link_clearance/` (+ `pyproject.toml` name `aei-link-clearance` 0.1.0) | `src/aei_link_clearance/`, `dynamic` version from `__init__.__version__ = "0.1.0"` |
| Role | in-tree copy ("internal engineering"); the Map's JS mirror (`web/linkmath.js`) is tested against it | the **public package**: tag `v0.1.0`, GitHub Release `v0.1.0` (2026-09-24), `.github/workflows/{ci,publish}.yml`, `CHANGELOG.md`, `dist/` |
| Difference | code identical; only comments/docstrings differ (internal "Phase 0/1" wording, "UI copy"); the standalone adds `py.typed` and an Open-Meteo licensing notice in `elevation.py` | |

* **Map web app consumes:** no Python at all. It ships a hand-written JS mirror (`web/linkmath.js:1-5`); the Python copy is used only by tests (`tests/test_web_automation_parity.py` imports it) and `examples/basic_usage.py`.
* **QGIS plugin consumes:** the *installed* package `aei_link_clearance` imported from QGIS's own Python (`core/engines/terrestrial.py:9-10`, `:82`).
* **Corrected curvature lives only in the Map repo's in-tree copy** (`808c84e`, `7c1fd4d`). **The published package and the standalone repo do not have it.**

### G.2 How QGIS resolves it — OBSERVED
* **Unpinned, not vendored, not bundled.** `requirements.txt:3` `aei-link-clearance`; `core/dependencies.py:13` `("aei_link_clearance", "aei-link-clearance")`; `README.md:72-73` `pip install … aei-link-clearance …` into QGIS's Python 3.12. `dependencies.py:20-29` checks only that the module is importable (`find_spec`), never a version.
* **Not in the zip:** listing of `dist/velorona-1.1.4.zip` contains `core/ ui/ data/ docs/ examples/ plugin.py metadata.txt requirements.txt README.md LICENSE` — no `aei_*`, no wheels.
* **This machine's QGIS Python:** `aei-link-clearance 0.1.0`, `INSTALLER pip`, `direct_url.json` = `file:///Users/aidedgeinc./velorona-repos/aei-link-clearance` (an install **from the Map repo directory**, not from PyPI); its `terrain.py` is byte-identical to Map `de2a870`. `aei-microwave-link-exposure 0.1.4`, `aei-geo-features 0.1.4`, `skyfield 1.55`.

### G.3 Is it published? — verified (online, read-only)
* **PyPI:** `aei-link-clearance` has exactly one release, **0.1.0** (wheel + sdist uploaded 2026-09-24T14:16–14:17). I downloaded the wheel: sha256 matches PyPI's record; its `terrain.py` is **identical to the standalone repo's** and has the **old sign and no `CLEARANCE_CONVENTION`**. The wheel in the standalone `dist/` has a different sha256 (rebuilt; same source).
* **GitHub:** release `v0.1.0` "Latest" in `AIDEdgeInc-Lab/aei-link-clearance` (via `gh`, read-only).
* `metadata.txt:35` claims "aei-link-clearance is now published on PyPI" — now confirmed, but that line alone was not evidence.

### G.4 Commit that contains the correction — OBSERVED
* `808c84e` "terrain: subtract effective-earth bulge from geometric clearance (P11)": `src/aei_link_clearance/terrain.py` (sign `terrain_adjusted = ground_elev + bulge` at line 179, docstring, `ProfilePoint` comment, `CLEARANCE_CONVENTION = "bulge-added-to-terrain"` at line 49), `web/linkmath.js`, `README.md`, `tests/test_curvature_convention.py`, `parity/compare.py`.
* `7c1fd4d` (NO DATA) also changes the library: `src/aei_link_clearance/elevation.py` adds `ElevationDataError(ValueError)` (line 20) and rejects null/NaN/infinite/non-numeric/boolean elevations (line 56). **The QGIS plugin imports `ElevationDataError` (`terrestrial.py:82`), so it needs both commits' library changes, not only the sign.**
* Dry run in `/tmp` (standalone repo copied, the two corrected files overlaid): **35 passed before and after** — the standalone's own tests do not pin sign-dependent numbers.

### G.5 Every consumer — OBSERVED
| Consumer | How | Affected by a new library release |
|---|---|---|
| QGIS plugin | imports `analyze_link`, `explain`, `terrain`, `elevation.ElevationDataError` | yes — requires the correction (guard) |
| Map web app | none (JS mirror) | no, but must keep `linkmath.js` in step |
| Map tests/examples | `tests/test_web_automation_parity.py`, `tests/test_curvature_convention.py`, `examples/basic_usage.py`, parity harness (sibling `src` path) | use the in-tree copy |
| `aei-workflow-runner` (`feat/initial-shared-core`) | `pyproject.toml:22` `aei-link-clearance[elevation]>=0.1.0`; records `analysis_engine.aei-link-clearance` version in every run and compares runs by it (`tests/test_automation_compare.py:59-62`) | yes — would pick up 0.2.0 silently; its version-change detection will flag it, which is the desired behaviour |
| `_worktrees/*`, `_ui-work/*` | older checkouts of the same repos | no action |
| Docs | QGIS `core/presentation/registry.py:41-53` data dictionary names library functions; README text | wording only |

### G.6 The QGIS guard — OBSERVED
`core/validation.py:12` `REQUIRED_CLEARANCE_CONVENTION = "bulge-added-to-terrain"`; `:19-25` `require_corrected_clearance(terrain_module)` reads `getattr(terrain_module, "CLEARANCE_CONVENTION", None)` and raises `LibraryOutOfDateError` if it differs. Called first thing in `terrestrial.analyze_endpoints` (`terrestrial.py:75`).
Exact message: *"The installed aei-link-clearance uses the pre-correction earth-curvature sign (CLEARANCE_CONVENTION=None, required 'bulge-added-to-terrain'). Terrain clearance would be overstated by twice the earth bulge. Upgrade aei-link-clearance to a release that contains the correction."*
Limits (OBSERVED/INFERRED): it fires **at the first terrain analysis, not at plugin start** (`dependencies.py` is presence-only), so a user with 0.1.0 sees a working plugin that errors on terrain; it is a marker check, so any future library that keeps the marker but changes behaviour again would pass; the weather path needs no guard (own provider).

### G.7 Packaging reality — OBSERVED
`tools/package.sh` (lines 31-44) tars the plugin directory excluding only `.git .gitignore __pycache__ *.pyc .pytest_cache .DS_Store dist tests tools SESSION_HANDOFF.md .github CONTRIBUTING.md`. It builds `dist/velorona-<version>.zip` from `metadata.txt` `version=`. **It does not exclude `parity/`** (300 KB, 38 files incl. `runner_qgis.py`, which installs a fake `qgis.core`) — **the corrected-code zip would ship the harness**. It does not bundle any library, so the correction would reach users only through `pip install`. The README (line 97-100) says the plugin is distributed via GitHub Release and "not yet submitted" to the QGIS repository; `plugins.xml?qgis=4.0` (online, read-only) lists **Velorona 1.1.2** (`velorona.1.1.2.zip`, updated 2026-09-24) — so 1.1.3/1.1.4 appear to be GitHub-only and the README is out of date. Nothing was built.

### G.8 Dependency release plan (ordered; exact files)
Source of truth for the public package is the **standalone repo**; the Map in-tree copy is not what PyPI/QGIS users get.
1. **[owner decision] Where to release from.** Recommended: port the two changed files into the standalone repo by hand (the overlay dry run proves compatibility, but a straight copy would leak internal wording such as "Velorona QGIS plugin" into a repo whose public text was scrubbed). Do **not** publish from the Map repo.
2. Standalone repo `AIDEdgeInc-Lab/aei-link-clearance`, branch `fix/earth-curvature-sign`:
   * `src/aei_link_clearance/terrain.py`: `terrain_adjusted = ground_elev + bulge`; fix `earth_bulge_m` docstring and the `ProfilePoint` comment; add `CLEARANCE_CONVENTION = "bulge-added-to-terrain"` (public wording).
   * `src/aei_link_clearance/elevation.py`: `import math`, `ElevationDataError(ValueError)`, `_is_finite_number`, the finite-number check (keep the standalone's licensing notice).
   * `src/aei_link_clearance/__init__.py:22` `__version__ = "0.2.0"`; optionally export `ElevationDataError`.
   * `CHANGELOG.md`: entry below. `README.md` lines 63–72: the validation table predates the correction — footnote or re-run.
   * tests: add `tests/test_curvature_convention.py` and `tests/test_elevation_no_data.py` (from the Map repo; adjust imports).
   * CI (`ci.yml`, Python 3.9–3.12) must pass.
3. **TestPyPI** via `publish.yml` `workflow_dispatch` `target=testpypi` (publishes to the *test* index). Verify in a throwaway venv: `CLEARANCE_CONVENTION == "bulge-added-to-terrain"`, 38.1 km flat case = 8.648 m. Re-run the QGIS parity harness against the installed wheel instead of the sibling `src` (harness currently prepends `…/aei-link-clearance/src`).
4. **PyPI 0.2.0** via a published GitHub Release (`release: published`); the `pypi` environment pauses for a required reviewer. **Irreversible** (a version can be yanked, never re-used or edited).
5. QGIS repo: `requirements.txt:3` and `core/dependencies.py:13` → `aei-link-clearance>=0.2.0,<0.3`; `README.md:72-73` install line; `core/validation.py:25` message names the minimum version; `tools/package.sh` add `--exclude='parity'`; `metadata.txt` `version=1.1.5` plus a rewritten changelog (line 15 of the 1.1.4 entry — "labelled total precipitation" — is now false). Optional, small: make `core/dependencies.py` also read the marker so the failure is shown at start-up instead of at first terrain analysis.
6. On the QGIS machine: upgrade the library in **QGIS's Python** (`…/MacOS/python3.12 -m pip install -U 'aei-link-clearance>=0.2.0'`; today it is a `file://` install of the Map directory), update `tests/qgis_e2e.py:667-668` to five types, run `tests/run_qgis_tests.sh`.
7. Map: keep `src/aei_link_clearance` only as a test reference, or add a test asserting functional equality with the released package, to stop the two trees drifting (they already differ in comments).
8. `aei-workflow-runner`: no code change; its stored-run comparison will report the engine version change.

**Version recommendation: `0.2.0` (minor).** The package is pre-1.0 and classified Alpha, where a minor bump is the conventional signal for a result-changing release. A **patch** (0.1.1) would tell consumers "same behaviour, a bug fixed" — but every `clearance_m`, `terrain_clearance_m`, `percent_fresnel_clear`, `los_status`, `near_threshold` and the meaning of `terrain_adjusted_m` change, and consumers pin `>=0.1.0` (`aei-workflow-runner`). A **major** (1.0.0) would promise API stability the project has not made; no function signature changes (new names only: `CLEARANCE_CONVENTION`, `ElevationDataError`, a subclass of `ValueError`). Bound consumers with `>=0.2.0,<0.3`.

### G.9 Draft changelog entry (NOT committed) — for operators
> **aei-link-clearance 0.2.0 — terrain clearance is now calculated correctly over long paths (results change)**
>
> **What changed.** The earth's curvature was being applied in the wrong direction: it *added* clearance instead of removing it. Clearance numbers were therefore too optimistic by **twice the earth bulge**, and corrected values are lower. Fresnel-zone size, the 60 % and 30 % limits, the k = 4/3 factor, elevation sampling and the elevation source are unchanged.
>
> **How much, and which links.** At the middle of a path the correction is **D² ÷ (4·k·R)** metres for a path of D km (k = 4/3, R = 6371 km): about **1 m at 6 km**, **5 m at 13 km**, **15 m at 23 km**, **43 m at 38 km**, **294 m at 100 km**. Paths under ~6 km barely change. Longer paths on flat or gently rolling ground, with lower masts, move the most and can change from CLEAR or WATCH to AT RISK or CRITICAL. A 38.1 km path over flat ground with 30 m masts now shows 8.6 m of clearance at its tightest point, not 51.4 m.
>
> **Why.** Checked against an independent straight-line geometry on an effective-radius earth (agreement to 0.01 m on every tested path from 0.6 to 203 km). This confirms the direction of the curvature term only; it is not a validation of the whole propagation model.
>
> **Scale on real data (computed, not measured outcomes).** On the Canadian ISED snapshot, the mid-path change is at least 15 m on 22.9 % of links and at least the required clearance on 37.2 %. How many of them actually change *status* depends on antenna heights and terrain; we have **not** validated a real-world rate, and this entry does not claim one.
>
> **Also in 0.2.0.** Missing, null, NaN, infinite or non-numeric elevations from the elevation service now raise `ElevationDataError` (a `ValueError`) instead of being used. New constant `CLEARANCE_CONVENTION`. `terrain_adjusted_m` is now ground elevation **plus** bulge.
>
> **Action.** Re-run any saved analysis; results from 0.1.x for paths longer than ~10 km should not be compared with 0.2.0 results.

## H. Remaining release blockers (ordered)
1. **BLOCKED — corrected library not published.** QGIS cannot run terrain analysis on any published library (PyPI 0.1.0 has the old sign; guard refuses it). Needs §G.8 steps 1–4 (owner approval for the PyPI release).
2. **OPEN — two library source trees.** Decide the source of truth (§G.8 step 1) before porting.
3. **BLOCKED — `qgis_e2e.py` not run** (needs corrected library in QGIS's Python; one assertion already stale).
4. **OPEN — plausibility gate.** Confirm the ISED height field's meaning, then run on a larger stratified sample (§3). No operator-facing severity statement before that.
5. **OPEN — `tools/package.sh` would ship `parity/`.**
6. **OPEN — xss_browser_check regression** (second badge) — owner/dev decision.
7. **OPEN — stale operator-facing text** (§4 addendum): public home page + FAQ JSON-LD, app disclaimer, README, QGIS `docs/OPERATIONAL_OUTPUT.md`, `metadata.txt` changelog.
8. **OPEN — Flake8/Bandit not run** (the repository scan used them).
9. **DEFERRED but owner should confirm it is not a blocker:** Map P10 wording (still "% above minimum"), fade-remaining and metre-margin display, export contract fields (§I).
10. **OPEN (pre-existing)** — data_flow and csp browser checks fail on the baseline too.
11. **OPEN** — provenance divergence policy (§4).
12. **UNKNOWN** — whether 1.1.3/1.1.4 were ever uploaded to plugins.qgis.org (listing shows 1.1.2; README says not submitted).

## I. Deferred scope
R1, R2, R6, R7, R8 (not implemented, not decided). Map P10 (metre-first wording, `explain.js` unchanged) and signed fade-remaining display; canonical-status columns in Map CSV/GeoJSON/automation exports; spec §G export fields (rule id, spec/library versions, raw weather fields, interval); using ISED antenna heights in either product (needs a snapshot schema change in both); QGIS terrain frequency-origin channel; startup version check; US pack (no USA work was done).

## J. Ordered actions before QGIS 1.1.5 can be tagged/packaged, and before Map can be deployed
**⚠ = irreversible or externally visible → needs owner approval.**
Library:
1. (owner) choose source of truth; 2. port + tests + changelog in standalone repo (local branch); 3. ⚠ push that branch / open PR; 4. ⚠ publish **TestPyPI** (test index; versions immutable there too); 5. verify wheel + parity harness against it; 6. ⚠ **IRREVERSIBLE: GitHub Release `v0.2.0` → PyPI 0.2.0**.
QGIS:
7. edit `requirements.txt`, `core/dependencies.py`, `README.md`, `core/validation.py` message, `tools/package.sh` (`--exclude='parity'`), `metadata.txt` (version + changelog); 8. fix `tests/qgis_e2e.py:667-668`; 9. upgrade the library in QGIS's Python; run `tests/run_qgis_tests.sh` (e2e), install Flake8/Bandit and run them; 10. update stale docs (`docs/OPERATIONAL_OUTPUT.md:25,88`); 11. `tools/package.sh` → `dist/velorona-1.1.5.zip` and clean-profile install test; 12. ⚠ merge/push branch to the plugin repo; 13. ⚠ **IRREVERSIBLE: tag `v1.1.5` push + GitHub Release**; 14. ⚠ **IRREVERSIBLE: plugin upload to plugins.qgis.org** (resolve the 1.1.2/1.1.3/1.1.4 question first).
Map:
15. merge `parity/1.1.5-p0` with `origin/main` (OBSERVED: local `main` de2a870 is **8 commits behind** recorded `origin/main` b1049a6; `git merge-tree` shows no conflicts; overlapping files `web/app.js`, `web/style.css`, `tests/js/remediation_browser_check.js`); 16. fix stale text in `content/faq.json` (source of `web/index.html:62,469`) and `web/app.html:443-444`, `README.md:46-49`; 17. resolve the xss assertion; 18. re-run pytest + the 7 passing browser checks + xss; 19. ⚠ push branch / PR; 20. ⚠ **Preview** deploy (Direct Upload, non-production) and review; 21. ⚠ **Production** deploy to map.velorona.ai (manual `wrangler`, per project practice) — reversible by redeploying a previous build but publicly visible, so approval-gated; `functions/api/agent.js` ships with it (its type list changed).

---

## Section 3 (brief) — Plausibility gate: options, with evidence
**3a. Do the Canadian data contain antenna height?** 
* **The shipped snapshot: no.** `web/fixed_service_snapshot.json` fields — links: `authorization_number, site_a_id, site_b_id, licensee, in_service_date, frequencies_mhz`; sites: `id, latitude, longitude, location_description, call_signs, authorizations, frequencies_mhz, roles, licensees, province, in_bbox`. Fill rate of any height/elevation/antenna/tower field: **0 of 16,956 links, 0 of 24,859 sites**.
* **The raw ISED extract (`~/velorona-backups/ised-raw/TAFL_LTAF_Fixe-2026-09-01.zip`, 109,292 rows × 61 columns): yes, height-like columns exist and are not read by the builder** (`scripts/build_ca_fixed_snapshot.py:10-14` uses columns 0, 1, 31, 33, 39, 40, 41, 47, 51, 52, 54 only). Candidates (0-based, as the builder numbers them): **col 28** — 100 % filled, 0–600, median 39, 1,487 distinct; **col 43** — 99.7 %, 1–555.3, median 55 (max resembles the CN Tower); **col 42** — 99.9 %, 0–2,407, median 301 (looks like ground elevation). Computed per link endpoint over all 16,956 links: col 28 present at **both endpoints on 16,956 (100 %)**, within the products' 0.1–1000 m bounds on **16,952 (99.98 %)**, ≤ col 43 in **99.2 %** of rows, median **38.7 m** (p5 11.0, p95 88.0), only **4.9 %** of endpoint values equal the 30 m default; 1,172 links have an endpoint with more than one distinct value (several antennas); col 43 usable on 16,939 (99.90 %).
* **UNKNOWN / UNVERIFIED:** what these columns *mean*. The ISED layout for `TAFL_LTAF_Fixe` was not obtained (the PDF I fetched is the *Terrestrial Spectrum Licence* extract, A–BI, with different columns: its "Structure Height [m]" and "TX/RX antenna height [m]" exist there, but its layout does not match this file, whose column 0 is TX/RX). Column meaning, AGL vs ASL, and which antenna a multi-value endpoint should use must be confirmed against ISED's "SMS Authorization Data Extract – Field Descriptions" or ISED itself. The mapping above is from value profile, the builder's column map and position only.

**3b. Design for the subset run (not executed beyond the small check below).** Usable subset = links with both endpoints in [0.1, 1000] m on the confirmed column (16,952 on the candidate). Run: stratify by distance band (<5, 5–20, 20–50, ≥50 km) and province; seeded sample (seed recorded) of ~100 per stratum; bracket multi-height endpoints with min and max; real elevations; terrain status from the corrected code. The Open-Meteo free API is **not feasible for the whole set**: 16,956 links × 50 points = 847,800 coordinates against a published limit of 10,000 calls/day (how a multi-coordinate request is counted is not stated on the pricing page; the 429s after ≈167 requests are consistent with per-coordinate counting — INFERRED). Options: spread a ~500-link sample over several days; or use locally stored Copernicus GLO-90 tiles for Canada (no API limit). Report per-stratum counts with confidence intervals; keep NO DATA, near-threshold and status counts separate.
**Small check actually run (offline, on the 167 cached elevations, `results/plausibility_heights_pilot.py`):** with candidate heights (col 28, ISED field 29), per-endpoint min and max give the same result: **CLEAR 161 (96.4 %), AT RISK 2 (1.2 %), CRITICAL 4 (2.4 %)**, WATCH 0, near-threshold 26; 10 of the 167 links have several candidate heights. Semantics unverified; 167 is not a design sample; **not a validation**.

**3c. Sensitivity (PROPOSED parameters, same 167 links, uniform height at both ends) — sensitivity, not validation:**
| Height (PROPOSED) | CLEAR | WATCH | AT RISK | CRITICAL | near-threshold |
|---|---|---|---|---|---|
| 20 m | 116 (69.5 %) | 3 | 12 (7.2 %) | 36 (21.6 %) | 103 |
| 30 m (product default) | 141 (84.4 %) | 2 | 7 (4.2 %) | 17 (10.2 %) | 53 |
| 45 m | 158 (94.6 %) | 1 | 0 | 8 (4.8 %) | 22 |
| 60 m | 160 (95.8 %) | 1 | 4 (2.4 %) | 2 (1.2 %) | 8 |
| 90 m | 167 (100 %) | 0 | 0 | 0 | 0 |
Reading: the non-CLEAR share ranges from 0 % to 30.5 % across 20–90 m, i.e. the height assumption dominates the result. (It is not monotone in AT RISK/CRITICAL because links move between those classes.)

**3d. The 33 unresolved elevation requests.** Not retried. Pricing page (read online): 600 calls/min, 5,000/h, 10,000/day, 300,000/month; it does not say how multi-location requests are counted. This session already made ≈8,500+ coordinate lookups (167×50 plus smaller calls); a retry of 33×50 = 1,650 more would exceed 10,000 if counted per coordinate. **Listed as unresolved; the sample is 167 of 200.** (A further retry after the daily window is possible but not needed to answer anything above.)

**3e. Evidence that would let an operator-facing severity-distribution claim be made** (I make no such claim):
1. ISED's own definition of the height field(s) (meaning, AGL/ASL, TX vs RX antenna) for this extract; heights carried into the snapshot of both products.
2. A pre-specified, seeded, stratified sample large enough for per-stratum confidence intervals, with the sampling rule and denominators published; failed lookups reported as NO DATA, not dropped.
3. A post-correction comparison against an independent tool on a subset (e.g. 20–30 links, including the three uptowhere cases) to show agreement beyond the sign.
4. A sanity reference: status distribution among links in service for years (`in_service_date`) — licensed ≠ operating, so this is context, not truth.
5. A statement of the DEM limitation (GLO-90 is a surface model: canopy and buildings raise terrain; ±15 m basis rests on one validation pair).
6. Owner review of ~20 flagged links by someone who knows the sites.

## Section 4 (brief) — coverage and checks not green yet
| Item | Status | Detail |
|---|---|---|
| Real-link fixture coverage: **0 WATCH, 0 AT RISK** (terrain and weather) | **OPEN, stated plainly** | Real fixtures only reach CLEAR (10), CRITICAL (7/6), NO DATA (4/5) because terrain is synthetic and was calibrated before the correction; synthetic-boundary cases cover WATCH (2/2) and AT RISK (2/2) for terrain/weather and are unit tests, not real-link evidence. The 167-sample shows WATCH/AT RISK only under assumed or unverified heights. No real offline terrain exists to select further real links without the API. |
| xss / data_flow / csp / qgis_e2e | see §D | xss: OPEN regression; data_flow, csp: OPEN pre-existing; qgis_e2e: BLOCKED. Release-blocking: **qgis_e2e yes**, xss yes until decided, data_flow/csp not caused by P0. |
| Flake8 / Bandit | OPEN | not installed |
| Provenance divergence on 29 fixtures | **Decision not taken** | **Option 1 — register as an interface policy.** Add IP entry to spec §H: "QGIS terrain export types frequency Assumed (no origin channel); more conservative than Map". Size **S** (a spec edit + one note in OPERATOR_VISIBLE_CHANGES). Risk: a record-sourced frequency is under-labelled in QGIS; contradicts spec §F.2 ("Observed only if the record's own") unless the policy overrides it; two products will keep disagreeing on that row. **Option 2 — add a frequency-origin channel to the QGIS terrain flow.** Pass `origins` into `terrestrial.analyze_endpoints/analyze` and `export._terrestrial_to_csv`; where the two selected features are the ends of one Fixed Service link, prefill frequency from the record (`build_link_params`-style) and type it Observed. Size **M** (`terrestrial.py`, `export.py`, `plugin.py` flow, dialog prefill, tests, e2e). Risk: new UI semantics (what is "the link" when two sites are picked), the dialog default changes from 7 GHz, and it needs `qgis_e2e` to verify. |
| OPERATOR_VISIBLE_CHANGES.md complete? | **No — addendum appended to that file** | Checked against `git diff parity/1.1.5-harness..parity/1.1.5-p0 -- . ':!tests' ':!parity'` (18 Map files, 9 QGIS files). Missing: **(1)** Map elevation failures now read `NO DATA (terrain): elevation request failed (T1): …` (`web/elevation.js`); **(2)** Map's Open-Meteo request now asks for `showers, snowfall, weather_code` (`web/mwexposure.js`) — no new host; **(3)** library-side changes (`src/aei_link_clearance/elevation.py`, `terrain.py`) and the QGIS `LibraryOutOfDateError` appearing at first terrain analysis, not at start-up; **(4)** stale public/operator text not edited: `web/index.html:62` and `:469` (FAQ + JSON-LD: "typed Observed, Calculated, Assumed or Inferred", three-band clearance), source `content/faq.json`; `web/app.html:443-444`; Map `README.md:46-49`; QGIS `docs/OPERATIONAL_OUTPUT.md:25,88` (near-threshold rule), `metadata.txt` changelog line 15, `docs/EVIDENCE_EXPORT_AUDIT.md`; **(5)** the second badge breaks the xss check; **(6)** deferrals not named there: P10 wording and fade-remaining display, export contract fields. |

## 6. Integrity check
| Ref | Before | After |
|---|---|---|
| Map `main` | `de2a8703687b624be62a19c9dd9dcea998dc4b58` | identical |
| Map `origin/main` (local record) | `b1049a63ba7e53dbbd3f5fc014884b6975713388` | identical (not fetched) |
| Map `release/1.1.4` | does not exist | does not exist |
| QGIS `main` / `origin/main` | `01ad3200414a3bdaaeb17d51bc468c214036bf71` | identical |
| QGIS `release/1.1.4` | `f6d2b07f0c1147557606dc2265f91fb41d7544ce` | identical |
* `parity/1.1.5-harness` and `parity/1.1.5-p0` have **no upstream** in either repo; `git branch -r --list '*parity*'` is empty; no remote ref exists for them. Tags unchanged (Map `v1.0.0`; QGIS `…v1.1.3 v1.1.4`).
* Tracked working trees clean; untracked: Map `audit/`, `shots/` (pre-existing). No `dist/` artifact newer than the session start; `~/Documents/QGIS` unchanged (1.1.3, 1.1.4 zips).
* Nothing published: the only network activity was read-only GETs (PyPI JSON + one wheel download, GitHub release list, plugins.xml, Open-Meteo docs/pricing/elevation reads). Nothing installed into any Python; `.wrangler` state was not created in the repo; scratch copies live in `/tmp`.
* **No commits were created in this task.** The report and the addendum are files under `~/velorona-parity-audit/stage1/results/`, outside both repos.
