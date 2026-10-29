"""Trust: the rain-fade number is an estimate from the CURRENT model rain rate, never a "prediction" or "forecast" (UI_AUDIT F2). The library's
field name ``predicted_attenuation_db`` is an identifier we read, not wording we show; "not an outage prediction" is the disclaimer."""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCANNED = ["core/presentation", "core/export.py", "core/evidence_record.py", "core/batch.py", "core/processing", "ui", "plugin.py", "docs/OPERATIONAL_OUTPUT.md"]
WORD = re.compile(r"\bpredict(?:ed|s|ing|ion|ions)?\b", re.IGNORECASE)
ALLOWED_PHRASES = ("outage prediction",)


def _files():
    for entry in SCANNED:
        p = ROOT / entry
        yield from ([p] if p.is_file() else sorted(p.rglob("*.py")))


def test_no_prediction_or_forecast_wording_in_user_facing_text():
    bad = []
    for f in _files():
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            cleaned = line
            for ok in ALLOWED_PHRASES:
                cleaned = re.sub(ok, "", cleaned, flags=re.IGNORECASE)
            if WORD.search(cleaned):
                bad.append(f"{f.relative_to(ROOT)}:{n}: {line.strip()[:100]}")
    assert not bad, "user-facing wording must say 'estimated from the current rain rate':\n" + "\n".join(bad)


def test_elevation_is_never_typed_observed():
    """Owner decision 2026-10-29: elevation (online DEM or a local raster) is 'Reference data (DEM)'; the Observed type is for measurements."""
    from core.presentation import registry
    assert registry.REFERENCE == "Reference data (DEM)"
    assert [f.key for f in registry.FIELDS.values() if "elevation" in f.key + f.label.lower() and f.kind == registry.OBSERVED] == []
    assert registry.FIELDS["samples"].kind == registry.REFERENCE
