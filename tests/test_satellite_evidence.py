"""Satellite evidence rows, CSV export and the engine adapter -- QGIS-free (the engine is imported with a stand-in `qgis.core`, as parity/runner_qgis.py does; the
real-QGIS path is covered only by tests/qgis_e2e.py, which needs a QGIS runtime).

Inputs are the SYNTHETIC orbits/stations of tests/fixtures/satgeo (geometry only; not real satellites)."""
import csv
import io
import json
import os
import re
import sys
import types
from datetime import datetime, timezone

import pytest

pytest.importorskip("skyfield")
try:
    import qgis.core  # noqa: F401
except ImportError:                                   # no QGIS runtime: a minimal stand-in so core.features imports
    stub = types.ModuleType("qgis.core")
    for name in ("QgsCoordinateReferenceSystem", "QgsCoordinateTransform", "QgsProject"):
        setattr(stub, name, type(name, (), {"__init__": lambda self, *a, **k: None}))
    sys.modules["qgis"] = types.ModuleType("qgis")
    sys.modules["qgis.core"] = stub

from core.engines import satellite_earth_space as eng  # noqa: E402
from core.engines import satellite_geometry as geom  # noqa: E402
from core.export import NotExportable, result_to_csv, result_to_xlsx  # noqa: E402
from core.presentation import satellite as psat  # noqa: E402

REF = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "satgeo", "reference.json"), encoding="utf-8"))
NOW = datetime(2026, 10, 1, 6, 0, 0, tzinfo=timezone.utc)


class _Pt:
    def __init__(self, x, y): self._x, self._y = x, y
    def x(self): return self._x
    def y(self): return self._y


class _Geom:
    def __init__(self, x, y): self._p = _Pt(x, y)
    def centroid(self): return self
    def asPoint(self): return self._p
    def isEmpty(self): return False


class _Feature:
    def __init__(self, attrs, lon=0.0, lat=0.0, fid=1):
        self._a, self._g, self._id = attrs, _Geom(lon, lat), fid
    def fields(self): return types.SimpleNamespace(names=lambda: list(self._a))
    def __getitem__(self, k): return self._a[k]
    def geometry(self): return self._g
    def id(self): return self._id


def tle_for(orbit_key):
    from sgp4.exporter import export_tle
    sat = geom.satellite_from_omm(REF["orbits"][orbit_key])
    return export_tle(sat.model)


def station_feature(key="ottawa", **over):
    s = REF["stations"][key]
    attrs = {"id": "satnogs-1", "name": "Test station", "source": "SatNOGS Network -- Ground Stations, static snapshot", "status": "Offline",
             "altitude_m": s["altitude_m"], "min_horizon_deg": 30.0, **over}
    return ("layer", _Feature(attrs, s["longitude"], s["latitude"]))


def satellite_feature(orbit_key="leo53", **over):
    l1, l2 = tle_for(orbit_key)
    attrs = {"id": "sat-99001", "name": "SYNTH-LEO-53", "source": "SYNTHETIC test element set", "norad_cat_id": "99001", "orbit_category": "LEO",
             "tle_epoch": REF["epoch"] + "Z", "tle_line1": l1, "tle_line2": l2, **over}
    return ("layer", _Feature(attrs, 0, 0, 2))


def run(params=None, st=None, sat=None, now=NOW):
    return eng.analyze(st or station_feature(), sat or satellite_feature(), params, now=now)


def rows_by_name(result):
    return {r[0]: r for r in psat.evidence_rows(result)}


# ---------------- engine adapter ----------------

def test_defaults_are_now_24h_and_a_10_degree_mask_typed_assumed():
    r = run()
    assert r.analysis_time_utc == "2026-10-01T06:00:00.000Z" and r.time_origin == "now"
    assert r.window_hours == 24.0 and r.min_elevation_mask_deg == 10.0 and (r.mask_origin, r.mask_type) == ("default", "Assumed")
    assert r.window_state == "windows" and len(r.windows) >= 1 and r.windows_error is None
    assert r.station_status == "Offline" and r.station_min_horizon_deg == 30.0 and r.satellite_source.startswith("SYNTHETIC")


def test_the_result_matches_a_direct_call_to_the_geometry_module():
    r = run()
    l1, l2 = tle_for("leo53")
    sat = geom.satellite_from_tle(l1, l2, "x")
    direct = geom.look_angles_at(sat, {"latitude": REF["stations"]["ottawa"]["latitude"], "longitude": REF["stations"]["ottawa"]["longitude"],
                                       "altitude_m": REF["stations"]["ottawa"]["altitude_m"]}, NOW)
    assert (r.elevation_deg, r.azimuth_deg, r.slant_range_km) == (direct["elevation_deg"], direct["azimuth_deg"], direct["range_km"])


def test_a_start_offset_moves_the_analysis_time_and_is_typed_as_entered():
    r = run({"start_offset_hours": 6.0})
    assert r.analysis_time_utc == "2026-10-01T12:00:00.000Z" and r.time_origin == "user"
    assert rows_by_name(r)["Analysis time (UTC)"][1] == "Assumed" and rows_by_name(r)["Analysis time (UTC)"][2] == "Entered by the user"


def test_the_stations_declared_horizon_is_used_only_when_chosen_and_then_typed_observed():
    assert run().min_elevation_mask_deg == 10.0
    r = run({"mask_basis": eng.STATION_HORIZON_CHOICE})
    assert (r.min_elevation_mask_deg, r.mask_origin, r.mask_type) == (30.0, "station", "Observed")
    assert rows_by_name(r)["Minimum elevation mask"][1] == "Observed"
    assert rows_by_name(run({"min_elevation_deg": 25.0}))["Minimum elevation mask"][1] == "Assumed"
    with pytest.raises(ValueError, match="no usable horizon"):
        run({"mask_basis": eng.STATION_HORIZON_CHOICE}, st=station_feature(min_horizon_deg=None))


def test_a_missing_tle_a_corrupt_tle_and_bad_parameters_are_refused_with_a_plain_message():
    with pytest.raises(ValueError, match="no TLE data"):
        run(sat=satellite_feature(tle_line1=""))
    l1, l2 = tle_for("leo53")
    with pytest.raises(ValueError, match="not a valid TLE"):
        run(sat=satellite_feature(tle_line1=l1[:-1] + str((int(l1[-1]) + 1) % 10)))
    for bad in ({"window_hours": 0.5}, {"window_hours": 100.0}, {"start_offset_hours": -1.0}, {"start_offset_hours": 80.0}, {"min_elevation_deg": 75.0}):
        with pytest.raises(ValueError):
            run(bad)


def test_a_station_without_altitude_or_status_is_reported_as_such_not_invented():
    r = run(st=station_feature(altitude_m=None, status=None, min_horizon_deg=None))
    rows = rows_by_name(r)
    assert rows["Station altitude"][1] == "Assumed" and "0 m used" in rows["Station altitude"][2]
    assert rows["Station listing status"][3] == "not published" and "Station declared minimum horizon" not in rows


def test_the_param_spec_is_well_formed_for_the_shared_dialog():
    keys = [p["key"] for p in eng.PARAM_SPEC]
    assert keys == ["start_offset_hours", "window_hours", "min_elevation_deg", "mask_basis"]
    for p in eng.PARAM_SPEC:
        assert p["type"] in ("float", "choice") and p["basis"]
        if p["type"] == "float":
            assert p["min"] <= p["default"] <= p["max"]
        else:
            assert p["default"] in p["choices"]
    assert eng.build_params() == {"start_offset_hours": 0.0, "window_hours": 24.0, "min_elevation_deg": 10.0, "mask_basis": "Use the value above"}


# ---------------- evidence rows ----------------

def test_evidence_types_follow_the_convention():
    rows = rows_by_name(run())
    types_ = {k: v[1] for k, v in rows.items()}
    assert types_["Analysis time (UTC)"] == "Assumed" and types_["Minimum elevation mask"] == "Assumed"
    assert types_["Orbital data age at the analysis time"] == "Calculated" and types_["Orbital data freshness"] == "Inferred"
    assert types_["Station listing status"] == "Observed" and types_["Station declared minimum horizon"] == "Observed"
    assert types_["Satellite position (at analysis time)"] == "Calculated" and types_["Visibility windows"] == "Calculated" and types_["Scope"] == "Inferred"
    assert "not verification" in rows["Station listing status"][5]
    assert "not a live observation" in rows["Satellite position (at analysis time)"][5]
    assert all(v[1] in ("Observed", "Calculated", "Assumed", "Inferred") for v in rows.values())


def test_a_far_from_epoch_analysis_is_flagged_stale():
    rows = rows_by_name(run(now=datetime(2026, 12, 25, tzinfo=timezone.utc)))
    assert rows["Orbital data freshness"][4] == "stale" and "unreliable" in rows["Orbital data freshness"][5]


def test_a_geo_type_satellite_above_the_minimum_throughout_reports_that_and_no_invented_window():
    st = station_feature("under_geo", min_horizon_deg=None)
    r = eng.analyze(st, satellite_feature("geo", name="SYNTH-GEO"), None, now=datetime(2026, 10, 1, tzinfo=timezone.utc))
    assert r.window_state == "always-above" and r.windows == []
    rows = psat.evidence_rows(r)
    assert any(x[0] == "Visibility windows" and "whole 24 h" in x[4] for x in rows) and not any(x[0].startswith("Window ") for x in rows)


def test_a_window_failure_keeps_the_look_angles_and_reports_why(monkeypatch):
    monkeypatch.setattr(geom, "find_windows", lambda *a, **k: {"ok": False, "reason": "Propagation failed at X"})
    r = run()
    assert r.windows == [] and r.windows_error == "Propagation failed at X" and isinstance(r.elevation_deg, float)
    assert any(x[0] == "Visibility windows" and x[4] == "not computed" for x in psat.evidence_rows(r))


def test_window_rows_are_capped_with_the_full_count_in_the_summary():
    r = run()
    many = [dict(r.windows[0]) for _ in range(20)]
    r.windows = many
    rows = psat.evidence_rows(r)
    assert sum(1 for x in rows if re.fullmatch(r"Window \d+", x[0])) == psat.MAX_WINDOW_ROWS
    assert next(x for x in rows if x[0] == "Visibility windows")[4].startswith("20 windows")
    assert any(x[0] == "Further windows" and x[4].startswith("8 more") for x in rows)


# ---------------- export ----------------

def test_csv_export_carries_the_preamble_the_evidence_table_and_the_scope_limit():
    text = result_to_csv(run())
    comments = [ln for ln in text.splitlines() if ln.startswith("# ")]
    assert any("Satellite / Earth-Space look-angle and visibility-window export" in ln for ln in comments)
    assert any("Analysis time (UTC): 2026-10-01T06:00:00.000Z" in ln and "minimum elevation 10 deg (Assumed)" in ln for ln in comments)
    assert any(ln.startswith("# Product: Velorona for QGIS") for ln in comments)
    table = list(csv.reader(io.StringIO("\n".join(ln for ln in text.splitlines() if not ln.startswith("#")))))
    assert table[0] == ["Evidence", "Type", "Source", "Observation-Input", "Calculated result", "Interpretation"]
    names = [r[0] for r in table[1:]]
    for expected in ("Analysis time (UTC)", "Orbital data age at the analysis time", "Station listing status", "Visibility windows", "Window 1", "Scope"):
        assert expected in names, expected
    assert all(len(r) == 6 for r in table[1:])
    assert "Geometry only: no propagation loss" in text and not re.search(r"link (is|will be) (up|available|working)", text, re.I)


def test_excel_is_not_offered_for_satellite_geometry_and_other_kinds_still_refuse():
    with pytest.raises(NotExportable):
        result_to_xlsx(run())
    with pytest.raises(NotExportable, match="no export"):
        result_to_csv(types.SimpleNamespace(kind="something-else"))


def test_the_dock_html_for_a_result_states_the_readings_and_never_a_link_claim():
    # the dock module imports Qt; its satellite renderer is exercised in tests/qgis_e2e.py. Here: the same text sources it renders.
    r = run()
    t = geom.plain_readings(r.__dict__)
    assert "Offline" in t["planner"] and "true north" in t["field"] and re.search(r"geometry only", t["analyst"], re.I)
