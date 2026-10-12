# Orbital-data core (`core/sources/orbit_data.py`)

Status: **library only, not wired into the plugin.** Nothing in the plugin calls it yet, so no user-visible behaviour changes. The satellite layer still uses `core/sources/space_public.py` (blocking `requests`, `FORMAT=tle`, five-digit ids, no cache, last-record-wins duplicates).

What it is: the Python counterpart of Velorona Map's `web/orbitdata.js`, QGIS-free and network-free (the caller passes a `fetch`), so it can be tested without QGIS:
- OMM JSON parsing with the same record classification (valid / incomplete / invalid; missing is never filled in);
- catalog ids of 1-9 digits kept exactly, flagged when they cannot be written as a TLE;
- duplicates resolve to the **newest epoch**;
- a per-group file cache (in a directory the plugin chooses, never a shared temp path) that stores a response only after it parsed, with the real retrieval time; older than 2 h is returned as `stale`, never `fresh`;
- request policy: after **any** non-200 answer, unusable body, network error or timeout the source is not asked again until a back-off passes (Retry-After, else 15 min; network 60 s), and the back-off is persisted so a restart does not skip it.

Verified (tests, no QGIS, no network): ingestion output equals the Map's own output on the shared fixture (counts, surviving ids and epochs, flags, element ages); the policy and cache behaviours above. **The fixtures are synthetic** (`tests/fixtures/orbitdata/README.md`, hashes pinned): this proves agreement on the rules, not that CelesTrak is reachable or that any real response parses.

Not done (needs a real QGIS to verify, so deliberately left out): the network adapter (`QgsNetworkAccessManager`/`QgsTask` instead of the blocking `requests` call, with a named User-Agent), switching the layer to this core, showing retrieval time and age, cancellation, the group workflow and export fields. Those are the next PRs; see velorona-map `docs/REAL_ORBIT_DATA_PATH.md` and `docs/ZENITH_STUDY.md`.
