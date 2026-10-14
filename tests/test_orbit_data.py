"""Orbital-data ingestion and cache (core/sources/orbit_data.py): QGIS-free, no network, no QGIS runtime.

Inputs are SYNTHETIC (tests/fixtures/orbitdata/, copies of the Map's fixtures); they carry no real orbital data. The ingestion result is compared with
the output of the Map's own ingestion (web/orbitdata.js) on the same file, so this proves Map/QGIS agreement on the rules, NOT that the plugin can reach
CelesTrak: nothing here fetches, and the plugin does not yet call this module.
"""
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone

import pytest

from core.sources import orbit_data as OD

FX = os.path.join(os.path.dirname(__file__), "fixtures", "orbitdata")
NOW = datetime(2026, 10, 2, tzinfo=timezone.utc)
FETCH_OK = lambda body: (lambda url: OD.FetchResult(status=200, text=body))


def rec(cid, **over):
    r = {"OBJECT_NAME": f"TEST-{cid}", "OBJECT_ID": "2026-050A", "NORAD_CAT_ID": cid, "EPOCH": "2026-10-01T00:00:00.000000", "MEAN_MOTION": 15.1, "ECCENTRICITY": 0.0001,
         "INCLINATION": 53.0, "RA_OF_ASC_NODE": 1.0, "ARG_OF_PERICENTER": 2.0, "MEAN_ANOMALY": 3.0, "BSTAR": 0.0001, "MEAN_MOTION_DOT": 0, "MEAN_MOTION_DDOT": 0}
    r.update(over)
    return r


def test_fixture_files_are_the_pinned_copies():
    for name, digest in (("synthetic_leo_group.json", "7336ac124293d611cdbe5f4b848853119f11c87f910991711b1f337d129fc7b7"),
                         ("synthetic_leo_group_ingest_golden.json", "01fbe9c7a3ce1db65d01788388ae9c09e4cecd0d513d7c93659fd375fcd2b620")):
        assert hashlib.sha256(open(os.path.join(FX, name), "rb").read()).hexdigest() == digest, name


def test_ingestion_matches_the_maps_own_output_on_the_shared_fixture():
    gold = json.load(open(os.path.join(FX, "synthetic_leo_group_ingest_golden.json")))["json"]
    records, report = OD.ingest(OD.parse_gp_json(open(os.path.join(FX, "synthetic_leo_group.json"), encoding="utf-8").read()), NOW)
    assert report["counts"] == gold["counts"]
    assert {str(r["satellite_id"]): {"epoch_utc": r["orbit_epoch_utc"], "legacy_tle_compatible": r["legacy_tle_compatible"], "name": r["satellite_name"]} for r in records} == gold["records"]
    for k, v in gold["epoch_age_days"].items():
        assert report["epoch_age_days"][k] == pytest.approx(v, abs=1.5e-3), k


def test_duplicates_resolve_to_the_newest_epoch_not_the_last_record_read():
    older, newer = rec(100001, EPOCH="2026-09-30T12:00:00.000000"), rec(100001, EPOCH="2026-10-01T12:00:00.000000")
    for order in ([older, newer], [newer, older]):
        records, report = OD.ingest(order, NOW)
        assert [r["orbit_epoch_utc"] for r in records] == ["2026-10-01T12:00:00.000Z"] and report["counts"]["duplicates"] == 1


def test_missing_is_not_invalid_and_nothing_is_filled_in():
    miss = rec(1); del miss["INCLINATION"]
    assert OD.normalize_record(miss)["status"] == "incomplete"
    assert OD.normalize_record(rec(1, INCLINATION=""))["status"] == "incomplete"
    for bad in (rec(1, INCLINATION="abc"), rec(1, ECCENTRICITY=1), rec(1, MEAN_MOTION=-1), rec(1, EPOCH="not a date"), rec(1, NORAD_CAT_ID="12ab"), rec(1, MEAN_ANOMALY=True), None, [], "x"):
        assert OD.normalize_record(bad)["status"] == "invalid", bad
    r = OD.normalize_record(rec(7, OBJECT_NAME="<img src=x>\x00A"))
    assert "\x00" not in r["record"]["satellite_name"] and r["record"]["satellite_name"].startswith("<img"), "names are cleaned of control characters, never trusted as markup"


def test_catalog_ids_above_five_digits_are_preserved_and_flagged_not_tle_compatible():
    for cid, legacy in ((99999, True), (100000, False), ("100001", False), (123456789, False)):
        r = OD.normalize_record(rec(cid))["record"]
        assert r["satellite_id"] == int(cid) and r["satellite_id_text"] == str(cid) and r["legacy_tle_compatible"] is legacy
    assert OD.normalize_record(rec("1234567890"))["status"] == "invalid"


def test_epochs_without_a_zone_are_utc():
    assert OD.parse_epoch_utc("2026-10-01T00:00:00.000000") == datetime(2026, 10, 1, tzinfo=timezone.utc)
    assert OD.parse_epoch_utc("2026-10-01T02:00:00+02:00") == datetime(2026, 10, 1, tzinfo=timezone.utc)
    assert OD.parse_epoch_utc("2026-13-40T00:00:00") is None


def test_payload_parsing_limits():
    assert OD.parse_gp_json("") == [] and OD.parse_gp_json("No GP data found") == []
    for body, code in (("{oops", "malformed"), ("{}", "malformed"), ("x" * (OD.MAX_PAYLOAD_CHARS + 1), "too_large"), ("[" + "{}," * OD.MAX_RECORDS + "{}]", "too_large")):
        with pytest.raises(OD.GpPayloadError) as e:
            OD.parse_gp_json(body)
        assert e.value.code == code


def test_success_is_cached_with_the_real_retrieval_time_and_reused_inside_the_cycle(tmp_path):
    calls = []
    def fetch(url):
        calls.append(url); return OD.FetchResult(status=200, text=json.dumps([rec(100001), rec(123456789)]))
    cache = OD.OrbitCache(str(tmp_path))
    a = OD.load_group("oneweb", fetch, cache, NOW)
    assert a["status"] == "fresh" and a["from_cache"] is False and a["retrieved_at_utc"] == "2026-10-02T00:00:00.000Z" and a["upstream_status"] == 200
    assert calls == ["https://celestrak.org/NORAD/elements/gp.php?GROUP=oneweb&FORMAT=json"] and a["request_url"] == calls[0]
    assert [r["satellite_id"] for r in a["records"]] == [100001, 123456789]
    b = OD.load_group("oneweb", fetch, cache, NOW + timedelta(hours=1))
    assert b["status"] == "fresh" and b["from_cache"] is True and b["age_seconds"] == 3600 and len(calls) == 1
    OD.load_group("oneweb", fetch, cache, NOW + timedelta(hours=2, seconds=1))
    assert len(calls) == 2, "refreshed after the 2 h cycle"
    assert not [f for f in os.listdir(tmp_path) if f.endswith(".tmp")], "atomic write leaves no temp file"


@pytest.mark.parametrize("status", [403, 404, 429, 500, 503])
def test_after_any_non_200_the_source_is_not_asked_again_inside_the_back_off(tmp_path, status):
    calls = []
    def fetch(url):
        calls.append(url); return OD.FetchResult(status=status, text="")
    cache = OD.OrbitCache(str(tmp_path))
    r = OD.load_group("oneweb", fetch, cache, NOW)
    assert r["status"] == "unavailable" and r["reason"] == f"http_{status}" and r["upstream_status"] == status
    assert OD.load_group("oneweb", fetch, cache, NOW + timedelta(minutes=14))["reason"] == "backoff" and len(calls) == 1
    OD.load_group("oneweb", fetch, OD.OrbitCache(str(tmp_path)), NOW + timedelta(minutes=16)); assert len(calls) == 2, "the back-off survives a new cache object (a restart) and then ends"


def test_retry_after_is_honoured_and_network_errors_back_off_60_s(tmp_path):
    calls = []
    def fetch(url):
        calls.append(1); return OD.FetchResult(status=503, text="", headers={"Retry-After": "3600"})
    cache = OD.OrbitCache(str(tmp_path))
    OD.load_group("oneweb", fetch, cache, NOW); OD.load_group("oneweb", fetch, cache, NOW + timedelta(minutes=50)); assert len(calls) == 1
    OD.load_group("oneweb", fetch, cache, NOW + timedelta(minutes=61)); assert len(calls) == 2
    n = []
    def down(url):
        n.append(1); return OD.FetchResult(error="network")
    c2 = OD.OrbitCache(str(tmp_path / "x"))
    assert OD.load_group("starlink", down, c2, NOW)["reason"] == "network"
    assert OD.load_group("starlink", down, c2, NOW + timedelta(seconds=30))["reason"] == "backoff" and len(n) == 1
    OD.load_group("starlink", down, c2, NOW + timedelta(seconds=61)); assert len(n) == 2


def test_an_unusable_body_is_never_cached_and_does_not_replace_good_data(tmp_path):
    cache = OD.OrbitCache(str(tmp_path))
    OD.load_group("oneweb", FETCH_OK(json.dumps([rec(100001)])), cache, NOW)
    later = NOW + timedelta(hours=3)
    r = OD.load_group("oneweb", FETCH_OK("<html>blocked</html>"), cache, later)
    assert r["status"] == "stale" and r["reason"] == "malformed" and r["retrieved_at_utc"] == "2026-10-02T00:00:00.000Z" and r["age_seconds"] == 3 * 3600
    assert len(r["records"]) == 1 and "older than its refresh interval" in " ".join(r["warnings"])
    assert OD.OrbitCache(str(tmp_path)).read("oneweb")["raw"][0]["NORAD_CAT_ID"] == 100001, "the good copy is still the stored one"


def test_stale_data_is_never_labelled_fresh(tmp_path):
    cache = OD.OrbitCache(str(tmp_path))
    OD.load_group("oneweb", FETCH_OK(json.dumps([rec(100001)])), cache, NOW)
    r = OD.load_group("oneweb", lambda u: OD.FetchResult(error="timeout"), cache, NOW + timedelta(days=1))
    assert r["status"] == "stale" and r["reason"] == "timeout" and r["age_seconds"] == 86400


def test_empty_group_is_reported_and_corrupt_cache_is_ignored(tmp_path):
    cache = OD.OrbitCache(str(tmp_path))
    assert "empty group" in " ".join(OD.load_group("oneweb", FETCH_OK("[]"), cache, NOW)["warnings"])
    (tmp_path / "orbit_starlink.json").write_text("{{{")
    assert OD.load_group("starlink", FETCH_OK(json.dumps([rec(1)])), cache, NOW)["status"] == "fresh"


def test_group_names_cannot_reach_the_file_system(tmp_path):
    cache = OD.OrbitCache(str(tmp_path))
    for bad in ("../etc/passwd", "ONEWEB", "oneweb/../x", "", "nope"):
        assert OD.load_group(bad, FETCH_OK("[]"), cache, NOW)["reason"] == "unknown_group"
        with pytest.raises(ValueError):
            cache._path(bad)
    assert os.listdir(tmp_path) == []


def test_the_cache_refuses_to_store_what_is_not_parsed_records_with_a_real_time(tmp_path):
    cache = OD.OrbitCache(str(tmp_path))
    assert cache.write("oneweb", {"raw": "<html>", "retrieved_at_utc": "2026-10-02T00:00:00.000Z"}) is False
    assert cache.write("oneweb", {"raw": [], "retrieved_at_utc": "not a time"}) is False
    assert cache.read("oneweb") is None


def test_the_module_has_no_network_qgis_or_fixture_dependency():
    src = open(OD.__file__, encoding="utf-8").read()
    for token in ("import requests", "from qgis", "import qgis", "urllib", "socket", "tests/fixtures", "SYNTH"):
        assert token not in src, token
    assert "NORAD_CAT_ID\": 1" not in src and "MEAN_MOTION\": 1" not in src, "no embedded records"


def test_group_names_equal_the_maps_registry():
    assert OD.GROUPS == {"geo": "geo", "intelsat": "intelsat", "ses": "ses", "eutelsat": "eutelsat", "telesat": "telesat", "starlink": "starlink", "oneweb": "oneweb",
                         "kuiper": "kuiper", "iridium-next": "iridium-NEXT", "globalstar": "globalstar", "orbcomm": "orbcomm", "planet": "planet"}
