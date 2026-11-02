"""What an analysis writes to history: kinds, units, UTC times, derived rows, hashing of the user's own entities, and that capture never raises."""
from types import SimpleNamespace

from core import history_capture as CAP
from core import history_store as H
from core.history_store import HistoryStore
from presentation_fixtures import weather_result

NOW = H.parse_utc("2026-10-07T00:10:00Z")


def store(tmp_path):
    return HistoryStore(str(tmp_path / "h.sqlite"), clock=lambda: NOW)


def result_with_offsets(offset=-4 * 3600, **kw):
    res = weather_result(**kw)
    res.utc_offsets = {"A": offset, "B": offset}
    return res


def test_model_values_are_stored_as_kind_model_with_units_and_true_utc_time(tmp_path):
    s = store(tmp_path)
    recs, skipped = CAP.records_from_result(result_with_offsets(), s, NOW)
    model = [r for r in recs if r.kind == "model" and not r.derived and r.entity_type == "site"]
    assert skipped == 0
    rain = [r for r in model if r.metric == "rain_rate"]
    assert {r.entity_id for r in rain} == {s.entity_hash("A"), s.entity_hash("B")}
    assert all(r.ts == "2026-10-07T00:00:00Z" for r in rain)            # 20:00 at UTC-4 is 00:00 UTC next day
    assert {(r.metric, r.unit) for r in model} >= {("rain_rate", "mm/h"), ("temperature", "degC"), ("wind_speed", "km/h")}
    assert all(r.source == "open-meteo" for r in model)


def test_station_values_are_observed_and_never_forecast(tmp_path):
    recs, _ = CAP.records_from_result(result_with_offsets(), store(tmp_path), NOW)
    obs = [r for r in recs if r.kind == "observed"]
    assert obs and all(r.metric == "rain_rate" and r.unit == "mm/h" and r.ts == "2026-10-06T19:55:00Z" and "ECCC" in r.source for r in obs)
    assert not [r for r in recs if r.kind == "forecast"]


def test_the_three_derived_numbers_are_marked_derived_and_belong_to_the_link(tmp_path):
    s = store(tmp_path)
    res = result_with_offsets(rain_a=9.0)
    recs, _ = CAP.records_from_result(res, s, NOW)
    derived = {r.metric: r for r in recs if r.derived}
    assert set(derived) == {"rain_attenuation_estimate", "exposure_ratio", "status"}
    assert all(r.entity_type == "link" and r.kind == "model" and r.entity_id == s.entity_hash(res.exposure.link.id) for r in derived.values())
    assert derived["rain_attenuation_estimate"].value == res.exposure.attenuation.predicted_attenuation_db and derived["rain_attenuation_estimate"].unit == "dB"
    assert derived["status"].unit == "enum" and derived["status"].value in ("CLEAR", "WATCH", "AT RISK", "CRITICAL")


def test_without_the_providers_utc_offset_nothing_is_stored_with_a_guessed_time(tmp_path):
    res = weather_result()
    recs, skipped = CAP.records_from_result(res, store(tmp_path), NOW)
    assert not [r for r in recs if r.kind == "model"] and skipped >= 4          # 2 model sites + 3 derived rows cannot be dated


def test_the_users_own_entities_are_hashed_public_records_keep_their_id(tmp_path):
    s = store(tmp_path)
    own, _ = CAP.records_from_result(result_with_offsets(), s, NOW)
    assert all(r.entity_id.startswith("h:") for r in own)
    pub = SimpleNamespace(kind="link-investigation", exposure=result_with_offsets())
    recs, _ = CAP.records_from_result(pub, s, NOW)
    assert {r.entity_id for r in recs if r.entity_type == "link"} == {pub.exposure.exposure.link.id}


def test_link_investigation_without_weather_stores_nothing():
    assert CAP.records_from_result(SimpleNamespace(kind="link-investigation", exposure=None), None, NOW) == ([], 0)


def test_capture_round_trips_through_the_store_and_is_idempotent(tmp_path):
    s = store(tmp_path)
    res = result_with_offsets()
    first = CAP.capture(res, s, NOW)
    assert first.ok and first.written > 0
    assert CAP.capture(res, s, NOW).written == 0                                # same provider times -> no duplicates
    assert len(s.records()) == first.written


def test_capture_never_raises_even_for_a_shape_it_does_not_know(tmp_path):
    rep = CAP.capture(SimpleNamespace(kind="microwave-exposure", exposure=SimpleNamespace(exposure=SimpleNamespace())), store(tmp_path), NOW)
    assert not rep.ok and "could not be turned into history rows" in rep.message


def test_capture_survives_an_unwritable_store(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    rep = CAP.capture(result_with_offsets(), HistoryStore(str(blocker / "sub" / "h.sqlite"), clock=lambda: NOW), NOW)
    assert not rep.ok
