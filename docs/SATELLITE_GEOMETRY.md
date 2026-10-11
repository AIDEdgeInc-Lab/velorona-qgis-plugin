# Satellite geometry (QGIS) -- what it computes, how it is checked, how it relates to Velorona Map

**Scope: geometry only.** For one ground station and one satellite: elevation, azimuth and slant range at a stated UTC instant, and the windows over the following
1-72 hours in which the elevation is at or above a minimum elevation. No propagation loss, link budget, signal strength, availability or service quality; geometric
visibility is not a working link. Code: `core/engines/satellite_geometry.py` (QGIS-free), adapted to QGIS features by `core/engines/satellite_earth_space.py`;
evidence rows `core/presentation/satellite.py`; export `core/export.py`.

## Inputs and their evidence type
| Input | Type | Rule |
|---|---|---|
| Station position, altitude, listing status, declared minimum horizon | Observed | SatNOGS station listing, bundled snapshot (its retrieval date is shown). A listing status is **not** verification that a station operates, is authorised, or can communicate with the satellite. |
| Element set (TLE), epoch | Observed | CelesTrak, as already loaded. A TLE that fails the format/checksum test is refused. |
| Analysis time | Assumed | Now, or now + the offset you enter (UTC). |
| Minimum elevation | Assumed (default 10 deg, or typed) / Observed (only if you choose the station's declared horizon) | The station's own horizon is its owner's tracking limit; it is not adopted silently. |
| Position, look angles, windows | Calculated | SGP4 via Skyfield; elevation scanned every 20 s, each crossing refined by bisection to 1 s. |
| Orbital-data age; freshness | Calculated; Inferred | fresh <= 3 d, aging <= 14 d, stale > 14 d: an assumed convention, not a property of any satellite. |

## How it is checked
`tests/test_satellite_geometry.py` compares this implementation with (a) an independent Skyfield reference and (b) **what Velorona Map's JavaScript implementation (satellite.js 7.1.0)
outputs on the same inputs** (`tests/fixtures/satgeo/js_golden.json`): look angles, window count, rise/set/maximum, state. The fixtures are byte-identical copies of the Map repo's
(`tests/fixtures/satgeo/README.md` lists their hashes). Orbits and station coordinates are **synthetic**; agreement proves the two implementations compute the same geometry, not the accuracy of
any real element set and not any link. `tests/test_satellite_evidence.py` covers evidence typing, export, the engine adapter (with a stand-in `qgis.core`) and the refusals.

## Parity with Velorona Map (measured, not assumed)
| Aspect | Map | QGIS | Same? |
|---|---|---|---|
| SGP4 front end | satellite.js 7.1.0 | Skyfield | different libraries; look angles agree within the test tolerances (0.01 deg, 0.5 km) on the shared fixtures |
| Window rule, scan/refine, always-above/never-above, open windows | `web/satgeo.js` | `satellite_geometry.find_windows` | same algorithm; boundaries agree within 2 s |
| Mask rule, element-set age convention, readings text | same | same | same |
| Time input | UTC instant (any past/future) | hours from now, 0-72 | **differs**: QGIS cannot analyse a past instant or type an absolute time (the shared dialog has no text field) |
| Export | evidence CSV | evidence CSV | same rows and typing; the preamble wording differs slightly |
| Excel | n/a | not offered for satellite | same |
| Drawer / dock | in-place recompute form | parameter dialog before each run | different interaction patterns, by design |

## Limits
Element sets are mean-element fits whose error grows from the epoch; no refraction; a pass shorter than the scan step can be missed; the QGIS dialog and dock for this feature have **not** been exercised
in a real QGIS in this change (see `tests/qgis_e2e.py`, which needs a QGIS runtime).
