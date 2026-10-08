# QGIS_STATUS — QGIS workstream, Velorona 1.1.5 (append-only; newest last)

Repo `velorona-qgis-plugin`, branch `release/1.1.5`, base `7d130b21d11f786f7314db91810ee1ef305156ce`. Map reference: `aei-link-clearance` committed HEAD `326e1745b4b8c9f8e6677cc965890ff56ae2a645` (M3), read via `git archive`; nothing in the Map repo was written.
Labels: OBSERVED (command/file) · INFERRED · UNKNOWN. Frozen: spec 0.3, `canonical.py`, P11. Changes needed in the contract go to `CONTRACT_CHANGE_REQUESTS.md` (this folder).

## Q0–Q4 — 2026-10-08 — USA provider, frequency-origin channel, USA parity
Commits (in order): `8ea9935` provider · `c90d18f` origin channel / wording / spec-G lines / USA actions · `f9d6f47` QGIS USA e2e + benchmark · `639e7d0` extract provider + height channel · `5ce8b10` USA fixtures + strict parity.

**What changed (QGIS)**
* `core/countries/` — `usa.py` reads the Map's tile pack (`velorona.us-fcc-uls-micro/1`) **or** the regional extract (`velorona.usa-extract/1`, from `parity/contract/usa/`) from a configurable local folder / https URL; extent -> 1-degree tiles; link/site de-dup by id (QGIS finds the same 52,057 / 45,963 duplicate rows the contract reports and 0 content conflicts); typed errors (not configured / missing / corrupt / unavailable / version / view too large) are never NO DATA. Pack is **not bundled**. Schema was PROVISIONAL until `USA_PACK_SCHEMA.md` appeared; reconciled — no field-level disagreement found.
* **Frequency-origin channel** (`core/record_source.py`): terrain can start from ONE selected link record (as the Map's `terrestrialAnalyze`); frequency = highest published (GHz = max(MHz)/1000), typed **Observed** only while the value used equals the record's own, **Assumed** once changed. Same rule for record antenna heights (`site_a/b_height_m` on the record; only the extract carries them). Source text prefix is the Map's: `ISED record -- ` / `FCC ULS record -- `.
* AID-1 is **closed**: Canada + USA parity is 54 fixtures, **1,106 stage comparisons, 0 non-MATCH**, no accepted divergence (the 17-fixture US height provenance DIVERGE you reported in M3 is resolved by the height channel; the Canada 29-fixture frequency one by the frequency channel).
* Exports carry the spec G identity block as `# ` preamble lines (product + version, spec 0.3, library versions, curvature convention, data source + dates + input sha256, nature of the data). No table row/column changed.
* `ParamDialog` returns an untouched field's exact default (a record's 6.22689 GHz was being rounded to 6.23 by the 2-decimal spin box — OBSERVED root cause of what would otherwise have been a spurious Assumed).

**What the Map needs to know**
1. Heights: USA analysis in QGIS uses record heights **only** from the extract (or a future pack /2); from tile pack /1 they are 30 m Assumed, as in the Map today.
2. Frequency < 1 GHz -> weather NO DATA for 13,079 US links (5.21 %), terrain still decided — QGIS reproduces your count class on the extract fixtures (`us-lowfreq`, `us-subghz`).
3. Wording difference (QCCR-1): contract section 3.3 prescribes "antenna height to centre (FCC field 'Height to Center RAAT'), licensee-reported record value, metres, interpreted as above ground; not a field measurement"; the fixtures' `height_source` says "FCC ULS AN 'Height to Center RAAT' (m), licensee-reported ...". QGIS uses the contract text. Presentation only.
4. Stale Map text (not changed by me): `docs/USA_FCC_ULS_PACK.md` §2 "Licence ... unresolved" and §8 "Not in the QGIS plugin yet" no longer hold; `uspack.js` `pairing_note` says "transmit and receive endpoints" while the contract §2 says a/b order is NOT the Tx/Rx role (QGIS now says so).
5. CCR-2 (rain table != ITU-R P.838-3): acknowledged; QGIS adds a caveat line to weather exports; no physics change (see OWNER_DECISIONS D-Q6).

**QGIS strengths Map lacks (candidates for Map, not requirements)**
* Excel workbook export (8 sheets) + the spec G identity lines in every export; hourly model-weather history as context (IP8); ECCC station/radar cross-check is in both.
* `ParamDialog`-style exact-value return is QGIS-only (the Map has no dialog).

**Blocked / not run today**: live QGIS e2e (`tests/qgis_e2e.py`, 483 checks) and anything that calls Open-Meteo — `api.open-meteo.com` answers HTTP 429 "Daily API request limit exceeded" (same as your M2). The USA e2e (29 checks, synthetic pack, no network) and all unit tests pass.

## Q5–Q9 — 2026-10-08 — backoff, caveat, packaging, heights, final checks
Commits since the entry above: `cadc214` rain-table notice on weather exports + `tools/verify_package.py` · `9360622` smoke test expects 7 actions · `547b037` README/docs · `dc16d15`/`e9645d0` docs/USA.md + changelog · `737a62b` https hardening · `abf2aa7`/`9fa8f37` notice on weather limits · `1143a0c` provider backoff.

**What changed / what Map needs to know**
1. **Library:** `aei-link-clearance` 0.2.0 and 0.2.1 are published; the QGIS pin `>=0.2.0,<0.3` is already the release pin (wheels differ only in `__version__`). Nothing is blocked on a library publish for the curvature path. The rain table (your CCR-2) would need a new `aei-microwave-link-exposure` release; QGIS has the pin change prepared in prose only (LIBRARY_DEPENDENCY_PLAN.md §6).
2. **CCR-2 reproduced:** your `p838_table_check.py` run unmodified against the *released* `aei-microwave-link-exposure` 0.1.5 gives the same table (21 of 24 rows differ). QGIS now shows a notice on weather limits and in weather exports. I did not re-verify your reference file against the ITU document.
3. **Provider failures:** QGIS retries only 429/5xx/network (1 s, 3 s; `Retry-After` ≤ 10 s), never a daily limit, and ends in NO DATA marked transient with the real cause. The Map's runner does not retry; outcomes are identical for your 503 fixtures. Worth considering for `getElevations`.
4. **Parity (final):** 54 fixtures, 1,106 stage comparisons, 0 non-MATCH, vs Map `326e1745`. Statuses: Canada CLEAR 4 / WATCH 4 / AT RISK 4 / CRITICAL 16 / NO DATA 6 (13 of the 34 are synthetic-boundary); USA 8 / 3 / 2 / 2 / 5 (FIXTURE_COVERAGE.md).
5. **USA NO DATA over the whole pack, with QGIS' own validators:** terrain 0; weather 13,079 (5.21 %); both equal your contract §5.
6. **ISED column 29 (antenna height, Canada):** height-like (100 % filled, ≤ structure height in 99.4 %, not above-sea-level) but **no header and no unit** in the raw file → not shipped; would need a snapshot rebuild on your side too (HEIGHT_AND_PLAUSIBILITY.md).
7. **Not run today (BLOCKED):** live `qgis_e2e.py` (483 checks passed at baseline before Open-Meteo's daily limit was used up; aborts at the first live call now), live part of `clean_install_smoke.py`, anything needing elevations/weather. After 00:00 UTC: `tests/run_qgis_tests.sh` and `tests/clean_install_smoke.py`.
8. **Your stale text (unchanged by me):** `docs/USA_FCC_ULS_PACK.md` §2 and §8; the uptowhere README table (cases 2–3 inputs are recorded nowhere I could find).
