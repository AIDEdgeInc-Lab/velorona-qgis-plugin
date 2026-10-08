"""Terrain brief: the numbers shown are the library's numbers, the status mapping
is the documented one, and a known flat-terrain case matches an independent
hand calculation of the Fresnel / earth-bulge geometry."""
import math

import importlib
import aei_link_clearance.terrain as lib_terrain
import pytest
from presentation_fixtures import terrain_result

from core.presentation import terrain as T
from core.presentation.model import AT_RISK, CLEAR, CRITICAL, NO_DATA, WATCH


def test_constants_match_the_library():
    lib_explain = importlib.import_module("aei_link_clearance.explain")  # the package re-exports a function of the same name
    assert T.COMFORTABLE_MARGIN_RATIO == lib_explain.COMFORTABLE_MARGIN_RATIO
    assert T.ELEVATION_UNCERTAINTY_M == lib_terrain.ELEVATION_UNCERTAINTY_M
    assert T.CLEAR_THRESHOLD == lib_terrain.CLEAR_THRESHOLD
    assert T.OBSTRUCTED_THRESHOLD == lib_terrain.OBSTRUCTED_THRESHOLD


def test_flat_terrain_matches_independent_hand_calculation():
    res = terrain_result(ground_m=100.0, h_a=30.0, h_b=30.0, freq=11.5)
    r = res.result
    brief = T.terrain_brief(res)
    crit = T.critical_point(r)
    d1, d2 = crit.distance_from_a_km, r.distance_km - crit.distance_from_a_km
    # independent: r1 = 17.3*sqrt(d1*d2/(f*D)); bulge = d1*d2/(2kR)*1000; LOS is level at 130 m
    r1 = 17.3 * math.sqrt(d1 * d2 / (11.5 * r.distance_km))
    bulge = d1 * d2 / (2 * (4 / 3) * 6371.0088) * 1000
    # P11 (owner-approved physics correction): the bulge is SUBTRACTED from geometric clearance, i.e. added to the terrain.
    expected_available = 130.0 - (100.0 + bulge)
    assert brief.data["terrain_clearance_m"] == pytest.approx(expected_available, abs=0.05)
    assert brief.data["required_clearance_m"] == pytest.approx(0.6 * r1, abs=0.01)
    assert brief.data["margin_m"] == brief.data["terrain_clearance_m"] - brief.data["required_clearance_m"]
    assert brief.status == CLEAR
    assert "well above" in brief.reason
    # the plain wording carries the physical comparison, not a percentage
    facts = {f.label: f for f in brief.key_facts}
    assert facts["Clearance available"].value.endswith(" m")
    assert facts["Margin"].value.startswith("+")
    assert "%" not in facts["Margin"].value + facts["Margin"].comparison
    assert brief.data["samples"] == 50


def test_critical_point_is_the_librarys_point():
    r = terrain_result(hump_m=40.0).result
    crit = T.critical_point(r)
    assert crit.clearance_m == r.terrain_clearance_m
    assert crit.fresnel_radius_m == r.first_fresnel_radius_m
    assert crit.distance_from_a_km == r.obstruction_distance_km or r.obstruction_distance_km is None


def test_displayed_numbers_are_the_result_numbers():
    res = terrain_result(hump_m=20.0)
    r = res.result
    b = T.terrain_brief(res)
    assert b.data["terrain_clearance_m"] == r.terrain_clearance_m
    assert b.data["required_clearance_m"] == r.required_clearance_m
    assert b.data["clearance_ratio"] == r.clearance_ratio
    assert b.data["distance_km"] == r.distance_km
    assert f"{r.terrain_clearance_m:.1f} m" in b.key_facts[1].value


def _status_for(hump):
    res = terrain_result(hump_m=hump)
    return T.terrain_brief(res), res.result


def test_status_follows_the_librarys_classification():
    seen = {}
    for hump in range(0, 120, 2):
        b, r = _status_for(hump)
        seen[b.status] = (hump, r)
        if r.los_status == "obstructed":
            assert b.status == CRITICAL
        elif r.los_status == "marginal":
            assert b.status == AT_RISK
        elif r.clearance_ratio < 1.3:          # P3: near_threshold is a verification flag and never changes the status
            assert b.status == WATCH
        else:
            assert b.status == CLEAR
    # the sweep must actually exercise every non-empty status, or this test proves nothing
    assert {CLEAR, WATCH, AT_RISK, CRITICAL} == set(seen), set(seen)


def test_watch_when_clear_but_small_margin():
    for hump in range(0, 60):
        res = terrain_result(hump_m=float(hump))
        r = res.result
        if r.los_status == "clear" and r.clearance_ratio < 1.3:
            b = T.terrain_brief(res)
            assert b.status == WATCH
            assert "margin" in b.reason
            return
    pytest.fail("no WATCH case found in the sweep")


def test_critical_reports_terrain_above_line_of_sight():
    res = terrain_result(hump_m=400.0)
    b = T.terrain_brief(res)
    assert b.status == CRITICAL
    assert res.result.terrain_clearance_m < 0
    assert "above the line of sight" in b.reason
    assert b.inspect and "km from Site A" in b.inspect


def test_no_profile_is_no_data():
    res = terrain_result()
    res.result = type(res.result)(**{**res.result.__dict__, "profile": []})
    b = T.terrain_brief(res)
    assert b.status == NO_DATA
    assert "could not be retrieved" in b.reason


def test_inputs_keep_their_exact_values():
    res = terrain_result(h_a=30.5, freq=7.25)
    b = T.terrain_brief(res)
    tech = {f.label: f.value for f in b.technical}
    assert tech["Antenna height A"] == "30.5 m"
    assert "7.25 GHz" in b.key_facts[0].comparison


def test_no_percent_in_primary_facts():
    b = T.terrain_brief(terrain_result())
    for f in b.key_facts:
        assert "%" not in f.value


def test_near_threshold_is_a_flag_not_a_status():
    """P3: a clear link with ratio >= 1.3 stays CLEAR even when the library flags it near_threshold; the flag is still reported."""
    for hump in range(0, 120):
        res = terrain_result(hump_m=float(hump))
        r = res.result
        if r.los_status == "clear" and r.clearance_ratio >= 1.3 and r.near_threshold:
            b = T.terrain_brief(res)
            assert b.status == CLEAR
            assert any("near a classification boundary" in c for c in b.caveats)       # the flag is still shown
            return
    pytest.skip("no clear + near-threshold + ratio >= 1.3 case in this sweep")


@pytest.mark.parametrize("pct,ratio,expected", [
    (0.2999, 0.4998, CRITICAL), (0.30, 0.5, AT_RISK), (0.5999, 0.9998, AT_RISK), (0.60, 1.0, WATCH),
    (0.7799, 1.2998, WATCH), (0.78, 1.3, CLEAR), (2.0, 3.3, CLEAR),
])
def test_status_boundaries_are_inclusive_where_specified(pct, ratio, expected):
    """0.30 and 0.60 belong to the upper class; the ratio threshold 1.3 is strictly below (1.3 itself is CLEAR). P2 is provisional."""
    from types import SimpleNamespace
    los = "obstructed" if pct < 0.30 else "marginal" if pct < 0.60 else "clear"
    r = SimpleNamespace(profile=[object()], los_status=los, near_threshold=True, clearance_ratio=ratio, terrain_clearance_m=1.0, required_clearance_m=1.0)
    assert T.terrain_status(r)[0] == expected
