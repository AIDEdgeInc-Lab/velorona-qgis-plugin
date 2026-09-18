# Velorona tests

| File | Needs QGIS? | What it covers |
|---|---|---|
| `test_viewport_cache.py` | no | Viewport cache: TTL, negative caching, LRU eviction, bound, key separation |
| `qgis_e2e.py` | yes | Real plugin through a real `QgsProject`/`QgsMapCanvas`: CRS, extent, layers, basemap, render, pan/zoom, inspector, dock, engines, exports, Qt6 idioms, ownership markers, unload lifecycle |
| `benchmark_viewport.py` | yes | Load / render / navigation timings, HTTP counts, canvas-refresh counts |

## Run everything

```sh
./tests/run_qgis_tests.sh            # checker + unit + end-to-end
./tests/run_qgis_tests.sh --bench    # also the benchmark
```

Set `QGIS_APP` if QGIS is not at `/Applications/QGIS-final-4_2_2.app`.

## Unit tests only (no QGIS)

```sh
python3 -m pytest tests -q
```

`qgis_e2e.py` and `benchmark_viewport.py` make real calls to the live
public services, so results vary with service availability. CelesTrak
rate-limits repeated runs; the end-to-end test reports the satellite engine as
explicitly skipped rather than failed when that happens.

## Release verification

`clean_install_smoke.py` loads the plugin from an installed copy in a separate
QGIS profile (the repo is kept off `sys.path`) and runs the whole workflow,
including disable/re-enable. Build and verify a release with:

```sh
./tools/package.sh
PROF="$HOME/Library/Application Support/QGIS/QGIS4/profiles/velorona_release_test"
rm -rf "$PROF" && mkdir -p "$PROF/python/plugins"
(cd "$PROF/python/plugins" && unzip -q /path/to/dist/velorona-<version>.zip)
QGIS_APP=/Applications/QGIS-final-4_2_2.app tests/run_qgis_tests.sh   # env setup
```
