# Changelog — Velorona for QGIS

Canonical human-readable version history. (The plugin manager shows the shorter `changelog=` text in `metadata.txt`; this file is the detailed record.)
Compare any two releases: https://github.com/AIDEdgeInc-Lab/velorona-qgis-plugin/compare/v1.1.4...v1.1.5

## 1.1.6 — 2026-10-09 (compared with 1.1.5)

Why it matters: setting up USA data no longer starts with an unexplained box asking you to type a folder path or web address. Nothing about calculations, statuses, data or Canada changes.

### Changed (user experience)
- **Guided USA data setup.** *Explore: USA Data Setup…* opens a window that says what the USA data is (a separate download, not included in the plugin; Canada works without it) and offers *Use Velorona's online USA data*, *Choose a folder…* (the normal folder picker) or an https address, with a built-in "How do I get the data?" guide. Previously, pressing *Load USA Links in View* with nothing set up opened a bare text box ("Folder on this computer, or https address…").
- **Honest status.** *Not set up yet* / *Ready* (link count and dates read from the data itself, after the index and one real tile were validated) / *Problem* (what is wrong and what to do: missing folder, `index.json` not found, incomplete or damaged tiles, a newer data version, unreachable address, plain http). *Use this data* is enabled only after a successful check.
- **Safe to back out.** Cancel changes nothing; *Forget the saved setting* removes it; a cancelled first-time window ends with a calm note that Canada is unaffected. Small slips are forgiven (typing `index.json`, quotes, choosing the folder above the pack).
- **Never unprompted.** The window opens only when you ask for US data; starting Velorona, loading Canada and every Canadian analysis never open it (covered by an end-to-end test).
- The action *Explore: Set USA Data Pack Source* is now *Explore: USA Data Setup…*. The setting is still saved in the QGIS project (never global QGIS settings), with `VELORONA_USA_PACK` as the fallback; existing projects keep working.

### Not changed
Calculations, the five-level status contract, parity fixtures, Canadian data and heights, US antenna heights (30 m, Assumed), data limits (20,000 links / 36 tiles per view), the required library versions.

## 1.1.5 — 2026-10-09 (compared with 1.1.4)

Why it matters: 1.1.5 changes numbers. Terrain clearance on long paths is lower, weather rain loss is higher (mostly 6–10 GHz), many Canadian terrain statuses move because real antenna heights replace a 30 m assumption, and anything that cannot be decided now says NO DATA instead of guessing. Re-run saved analyses.

### Calculation corrections (results change)
- **Earth curvature.** `aei-link-clearance` 0.1.x applied the earth's bulge in the wrong direction (it added clearance). From 0.2.0 it is subtracted: clearance at mid-path is lower by about D²/(4·k·R) metres (k = 4/3, R = 6371 km): ~1 m at 6 km, 5 m at 13 km, 43 m at 38 km. The plugin refuses to run terrain analysis against an older library.
- **Rain attenuation (ITU-R P.838-3).** `aei-microwave-link-exposure` up to 0.1.5 used a 24-row coefficient table that differed from the Recommendation's Table 5 in 21 rows (rain loss understated, most at 6–10 GHz). 0.2.0 evaluates the Recommendation's equations. The plugin requires `>=0.2.0,<0.3` and shows an open-issue notice on weather results if an older model is installed.
- **Rain rate is per hour.** Open-Meteo reports millimetres per 15 minutes; 1.1.4 used that as mm/h. It is now ×4. Snow, freezing and mixed precipitation are no longer counted as rain; showers are. If the source does not split precipitation by type, the weather result is NO DATA.
- **Near threshold is a flag, not WATCH.** In 1.1.4 "near threshold" turned a result WATCH; now it is a verification note beside the status. Terrain WATCH means clearance ratio < 1.3, a provisional threshold, neither physics- nor operator-validated.

### Decision contract (shared with Velorona Map)
- The five levels CLEAR / WATCH / AT RISK / CRITICAL / NO DATA and "overall = worst of terrain and weather" already appeared in 1.1.4's Summary. 1.1.5 makes them a contract: same frozen input → same status, evidence, provenance and NO DATA as Velorona Map, checked on 96 shared fixtures (2,026 comparisons, 0 divergences; agreement between two implementations, not proof of correct physics).
- **NO DATA only through explicit validation**: invalid coordinates, identical endpoints, missing/null elevation (never 0 m), unusable weather interval, provider unreachable, weather frequency outside 1–100 GHz, antenna height outside 0.1–1000 m. A rate limit or outage is reported with its cause (bounded retry, never a status of its own); a data-pack problem is reported as a pack problem, never as a link's NO DATA.
- **Provenance.** Observed / Model-derived / Calculated / Inferred / Assumed. Anything you type or change is Assumed. Terrain can now start from one selected link: its highest published frequency is Observed while unchanged (in 1.1.4 the terrain dialog always typed frequency Assumed).

### New
- **USA (FCC ULS microwave links).** Explore: Set USA Data Pack Source, then Load USA Links in View. The dataset is **not bundled** (size, weekly refresh): you point Velorona at a pack folder or https address; only the 1° tiles under the map view are read; views over 20,000 links are refused. Source, source-file date, pack date and attribution travel with the layer and every export; it is licensee-reported record data, not a field measurement. US antenna heights stay 30 m (Assumed): the FCC's field documentation gives no unit or reference for its height field. See `docs/USA.md`. Not validated.
- **Canadian antenna heights.** The bundled Canada snapshot is schema 1.1 (shared byte-for-byte with Velorona Map): each link carries the heights its licensee reported (ISED column 29, "Height above ground level [m]"). They replace the 30 m assumption: Observed while unchanged, Assumed once you change them, 30 m Assumed when missing, terrain NO DATA when outside 0.1–1000 m (never clamped). ISED does not say whether the height is to the antenna centre or tip; an endpoint with several values uses the first row in the file (5.8 % of endpoints). Citation: `parity/contract/ISED_COLUMN29_CITATION.md`.
- **Exports** carry product/spec/library versions, the earth-curvature convention and the data source as `#` comment lines above the evidence table (table unchanged).
- **Start-up warning** when `aei-link-clearance` / `aei-microwave-link-exposure` is outside the supported range; install messages now give the exact line to run in QGIS's Python Console.

### Fixed
- The analysis dialog rounded a published frequency (6.22689 GHz → 6.23); an untouched field now returns its exact value.
- A deterministic NO DATA (e.g. a sub-GHz link) was remembered as "unavailable a moment ago"; it is now reported as what it is, every time.
- README claimed a GeoJSON export that the plugin does not have (CSV and Excel).
- Wording that said "ISED" for every record now follows the record's source.

### Dependencies and installation
- Requires `aei-link-clearance>=0.2.0,<0.3` (was unpinned) and `aei-microwave-link-exposure>=0.2.0,<0.3` (was `>=0.1.4`), `aei-geo-features`, `skyfield`, in QGIS's own Python. **QGIS does not install Python packages for plugins**; see the README for the one-line install from the Python Console.

### Documentation and development (no effect on results)
- New: `docs/USA.md`, `docs/RAIN_COEFFICIENTS_CAVEAT.md`, this file; `parity/` harness and handoff notes; `tools/verify_package.py`; USA end-to-end test and loading benchmark.

### Not changed
Thresholds, the Fresnel/clearance formulas, the earth-model constants (k = 4/3), the satellite engine.

## 1.1.4 — 2026-10 (reference)
Operational output: plain-language Summary / Details / Evidence, Ask box, Excel export, hourly weather history; Bandit/Flake8 cleanups. Earlier versions: see `metadata.txt`.
