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
    assert any("earlier group failed" in w for w in r["warnings"])


def test_failure_does_not_retry_on_next_toggle_within_backoff(tmp_path):
    f = Fake({"geo": FetchResult(status=403)})
    sf.load_groups(["geo"], cache(tmp_path), NOW, f)
    r = sf.load_groups(["geo"], cache(tmp_path), NOW + timedelta(minutes=5), f)
    assert f.calls == ["geo"], "a layer toggle 5 minutes after a 403 must not ask again"
    assert r["status"] == "unavailable" and r["per_group"]["geo"]["reason"] == "backoff"


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
    assert out["skipped"] == {"propagation_failed": 0, "beyond_legacy_tle": 0}
    row = out["rows"][0]
    assert row["norad_cat_id"] == "90001" and row["id"] == "sat-90001"
    assert row["tle_epoch"] == "2026-10-11T00:00:00.000Z"
    assert row["retrieved_at"] == orbit_data.iso_ms(NOW) and row["data_status"] == "fresh"
    assert "geo" in row["source"] and orbit_data.iso_ms(NOW) in row["source"]
    assert row["orbit_category"] == "GEO"
    assert -90 <= row["latitude"] <= 90 and -180 <= row["longitude"] <= 180
    assert len(row["tle_line1"]) == 69 and len(row["tle_line2"]) == 69 and row["tle_line1"][2:7] == "90001"


def test_ids_beyond_five_digits_are_skipped_and_counted_not_truncated(tmp_path):
    r = sf.load_groups(["geo"], cache(tmp_path), NOW, Fake({"geo": [synth(123456, "SYNTH-BIG"), synth(90001)]}))
    out = sf.build_rows(r["records"], NOW)
    assert out["skipped"]["beyond_legacy_tle"] == 1 and [x["norad_cat_id"] for x in out["rows"]] == ["90001"]


def test_unpropagatable_record_is_skipped_not_invented(tmp_path):
    bad = synth(90009, "SYNTH-DECAY", mm=16.0, ECCENTRICITY=0.5)   # perigee below the surface: SGP4 error 6
    r = sf.load_groups(["geo"], cache(tmp_path), NOW, Fake({"geo": [bad]}))
    out = sf.build_rows(r["records"], NOW)
    assert out["rows"] == [] and sum(out["skipped"].values()) == 1


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
