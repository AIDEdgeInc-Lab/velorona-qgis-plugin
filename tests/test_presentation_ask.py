"""Ask: every answer is built from the Brief, names its evidence, and an
unanswerable question says so instead of guessing."""
from presentation_fixtures import terrain_result, weather_result
from test_presentation_weather import _history

from core.presentation.ask import AskContext, ask, suggested_questions
from core.presentation.terrain import terrain_brief
from core.presentation.weather import exposure_brief


def _terrain(hump=0.0):
    return AskContext(terrain=terrain_brief(terrain_result(hump_m=hump)))


def _weather(**kw):
    return AskContext(weather=exposure_brief(weather_result(history={"A": _history("A")}, **kw)))


def test_is_this_link_clear_quotes_the_three_numbers_and_evidence():
    ctx = _terrain()
    a = ask("Is this link clear?", ctx)
    d = ctx.terrain.data
    assert a.matched == "status"
    assert a.text.startswith("YES — CLEAR.")
    assert f"{d['terrain_clearance_m']:.1f} m" in a.as_text()
    assert "Evidence:" in a.as_text() and "50 elevation samples" in a.as_text()


def test_not_clear_is_not_reported_as_yes():
    a = ask("Is this link clear?", _terrain(hump=400.0))
    assert a.text.startswith("NOT CLEAR") and "YES" not in a.text


def test_how_much_clearance():
    ctx = _terrain()
    d = ctx.terrain.data
    a = ask("How much clearance do we have?", ctx)
    assert a.matched == "clearance"
    assert f"{d['terrain_clearance_m']:.1f} m" in a.text and f"{d['required_clearance_m']:.1f} m" in a.text
    assert "above the minimum" in a.text


def test_critical_point():
    ctx = _terrain()
    a = ask("Where is the critical point?", ctx)
    assert a.matched == "critical" and "km from Site A" in a.text and "lat " in a.text


def test_why_marked():
    ctx = _terrain()
    a = ask("Why is this marked CLEAR?", ctx)
    assert a.matched == "why" and ctx.terrain.reason in a.text


def test_changes_use_the_requested_window_and_state_the_baseline():
    ctx = _weather()
    a = ask("What changed in the last 2 hours?", ctx)
    assert a.matched == "changed"
    assert "2 hours earlier" in a.text and "vs 2 hours ago" in a.text
    assert "Temperature" in a.text and "↓" in a.text or "→" in a.text


def test_asking_beyond_available_history_says_so():
    a = ask("What changed in the last 12 hours?", _weather())
    assert "Only 4 hours of history" in a.text


def test_station_answer_names_station_distance_and_why():
    a = ask("Which weather station was used?", _weather())
    assert "BRAMPTON" in a.text and "4.8 km" in a.text and "Why:" in a.text
    assert "Model-derived" in a.text


def test_history_lists_hourly_values():
    a = ask("Show me the weather history.", _weather())
    assert a.matched == "history" and "2026-10-06T20:00" in a.text and "10.9" in a.text


def test_evidence_question():
    a = ask("What evidence supports this result?", _terrain())
    assert a.matched == "evidence" and "elevation samples" in a.text


def test_weather_questions_on_a_terrain_only_result_are_refused_honestly():
    a = ask("Which weather station was used?", _terrain())
    assert "not part of this analysis" in a.text
    a = ask("What changed in the last 2 hours?", _terrain())
    assert "No weather history" in a.text


def test_terrain_questions_on_a_weather_only_result_are_refused_honestly():
    a = ask("How much clearance do we have?", _weather())
    assert "not part of this analysis" in a.text


def test_unknown_question_does_not_guess():
    a = ask("What is the capital of France?", _terrain())
    assert a.matched == "help" and "could not match" in a.text
    assert "Paris" not in a.as_text()


def test_empty_context():
    assert "no analysis result" in ask("anything", AskContext()).text


def test_suggestions_only_offer_answerable_questions():
    t = suggested_questions(_terrain())
    assert not any("weather" in q.lower() for q in t)
    w = suggested_questions(_weather())
    assert not any("clearance" in q.lower() for q in w)
