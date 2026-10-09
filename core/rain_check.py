"""Does the INSTALLED rain model reproduce Recommendation ITU-R P.838-3? A cheap, pure, read-only spot check run when a result needs to say so. Stdlib only.

It calls the library's public ``physics.rain_coefficients`` (no mutation, no network) at three frequencies and compares k and alpha, both
polarizations, with the
Recommendation's own Table 5. SOURCE of the reference numbers: Rec. ITU-R P.838-3 (03/2005) Table 5,
https://www.itu.int/dms_pubrec/itu-r/rec/p/R-REC-P.838-3-200503-I!!PDF-E.pdf
(sha256 3ab7482993e51fc63c5127a72e9e8930614e73652ac614882760817e7c1469cb), copied from the document text, not from memory.

Why it exists: releases of aei-microwave-link-exposure up to 0.1.5 looked coefficients up in a 24-row table that differed from the Recommendation in
21 rows (QGIS and
Map audits, 2026-10-09); 0.2.0 evaluates the Recommendation's equations. Rather than trust a version string, the plugin checks behaviour, so the
open-issue notice
appears exactly when the installed model is wrong and disappears when it is not. It is a spot check at 3 frequencies, NOT a validation of the model.
"""

from __future__ import annotations

TOLERANCE = 0.005   # 0.5 %: Table 5 is printed to 3-4 significant figures (0.2 % worst rounding, measured over all 111 rows)
# f GHz -> (kH, alphaH, kV, alphaV)  -- Table 5 rows 6, 10, 38 GHz (the old table was wrong at all three)
TABLE5 = {6.0: (0.0007056, 1.5900, 0.0004878, 1.5728),
          10.0: (0.01217, 1.2571, 0.01129, 1.2156),
          38.0: (0.4001, 0.8816, 0.3844, 0.8552)}

_cache = {}


def rain_model_matches_p838_3():
    """True / False; None when the installed library has no ``physics.rain_coefficients`` to test (then nothing is claimed either way)."""
    if "v" not in _cache:
        _cache["v"] = _check()
    return _cache["v"]


def _check():
    try:
        from aei_mw_exposure import physics
        coefficients = physics.rain_coefficients
    except (ImportError, AttributeError):
        return None
    for f, (kh, ah, kv, av) in TABLE5.items():
        for pol, k_ref, a_ref in (("H", kh, ah), ("V", kv, av)):
            k, a = coefficients(f, pol)
            if abs(k / k_ref - 1) > TOLERANCE or abs(a / a_ref - 1) > TOLERANCE:
                return False
    return True
