"""Satellite geometry (core/engines/satellite_geometry.py) -- QGIS-free.

Checked three ways: against the independent Skyfield reference and the Map's own find-events output (reference.json), and against what the Map's JavaScript
implementation (satellite.js) outputs on the same inputs (js_golden.json) -- so Map <-> QGIS agreement on look angles, window boundaries, maximum elevation
and state is MEASURED here, not assumed. The orbits and stations are SYNTHETIC (tests/fixtures/satgeo/README.md): agreement proves the geometry code, not the accuracy of
any real element set, and not any link."""
import json
import os

import pytest

pytest.importorskip("skyfield")
from core.engines import satellite_geometry as G  # noqa: E402

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "satgeo")
REF = json.load(open(os.path.join(FIX, "reference.json"), encoding="utf-8"))
GOLD = json.load(open(os.path.join(FIX, "js_golden.json"), encoding="utf-8"))
# Set from the agreement measured when written (see test output notes in the PR) with margin; far tighter than any real element-set error.
TOL = {"el": 0.01, "az": 0.01, "range_km": 0.5, "boundary_s": 2.0, "max_el": 0.05, "max_time_s": 10.0}


def sat(key):
    s = G.satellite_from_omm(REF["orbits"][key])
    assert s is not None
    return s


def ang_diff(a, b):
    d = abs(a - b) % 360
    return min(d, 360 - d)


def secs(a, b):
    return abs((G.parse_utc(a) - G.parse_utc(b)).total_seconds())


def test_look_angles_match_the_skyfield_reference_and_the_map_javascript():
    for s, g in zip(REF["samples"], GOLD["samples"]):
        assert (s["orbit"], s["station"], s["time"]) == (g["orbit"], g["station"], g["time"])
        r = G.look_angles_at(sat(s["orbit"]), REF["stations"][s["station"]], s["time"])
        assert r["ok"], r
        for name, ref in (("reference", s), ("map javascript", g)):
            assert abs(r["elevation_deg"] - ref["elevation_deg"]) < TOL["el"], f"elevation vs {name}: {s['orbit']}/{s['station']}/{s['time']}"
            assert abs(r["range_km"] - ref["range_km"]) < TOL["range_km"], f"range vs {name}"
            if -80 < ref["elevation_deg"] < 89:
                assert ang_diff(r["azimuth_deg"], ref["azimuth_deg"]) < TOL["az"], f"azimuth vs {name}"


def test_windows_match_the_map_javascript_state_count_boundaries_and_maximum():
    for w in GOLD["windows"]:
        res = G.find_windows(sat(w["orbit"]), REF["stations"][w["station"]], w["start"], w["end"], w["mask_deg"])
        tag = f"{w['orbit']}/{w['station']}/{w['mask_deg']}"
        assert res["ok"], res
        assert res["state"] == w["state"], tag
        assert len(res["windows"]) == len(w["windows"]), f"{tag} window count"
        for mine, theirs in zip(res["windows"], w["windows"]):
            assert secs(mine["rise_utc"], theirs["rise"]) < TOL["boundary_s"], f"{tag} rise"
            assert secs(mine["set_utc"], theirs["set"]) < TOL["boundary_s"], f"{tag} set"
            assert abs(mine["max_elevation_deg"] - theirs["max_elevation_deg"]) < TOL["max_el"], f"{tag} max elevation"
            assert secs(mine["max_utc"], theirs["max"]) < TOL["max_time_s"], f"{tag} time of maximum"
            assert abs(mine["duration_sec"] - theirs["duration_sec"]) <= TOL["boundary_s"] * 2, f"{tag} duration"


def test_windows_match_the_independent_skyfield_find_events_reference():
    for w in REF["windows"]:
        res = G.find_windows(sat(w["orbit"]), REF["stations"][w["station"]], w["start"], w["end"], w["mask_deg"])
        rises = [e for e in w["events"] if e["event"] == 0]
        sets = [e for e in w["events"] if e["event"] == 2]
        culm = [e for e in w["events"] if e["event"] == 1]
        if not rises and culm:
            assert res["state"] == "always-above" and res["windows"] == []
            continue
        if not rises and not culm:
            assert res["state"] == "never-above" and res["windows"] == []
            continue
        assert len(res["windows"]) == len(rises)
        for i, win in enumerate(res["windows"]):
            assert secs(win["rise_utc"], rises[i]["time"]) < TOL["boundary_s"]
            assert secs(win["set_utc"], sets[i]["time"]) < TOL["boundary_s"]
            assert abs(win["max_elevation_deg"] - culm[i]["elevation_deg"]) < TOL["max_el"]
            assert win["max_elevation_deg"] >= w["mask_deg"] and win["duration_sec"] > 0
            assert not win["open_at_start"] and not win["open_at_end"]


def test_station_beneath_a_geo_type_satellite_sees_it_near_90_degrees_and_the_antipode_sees_it_below_the_horizon():
    r = G.look_angles_at(sat("geo"), REF["stations"]["under_geo"], REF["epoch"] + "Z")
    assert r["elevation_deg"] > 89.9 and 35700 < r["range_km"] < 35850
    sp = REF["geo_subpoint_epoch"]
    anti = {"latitude": -sp["latitude"], "longitude": sp["longitude"] - 180 if sp["longitude"] > 0 else sp["longitude"] + 180, "altitude_m": 0}
    assert G.look_angles_at(sat("geo"), anti, REF["epoch"] + "Z")["elevation_deg"] < -80


def test_a_higher_minimum_elevation_only_removes_or_shortens_windows():
    lo = G.find_windows(sat("leo53"), REF["stations"]["ottawa"], REF["epoch"], "2026-10-02T00:00:00Z", 10)
    hi = G.find_windows(sat("leo53"), REF["stations"]["ottawa"], REF["epoch"], "2026-10-02T00:00:00Z", 25)
    assert len(hi["windows"]) <= len(lo["windows"])
    for w in hi["windows"]:
        assert any(x["rise_utc"] <= w["rise_utc"] and x["set_utc"] >= w["set_utc"] for x in lo["windows"])
    assert sum(w["duration_sec"] for w in hi["windows"]) < sum(w["duration_sec"] for w in lo["windows"])


def test_windows_open_at_the_start_or_end_are_reported_as_open():
    w = next(x for x in REF["windows"] if (x["orbit"], x["station"], x["mask_deg"]) == ("leo53", "ottawa", 10))
    rise = G.parse_utc(next(e for e in w["events"] if e["event"] == 0)["time"])
    set_ = G.parse_utc(next(e for e in w["events"] if e["event"] == 2)["time"])
    mid = rise + (set_ - rise) / 2
    from datetime import timedelta
    a = G.find_windows(sat("leo53"), REF["stations"]["ottawa"], mid, set_ + timedelta(hours=1), 10)
    assert a["windows"][0]["rise_utc"] is None and a["windows"][0]["open_at_start"] and a["windows"][0]["duration_sec"] is None
    b = G.find_windows(sat("leo53"), REF["stations"]["ottawa"], rise - timedelta(hours=1), mid, 10)
    last = b["windows"][-1]
    assert last["set_utc"] is None and last["open_at_end"] and last["max_elevation_deg"] >= 10


def test_utc_handling_no_zone_means_utc_an_offset_is_honoured():
    s, st = sat("leo53"), REF["stations"]["ottawa"]
    z = G.look_angles_at(s, st, "2026-10-01T03:11:00Z")["elevation_deg"]
    assert z == G.look_angles_at(s, st, "2026-10-01T03:11:00")["elevation_deg"] == G.look_angles_at(s, st, "2026-09-30T23:11:00-04:00")["elevation_deg"]
    assert G.iso_ms(G.parse_utc("2026-10-01T00:00:00.123456")) == "2026-10-01T00:00:00.123Z"
    for bad in ("not a time", "", None, 12, "2026-13-01T00:00:00Z"):
        assert G.parse_utc(bad) is None


def test_invalid_inputs_are_refused_with_a_reason_never_computed():
    s, st = sat("leo53"), REF["stations"]["ottawa"]
    assert not G.look_angles_at(s, st, "garbage")["ok"]
    assert not G.look_angles_at(s, {"latitude": 91, "longitude": 0}, REF["epoch"])["ok"]
    assert not G.look_angles_at(s, {"latitude": float("nan"), "longitude": 0}, REF["epoch"])["ok"]
    assert not G.look_angles_at(s, {"latitude": 0, "longitude": 0, "altitude_m": "high"}, REF["epoch"])["ok"]
    assert not G.look_angles_at(None, st, REF["epoch"])["ok"]
    assert not G.find_windows(s, st, "2026-10-02T00:00:00Z", REF["epoch"], 10)["ok"]
    assert not G.find_windows(s, st, REF["epoch"], "2026-10-05T00:00:00Z", 10)["ok"]
    for m in (-1, 61, float("nan"), "10"):
        assert not G.find_windows(s, st, REF["epoch"], "2026-10-01T06:00:00Z", m)["ok"]
    assert not G.find_windows(s, st, "x", "y", 10)["ok"]


def test_an_unusable_element_set_is_none_and_a_failing_propagation_stops_the_search_with_a_reason():
    assert G.satellite_from_omm({"OBJECT_NAME": "NO ELEMENTS"}) is None
    assert G.satellite_from_tle("not", "a tle") is None
    # a corrupted real-format TLE (checksum no longer matches) is refused, not computed: sgp4 would happily parse it
    l1 = "1 25544U 98067A   20194.88612269 -.00002218  00000-0 -31515-4 0  9992"
    l2 = "2 25544  51.6461 221.2784 0001413  89.1723 280.4612 15.49507896236008"
    assert G.satellite_from_tle(l1, l2) is not None, "a well-formed TLE (public documentation example) is accepted"
    assert G.satellite_from_tle(l1[:-1] + "0", l2) is None and G.satellite_from_tle(l1, l2.replace("51.6461", "51.6462")) is None
    assert G.satellite_from_tle(l1, l2.replace("25544", "25545")) is None, "line 2 for a different catalogue number"
    decaying = G.satellite_from_omm({**REF["orbits"]["leo53"], "MEAN_MOTION": 16.2, "ECCENTRICITY": 0.02, "BSTAR": 0.5, "MEAN_MOTION_DOT": 0.01})
    if decaying is not None:
        r = G.find_windows(decaying, REF["stations"]["ottawa"], REF["epoch"], "2026-10-03T00:00:00Z", 10)
        assert not r["ok"] and "Propagation failed" in r["reason"]


def test_mask_resolution_default_and_typed_are_assumed_station_horizon_only_on_request_then_observed():
    assert G.resolve_mask({"min_horizon_deg": 30}) == {"ok": True, "deg": 10.0, "origin": "default", "type": "Assumed"}
    assert G.resolve_mask({"min_horizon_deg": 30}, None, True) == {"ok": True, "deg": 30.0, "origin": "station", "type": "Observed"}
    assert G.resolve_mask({"min_horizon_deg": 0}, None, True)["deg"] == 0.0     # 0 is a real published value, not "missing"
    for st in ({}, {"min_horizon_deg": None}, {"min_horizon_deg": 95}):
        assert not G.resolve_mask(st, None, True)["ok"]
    assert G.resolve_mask({"min_horizon_deg": 30}, 15, True)["origin"] == "user"
    assert not G.resolve_mask({}, 70)["ok"] and not G.resolve_mask({}, -1)["ok"] and not G.resolve_mask({}, "10")["ok"]


def test_element_set_age_fresh_aging_stale_on_either_side_unreadable_is_unknown():
    at = "2026-10-10T00:00:00Z"
    assert G.epoch_status("2026-10-09T00:00:00", at)["level"] == "fresh"
    assert G.epoch_status("2026-10-05T00:00:00", at)["level"] == "aging"
    assert G.epoch_status("2026-09-01T00:00:00", at)["level"] == "stale"
    assert G.epoch_status("2026-10-20T00:00:00", at)["level"] == "aging"
    assert G.epoch_status("2026-10-09T00:00:00", at)["age_days"] > 0 > G.epoch_status("2026-10-20T00:00:00", at)["age_days"]
    assert G.epoch_status("junk", at)["level"] == "unknown" and G.epoch_status(None, at)["level"] == "unknown"


def test_results_are_deterministic():
    a = G.find_windows(sat("issish"), REF["stations"]["sydney"], REF["epoch"], "2026-10-02T00:00:00Z", 10)
    b = G.find_windows(sat("issish"), REF["stations"]["sydney"], REF["epoch"], "2026-10-02T00:00:00Z", 10)
    assert a == b


def test_plain_readings_three_audiences_each_states_the_geometry_only_limit_and_none_claims_a_link():
    st = REF["stations"]["ottawa"]
    w = G.find_windows(sat("leo53"), st, REF["epoch"], "2026-10-02T00:00:00Z", 10)
    look = G.look_angles_at(sat("leo53"), st, REF["epoch"])
    e = G.epoch_status(REF["epoch"], REF["epoch"])
    r = {**look, "visible": look["elevation_deg"] >= 10, "min_elevation_mask_deg": 10.0, "mask_origin": "default", "mask_type": "Assumed",
         "analysis_time_utc": REF["epoch"] + "Z", "window_hours": 24.0, "windows": w["windows"], "window_state": w["state"],
         "window_start_utc": w["start_utc"], "window_end_utc": w["end_utc"], "window_step_sec": w["step_sec"], "window_refine_sec": w["refine_sec"],
         "tle_epoch": REF["epoch"], "epoch_level": e["level"], "epoch_note": e["note"], "station_status": "Offline", "station_source_short": "SatNOGS listing"}
    t = G.plain_readings(r)
    import re
    for k in ("field", "planner", "analyst"):
        assert len(t[k]) > 80 and re.search(r"geometry only", t[k], re.I), k
        assert not re.search(r"link (is|will be) (up|available|working)|will (work|connect)|signal strength is", t[k], re.I), k
    assert "true north" in t["field"] and "listing, not verification" in t["planner"] and "Skyfield" in t["analyst"]
    assert f"{len(w['windows'])} window" in t["planner"]
