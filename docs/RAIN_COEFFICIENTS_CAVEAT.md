# Rain-coefficient table: open caveat (1.1.5)

**What is open.** `aei_mw_exposure.physics._P838_TABLE` (aei-microwave-link-exposure) is documented as transcribed from ITU-R P.838-3 and "re-verify against the official text". The Velorona Map workstream's independent check (2026-10-08, `parity/p838_table_check.py`, reference `parity/contract/ref/itu_p838_3.json` from the ITU document, pdf sha256 `7be111bf…77c4f`) reports that **21 of 24 rows differ** from Table 5. The QGIS workstream re-ran that script unmodified against the *released* packages (aei-microwave-link-exposure 0.1.5 from PyPI) and got the same result (OBSERVED, same output table). The reference file itself was not independently re-verified against the ITU (UNKNOWN).

**Effect (from that script's own hop table, vertical polarisation, 32 mm/h).** Predicted attenuation as a fraction of the value with the Recommendation's coefficients: 0.21 (6 GHz, 38 km), 0.18 (7 GHz), 0.16 (8 GHz, 15 km), 0.09 (10 GHz, 12 km), then 0.90–0.95 at 12–38 GHz. So weather attenuation, exposure ratio and weather status can be **understated**, most at 6–10 GHz. Both products use the same table, so Map-vs-QGIS parity is unaffected; correctness against the Recommendation is.

**What 1.1.5 does.** Nothing is changed in the physics (no change is approved). Weather exports carry a caveat line; the README and release notes say the table is unverified. "ITU-R P.838-3" in text names the method, not a verified table.

**What resolves it.** Owner decision D-4 (Map `OWNER_DECISIONS.md`): a library release with the verified coefficients, then re-freezing the weather expectations in both products' fixtures, then this caveat and `core/evidence_record.py` `RAIN_TABLE_CAVEAT` are removed in the same release.
