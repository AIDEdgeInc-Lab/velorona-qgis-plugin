"""Canonical status model (owner-approved P1, P4, P6): CLEAR / WATCH / AT RISK / CRITICAL / NO DATA; overall = worst of terrain and weather.
R1/R2/R7/R8 are not approved and not asserted here."""
from types import SimpleNamespace

import pytest

from core.presentation import model as M
from core.presentation.ask import AskContext, ask
from core.presentation.terrain import terrain_brief
from core.presentation.weather import exposure_brief, weather_status
from presentation_fixtures import terrain_result, weather_result


def _exp(att, fade, severity):
    return SimpleNamespace(attenuation=SimpleNamespace(predicted_attenuation_db=att), link=SimpleNamespace(fade_margin_db=fade), severity=severity)


@pytest.mark.parametrize("att,fade,sev,expected", [
    (13.5, 13.5, "high", M.CRITICAL),            # equality is exhausted (P4)
    (13.49, 13.5, "high", M.AT_RISK),            # just below: dB comparison, not the rounded ratio
    (14.0, 13.5, "high", M.CRITICAL),
    (5.0, 10.0, "high", M.AT_RISK), (3.0, 10.0, "moderate", M.WATCH), (0.5, 10.0, "low", M.CLEAR),
])
def test_weather_status_boundaries(att, fade, sev, expected):
    assert weather_status(_exp(att, fade, sev))[0] == expected


def test_weather_without_exposure_is_no_data():
    assert weather_status(None)[0] == M.NO_DATA


def test_worst_of_orders_no_data_between_clear_and_watch():
    assert M.worst(M.CLEAR, M.NO_DATA) == M.NO_DATA            # an unknown is never reported as fine
    assert M.worst(M.NO_DATA, M.WATCH) == M.WATCH              # a missing feed must not hide a real concern
    assert M.worst(M.CLEAR, M.CRITICAL, M.WATCH) == M.CRITICAL
    assert M.worst(M.AT_RISK, M.NO_DATA) == M.AT_RISK


def test_ask_leads_with_the_worst_domain_not_the_first_brief():
    """The overall verdict is the worst of terrain and weather; it used to follow whichever brief came first."""
    wx = exposure_brief(weather_result(rain_a=0.0, rain_b=0.0))             # CLEAR
    tr = terrain_brief(terrain_result(hump_m=60.0))                          # obstructed -> CRITICAL
    assert wx.status == M.CLEAR and tr.status == M.CRITICAL
    for briefs in (dict(weather=wx, terrain=tr), dict(terrain=tr, weather=wx)):
        text = ask("Is this link OK?", AskContext(**briefs)).text
        assert text.startswith("NOT CLEAR") and "CRITICAL" in text.splitlines()[0]
        assert "Weather exposure: CLEAR" in text and "Terrain clearance: CRITICAL" in text      # both domains stay visible
