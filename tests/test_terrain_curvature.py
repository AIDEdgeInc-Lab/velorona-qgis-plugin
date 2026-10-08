"""Earth-curvature sign (owner decision P11). The plugin calls aei_link_clearance unmodified; these tests pin what the plugin relies on:
the library's corrected convention, the independent closed-form chord geometry it must agree with, and the refusal of an old library.
Constants: k = 4/3, R = 6371 km (aei_link_clearance.terrain / aei_geo_features)."""
import math
from types import SimpleNamespace

import pytest

import aei_link_clearance.terrain as terrain
from core.validation import LibraryOutOfDateError, REQUIRED_CLEARANCE_CONVENTION, require_corrected_clearance

RE_M = (4.0 / 3.0) * 6371.0 * 1000.0


def chord_clearance_m(distance_km, fraction, ground_m, mast_m):
    theta = distance_km * 1000.0 / RE_M
    ra = RE_M + ground_m + mast_m
    ax, ay = ra, 0.0
    bx, by = ra * math.cos(theta), ra * math.sin(theta)
    t = fraction * theta
    ux, uy = math.cos(t), math.sin(t)
    dx, dy = bx - ax, by - ay
    s = (ay * ux - ax * uy) / (dx * uy - dy * ux)
    return math.hypot(ax + s * dx, ay + s * dy) - (RE_M + ground_m)


def _flat(monkeypatch, km):
    monkeypatch.setattr(terrain, "get_elevations", lambda pts: [100.0] * len(pts))
    return terrain.analyze_link("flat", 45.0, -75.0, 30.0, 45.0 + km / 111.195, -75.0, 30.0, 6.35)


def test_installed_library_has_the_corrected_convention():
    require_corrected_clearance(terrain)          # must not raise
    assert terrain.CLEARANCE_CONVENTION == REQUIRED_CLEARANCE_CONVENTION


def test_old_library_is_refused_with_a_clear_message():
    with pytest.raises(LibraryOutOfDateError, match="pre-correction earth-curvature sign"):
        require_corrected_clearance(SimpleNamespace())          # an old release has no CLEARANCE_CONVENTION
    with pytest.raises(LibraryOutOfDateError):
        require_corrected_clearance(SimpleNamespace(CLEARANCE_CONVENTION="bulge-subtracted-from-terrain"))


def test_38km_case_matches_independent_geometry_not_the_old_value(monkeypatch):
    r = _flat(monkeypatch, 38.1)
    crit = min((p for p in r.profile if p.percent_fresnel_clear is not None), key=lambda p: p.percent_fresnel_clear)
    assert crit.clearance_m == pytest.approx(chord_clearance_m(r.distance_km, crit.distance_from_a_km / r.distance_km, 100.0, 30.0), abs=0.01)
    assert crit.clearance_m == pytest.approx(8.648, abs=0.02)
    assert abs(crit.clearance_m - 51.352) > 40           # the pre-correction value


@pytest.mark.parametrize("km", [10.0, 100.0, 203.3])
def test_all_samples_match_independent_geometry(monkeypatch, km):
    r = _flat(monkeypatch, km)
    for p in r.profile[1:-1]:
        assert p.clearance_m == pytest.approx(chord_clearance_m(r.distance_km, p.distance_from_a_km / r.distance_km, 100.0, 30.0), abs=0.02)
