"""Frequency-origin channel (spec F.1, owner-approved P9): a frequency is Observed only if it is the record's own value; a value the user typed
or changed is Assumed. Also: wording that names the register follows the record's source (Canada unchanged), and every exported decision
carries the spec section G identity / source lines. No network: the elevation edge is faked, the library's own analysis runs."""
import csv
import io
import sys
import types

import pytest
import requests

if "qgis" not in sys.modules:
    try:
        import qgis.core  # noqa: F401
    except ImportError:
        class _P:
            def __init__(self, *a, **k): pass
        _q, _qc = types.ModuleType("qgis"), types.ModuleType("qgis.core")
        for _n in ("QgsCoordinateReferenceSystem", "QgsCoordinateTransform", "QgsProject"):
            setattr(_qc, _n, _P)
        _q.core = _qc
        sys.modules["qgis"], sys.modules["qgis.core"] = _q, _qc

from core import evidence_record, export  # noqa: E402
from core import record_source as RS  # noqa: E402
from core.engines import microwave_exposure as MW  # noqa: E402
from core.engines import terrestrial as TR  # noqa: E402

A, B = (43.70, -79.40), (43.80, -79.20)
PARAMS = {"site_a_height_m": 30.0, "site_b_height_m": 30.0, "frequency_ghz": 6.22689}

ATTRIBUTION = ("Source: U.S. Federal Communications Commission, Universal Licensing System (ULS) public access database, "
               "microwave services (l_micro). Data as published; not endorsed by the FCC.")
CA = {"id": "ised-fixed-link-010029391-004", "authorization_number": "010029391-004",
      "source": "ISED SMS Authorization Data Extract: Fixed Service, Open Government Licence - Canada",
      "frequencies_mhz": "5945.2, 5974.85, 6197.24, 6226.89", "coverage": "National (Canada-wide) -- snapshot, not a live query"}
US = {"id": "fcc-link-1001939-1", "authorization_number": "WMJ504-1", "country": "US",
      "source": "FCC ULS public access database: Microwave (l_micro), U.S. Federal Communications Commission",
      "frequencies_mhz": "11245, 6078.625", "coverage": "United States -- snapshot, not a live query",
      "attribution": ATTRIBUTION, "pack_generated": "2026-10-03", "source_file_updated": "2026-09-27", "pack_input_sha256": "177254c8"}


class _Resp:
    def __init__(self, body): self.body = body
    def raise_for_status(self): pass
    def json(self): return self.body


@pytest.fixture(autouse=True)
def flat_terrain(monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **k: _Resp({"elevation": [100.0] * 50}))


def table(csv_text):
    body = "".join(ln for ln in io.StringIO(csv_text) if not ln.startswith("#"))
    return {r[0]: r for r in list(csv.reader(io.StringIO(body)))[1:]}


def preamble(csv_text):
    return [ln[2:].rstrip("\n") for ln in io.StringIO(csv_text) if ln.startswith("# ")]


# --- pure rule ---------------------------------------------------------------------------------------------------------------------
def test_highest_published_frequency_is_used():
    assert RS.frequency_ghz_from_record("5945.2, 6226.89, 5974.85")[0] == pytest.approx(6.22689)
    assert RS.frequency_ghz_from_record("11245, 6078.625")[0] == pytest.approx(11.245)


@pytest.mark.parametrize("raw", [None, "", "abc", "nan", "inf, nan"])
def test_unusable_record_frequency_is_none_with_a_reason(raw):
    ghz, note = RS.frequency_ghz_from_record(raw)
    assert ghz is None and note


def test_origin_rule():
    assert RS.frequency_origin(6.22689, "n", 6.22689)[0] == "Observed"
    assert RS.frequency_origin(6.22689, "n", 7.0)[0] == "Assumed"
    kind, note = RS.frequency_origin(6.22689, "n", 7.0)
    assert "6.22689" in note and "7" in note                     # the note says what the record said and what was entered
    assert RS.frequency_origin(None, "no frequency", 7.0)[0] == "Assumed"


# --- the engine and the export -------------------------------------------------------------------------------------------------
def run(link, used_ghz):
    return TR.analyze_link_record(link, A, B, {**PARAMS, "frequency_ghz": used_ghz})


def test_record_frequency_unchanged_is_observed_in_the_terrain_export():
    res = run(CA, 6.22689)
    row = table(export.result_to_csv(res))["Frequency"]
    assert row[1] == "Observed" and row[2].startswith("ISED record -- ") and row[3] == "6.22689 GHz"


def test_record_frequency_overridden_is_assumed_and_says_so():
    res = run(CA, 7.0)
    row = table(export.result_to_csv(res))["Frequency"]
    assert row[1] == "Assumed" and "6.22689" in row[5] and "7" in row[3]


def test_us_record_frequency_is_observed_with_the_fcc_prefix():
    row = table(export.result_to_csv(run(US, 11.245)))["Frequency"]
    assert row[1] == "Observed" and row[2].startswith("FCC ULS record -- ")


def test_two_site_flow_is_unchanged_and_still_assumed():
    res = types.SimpleNamespace(**{**run(CA, 6.22689).__dict__, "frequency_origin": None, "record": None})
    row = table(export.result_to_csv(res))["Frequency"]
    assert row[1] == "Assumed" and "user-provided" in row[5].lower()


def test_user_entered_values_other_than_the_frequency_stay_assumed():
    rows = table(export.result_to_csv(run(US, 11.245)))
    assert rows["Site A antenna height"][1] == "Assumed" and rows["Site B antenna height"][1] == "Assumed"


def test_a_record_without_a_frequency_can_not_be_observed():
    res = run({**CA, "frequencies_mhz": ""}, 7.0)
    assert table(export.result_to_csv(res))["Frequency"][1] == "Assumed"


def test_link_flow_validation_still_produces_no_data_not_a_guess():
    from core.validation import NoDataError
    with pytest.raises(NoDataError):
        TR.analyze_link_record(CA, A, A, PARAMS)           # identical endpoints
    with pytest.raises(NoDataError):
        TR.analyze_link_record(CA, A, B, {**PARAMS, "frequency_ghz": 500.0})


# --- wording follows the record's source ------------------------------------------------------------------------------------------
def test_canadian_weather_wording_is_unchanged():
    params, origins = MW.build_link_params(CA)
    assert origins["polarization"][1] == "Engine default (V); not published in the ISED Fixed Service extract."
    assert origins["fade_margin_db"][1] == "Engine default (32 dB); not published in the ISED Fixed Service extract."
    assert origins["frequency_ghz"][0] == "Observed" and params["frequency_ghz"] == pytest.approx(6.22689)


def test_us_weather_wording_names_the_fcc_and_never_ised():
    params, origins = MW.build_link_params(US)
    assert "FCC ULS" in origins["polarization"][1] and "ISED" not in origins["polarization"][1] + origins["fade_margin_db"][1]
    assert origins["frequency_ghz"][0] == "Observed" and params["frequency_ghz"] == pytest.approx(11.245)


def test_fcc_detection():
    assert RS.is_fcc(US) and not RS.is_fcc(CA) and RS.is_fcc({"country": "us"})


# --- spec G identity / source lines -------------------------------------------------------------------------------------------------
def test_terrain_export_carries_identity_convention_and_data_source():
    pre = "\n".join(preamble(export.result_to_csv(run(US, 11.245))))
    assert "Product: Velorona for QGIS 1.1.5; decision spec 0.3" in pre
    assert "aei-link-clearance 0." in pre
    assert "Earth-curvature convention: bulge-added-to-terrain" in pre
    assert ATTRIBUTION in pre and "source file dated 2026-09-27" in pre and "pack built 2026-10-03" in pre
    assert "not a field measurement" in pre and "30 m default" in pre and "sha256 177254c8" in pre


def test_canadian_export_names_its_register_and_snapshot_hash():
    pre = "\n".join(preamble(export.result_to_csv(run(CA, 6.22689))))
    assert "Open Government Licence - Canada" in pre
    assert "bundled fixed_service_snapshot.json, sha256 f9daa05e51a38a8083d50513d63c7c173caa1ffd5257011af54aed11ce1387c8" in pre


def test_identity_lines_do_not_enter_the_evidence_table():
    t = table(export.result_to_csv(run(US, 11.245)))
    assert not any(k.startswith(("Product", "Libraries", "Data source", "Earth-curvature")) for k in t)


def test_single_record_exports_carry_the_attribution():
    link_csv = export.link_feature_to_csv(US, A, B)
    assert ATTRIBUTION in link_csv
    site_csv = export.feature_to_csv({**US, "name": "x"}, 1.0, 2.0)
    assert ATTRIBUTION in site_csv


def test_product_version_comes_from_metadata():
    assert evidence_record.product_version() == "1.1.5"


# --- antenna heights: the same rule (spec F.2: Observed only if the record carries it; F.1: overridden -> Assumed) ---------------------------------
US_H = {**US, "site_a_height_m": 32.5, "site_b_height_m": 45.0,
        "height_source": "antenna height to centre (FCC field 'Height to Center RAAT'), licensee-reported record value, metres, "
                         "interpreted as above ground; not a field measurement"}


def run_h(link, ha, hb, f=11.245):
    return TR.analyze_link_record(link, A, B, {"site_a_height_m": ha, "site_b_height_m": hb, "frequency_ghz": f})


def test_record_heights_are_the_dialog_defaults():
    defaults, ghz, _ = TR.build_link_params(US_H)
    assert defaults["site_a_height_m"] == 32.5 and defaults["site_b_height_m"] == 45.0 and ghz == pytest.approx(11.245)
    plain, _, _ = TR.build_link_params(US)
    assert plain["site_a_height_m"] == 30.0                      # no record height -> the engine default


def test_record_height_unchanged_is_observed_with_the_records_source_text():
    rows = table(export.result_to_csv(run_h(US_H, 32.5, 45.0)))
    assert rows["Site A antenna height"][1] == "Observed" and "Height to Center RAAT" in rows["Site A antenna height"][2]
    assert rows["Site B antenna height"][1] == "Observed" and rows["Site A antenna height"][3] == "32.5 m"


def test_one_height_overridden_only_that_one_becomes_assumed():
    rows = table(export.result_to_csv(run_h(US_H, 40.0, 45.0)))
    assert rows["Site A antenna height"][1] == "Assumed" and "32.5" in rows["Site A antenna height"][2]
    assert rows["Site B antenna height"][1] == "Observed"


def test_a_record_without_heights_keeps_them_assumed():
    rows = table(export.result_to_csv(run_h(US, 30.0, 30.0)))
    assert rows["Site A antenna height"][1] == "Assumed" and rows["Site B antenna height"][1] == "Assumed"


@pytest.mark.parametrize("bad", [0.0, -3.0, 1000.5, 2694.7])
def test_record_height_outside_0_1_to_1000_m_is_no_data_never_clamped(bad):
    from core.validation import NoDataError
    with pytest.raises(NoDataError) as exc:
        run_h({**US_H, "site_a_height_m": bad}, bad, 45.0)
    assert any("height" in r.lower() for r in exc.value.reasons)


def test_non_numeric_record_height_is_treated_as_absent():
    assert TR.record_heights({**US_H, "site_a_height_m": "tall"})[0] is None
    assert TR.record_heights({**US_H, "site_a_height_m": float("nan")})[0] is None
    assert TR.record_heights({**US_H, "site_a_height_m": True})[0] is None
