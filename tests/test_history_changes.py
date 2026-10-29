"""'What changed' rules (CONTRACT section 2), checked against hand-computed cases and a golden file a JavaScript port must also reproduce."""
import json
import pathlib

import pytest

from core import history_changes as C
from core import history_store as H
from core.history_store import HistoryRecord

NOW = 1_790_000_000.0
GOLDEN = pathlib.Path(__file__).parent / "fixtures" / "history_changes_golden.json"


def ts(hours_ago):
    return H.utc_text(NOW - hours_ago * 3600)


def rec(hours_ago, value, metric="rain_rate", kind="model", source="open-meteo", entity="A", unit="mm/h"):
    return HistoryRecord(ts=ts(hours_ago), source=source, entity_id=entity, metric=metric, value=value, unit=unit, kind=kind, data_version="v")


def one(records, n=5, metric="rain_rate", **kw):
    s = C.compute_changes(records, "A", NOW, n, **kw)
    return next(c for c in s["changes"] if c["metric"] == metric), s


def test_increase_with_delta_and_sentence():
    c, s = one([rec(5, 0.0), rec(0, 1.2)])
    assert (c["result"], c["then"], c["now"], c["delta"]) == ("increased", 0.0, 1.2, 1.2)
    assert C.sentences(s, "Site A")[0] == "Rain rate at Site A: 1.2 mm/h now, 0.0 mm/h 5 h earlier (model-derived, open-meteo, " + ts(5)[11:16] + " UTC → " + ts(0)[11:16] + " UTC)"


def test_decrease():
    assert one([rec(5, 3.0), rec(0, 1.0)])[0]["result"] == "decreased"


def test_unchanged_means_equal_at_the_displayed_precision_not_a_threshold():
    assert one([rec(5, 1.04), rec(0, 1.01)])[0]["result"] == "unchanged"       # both show 1.0
    assert one([rec(5, 1.04), rec(0, 1.06)])[0]["result"] == "increased"        # 1.0 -> 1.1


def test_then_is_the_nearest_stored_row_within_tolerance():
    c, _ = one([rec(5.4, 9.0), rec(4.9, 2.0), rec(0, 3.0)], n=5)
    assert c["then"] == 2.0 and c["then_ts_actual"] == ts(4.9)


def test_tolerance_is_30_minutes_or_a_quarter_of_the_window():
    assert one([rec(5.6, 1.0), rec(0, 2.0)], n=5)[0]["result"] == "increased"                      # 36 min off, limit 75 min for n=5 -> accepted
    assert one([rec(6.4, 1.0), rec(0, 2.0)], n=5)[0]["result"] == "insufficient_history"           # 84 min off -> refused
    c, _ = one([rec(5.6, 1.0), rec(0, 2.0)], n=1)
    assert c["result"] == "insufficient_history"                                                    # n=1: limit 30 min, nearest row is 4.6 h away


def test_insufficient_history_states_how_much_there_is():
    c, s = one([rec(2, 1.0), rec(0, 2.0)], n=5)
    assert c["result"] == "insufficient_history" and c["history_span_h"] == 2.0
    assert "no stored value close enough to 5 h ago" in C.sentences(s, "Site A")[0] and "stored over 2 h" in C.sentences(s, "Site A")[0]


def test_a_single_row_is_insufficient_history_not_a_comparison_with_itself():
    assert one([rec(0, 1.0)])[0]["result"] == "insufficient_history"


def test_like_with_like_never_mixes_kind_or_source():
    records = [rec(5, 0.0, kind="observed", source="ECCC station"), rec(0, 4.0, kind="model"), rec(0, 0.2, kind="observed", source="ECCC station"),
               rec(5, 9.0, source="other-model")]
    s = C.compute_changes(records, "A", NOW, 5)
    by = {(c["kind"], c["source"]): c for c in s["changes"]}
    assert by[("observed", "ECCC station")]["result"] == "increased"
    assert by[("model", "open-meteo")]["result"] == "insufficient_history"          # the only model row has nothing to compare with
    assert by[("model", "other-model")]["result"] == "insufficient_history"


def test_missing_value_is_no_data_never_zero():
    c, s = one([rec(5, None), rec(0, 1.0)])
    assert c["result"] == "no_data" and "delta" not in c
    assert "not read as zero" in C.sentences(s, "Site A")[0]
    assert one([rec(5, 1.0), rec(0, None)])[0]["result"] == "no_data"


def test_status_changes_report_both_words():
    c, s = one([rec(5, "CLEAR", metric="status", unit="enum"), rec(0, "WATCH", metric="status", unit="enum")], metric="status")
    assert c["result"] == "status_changed"
    assert C.sentences(s, "the link")[0].startswith("Status at the link: WATCH now, CLEAR 5 h earlier")
    assert one([rec(5, "CLEAR", metric="status", unit="enum"), rec(0, "CLEAR", metric="status", unit="enum")], metric="status")[0]["result"] == "unchanged"


def test_other_entities_are_ignored():
    records = [rec(5, 0.0, entity="B"), rec(0, 9.0, entity="B"), rec(0, 1.0)]
    assert one(records)[0]["result"] == "insufficient_history"


def test_no_adjectives_in_any_sentence():
    records = [rec(5, 0.0), rec(0, 9.9)]
    text = " ".join(C.sentences(C.compute_changes(records, "A", NOW, 5), "Site A")).lower()
    for word in ("worsen", "improv", "better", "worse", "rapid", "sharp", "severe", "predict", "forecast", "will "):
        assert word not in text


def test_age_text():
    assert C.age_text(NOW, ts(0)) == "just now"
    assert C.age_text(NOW, ts(0.5)) == "30 min ago"
    assert C.age_text(NOW, ts(5)) == "5.0 h ago"
    assert C.age_text(NOW, ts(20)) == "20 h ago"


def _golden_cases():
    cases = []
    def add(name, records, n):
        cases.append({"name": name, "now_ts": H.utc_text(NOW), "n_hours": n,
                      "records": [{k: getattr(r, k) for k in ("ts", "source", "entity_id", "metric", "value", "unit", "kind")} for r in records]})
    add("increase", [rec(5, 0.0), rec(0, 1.2)], 5)
    add("unchanged-precision", [rec(5, 1.04), rec(0, 1.01)], 5)
    add("insufficient", [rec(2, 1.0), rec(0, 2.0)], 5)
    add("no-data", [rec(5, None), rec(0, 1.0)], 5)
    add("status", [rec(5, "CLEAR", metric="status", unit="enum"), rec(0, "WATCH", metric="status", unit="enum")], 5)
    add("kinds-not-mixed", [rec(5, 0.0, kind="observed", source="ECCC"), rec(0, 0.2, kind="observed", source="ECCC"), rec(0, 4.0)], 5)
    add("window-1h", [rec(1.1, 2.0), rec(0, 3.0)], 1)
    for c in cases:
        recs = [HistoryRecord(ts=r["ts"], source=r["source"], entity_id=r["entity_id"], metric=r["metric"], value=r["value"], unit=r["unit"],
                              kind=r["kind"], data_version="v") for r in c["records"]]
        c["expected"] = C.compute_changes(recs, "A", H.parse_utc(c["now_ts"]), c["n_hours"])
    return {"schema": "velorona.change-summary-golden/1", "cases": cases}


def test_golden_file_is_current_and_reproduced():
    fresh = _golden_cases()
    if not GOLDEN.exists():
        GOLDEN.write_text(json.dumps(fresh, indent=1) + "\n")
    committed = json.loads(GOLDEN.read_text())
    assert committed == json.loads(json.dumps(fresh)), "history_changes_golden.json is stale: delete it, run this test once, review the diff"
