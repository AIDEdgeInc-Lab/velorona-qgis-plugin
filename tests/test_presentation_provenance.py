"""Regression tests for the provenance / precipitation-type corrections:
Open-Meteo values are Model-derived everywhere, snow is never presented as rain,
and the critical point is defined as the library defines it."""
import csv
import io

import pytest
from aei_mw_exposure import MicrowaveSite, Provenance
from aei_mw_exposure.providers import open_meteo as lib_open_meteo
from presentation_fixtures import A, terrain_result, weather_result
from test_presentation_weather import _history

from core.export import result_to_csv, result_to_xlsx
from core.presentation import precip
from core.presentation.history import parse_history
from core.presentation.terrain import CRITICAL_POINT_DEFINITION, terrain_brief
from core.presentation.weather import exposure_brief
from core.presentation.workbook import raw_rows, context_for
from xlsx_reader import read_workbook
from core.sources.open_meteo_rain import TypedPrecipitationProvider
from core.validation import NoDataError

SITE = MicrowaveSite(id="S", name="S", latitude=A[0], longitude=A[1], provenance=Provenance.USER_PROVIDED)


class _Resp:
    def __init__(self, current): self._c = current
    def raise_for_status(self): pass
    def json(self): return {"current": {"time": "2026-10-06T20:15", "interval": 900, "temperature_2m": -2.0, "wind_speed_10m": 12.0, **self._c}}


def _rate(current):
    provider = TypedPrecipitationProvider(get=lambda url, params, timeout: _Resp(current))
    obs = provider.get_current(SITE)
    return obs.rain_rate_mm_h, provider.precipitation["S"]


# ---- 2. rain / snow / mixed / zero-rain-with-precipitation ----------------

def test_rain_only():
    rate, p = _rate({"precipitation": 2.4, "rain": 2.4, "showers": 0.0, "snowfall": 0.0})
    assert rate == pytest.approx(2.4 * 4) and not p.has_frozen and p.basis == precip.BASIS_SPLIT     # P8: mm over 900 s -> mm/h is x4
    assert p.precip_class == "RAIN"


def test_snow_only_is_not_rain():
    rate, p = _rate({"precipitation": 0.30, "rain": 0.0, "showers": 0.0, "snowfall": 2.1})      # 2.1 cm / 7 = 0.30 mm water equivalent
    assert rate == 0.0 and p.precip_class == "SNOW"
    assert p.has_frozen and p.frozen_mm == pytest.approx(0.30) and p.total_mm == 0.30


def test_mixed_rain_and_snow_counts_only_the_liquid_part():
    rate, p = _rate({"precipitation": 1.8, "rain": 1.0, "showers": 0.5, "snowfall": 2.1})
    assert rate == pytest.approx(1.5 * 4) and p.precip_class == "MIXED"           # (rain + showers) x4
    assert p.frozen_mm == pytest.approx(0.3) and p.has_frozen


def test_showers_are_liquid_rain():
    rate, p = _rate({"precipitation": 0.8, "rain": 0.0, "showers": 0.8, "snowfall": 0.0})
    assert rate == pytest.approx(0.8 * 4) and not p.has_frozen and p.precip_class == "SHOWERS"


def test_zero_rain_with_nonzero_total_and_type_reported_is_zero_rain():
    rate, _ = _rate({"precipitation": 0.6, "rain": 0.0, "showers": 0.0, "snowfall": 0.4})
    assert rate == 0.0


def test_type_not_reported_is_no_data_not_rain():
    """P7: unknown never silently becomes rain. This used to be total precipitation used as rain, with a label."""
    with pytest.raises(NoDataError, match="type not reported"):
        _rate({"precipitation": 0.6})            # source gives no rain/showers split


def test_nothing_reported_is_no_data():
    with pytest.raises(NoDataError):
        _rate({})


def test_freezing_is_flagged_and_never_substituted_by_the_total():
    rate, p = _rate({"precipitation": 1.2, "rain": 0.0, "showers": 0.0, "snowfall": 0.0, "weather_code": 67})
    assert p.precip_class == "FREEZING" and rate == 0.0 and "freezing_unquantified" in p.flags and p.has_freezing
    rate, p = _rate({"precipitation": 1.2, "rain": 1.2, "weather_code": 66})
    assert p.precip_class == "FREEZING" and rate == pytest.approx(1.2 * 4)


@pytest.mark.parametrize("interval,mult", [(900, 4.0), (3600, 1.0), (1800, 2.0)])
def test_conversion_is_3600_over_interval(interval, mult):
    provider = TypedPrecipitationProvider(get=lambda url, params, timeout: type("R", (), {
        "raise_for_status": lambda s: None,
        "json": lambda s: {"current": {"time": "t", "interval": interval, "rain": 1.0, "showers": 0.0, "precipitation": 1.0}}})())
    assert provider.get_current(SITE).rain_rate_mm_h == pytest.approx(mult)


def test_the_library_provider_does_have_the_defect(monkeypatch):
    """Documents why the plugin overrides it: snow-only becomes 'rain' in the library."""
    snow = {"precipitation": 0.30, "rain": 0.0, "showers": 0.0, "snowfall": 0.21}
    monkeypatch.setattr(lib_open_meteo.requests, "get",
                        lambda *a, **k: type("R", (), {"raise_for_status": lambda s: None,
                                                       "json": lambda s: {"current": {"time": "t", "interval": 900, **snow}}})())
    monkeypatch.setattr(lib_open_meteo.OpenMeteoProvider, "_fetch",
                        lambda self, site: {"current": {"time": "t", "interval": 900, **snow}})
    assert lib_open_meteo.OpenMeteoProvider().get_current(SITE).rain_rate_mm_h == 0.30  # the defect
    assert _rate(snow)[0] == 0.0                                                         # the plugin's fix


def test_hourly_history_excludes_snow_and_includes_showers():
    data = {"timezone": "x", "current": {"time": "2026-10-06T20:00"},
            "hourly": {"time": ["2026-10-06T19:00", "2026-10-06T20:00"],
                       "temperature_2m": [0.0, 0.0], "wind_speed_10m": [5.0, 5.0],
                       "rain": [0.0, 1.0], "showers": [0.0, 0.5], "snowfall": [0.4, 0.4]}}
    h = parse_history(data, "S", 0, 0, 0.0)
    assert [p.rain_mm_h for p in h.points] == [0.0, 1.5]


def test_snow_is_called_out_in_the_brief_csv_and_workbook():
    res = weather_result()
    res.precipitation = {"A": precip.classify({"interval": 900, "precipitation": 0.3, "rain": 0.0, "showers": 0.0, "snowfall": 2.1}),   # 2.1 cm = 0.3 mm w.e.
                         "B": precip.classify({"interval": 900, "precipitation": 0.0, "rain": 0.0, "showers": 0.0, "snowfall": 0.0})}
    b = exposure_brief(res)
    assert any("not counted as rain" in c and "does not change the status" in c for c in b.caveats)
    text = result_to_csv(res)
    assert "Not counted as rain" in text and "Precipitation class" in text and "Rain-rate conversion" in text
    wb = read_workbook(result_to_xlsx(res))
    weather = {r[0]: r for r in wb["WEATHER"] if r}
    assert "rain + showers" in str(weather["Precipitation basis"][1])
    assert weather["Total precipitation, model (mm/h)"][1] == pytest.approx(0.3 * 4)       # mm over 900 s -> mm/h


def test_unknown_type_is_no_data_never_labelled_rain():
    """P7: the source gave no rain/showers split -> NO DATA. (It used to be total precipitation used as rain with a caveat.)"""
    with pytest.raises(NoDataError, match="type not reported"):
        precip.classify({"interval": 900, "precipitation": 0.6})


# ---- 1. model values are Model-derived everywhere --------------------------

def _evidence_rows(res):
    body = "".join(l for l in io.StringIO(result_to_csv(res)) if not l.startswith("#"))
    return list(csv.reader(io.StringIO(body)))[1:]


def test_csv_types_open_meteo_values_as_model_derived():
    rows = _evidence_rows(weather_result())
    by_name = {r[0]: r for r in rows}
    assert by_name["Rain rate used"][1] == "Model-derived"
    model_rows = [r for r in rows if r[0].startswith("Model precipitation")]
    assert model_rows and all(r[1] == "Model-derived" for r in model_rows)
    for r in rows:
        if "Open-Meteo" in r[2] and "Elevation" not in r[2]:
            assert r[1] != "Observed", r
    # the station and radar rows keep their own types
    assert next(r for r in rows if r[0].startswith("Station precipitation"))[1] == "Observed"


def test_link_investigation_csv_is_model_derived_too():
    from types import SimpleNamespace
    mw = weather_result()
    entry = SimpleNamespace(data={"authorization_number": "X1"}, site_a_point=A, site_b_point=(43.8, -79.2))
    inv = SimpleNamespace(kind="link-investigation", entry=entry, exposure=mw, param_origins={}, weather_error=None)
    rows = _evidence_rows(inv)
    assert next(r for r in rows if r[0] == "Rain rate used")[1] == "Model-derived"
    failed = SimpleNamespace(kind="link-investigation", entry=entry, exposure=None, param_origins={}, weather_error="down")
    assert next(r for r in _evidence_rows(failed) if r[0] == "Weather evidence")[1] == "Model-derived"


def test_workbook_labels_model_values_and_history():
    res = weather_result(history={"A": _history("A"), "B": _history("B")})
    wb = read_workbook(result_to_xlsx(res))
    raw = {r[0]: r for r in wb["RAW DATA"] if r}
    for key in ("weather.Site A.model_rain_mm_h", "weather.Site A.model_temperature_c", "weather.rain_rate_mm_h"):
        assert raw[key][3] == "Model-derived", key
    assert raw["weather.Site A.station_rain_mm_h"][3] == "Observed"
    hist = wb["WEATHER HISTORY"]
    assert "model-derived" in hist[0][0] and "not station observations" in hist[0][0]
    assert any("not station observations" in str(c) for row in hist for c in row if c)
    weather = {r[0]: r for r in wb["WEATHER"] if r}
    assert "Model value time" in weather and "Observation time" not in weather
    assert "Observed" not in str(weather["Kind of value"])


def test_history_source_says_model_derived():
    assert "model-derived" in _history("A").source and "not station observations" in _history("A").source


# ---- 3. critical point definition -------------------------------------------

def test_critical_point_definition_is_stated_and_matches_the_library():
    assert "lowest" in CRITICAL_POINT_DEFINITION and "Fresnel" in CRITICAL_POINT_DEFINITION
    assert "not necessarily" in CRITICAL_POINT_DEFINITION
    b = terrain_brief(terrain_result(hump_m=20.0))
    assert CRITICAL_POINT_DEFINITION in b.caveats
    assert any(f.label == "Critical point" and f.meaning == CRITICAL_POINT_DEFINITION for f in b.technical)


def test_critical_point_can_differ_from_lowest_absolute_clearance():
    """The library picks lowest fraction-of-Fresnel; find a profile where that is not the fewest metres."""
    from core.presentation.terrain import critical_point
    for hump in range(0, 40):
        for ha, hb in ((30.0, 30.0), (10.0, 80.0), (80.0, 10.0)):
            r = terrain_result(hump_m=float(hump), h_a=ha, h_b=hb).result
            lowest_m = min((p for p in r.profile if p.percent_fresnel_clear is not None), key=lambda p: p.clearance_m)
            if critical_point(r) is not lowest_m:
                assert critical_point(r).percent_fresnel_clear <= lowest_m.percent_fresnel_clear
                return
    pytest.skip("no profile in the sweep separates the two definitions")


def test_workbook_critical_point_wording():
    wb = read_workbook(result_to_xlsx(terrain_result(hump_m=10.0)))
    la = {r[0]: r for r in wb["LINK ANALYSIS"] if r}
    assert CRITICAL_POINT_DEFINITION in la["Critical point, distance from Site A"][4]
    assert any("Critical point" in str(c) for c in wb["ELEVATION-TERRAIN"][0])
    d = {r[0]: r for r in wb["DATA DICTIONARY"] if r}
    assert "NOT the lowest absolute clearance" in d["terrain.critical_point"][2]
