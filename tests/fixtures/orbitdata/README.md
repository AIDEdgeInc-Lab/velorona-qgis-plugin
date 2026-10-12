# Orbital-data test fixtures (SYNTHETIC)

Byte-identical copies of files from velorona-map (`tests/fixtures/orbitdata/`, built there by `parity/build_leo_group_fixture.py` and `parity/build_ingest_golden.mjs`).
**These are invented test inputs, not real satellites and not real source data.** They exist only to prove the ingestion logic and Map/QGIS agreement; they must never be
loaded by the plugin at run time (the plugin ships none of `tests/`).

| file | sha256 |
|---|---|
| synthetic_leo_group.json | 7336ac124293d611cdbe5f4b848853119f11c87f910991711b1f337d129fc7b7 |
| synthetic_leo_group_ingest_golden.json | 01fbe9c7a3ce1db65d01788388ae9c09e4cecd0d513d7c93659fd375fcd2b620 |
