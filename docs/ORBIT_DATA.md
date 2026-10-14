# Orbital-data core (`core/sources/orbit_data.py`)

Status: **wired into the Satellites layer through `core/sources/satellite_feed.py`** (see "Plugin wiring" below) and, since the real-source and real-QGIS runs of 2026-10-14, **observed working against the live CelesTrak source in a real QGIS 4.0 runtime** (see "Verification" at the end for exactly what was and was not shown, and on which commit).

What it is: the Python counterpart of Velorona Map's `web/orbitdata.js`, QGIS-free and network-free (the caller passes a `fetch`), so it can be tested without QGIS:
- OMM JSON parsing with the same record classification (valid / incomplete / invalid; missing is never filled in);
- catalog ids of 1-9 digits kept exactly, flagged when they cannot be written as a TLE;
- duplicates resolve to the **newest epoch**;
- a per-group file cache (in a directory the plugin chooses, never a shared temp path) that stores a response only after it parsed, with the real retrieval time; older than 2 h is returned as `stale`, never `fresh`;
- request policy: after **any** non-200 answer, unusable body, network error or timeout the source is not asked again until a back-off passes (Retry-After, else 15 min; network 60 s), and the back-off is persisted so a restart does not skip it.

Verified in the unit tests (no QGIS, no network): ingestion output equals the Map's own output on the shared fixture (counts, surviving ids and epochs, flags, element ages); the policy and cache behaviours above. **The fixtures are synthetic** (`tests/fixtures/orbitdata/README.md`, hashes pinned): they prove agreement on the rules. That real responses parse is shown separately, in "Verification" below.

Originally left out of the core (now done in the plugin, not in this module): the network call in a worker (`QgsTask`, see "Plugin wiring"), switching the layer to this core, showing retrieval time and age, cancellation and the provenance fields. Not done: group workflow and export fields beyond those; the call still uses `requests` with the named User-Agent `VeloronaQGIS (+https://velorona.ai)`, not `QgsNetworkAccessManager` (so QGIS proxy settings are not applied to it).


## Plugin wiring (`core/sources/satellite_feed.py`, `plugin.py::_populate_satellites`)

What changed for the Satellites layer (the five GEO groups the plugin already used):
- the provider is asked **at most once per group per 2 h cache window**, and not again after a failed request until its persisted back-off passes. Before: every 10 minutes, and again on every layer toggle after a failure;
- after a failed request, **no group is requested** until the back-off passes -- within the run and on later layer toggles (the groups share one host). Other groups are served from their cache (labelled stale once older than the window) or reported unavailable, and that never writes or extends a back-off;
- records are validated before use; ids keep all digits. Ids above 99999 have no valid TLE (exporting one gives a non-standard alpha-numeric id), so those rows carry no TLE lines and are propagated from the stored OMM record (`omm_json`), in the layer and in the satellite-earth-space engine; they are counted as `omm_only`. TLE and OMM propagation agree within 1 km in a test;
- SGP4 error codes are honoured, in the layer and in the engine at analysis time. Before, a decayed element set produced a number (a position below the surface) instead of being rejected. (A below-surface radius check also exists; no test case reaches it without an SGP4 error, so it is not mutation-covered);
- each row carries `retrieved_at` and `data_status` (`fresh` | `stale`), and the source text includes the retrieval time; positions are recomputed from cached elements every 10 minutes without network I/O;
- status is stated in the QGIS message bar: fresh is silent; stale, partial, unavailable and "some element sets not shown" are reported. Nothing is substituted when the source is unavailable.

The request runs in a `QgsTask` worker thread (nothing QGIS-related is touched there): the toggle returns immediately, the GUI stays responsive during the request (real-QGIS check: 298 event-loop iterations during a 3 s request) and the task is cancellable and waited for (bounded) on unload. A cache hit does no network I/O. Bounded: 5 s connect / 20 s read per group, one group when the host is down.

## Verification (what was shown, where, on which commit)

All of the following ran on GitHub-hosted runners (the build sandbox and the maintainer's machine could not reach the source at the time of the later runs).

**Real source, the plugin's own feed code** (`tools/live_orbit_probe.py`, workflow *Live orbit probe + real QGIS runtime*, branch `claude/qgis-live-probe`, which is `main` plus two workflow files):
- 2026-10-14 00:11 UTC (code of PR #17 before two later test fixes) and 01:13 UTC: all five groups answered HTTP 200.
- **2026-10-14 14:12 UTC, on the final merged code (`main` at `f3f7fb9` + workflows, branch commit `4fba910`):** HTTP 200 for all five groups; 599 unique records, 599 layer rows, 3 of them only representable as OMM (highest catalog id above 99999 seen: 100688), 0 propagation failures, all latitudes/longitudes finite; TLE and OMM propagation agree within 0.0053 km on the 596 records that have both; a second call was served entirely from the cache.
- Not a reliability measure: one retrieval per group per run.

**Real QGIS 4.0.3 runtime, final code** (`tests/qgis_satellite_feed_e2e.py`, 14:12 UTC run): **28/28 checks passed**, including: real records populate the layer from the cache without a request; the load runs in a worker; the GUI keeps responding during a slow request; catalog ids stay full text; every row carries retrieval time, status and the OMM record; the OMM-only analysis agrees with the TLE analysis (0.5211 vs 0.5211 deg); a decayed element set is refused with an explanation; an unavailable source leaves the layer empty (nothing substituted), tells the user in the message bar, and makes exactly one request; the back-off is on disk and blocks later toggles; an old cache is shown with every row flagged stale. **That run was marked failed by the workflow** because the process was killed (exit 139) at interpreter shutdown *after* printing 28/28: the documented QGIS 4.0.3 exit abort (docs/QUALITY.md). The workflow now runs the script through `tools/run_qgis_suite.py`, which tolerates exactly that case with a visible warning. **Clean re-run on the same code, 2026-10-14 15:14-15:18 UTC (workflow run 38587550253, branch commit `1726563`, which is `main` at `f3f7fb9` plus workflow files only): the whole workflow passed.** The probe got HTTP 200 for all five groups (599 unique records, 599 rows, 3 OMM-only, 0 propagation failures, TLE vs OMM within 0.0053 km, second call all from cache); unit tests 387 passed, 2 allowed skips; the feed e2e passed 28/28 in the real QGIS 4.0.3 runtime; the existing full e2e suite, with the orbital source blocked, passed 484/486, the two failures being the QGIS 4.0 layer-group-order checks that fail identically on v1.1.7 (they are not about satellites).

**Source availability is intermittent.** The same runners got HTTP 200 on 2026-10-12 23:45, 2026-10-14 00:11, 01:13 and 14:12 UTC, and timeouts on 2026-10-13 00:47 (Map probe), 2026-10-14 02:19 and 13:47-13:53 (the plugin's live end-to-end workflow). A timeout is the source being unreachable, and the feed handled it as designed (back-off, nothing invented, a message to the user); it is not evidence about the parser. A timeout is never counted as a pass.

**Not shown:** behaviour on Windows or on QGIS older than 4.0.3 / newer than 4.2 for this feed; the full existing end-to-end suite (`tests/qgis_e2e.py`) with the live source reachable (its orbital section was run with the source blocked; the feed's own 28-check test covers the live-data path); the provider's redistribution terms (unread); the five group names against the provider's current documentation beyond the fact that all five answered.
