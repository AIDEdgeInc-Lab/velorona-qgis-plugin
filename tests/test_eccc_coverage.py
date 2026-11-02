"""ECCC radar is used inside Canada only, with the Map's own outline: a place outside is not asked, shows "Not covered", and nothing from the radar is
stored. 0 disagreements with the Map's ecccRadarCovers on the shared place list (tests/fixtures/radar_places.json)."""
import json
import os
import re
import shutil
import subprocess
import sys
import types

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

import test_no_data as ND  # noqa: E402  (installs the qgis stand-in when QGIS is absent)
from core import eccc_coverage  # noqa: E402
from core.engines import microwave_exposure as MW  # noqa: E402

PLACES = json.load(open(os.path.join(HERE, "fixtures", "radar_places.json"), encoding="utf-8"))["places"]
MAP_JS = os.path.join(os.environ.get("MAP_REPO", ""), "web", "eccc_coverage.js")


def test_the_shared_list_has_at_least_67_places():
    assert len(PLACES) >= 67 and any(p["covered"] for p in PLACES) and any(not p["covered"] for p in PLACES)


@pytest.mark.parametrize("place", PLACES, ids=[p["name"] for p in PLACES])
def test_same_answer_as_the_map_for_every_shared_place(place):
    assert eccc_coverage.covers(place["lat"], place["lon"]) is place["covered"], place["name"]


@pytest.mark.parametrize("name,lat,lon", [("Phoenix", 33.432, -112.073), ("Skagway AK", 59.46, -135.31), ("Ogdensburg NY", 44.69, -75.49), ("Calais ME", 45.19, -67.28)])
def test_us_places_are_not_covered(name, lat, lon):
    assert not eccc_coverage.covers(lat, lon), name


@pytest.mark.parametrize("name,lat,lon", [("Ajax link A", 43.8475, -79.04333), ("Coppin's Corners", 44.03186, -79.13678), ("Toronto", 43.65, -79.38), ("Whitehorse", 60.72, -135.05)])
def test_canadian_places_are_covered(name, lat, lon):
    assert eccc_coverage.covers(lat, lon), name


@pytest.mark.parametrize("bad", [(float("nan"), 1), (1, float("nan")), (None, 1), ("43", "-79"), (None, None), (True, False), (float("inf"), 0)])
def test_anything_that_is_not_a_pair_of_finite_numbers_is_not_covered(bad):
    assert eccc_coverage.covers(*bad) is False


def test_the_outline_equals_the_maps_and_the_maps_function_agrees_everywhere():
    if not os.path.exists(MAP_JS):
        return                                               # no Map checkout: the stored answers above are the check
    sys.path.insert(0, os.path.join(os.path.dirname(HERE), "tools"))
    import sync_eccc_coverage
    assert sync_eccc_coverage.read_rings(os.environ["MAP_REPO"]) == json.load(open(eccc_coverage.PATH, encoding="utf-8"))["rings"], \
        "core/eccc_coverage.json drifted from the Map's outline; run tools/sync_eccc_coverage.py"
    if shutil.which("node"):
        js = "const {ecccRadarCovers}=require(process.argv[1]);const p=JSON.parse(process.argv[2]);console.log(JSON.stringify(p.map(([a,b])=>ecccRadarCovers(a,b))));"
        out = subprocess.run(["node", "-e", js, MAP_JS, json.dumps([[p["lat"], p["lon"]] for p in PLACES])], capture_output=True, text=True, check=True).stdout
        theirs = json.loads(out)
        assert [p["name"] for p, t in zip(PLACES, theirs) if eccc_coverage.covers(p["lat"], p["lon"]) != t] == []


def test_the_message_is_in_the_registry_with_the_maps_words():
    from core import messages
    assert messages.has(eccc_coverage.MESSAGE_ID) and "Radar not covered" in eccc_coverage.short_text()
    assert eccc_coverage.NOT_COVERED.startswith("Not covered: ECCC radar is used only inside Canada")


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
    result, asked = _run(monkeypatch, (33.41531, -112.06958), (33.44808, -112.07708))      # the Phoenix FCC link
    assert asked == []
    assert all(rep.radar_observation is None for rep in result.representativeness.values())


def test_a_canadian_link_asks_the_radar_for_both_sites_and_keeps_a_real_zero(monkeypatch):
    result, asked = _run(monkeypatch, (43.8475, -79.04333), (44.03186, -79.13678))         # the Ajax link
    assert len(asked) == 2
    assert all(rep.radar_observation is not None and rep.radar_observation.rain_rate_mm_h == 0.0 for rep in result.representativeness.values())


def test_the_export_says_not_covered_for_a_us_site(monkeypatch):
    from core import export
    result, _ = _run(monkeypatch, (33.41531, -112.06958), (33.44808, -112.07708))
    text = export.result_to_csv(result)
    assert "Radar precipitation" in text and eccc_coverage.NOT_COVERED in text and "0.0 mm/h (estimated" not in text


def test_a_radar_value_that_got_here_for_a_us_site_is_not_stored_or_shown(monkeypatch, tmp_path):
    import dataclasses
    from core import history_capture, history_store
    from core.presentation import weather
    result, _ = _run(monkeypatch, (33.41531, -112.06958), (33.44808, -112.07708))
    forged = types.SimpleNamespace(latitude=33.4, longitude=-112.0, timestamp="2026-10-30T23:06:00Z", rain_rate_mm_h=0.0, source="ECCC Radar (forged)")
    result.representativeness = {k: dataclasses.replace(rep, radar_observation=forged) for k, rep in result.representativeness.items()}
    result.utc_offsets = {sid: 0 for sid in result.representativeness}
    records, _skipped = history_capture.records_from_result(result, history_store.HistoryStore(str(tmp_path / "h.sqlite")), 1_790_000_000.0)
    assert records and not [r for r in records if "forged" in r.source]
    rep = next(iter(result.representativeness.values()))
    assert weather._site_weather(rep, "Site A", (33.41531, -112.06958)).radar_rain_mm_h is None


def test_the_panel_html_says_not_covered_for_a_us_site(monkeypatch):
    src = open(os.path.join(os.path.dirname(HERE), "ui", "results_dock.py"), encoding="utf-8").read()
    assert len(re.findall(r"eccc_coverage\.covers\(rep\.site\.latitude, rep\.site\.longitude\)", src)) == 2     # evidence rows and details rows
