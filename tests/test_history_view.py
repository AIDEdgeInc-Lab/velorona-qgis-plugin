"""History HTML: escaped, kinds kept apart, every row has unit/source/as-of, hashed entities named honestly."""
from core import history_store as H
from core import history_view as V
from core.history_store import HistoryRecord

NOW = 1_790_000_000.0


def rec(hours_ago, value, kind="model", metric="rain_rate", source="open-meteo", entity="A", unit="mm/h", **kw):
    return HistoryRecord(ts=H.utc_text(NOW - hours_ago * 3600), source=source, entity_id=entity, metric=metric, value=value, unit=unit, kind=kind,
                         data_version="v", **kw)


def test_kinds_are_separate_sections_in_a_fixed_order():
    html = V.timeline_html([rec(0, 1.0, kind="model"), rec(0, 0.4, kind="observed", source="ECCC")], NOW)
    assert html.index("Observed") < html.index("Model-derived") and html.count("<table") == 2
    assert "Forecast" not in html


def test_every_row_has_unit_source_as_of_and_age():
    html = V.timeline_html([rec(5, 1.2)], NOW)
    for fragment in ("mm/h", "open-meteo", " UTC", "5.0 h ago", "<th>Unit</th>", "<th>Source</th>", "<th>As of</th>"):
        assert fragment in html


def test_no_data_is_labelled_not_zero():
    html = V.timeline_html([rec(0, None, nodata_reason="the provider did not report it")], NOW)
    assert "NO DATA" in html and "the provider did not report it" in html and ">0.0<" not in html


def test_untrusted_text_is_escaped():
    html = V.timeline_html([rec(0, 1.0, source="<script>alert(1)</script>")], NOW)
    assert "<script>" not in html and "&lt;script&gt;" in html


def test_hashed_entities_are_not_shown_as_a_name_they_do_not_have():
    assert V.label_for("h:abcdef0123456789") == "Your link or site (h:abcd)" and V.label_for("010752966-001") == "010752966-001"
    assert V.label_for("h:x", {"h:x": "Site A"}) == "Site A"


def test_empty_and_error_states_say_what_happened_and_that_nothing_leaves():
    assert "No history is stored yet" in V.empty_html() and "Nothing is uploaded" in V.empty_html()
    e = V.error_html("locked <b>")
    assert "could not be read" in e and "&lt;b&gt;" in e and "not affected" in e


def test_changes_block_lists_only_comparable_pairs_and_states_why_others_are_missing():
    html = V.changes_html([rec(5, 0.0), rec(0, 1.2)], {"A": "Site A"}, NOW, windows=(6, 24))
    assert "Compared with 6 h ago" in html and "Rain rate at Site A: 1.2 mm/h now, 0.0 mm/h 5 h ago" in html   # the sentence states the stored value's real age (contract 0.2.0), not the requested window
    assert "Compared with 24 h ago" in html and "No stored value is close enough to 24 h ago" in html
    assert V.changes_html([], {"A": "Site A"}, NOW) == ""
