"""Reliability matrix for the satellite data path (CelesTrak GP -> validated cache -> layer rows), QGIS-free.

Fills the cases of the reliability brief that the existing suites (test_orbit_data.py, test_satellite_feed.py) did not name individually: a restart reusing a valid cache,
each of HTTP 403 / 429 / 500 and a timeout with and without a cache, a corrupt cache file, a valid cache while the provider is down, no cache while it is down, the
2-hour boundary, and the guarantee that nothing is ever produced from a failure. All payloads are SYNTHETIC test inputs with obviously fake names; none ships."""
import json
import os
from datetime import datetime, timedelta, timezone

import pytest

from core.sources import orbit_data, satellite_feed as sf
from core.sources.orbit_data import FetchResult, OrbitCache

NOW = datetime(2026, 10, 12, 12, 0, 0, tzinfo=timezone.utc)
GROUPS = ("geo", "intelsat", "ses", "eutelsat", "telesat")


def synth(cat, name="SYNTH-GEO"):
    return {"OBJECT_NAME": name, "OBJECT_ID": "2026-001A", "EPOCH": "2026-10-11T00:00:00.000000", "MEAN_MOTION": 1.0027, "ECCENTRICITY": 0.0002,
            "INCLINATION": 0.05, "RA_OF_ASC_NODE": 80.0, "ARG_OF_PERICENTER": 100.0, "MEAN_ANOMALY": 20.0, "EPHEMERIS_TYPE": 0, "CLASSIFICATION_TYPE": "U",
            "NORAD_CAT_ID": cat, "ELEMENT_SET_NO": 999, "REV_AT_EPOCH": 1, "BSTAR": 0.0, "MEAN_MOTION_DOT": 0.0, "MEAN_MOTION_DDOT": 0.0}


class Counting:
    def __init__(self, status=200, body=None, error=None, headers=None):
        self.calls, self.status, self.body, self.error, self.headers = [], status, body, error, headers or {}

    def __call__(self, url):
        self.calls.append(url)
        if self.status is None:
            return FetchResult(status=None, error=self.error or "timeout")
        text = json.dumps(self.body if self.body is not None else [synth(90001)]) if self.status == 200 else None
        return FetchResult(status=self.status, text=text, headers=self.headers)


def load(tmp_path, fetch, when=NOW):
    return sf.load_groups(GROUPS, OrbitCache(str(tmp_path)), when, fetch)


def test_first_launch_without_a_cache_asks_once_per_group_and_creates_the_cache(tmp_path):
    f = Counting()
    r = load(tmp_path, f)
    assert r["status"] == "fresh" and len(f.calls) == len(GROUPS)
    assert sorted(os.listdir(tmp_path)) == sorted(f"orbit_{g}.json" for g in GROUPS)        # persisted, one file per group


def test_a_restart_reuses_the_valid_cache_without_any_request(tmp_path):
    load(tmp_path, Counting())
    f2 = Counting()
    r = load(tmp_path, f2, NOW + timedelta(minutes=90))              # "new session": new cache object on the same directory, inside the 2 h window
    assert f2.calls == [] and r["status"] == "fresh" and r["records"]


def test_the_two_hour_boundary(tmp_path):
    load(tmp_path, Counting())
    inside, after = Counting(), Counting()
    load(tmp_path, inside, NOW + timedelta(hours=2) - timedelta(seconds=1))
    assert inside.calls == []
    load(tmp_path, after, NOW + timedelta(hours=2, seconds=1))
    assert len(after.calls) == len(GROUPS)                            # asked again only after the window


@pytest.mark.parametrize("status,headers", [(403, {}), (429, {"Retry-After": "900"}), (500, {}), (503, {}), (None, {})])
def test_every_failure_without_a_cache_is_unavailable_and_stops_after_the_first_request(tmp_path, status, headers):
    f = Counting(status=status, headers=headers)
    r = load(tmp_path, f)
    assert r["status"] == "unavailable" and r["records"] == []
    assert len(f.calls) == 1                                          # the policy: stop after a non-200 (no request for the other four groups)
    again = Counting()
    r2 = load(tmp_path, again, NOW + timedelta(seconds=30))     # inside every back-off (network errors: 60 s; HTTP failures: longer)
    assert again.calls == [] and r2["status"] == "unavailable"       # and not asked again inside the back-off, even by a "new session"


@pytest.mark.parametrize("status", [403, 429, 500, None])
def test_a_valid_cache_survives_a_provider_failure_and_is_labelled_stale_with_its_time(tmp_path, status):
    load(tmp_path, Counting())
    f = Counting(status=status)
    r = load(tmp_path, f, NOW + timedelta(hours=3))
    assert r["status"] == "stale" and r["records"]
    assert len(f.calls) == 1
    assert all(rec["data_status"] == "stale" and rec["retrieved_at_utc"] for rec in r["records"])
    rows = sf.build_rows(r["records"], NOW + timedelta(hours=3))["rows"]
    assert rows and all(row["data_status"] == "stale" for row in rows)


def test_a_corrupt_cache_file_is_ignored_and_never_shown(tmp_path):
    load(tmp_path, Counting())
    for g in GROUPS:
        (tmp_path / f"orbit_{g}.json").write_text("{ this is not json")
    down = Counting(status=500)
    r = load(tmp_path, down, NOW + timedelta(hours=3))
    assert r["status"] == "unavailable" and r["records"] == []


def test_a_cache_with_the_wrong_schema_or_group_is_ignored(tmp_path):
    load(tmp_path, Counting())
    p = tmp_path / "orbit_geo.json"
    e = json.loads(p.read_text())
    p.write_text(json.dumps({**e, "schema_version": 999}))
    assert OrbitCache(str(tmp_path)).read("geo") is None
    p.write_text(json.dumps({**e, "group": "ses"}))
    assert OrbitCache(str(tmp_path)).read("geo") is None


def test_a_cache_entry_with_garbage_records_yields_no_valid_rows(tmp_path):
    cache = OrbitCache(str(tmp_path))
    cache.write("geo", {"raw": [{"NORAD_CAT_ID": "x"}, "not a dict", {"EPOCH": "nope"}], "retrieved_at_utc": orbit_data.iso_ms(NOW), "upstream_status": 200})
    r = sf.load_groups(("geo",), cache, NOW + timedelta(minutes=5), Counting(status=500))
    assert r["records"] == [] and sf.build_rows(r["records"], NOW)["rows"] == []


def test_an_unusable_200_never_replaces_good_cached_data(tmp_path):
    load(tmp_path, Counting())
    r = load(tmp_path, Counting(body={"error": "not a list"}), NOW + timedelta(hours=3))
    assert r["status"] == "stale" and r["records"]


def test_a_failure_with_no_cache_builds_no_rows_ever(tmp_path):
    for status in (403, 429, 500, None):
        r = load(tmp_path / f"d{status}", Counting(status=status))
        assert r["records"] == [] and sf.build_rows(r["records"], NOW) == {"rows": [], "skipped": {"propagation_failed": 0}, "omm_only": 0}


def test_two_loads_racing_for_the_same_cache_directory_leave_a_valid_cache(tmp_path):
    """Two QGIS windows (or a plugin reload) can refresh at once: writes are atomic (temp file + rename), so a reader never sees half a file."""
    import threading
    errors = []

    def work():
        try:
            for _ in range(5):
                load(tmp_path, Counting(), NOW + timedelta(hours=3, seconds=_))
        except Exception as exc:                                       # pragma: no cover - the assertion below reports it
            errors.append(exc)
    threads = [threading.Thread(target=work) for _ in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors
    for g in GROUPS:
        e = OrbitCache(str(tmp_path)).read(g)
        assert e is not None and e["raw"] and orbit_data.parse_epoch_utc(e["retrieved_at_utc"])
    assert not [n for n in os.listdir(tmp_path) if n.endswith(".tmp")]


def test_the_endpoint_and_format_are_the_documented_current_ones():
    """OMM JSON, not legacy TLE: catalog numbers above 99999 exist only in OMM; the host and path are CelesTrak's GP query."""
    f = Counting()
    OrbitCache  # noqa: B018
    load_dir = __import__("tempfile").mkdtemp()
    load(load_dir, f)
    assert f.calls[0].startswith("https://celestrak.org/NORAD/elements/gp.php?GROUP=") and f.calls[0].endswith("&FORMAT=json")
    assert sf.USER_AGENT.startswith("VeloronaQGIS") and sf.TIMEOUT == (5.0, 20.0)
