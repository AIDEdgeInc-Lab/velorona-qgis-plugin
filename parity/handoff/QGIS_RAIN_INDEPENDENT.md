# QGIS_RAIN_INDEPENDENT — independent check of the ITU-R P.838-3 rain coefficients (QGIS workstream, 2026-10-09)

Order of work (as required): the calculator and its results were written and **committed (`64d5920`) before** the Map workstream's audit, oracle or corrected library were read. Labels OBSERVED / INFERRED / UNKNOWN.

## What was computed
`parity/rain_independent.py` — stdlib only, **no import from the product, the aei libraries or the Map**. Equations (1)-(3) of Rec. ITU-R P.838-3; constants = Tables 1-4 of the PDF (https://www.itu.int/dms_pubrec/itu-r/rec/p/R-REC-P.838-3-200503-I!!PDF-E.pdf, retrieved 2026-10-09 01:30 UTC, sha256 `3ab7482993e51fc63c5127a72e9e8930614e73652ac614882760817e7c1469cb`), extracted from `pdftotext -layout` output by a script, not typed from memory (Table 4's m, c read from its third row). Grid: 21 frequencies (1, 2, 4, 6, 7, 8, 10, 11, 12, 13, 15, 18, 20, 23, 26, 28, 32, 38, 50, 80, 100 GHz) × H, V × 7 rain rates (1, 5, 12, 25, 32, 50, 100 mm/h) -> `QGIS_RAIN_INDEPENDENT.json` (sha256 of the committed file in `git`).
**Self-check against the document's own Table 5, all 111 rows (1-1000 GHz): worst relative difference 3.8e-4** (tolerance 2e-3, the rounding of 3-significant-figure entries such as 2.59e-5). A wrong constant or a bad extraction cannot pass this.
Common-mode caveat: my extraction and the Map's `parity/contract/ref/extract_p838.py` both read the same PDF through poppler's text layer; Table 5 (printed numbers) is the guard against a shared extraction error, and the ITU-Rpy comparison below uses different code and data files.

## Comparisons (OBSERVED)
| compared with | result |
|---|---|
| Installed library aei-microwave-link-exposure 0.1.5 (`_P838_TABLE`) | **21 of 24 rows differ** (> 1 % in k or > 0.005 in alpha); only 1, 2, 4 GHz agree. Same count as the Map's audit (`RAIN_COEFFICIENT_AUDIT.md`) and CCR-2. Library alpha_V at 6 GHz (1.4745) equals the Recommendation's value at **7** GHz |
| Map workstream's `parity/itu_p838.py` + its `itu_p838_3.json` constants (commit `d2090c3`) | constants of Tables 1-4: max absolute difference **0**; 294 gamma values: max relative difference 2.0e-15. **No disagreement; no CCR needed** |
| ITU-Rpy 0.4.0 (`itur.models.itu838.rain_specific_attenuation`, own code and data) | 294 gamma values: max relative difference **2.0e-15** |
| aei-microwave-link-exposure **0.2.0**, built by me with `pip wheel` from the Map workstream's repo commit `4b13f64` (branch `fix/p838-3-coefficients`, scratch dir; wheel sha256 `a32fda98c96c37567c41059b5806dc16464377868378a0679b96ac4d35c1f285`) | k, alpha and 294 gamma values: difference **0.0**; the library's own 220 tests pass in a clean venv |
| Interpolation | a hypothetical *correct* 24-row table interpolated like the old code differs from the equations by up to 12.9 % (V) / 20.1 % (H) in gamma at 32 mm/h between rows (worst at 1.5 GHz). The equations (no table) remove that error class |

## Scope
P.838 only (specific attenuation per km). The P.530 path factor, rain-rate selection, thresholds, and DEM are not part of this check. This is not a validation of the weather model or of any status.
