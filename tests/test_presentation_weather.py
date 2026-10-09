"""Weather brief, history comparison, station provenance, and the library
defaults this layer quotes."""
import inspect

import pytest
from aei_mw_exposure import representativeness as lib_rep
from aei_mw_exposure.providers import eccc
from presentation_fixtures import weather_result

from core.presentation import history as H
from core.presentation import weather as W
from core.presentation.model import AT_RISK, CLEAR, CRITICAL, NO_DATA, WATCH

# A real Open-Meteo response (Toronto, captured 2026-10-06 20:00 local) plus one
# forecast hour appended after `current.time`, which must not count as history.
REAL = {
    "timezone": "America/Toronto",
    "current": {"time": "2026-10-06T20:00", "temperature_2m": 10.9, "rain": 0.0, "wind_speed_10m": 9.9},
    "hourly": {
        "time": ["2026-10-06T16:00", "2026-10-06T17:00", "2026-10-06T18:00", "2026-10-06T19:00",
                 "2026-10-06T20:00", "2026-10-06T21:00"],
        "temperature_2m": [13.9, 13.7, 13.0, 11.5, 10.9, 10.4],
        "rain": [0.0, 0.0, 0.0, 0.0, 0.0, 0.3],
        "wind_speed_10m": [11.4, 12.1, 9.8, 7.9, 9.9, 9.0],
    },
}


def _history(site="A"):
    return H.parse_history(REAL, site, 43.7, -79.4, 0.0)


def test_station_defaults_match_the_library():
    sig = inspect.signature(eccc.find_nearest_station).parameters
    assert W.STATION_SEARCH_RADIUS_KM == sig["search_radius_km"].default
    assert W.STATION_WINDOW_MINUTES == sig["window_minutes"].default
    assert lib_rep.DEFAULT_MAX_STATION_DISTANCE_KM == 50.0


def test_parse_history_drops_forecast_hours():
    h = _history()
    assert [p.time[-5:] for p in h.points] == ["16:00", "17:00", "18:00", "19:00", "20:00"]
    assert h.latest.temperature_c == 10.9


def test_changes_against_real_data():
    h = _history()
    t = H.compare(h, "temperature", 1)       # 11.5 -> 10.9
    assert (t.direction, round(t.delta, 1), t.baseline) == ("down", -0.6, "vs 1 hour ago")
    w = H.compare(h, "wind", 2)              # 9.8 -> 9.9 at 2 h back: +0.1
    assert (w.direction, round(w.delta, 1)) == ("up", 0.1)
    r = H.compare(h, "rain", 3)
    assert r.direction == "flat" and r.delta_text == "\u2192 No change"
    assert H.compare(h, "rain", 5) is None   # only 4 hours of history exist
    assert H.available_hours(h) == 4
    assert t.text == "10.9 °C   ↓ -0.6 °C vs 1 hour ago"


def test_missing_values_are_not_filled_in():
    data = {**REAL, "hourly": {**REAL["hourly"], "wind_speed_10m": [None] * 6}}
    h = H.parse_history(data, "A", 0, 0, 0.0)
    assert H.compare(h, "wind", 1) is None
    assert [c.label for c in H.changes(h, 1)] == ["Hourly rain", "Temperature"]


def test_fetch_uses_injected_getter_and_reports_failures():
    calls = {}

    class Resp:
        def raise_for_status(self): pass
        def json(self): return REAL

    def get(url, params, timeout):
        calls.update(params)
        return Resp()

    h = H.fetch_weather_history("A", 43.7, -79.4, hours=6, get=get)
    assert calls["past_hours"] == 6 and h.points[-1].time == "2026-10-06T20:00"

    class Bad:
        def raise_for_status(self): raise RuntimeError("503")
    with pytest.raises(RuntimeError):
        H.fetch_weather_history("A", 0, 0, get=lambda *a, **k: Bad())


def _band_cases():
    """Predicted attenuation comes from the library; the fade margin is chosen to
    land each library severity band, so the test cannot drift from its rules."""
    base = weather_result(rain_a=12.0, rain_b=1.0, fade_margin=32.0)
    fade = base.exposure.attenuation.predicted_attenuation_db
    return fade


def test_status_mapping_covers_every_band():
    fade = _band_cases()
    cases = {CLEAR: fade / 0.1, WATCH: fade / 0.5, AT_RISK: fade / 0.8, CRITICAL: fade * 0.9}
    for want, margin in cases.items():
        res = weather_result(rain_a=12.0, rain_b=1.0, fade_margin=margin)
        b = W.exposure_brief(res)
        assert b.status == want, (want, b.status, res.exposure.exposure_ratio if hasattr(res.exposure, "exposure_ratio") else None)
        assert b.reason


def test_critical_means_fade_exceeds_margin():
    fade = _band_cases()
    b = W.exposure_brief(weather_result(rain_a=12.0, rain_b=1.0, fade_margin=fade * 0.9))
    assert "larger than the fade margin" in b.reason
    assert b.data["fade_remaining_db"] == pytest.approx(b.data["fade_margin_db"] - b.data["predicted_attenuation_db"])
    assert b.data["fade_remaining_db"] < 0


def test_numbers_come_straight_from_the_library():
    res = weather_result()
    b = W.exposure_brief(res)
    e = res.exposure
    assert b.data["predicted_attenuation_db"] == e.attenuation.predicted_attenuation_db
    assert b.data["rain_rate_mm_h"] == e.rain_rate_mm_h == 2.4
    assert b.data["driver_site"] == "Site A"
    assert b.data["exposure_ratio"] == e.exposure_ratio
    facts = {f.label: f for f in b.key_facts}
    assert facts["Rain rate used"].value == "2.4 mm/h"
    assert "Site A" in facts["Rain rate used"].comparison and "0.5 mm/h at Site B" in facts["Rain rate used"].comparison


def test_station_provenance_is_explicit():
    b = W.exposure_brief(weather_result())
    s = b.sites[0]
    assert s.station_name == "BRAMPTON"
    assert s.station_distance_km == 4.8
    assert s.station_time == "2026-10-06T19:55:00Z"
    assert s.kind.startswith("Model-derived")
    assert "Nearest ECCC station" in W.SELECTION_STATION and "50 km" in W.SELECTION_STATION
    assert s.station_point is not None


def test_no_station_is_stated_not_hidden():
    b = W.exposure_brief(weather_result(station=False))
    assert b.sites[0].station_name is None and b.sites[0].station_distance_km is None
    assert b.sites[0].representativeness == W.LEVEL_TEXT["insufficient_evidence"]


def test_trend_is_attached_when_history_exists():
    res = weather_result(history={"A": _history("A")})
    b = W.exposure_brief(res)
    assert any(c.baseline == "vs 1 hour ago" for c in b.changes)
    assert any(c.baseline == "vs 3 hours ago" for c in b.changes)
    assert "Hourly model rain" in b.answer and ("unchanged" in b.answer or "than" in b.answer)


def test_no_exposure_is_no_data():
    b = W.exposure_brief(None, weather_error="timeout")
    assert b.status == NO_DATA and b.reason == "timeout"


def test_assumed_inputs_are_called_out():
    origins = {"fade_margin_db": ("Assumed", "Engine default (32 dB)"), "frequency_ghz": ("Observed", "from record")}
    b = W.exposure_brief(weather_result(), param_origins=origins)
    assert any("fade margin" in c for c in b.caveats)
