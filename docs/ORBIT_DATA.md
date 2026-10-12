# Orbital-data core (`core/sources/orbit_data.py`)

Status: **wired into the Satellites layer through `core/sources/satellite_feed.py`** (see "Plugin wiring" below). The wiring is covered by QGIS-free unit tests only; **it has not been run in a QGIS runtime** (none was available).

What it is: the Python counterpart of Velorona Map's `web/orbitdata.js`, QGIS-free and network-free (the caller passes a `fetch`), so it can be tested without QGIS:
- OMM JSON parsing with the same record classification (valid / incomplete / invalid; missing is never filled in);
- catalog ids of 1-9 digits kept exactly, flagged when they cannot be written as a TLE;
- duplicates resolve to the **newest epoch**;
- a per-group file cache (in a directory the plugin chooses, never a shared temp path) that stores a response only after it parsed, with the real retrieval time; older than 2 h is returned as `stale`, never `fresh`;
- request policy: after **any** non-200 answer, unusable body, network error or timeout the source is not asked again until a back-off passes (Retry-After, else 15 min; network 60 s), and the back-off is persisted so a restart does not skip it.

Verified (tests, no QGIS, no network): ingestion output equals the Map's own output on the shared fixture (counts, surviving ids and epochs, flags, element ages); the policy and cache behaviours above. **The fixtures are synthetic** (`tests/fixtures/orbitdata/README.md`, hashes pinned): this proves agreement on the rules, not that CelesTrak is reachable or that any real response parses.

Not done (needs a real QGIS to verify, so deliberately left out): the network adapter (`QgsNetworkAccessManager`/`QgsTask` instead of the blocking `requests` call, with a named User-Agent), switching the layer to this core, showing retrieval time and age, cancellation, the group workflow and export fields. Those are the next PRs; see velorona-map `docs/REAL_ORBIT_DATA_PATH.md` and `docs/ZENITH_STUDY.md`.


## Plugin wiring (`core/sources/satellite_feed.py`, `plugin.py::_populate_satellites`)

What changed for the Satellites layer (the five GEO groups the plugin already used):
- the provider is asked **at most once per group per 2 h cache window**, and not again after a failed request until its persisted back-off passes. Before: every 10 minutes, and again on every layer toggle after a failure;
- after a failed request, **no group is requested** until the back-off passes -- within the run and on later layer toggles (the groups share one host). Other groups are served from their cache (labelled stale once older than the window) or reported unavailable, and that never writes or extends a back-off;
- records are validated before use; ids keep all digits. Ids above 99999 have no valid TLE (exporting one gives a non-standard alpha-numeric id), so those rows carry no TLE lines and are propagated from the stored OMM record (`omm_json`), in the layer and in the satellite-earth-space engine; they are counted as `omm_only`. TLE and OMM propagation agree within 1 km in a test;
- SGP4 error codes are honoured, in the layer and in the engine at analysis time. Before, a decayed element set produced a number (a position below the surface) instead of being rejected. (A below-surface radius check also exists; no test case reaches it without an SGP4 error, so it is not mutation-covered);
- each row carries `retrieved_at` and `data_status` (`fresh` | `stale`), and the source text includes the retrieval time; positions are recomputed from cached elements every 10 minutes without network I/O;
- status is stated in the QGIS message bar: fresh is silent; stale, partial, unavailable and "some element sets not shown" are reported. Nothing is substituted when the source is unavailable.

Still true: the request is **synchronous on the GUI thread** (bounded: 5 s connect / 20 s read per group, one group when the host is down). A cache hit does no network I/O. Moving it to `QgsTask`/`QgsNetworkAccessManager` is not done because it cannot be verified without a QGIS runtime.

Not verified: any real CelesTrak response; the five group names against the provider's current documentation; `tests/qgis_e2e.py` section 28 was edited to the new path but **not run** (needs QGIS).
