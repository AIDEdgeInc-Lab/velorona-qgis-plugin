# satgeo fixtures (shared with Velorona Map)

Byte-identical copies of the Map repo's `tests/fixtures/satgeo/` files (AIDEdgeInc-Lab/velorona-map, `web/satgeo.js`):

| file | what | sha256 |
|---|---|---|
| `reference.json` | SYNTHETIC orbits and station coordinates + Skyfield reference values (look angles, rise/culminate/set events). Built by the Map's `parity/build_satgeo_reference.py`. | `043bc816d42c9af09214cd5dcc73cfdbfe34d7989cdaac6d38bfde7c692c6564` |
| `js_golden.json` | What the Map's JavaScript geometry (satellite.js 7.1.0) outputs on those same inputs. Built by the Map's `parity/build_satgeo_js_golden.mjs`. | `f5af546752f2d945438c06b86b2ff8bc7dbb290d6ffafcd941ae09458a2ec2a8` |

The orbits are invented, well-formed element sets (not real satellites); the stations are plausible coordinates chosen for geometry diversity. Agreement shows the
two implementations compute the same geometry; it says nothing about any real element set or any link. Re-sync both files together when the Map regenerates them.
