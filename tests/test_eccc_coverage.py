"""ECCC radar is used for sites in Canada only: a US (or other) site is not asked, shows "not covered", and nothing from the radar is stored."""
import os
import sys
import types

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import test_no_data as ND  # noqa: E402  (installs the qgis stand-in when QGIS is absent)
from core import eccc_coverage  # noqa: E402
from core.engines import microwave_exposure as MW  # noqa: E402

CANADA = {"Toronto": (43.65, -79.38), "Vancouver": (49.28, -123.12), "Victoria": (48.43, -123.37), "Calgary": (51.05, -114.07),
          "Winnipeg": (49.9, -97.14), "Halifax": (44.65, -63.57), "Montreal": (45.5, -73.57), "Whitehorse": (60.72, -135.05),
          "St John's": (47.56, -52.71), "Thunder Bay": (48.38, -89.25), "Iqaluit": (63.75, -68.52), "Fredericton": (45.96, -66.64),
          "Sault Ste. Marie ON": (46.52, -84.35), "Prince Rupert": (54.31, -130.32), "Kingston": (44.23, -76.48)}
OUTSIDE = {"Phoenix": (33.45, -112.07), "Seattle": (47.6, -122.33), "Chicago": (41.88, -87.63), "Minneapolis": (44.98, -93.27),
           "Boston": (42.36, -71.06), "Rochester NY": (43.16, -77.61), "Portland ME": (43.66, -70.26), "Anchorage": (61.2, -149.9),
           "Havana": (23.1, -82.4), "Honolulu": (21.3, -157.8), "Monterrey": (25.67, -100.3), "Sault Ste. Marie MI": (46.49, -84.35),
           "Cleveland": (41.5, -81.69), "Juneau": (58.3, -134.4)}


@pytest.mark.parametrize("name", sorted(CANADA))
def test_canadian_places_are_covered(name):
    assert eccc_coverage.covers(*CANADA[name]), name


@pytest.mark.parametrize("name", sorted(OUTSIDE))
def test_places_outside_canada_are_not(name):
    assert not eccc_coverage.covers(*OUTSIDE[name]), name


def _run(monkeypatch, a, b):
    asked = []
    fake = types.SimpleNamespace(latitude=0, longitude=0, timestamp="2026-10-30T23:06:00Z", rain_rate_mm_h=0.0, source="ECCC Radar (RADAR_1KM_RRAI, radar-estimated, not gauge-measured)")
    monkeypatch.setattr(MW.eccc, "find_nearest_station", lambda *x, **k: None)
    monkeypatch.setattr(MW.eccc, "get_radar_precipitation", lambda lat, lon, **k: asked.append((lat, lon)) or fake)
    def no_history(*_a, **_k): raise RuntimeError("history is context only")
    current = {"time": "2026-10-30T22:00", "interval": 900, "rain": 0.0, "showers": 0.0, "snowfall": 0.0, "precipitation": 0.0}
    result = MW.analyze_link_record(a, b, {"authorization_number": "X-1", "source": "t"}, ND.GOOD_W, provider=ND._provider(current), history_fetcher=no_history)
    return result, asked


def test_a_us_link_never_asks_the_radar_and_has_no_radar_value(monkeypatch):
    result, asked = _run(monkeypatch, (33.45, -112.07), (33.55, -112.07))
    assert asked == []
    assert all(rep.radar_observation is None for rep in result.representativeness.values())


def test_a_canadian_link_asks_the_radar_for_both_sites_and_keeps_a_real_zero(monkeypatch):
    result, asked = _run(monkeypatch, (44.0, -79.4), (44.1, -79.4))
    assert len(asked) == 2
    assert all(rep.radar_observation is not None and rep.radar_observation.rain_rate_mm_h == 0.0 for rep in result.representativeness.values())


def test_the_export_says_not_covered_for_a_us_site(monkeypatch):
    from core import export
    result, _ = _run(monkeypatch, (33.45, -112.07), (33.55, -112.07))
    text = export.export_csv(result, include_names=True)
    assert "Radar precipitation" in text and "Not covered: the ECCC radar is used for sites in Canada only." in text


def test_a_radar_value_that_got_here_for_a_us_site_is_not_stored_or_shown(monkeypatch, tmp_path):
    import dataclasses
    from core import history_capture, history_store
    from core.presentation import weather
    result, _ = _run(monkeypatch, (33.45, -112.07), (33.55, -112.07))
    forged = types.SimpleNamespace(latitude=33.45, longitude=-112.07, timestamp="2026-10-30T23:06:00Z", rain_rate_mm_h=0.0, source="ECCC Radar (forged)")
    result.representativeness = {k: dataclasses.replace(rep, radar_observation=forged) for k, rep in result.representativeness.items()}
    result.utc_offsets = {sid: 0 for sid in result.representativeness}
    records, _skipped = history_capture.records_from_result(result, history_store.HistoryStore(str(tmp_path / "h.sqlite")), 1_790_000_000.0)
    assert records and not [r for r in records if "forged" in r.source]
    rep = next(iter(result.representativeness.values()))
    assert weather._site_weather(rep, "Site A", (33.45, -112.07)).radar_rain_mm_h is None
