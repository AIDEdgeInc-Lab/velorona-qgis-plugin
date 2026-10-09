"""Real library objects for the presentation tests -- the analysis functions are
the libraries' own; only the network edge (elevation lookup, weather) is fixed."""
from types import SimpleNamespace

import aei_link_clearance.terrain as terrain_mod
from aei_link_clearance import analyze_link
from aei_mw_exposure import MicrowaveLink, MicrowaveSite, Provenance, calculate_exposure
from aei_mw_exposure.representativeness import assess_representativeness
from aei_mw_exposure.weather import WeatherObservation

A = (43.70, -79.40)
B = (43.80, -79.20)


def terrain_result(ground_m=100.0, h_a=30.0, h_b=30.0, freq=11.5, hump_m=0.0, monkeypatch=None):
    """Real analyze_link over synthetic flat terrain (+ optional hump in the middle)."""
    def elevations(points):
        n = len(points)
        out = []
        for i in range(n):
            mid = 1 - abs(2 * i / (n - 1) - 1)  # 0 at the ends, 1 in the middle
            out.append(ground_m + hump_m * mid)
        return out
    original = terrain_mod.get_elevations
    terrain_mod.get_elevations = elevations
    try:
        r = analyze_link("T-1", A[0], A[1], h_a, B[0], B[1], h_b, freq)
    finally:
        terrain_mod.get_elevations = original
    return SimpleNamespace(
        kind="terrestrial", site_a_name="Site A", site_b_name="Site B",
        site_a_source="Selected QGIS feature", site_b_source="Selected QGIS feature",
        site_a_height_m=h_a, site_b_height_m=h_b, site_a_height_from_feature=False,
        site_b_height_from_feature=True, result=r, explanation="(library explain text)")


def _site(id_, name, point):
    return MicrowaveSite(id=id_, name=name, latitude=point[0], longitude=point[1],
                         provenance=Provenance.USER_PROVIDED, source="test")


def obs(site, rain, temp=10.0, wind=10.0, ts="2026-10-06T20:00"):
    return WeatherObservation(latitude=site.latitude, longitude=site.longitude, timestamp=ts, rain_rate_mm_h=rain,
                              source="open-meteo", temperature_c=temp, wind_speed_kmh=wind, site_id=site.id)


def weather_result(rain_a=2.4, rain_b=0.5, freq=18.0, fade_margin=32.0, history=None, station=True):
    sa, sb = _site("A", "Site A", A), _site("B", "Site B", B)
    link = MicrowaveLink(id="L", site_a=sa, site_b=sb, frequency_ghz=freq, polarization="V",
                         fade_margin_db=fade_margin, provenance=Provenance.USER_PROVIDED, source="test")
    by_site = {"A": obs(sa, rain_a), "B": obs(sb, rain_b)}
    exposure = calculate_exposure(link, by_site)
    reps = {}
    for s in (sa, sb):
        st = None
        if station:
            st = WeatherObservation(latitude=s.latitude + 0.04, longitude=s.longitude, timestamp="2026-10-06T19:55:00Z",
                                    rain_rate_mm_h=0.2, source="ECCC SWOB-Realtime -- BRAMPTON", site_id="BRAMPTON")
        reps[s.id] = assess_representativeness(
            site=s, nearest_station=st, station_distance_km=4.8 if st else None,
            station_reports_precipitation=True, model_observation=by_site[s.id])
    return SimpleNamespace(kind="microwave-exposure", exposure=exposure, representativeness=reps,
                           weather_errors={}, history=history or {})
