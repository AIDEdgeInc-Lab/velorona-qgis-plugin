"""'What changed' through the shared aei-history-contract. The rules themselves (tolerance, precision, no_data, like-with-like) are the contract's own
golden cases (82 of them, Python and JavaScript); these tests check that the plugin delegates to it, adds nothing of its own to the answer, and
phrases it as the contract does."""
import aei_history_contract as contract
import pytest

from core import history_changes as C
from core import history_store as H
from core.history_store import HistoryRecord

NOW = 1_790_000_000.0


def ts(hours_ago):
    return H.utc_text(NOW - hours_ago * 3600)


def rec(hours_ago, value, metric="rain_rate", kind="model", source="open-meteo", entity="A", unit="mm/h"):
    return HistoryRecord(ts=ts(hours_ago), source=source, entity_id=entity, metric=metric, value=value, unit=unit, kind=kind, data_version="v")


def one(records, n=5, metric="rain_rate", **kw):
    s = C.compute_changes(records, "A", NOW, n, **kw)
    return next(c for c in s["changes"] if c["metric"] == metric), s


def test_the_answer_is_the_contracts_answer_unchanged():
    records = [rec(5, 0.0), rec(0, 1.2), rec(5, "CLEAR", metric="status", unit="enum"), rec(0, "WATCH", metric="status", unit="enum")]
    ours = C.compute_changes(records, "A", NOW, 5, entity_label="Site A")
    theirs = contract.summarize_changes([r.to_dict() for r in records], "A", ts(0), 5)
    assert {k: v for k, v in ours.items() if k != "entity_label"} == theirs and ours["entity_label"] == "Site A"


def test_sentences_are_the_contracts_wording():
    c, s = one([rec(5, 0.0), rec(0, 1.2)])
    assert (c["result"], c["then"], c["now"], c["delta"]) == ("increased", 0.0, 1.2, 1.2)
    assert C.sentences(s, "Site A")[0] == contract.render_text(c, 5, "Site A")
    assert C.sentences(s, "Site A")[0] == f"Rain rate at Site A: 1.2 mm/h now, 0.0 mm/h 5 h ago (model-derived, open-meteo, {ts(5)[11:16]} UTC \u2192 {ts(0)[11:16]} UTC)."


def test_insufficient_history_and_no_data_are_stated_not_guessed():
    c, s = one([rec(2, 1.0), rec(0, 2.0)], n=5)
    assert c["result"] == "insufficient_history" and c["available_hours"] == 2.0
    assert "no stored value from about 5 h ago" in C.sentences(s, "Site A")[0]
    c, s = one([rec(5, None), rec(0, 1.0)])
    assert c["result"] == "no_data" and "NO DATA" in C.sentences(s, "Site A")[0]


def test_other_entities_are_ignored_and_kinds_are_not_mixed():
    records = [rec(5, 0.0, entity="B"), rec(0, 9.0, entity="B"), rec(0, 1.0)]
    assert one(records)[0]["result"] == "insufficient_history"
    s = C.compute_changes([rec(5, 0.0, kind="observed", source="ECCC"), rec(0, 4.0, kind="model")], "A", NOW, 5)
    assert {(c["kind"], c["source"]) for c in s["changes"]} == {("observed", "ECCC"), ("model", "open-meteo")}


def test_no_adjectives_in_any_sentence():
    text = " ".join(C.sentences(C.compute_changes([rec(5, 0.0), rec(0, 9.9)], "A", NOW, 5), "Site A")).lower()
    for word in ("worsen", "improv", "better", "worse", "rapid", "sharp", "severe", "predict", "forecast", "will "):
        assert word not in text


def test_a_non_positive_window_is_refused():
    with pytest.raises(ValueError):
        C.compute_changes([], "A", NOW, 0)


def test_age_text():
    assert C.age_text(NOW, ts(0)) == "just now"
    assert C.age_text(NOW, ts(0.5)) == "30 min ago"
    assert C.age_text(NOW, ts(5)) == "5.0 h ago"
    assert C.age_text(NOW, ts(20)) == "20 h ago"
