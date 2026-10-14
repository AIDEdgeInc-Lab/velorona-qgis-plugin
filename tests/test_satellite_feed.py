"""satellite_feed: the production path between CelesTrak GP JSON and the Satellites layer rows.

All payloads here are SYNTHETIC test inputs built inline (obviously fake names and ids); none is real orbital data, and none is shipped in the plugin.
The fetch function is a fake: these tests prove the logic (cache window, stop-after-failure, dedupe, provenance, no invented rows), not that CelesTrak
answers. The real HTTP function http_fetch is only exercised against a stubbed `requests`."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from core.sources import orbit_data, satellite_feed as sf
from core.sources.orbit_data import FetchResult, OrbitCache

NOW = datetime(2026, 10, 12, 12, 0, 0, tzinfo=timezone.utc)


def synth(cat, name="SYNTH-GEO", epoch="2026-10-11T00:00:00.000000", mm=1.0027, **kw):
    r = {"OBJECT_NAME": name, "OBJECT_ID": "2026-001A", "EPOCH": epoch, "MEAN_MOTION": mm, "ECCENTRICITY": 0.0002, "INCLINATION": 0.05,
         "RA_OF_ASC_NODE": 80.0, "ARG_OF_PERICENTER": 100.0, "MEAN_ANOMALY": 20.0, "EPHEMERIS_TYPE": 0, "CLASSIFICATION_TYPE": "U",
         "NORAD_CAT_ID": cat, "ELEMENT_SET_NO": 999, "REV_AT_EPOCH": 1, "BSTAR": 0.0, "MEAN_MOTION_DOT": 0.0, "MEAN_MOTION_DDOT": 0.0}
    r.update(kw)
    return r


class Fake:
    def __init__(self, by_group):
        self.by_group, self.calls = by_group, []

    def __call__(self, url):
        g = url.split("GROUP=")[1].split("&")[0]
        self.calls.append(g)
        v = self.by_group[g]
        return v if isinstance(v, FetchResult) else FetchResult(status=200, text=json.dumps(v))


def cache(tmp_path):
    return OrbitCache(str(tmp_path))


def test_fresh_load_then_cache_hit_makes_no_request(tmp_path):
    f = Fake({"geo": [synth(90001)], "intelsat": [synth(90002)]})
    r1 = sf.load_groups(["geo", "intelsat"], cache(tmp_path), NOW, f)
    assert r1["status"] == "fresh" and len(r1["records"]) == 2 and f.calls == ["geo", "intelsat"]
    r2 = sf.load_groups(["geo", "intelsat"], cache(tmp_path), NOW + timedelta(minutes=30), f)
    assert r2["status"] == "fresh" and f.calls == ["geo", "intelsat"], "a cache hit must not call the provider"
    assert all(g["from_cache"] for g in r2["per_group"].values())


def test_after_cache_window_refetches(tmp_path):
    f = Fake({"geo": [synth(90001)]})
    sf.load_groups(["geo"], cache(tmp_path), NOW, f)
    sf.load_groups(["geo"], cache(tmp_path), NOW + timedelta(seconds=sf.REFRESH_SECONDS + 1), f)
    assert f.calls == ["geo", "geo"]


def test_first_failure_stops_further_group_requests(tmp_path):
    f = Fake({"geo": FetchResult(status=429, headers={"Retry-After": "3600"}), "intelsat": [synth(90002)], "ses": [synth(90003)]})
    r = sf.load_groups(["geo", "intelsat", "ses"], cache(tmp_path), NOW, f)
    assert f.calls == ["geo"], "no request after a non-200 in the same run"
    assert r["status"] == "unavailable" and r["records"] == []
    assert any("not requested" in w for w in r["warnings"])


def test_failure_does_not_retry_on_next_toggle_within_backoff(tmp_path):
    f = Fake({"geo": FetchResult(status=403)})
    sf.load_groups(["geo"], cache(tmp_path), NOW, f)
    r = sf.load_groups(["geo"], cache(tmp_path), NOW + timedelta(minutes=5), f)
    assert f.calls == ["geo"], "a layer toggle 5 minutes after a 403 must not ask again"
    assert r["status"] == "unavailable" and r["per_group"]["geo"]["reason"] == "not_requested"


def test_stale_cache_served_labelled_after_refresh_failure(tmp_path):
    f = Fake({"geo": [synth(90001)]})
    sf.load_groups(["geo"], cache(tmp_path), NOW, f)
    f.by_group["geo"] = FetchResult(status=None, error="network")
    later = NOW + timedelta(seconds=sf.REFRESH_SECONDS + 5)
    r = sf.load_groups(["geo"], cache(tmp_path), later, f)
    assert r["status"] == "stale" and r["records"][0]["data_status"] == "stale"
    assert r["records"][0]["retrieved_at_utc"] == orbit_data.iso_ms(NOW)


def test_failure_never_produces_rows(tmp_path):
    r = sf.load_groups(["geo"], cache(tmp_path), NOW, Fake({"geo": FetchResult(status=None, error="timeout")}))
    assert r["status"] == "unavailable" and r["records"] == []
    assert sf.build_rows(r["records"], NOW)["rows"] == []


def test_invalid_payload_is_not_cached_and_not_shown(tmp_path):
    f = Fake({"geo": FetchResult(status=200, text="<html>nope</html>")})
    r = sf.load_groups(["geo"], cache(tmp_path), NOW, f)
    assert r["status"] == "unavailable" and cache(tmp_path).read("geo") is None or cache(tmp_path).read("geo").get("raw") is None


def test_partial_when_one_group_has_no_data_and_is_not_requested_after_failure(tmp_path):
    f = Fake({"geo": [synth(90001)], "intelsat": FetchResult(status=500)})
    r = sf.load_groups(["geo", "intelsat", "ses"], cache(tmp_path), NOW, f)
    assert r["status"] == "partial" and len(r["records"]) == 1 and f.calls == ["geo", "intelsat"]


def test_dedupe_across_groups_newest_epoch_wins(tmp_path):
    old = synth(90001, "OLD", "2026-10-09T00:00:00.000000")
    new = synth(90001, "NEW", "2026-10-11T00:00:00.000000")
    r = sf.load_groups(["geo", "intelsat"], cache(tmp_path), NOW, Fake({"geo": [new], "intelsat": [old]}))
    assert [x["satellite_name"] for x in r["records"]] == ["NEW"]
    r = sf.load_groups(["geo", "intelsat"], cache(tmp_path / "b"), NOW, Fake({"geo": [old], "intelsat": [new]}))
    assert [x["satellite_name"] for x in r["records"]] == ["NEW"]


def test_build_rows_carries_provenance_and_full_id(tmp_path):
    r = sf.load_groups(["geo"], cache(tmp_path), NOW, Fake({"geo": [synth(90001, "SYNTH-1")]}))
    out = sf.build_rows(r["records"], NOW)
    assert out["skipped"] == {"propagation_failed": 0}
    row = out["rows"][0]
    assert row["norad_cat_id"] == "90001" and row["id"] == "sat-90001"
    assert row["tle_epoch"] == "2026-10-11T00:00:00.000Z"
    assert row["retrieved_at"] == orbit_data.iso_ms(NOW) and row["data_status"] == "fresh"
    assert "geo" in row["source"] and orbit_data.iso_ms(NOW) in row["source"]
    assert row["orbit_category"] == "GEO"
    assert -90 <= row["latitude"] <= 90 and -180 <= row["longitude"] <= 180
    assert len(row["tle_line1"]) == 69 and len(row["tle_line2"]) == 69 and row["tle_line1"][2:7] == "90001"


def test_ids_beyond_five_digits_are_propagated_from_omm_without_a_tle(tmp_path):
    r = sf.load_groups(["geo"], cache(tmp_path), NOW, Fake({"geo": [synth(123456, "SYNTH-BIG"), synth(90001)]}))
    out = sf.build_rows(r["records"], NOW)
    by_id = {x["norad_cat_id"]: x for x in out["rows"]}
    assert set(by_id) == {"123456", "90001"} and out["omm_only"] == 1 and out["skipped"] == {"propagation_failed": 0}
    big = by_id["123456"]
    assert big["tle_line1"] is None and big["tle_line2"] is None and json.loads(big["omm_json"])["NORAD_CAT_ID"] == 123456
    assert by_id["90001"]["tle_line1"] is not None


def test_omm_and_tle_paths_agree_for_the_same_record(tmp_path):
    """The two ways the engine can build a satellite (TLE lines vs stored OMM) must give the same position (TLE text rounds the elements slightly)."""
    from skyfield.api import load
    ts = load.timescale()
    r = sf.load_groups(["geo"], cache(tmp_path), NOW, Fake({"geo": [synth(90001)]}))
    row = sf.build_rows(r["records"], NOW)["rows"][0]
    a = sf.earth_satellite(row["tle_line1"], row["tle_line2"], None, "A", ts)
    b = sf.earth_satellite(None, None, row["omm_json"], "B", ts)
    t = ts.from_datetime(NOW)
    d = (a.at(t).position.km - b.at(t).position.km)
    assert (d ** 2).sum() ** 0.5 < 1.0, "TLE and OMM propagation differ by more than 1 km"
    with pytest.raises(ValueError):
        sf.earth_satellite(None, None, None, "C", ts)


def test_ensure_propagates_rejects_decayed_elements():
    from skyfield.api import load
    ts = load.timescale()
    sat = sf.earth_satellite(None, None, json.dumps(synth(90009, mm=16.0, ECCENTRICITY=0.5, EPOCH="2026-10-11T00:00:00.000000")), "D", ts)
    with pytest.raises(ValueError, match="SGP4 error"):
        sf.ensure_propagates(sat, NOW)


def test_backoff_blocks_every_group_across_runs_not_only_the_failed_one(tmp_path):
    """Layer toggled again after a 429 on the first group: the OTHER groups must not be requested either (same host)."""
    f = Fake({"geo": FetchResult(status=429, headers={"Retry-After": "3600"}), "intelsat": [synth(90002)]})
    sf.load_groups(["geo", "intelsat"], cache(tmp_path), NOW, f)
    assert f.calls == ["geo"]
    r = sf.load_groups(["geo", "intelsat"], cache(tmp_path), NOW + timedelta(minutes=11), f)
    assert f.calls == ["geo"], "no group may be requested while the host is in back-off"
    assert r["status"] == "unavailable"


def test_blocked_groups_serve_their_cache_without_touching_it(tmp_path):
    f = Fake({"geo": [synth(90001)], "intelsat": [synth(90002)]})
    sf.load_groups(["geo", "intelsat"], cache(tmp_path), NOW, f)
    later = NOW + timedelta(seconds=sf.REFRESH_SECONDS + 5)
    f.by_group["geo"] = FetchResult(status=503)
    r = sf.load_groups(["geo", "intelsat"], cache(tmp_path), later, f)
    assert f.calls == ["geo", "intelsat", "geo"], "intelsat must not be requested after geo failed"
    assert r["status"] == "stale" and len(r["records"]) == 2 and all(x["data_status"] == "stale" for x in r["records"])
    assert cache(tmp_path).read("intelsat")["raw"] is not None and not cache(tmp_path).read("intelsat").get("not_before")


def test_unpropagatable_record_is_skipped_not_invented(tmp_path):
    bad = synth(90009, "SYNTH-DECAY", mm=16.0, ECCENTRICITY=0.5)   # perigee below the surface: SGP4 error 6
    r = sf.load_groups(["geo"], cache(tmp_path), NOW, Fake({"geo": [bad]}))
    out = sf.build_rows(r["records"], NOW)
    assert out["rows"] == [] and out["skipped"]["propagation_failed"] == 1


def test_cache_directory_is_group_allowlisted(tmp_path):
    assert cache(tmp_path).read("../etc/passwd") is None
    with pytest.raises(ValueError):
        cache(tmp_path).write("../etc/passwd", {"raw": [], "retrieved_at_utc": orbit_data.iso_ms(NOW)})


def test_http_fetch_maps_outcomes(monkeypatch):
    import requests

    class R:
        def __init__(self, code, text="[]"):
            self.status_code, self.text, self.headers = code, text, {"Retry-After": "7"}

    seen = {}

    def ok(url, headers=None, timeout=None):
        seen.update(headers=headers, timeout=timeout)
        return R(200)
    monkeypatch.setattr(requests, "get", ok)
    r = sf.http_fetch("https://example.invalid/x")
    assert r.status == 200 and r.text == "[]" and seen["headers"]["User-Agent"].startswith("VeloronaQGIS") and seen["timeout"] == sf.TIMEOUT
    monkeypatch.setattr(requests, "get", lambda *a, **k: R(429))
    r = sf.http_fetch("u")
    assert r.status == 429 and r.text is None and r.headers["Retry-After"] == "7"

    def boom(*a, **k):
        raise requests.exceptions.Timeout()
    monkeypatch.setattr(requests, "get", boom)
    assert sf.http_fetch("u").error == "timeout"

    def boom2(*a, **k):
        raise requests.exceptions.ConnectionError()
    monkeypatch.setattr(requests, "get", boom2)
    assert sf.http_fetch("u").error == "network"


def test_plugin_is_wired_to_the_validated_feed_not_the_legacy_fetch():
    """Static wiring check (no QGIS runtime here): the production method must go through satellite_feed and must not call the legacy fetch."""
    import ast
    import pathlib
    src = pathlib.Path(__file__).resolve().parent.parent.joinpath("plugin.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef) and n.name == "_populate_satellites")
    body = ast.get_source_segment(src, fn)
    assert "satellite_feed.load_groups" in body and "satellite_feed.build_rows" in body
    assert "fetch_celestrak_satellites" not in body and "build_satellite_records" not in body
    assert "SATELLITE_REFRESH_SECONDS" in body


def test_source_string_makes_no_public_domain_claim():
    from pathlib import Path
    text = Path(__file__).resolve().parent.parent.joinpath("core", "sources", "space_public.py").read_text(encoding="utf-8")
    assert "Public Domain" not in text


class _Pt:
    def __init__(self, x, y):
        self._x, self._y = x, y

    def x(self): return self._x
    def y(self): return self._y


class _Geom:
    def __init__(self, x, y): self._p = _Pt(x, y)
    def centroid(self): return self
    def asPoint(self): return self._p


class _Feat:
    """Minimal stand-in for QgsFeature (attribute access only). NOT a QGIS object: this exercises the engine's own logic, not QGIS."""
    def __init__(self, attrs, x=0.0, y=0.0):
        self._a, self._g = attrs, _Geom(x, y)

    def fields(self):
        class F:
            def __init__(s, n): s._n = n
            def names(s): return list(s._n)
        return F(self._a)

    def __getitem__(self, k): return self._a[k]
    def geometry(self): return self._g
    def id(self): return 1


def _engine(monkeypatch):
    import importlib
    import sys
    import types
    qc = types.ModuleType("qgis.core")
    for n in ("QgsCoordinateReferenceSystem", "QgsCoordinateTransform", "QgsProject"):
        setattr(qc, n, lambda *a, **k: None)
    monkeypatch.setitem(sys.modules, "qgis", types.ModuleType("qgis"))
    monkeypatch.setitem(sys.modules, "qgis.core", qc)
    for m in ("core.features", "core.engines.satellite_earth_space"):
        sys.modules.pop(m, None)
    return importlib.import_module("core.engines.satellite_earth_space")


def test_engine_analyses_a_satellite_that_has_only_an_omm_record(monkeypatch, tmp_path):
    engine = _engine(monkeypatch)
    now = datetime.now(timezone.utc)
    r = sf.load_groups(["geo"], cache(tmp_path), now, Fake({"geo": [synth(123456, "SYNTH-BIG", epoch=orbit_data.iso_ms(now - timedelta(hours=3)))]}))
    row = sf.build_rows(r["records"], now)["rows"][0]
    assert row["tle_line1"] is None
    res = engine.analyze((None, _Feat({"name": "STN", "id": "s1", "altitude_m": 0}, x=row["longitude"], y=row["latitude"])), (None, _Feat(row)))
    assert res.elevation_deg > 80, "a station under the sub-point must see the satellite almost overhead"
    assert res.satellite_name == "SYNTH-BIG"


def test_engine_refuses_a_decayed_record_instead_of_returning_a_number(monkeypatch):
    engine = _engine(monkeypatch)
    ep = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000000")
    row = {"name": "D", "id": "sat-1", "omm_json": json.dumps(synth(90009, mm=16.0, ECCENTRICITY=0.5, EPOCH=ep)), "tle_epoch": "x"}
    with pytest.raises(ValueError, match="cannot be propagated|below the Earth"):
        engine.analyze((None, _Feat({"name": "S", "id": "s", "altitude_m": 0})), (None, _Feat(row)))


def test_engine_reports_missing_elements(monkeypatch):
    engine = _engine(monkeypatch)
    with pytest.raises(ValueError, match="no orbital elements"):
        engine.analyze((None, _Feat({"name": "S", "id": "s"})), (None, _Feat({"name": "X", "id": "y"})))


def test_cancelled_load_makes_no_request_and_serves_the_cache(tmp_path):
    f = Fake({"geo": [synth(90001)], "intelsat": [synth(90002)]})
    sf.load_groups(["geo", "intelsat"], cache(tmp_path), NOW, f)
    f.calls.clear()
    later = NOW + timedelta(seconds=sf.REFRESH_SECONDS + 5)
    r = sf.load_groups(["geo", "intelsat"], cache(tmp_path), later, f, cancelled=lambda: True)
    assert f.calls == [], "a cancelled load must not touch the network"
    assert r["status"] == "stale" and len(r["records"]) == 2
