"""Negative clearance and the retired "X% above minimum" wording: one explanation,
used identically by Brief, CSV, Excel and Ask."""
import csv
import importlib
import io
import re

import pytest
from presentation_fixtures import terrain_result, weather_result

from core.export import result_to_csv, result_to_xlsx
from core.presentation import terrain as T
from core.presentation.ask import AskContext, ask
from core.presentation.model import CRITICAL
from xlsx_reader import read_workbook

OLD_WORDING = re.compile(r"\d+%\s+(above|below)\s+(the\s+)?(minimum|standard)", re.I)


def _res(hump):
    res = terrain_result(hump_m=float(hump))
    lib = importlib.import_module("aei_link_clearance.explain")
    res.explanation = lib.explain(res.result)       # the library's real wording, as the engine stores it
    return res


# ---- negative clearance ----------------------------------------------------

def test_negative_ratio_is_the_librarys_exact_quotient():
    r = _res(100).result
    assert r.terrain_clearance_m < 0 and r.clearance_ratio < 0
    assert r.clearance_ratio == r.terrain_clearance_m / r.required_clearance_m   # no clamp, no defect


def test_negative_clearance_means_terrain_above_line_of_sight():
    """terrain_clearance_m = LOS height - curvature-adjusted terrain, at the critical point."""
    r = _res(100).result
    crit = T.critical_point(r)
    assert crit.clearance_m == crit.los_height_m - crit.terrain_adjusted_m < 0
    assert crit.terrain_adjusted_m > crit.los_height_m


def test_every_negative_ratio_case_is_critical():
    for hump in range(36, 200, 4):
        res = _res(hump)
        if res.result.clearance_ratio < 0:
            b = T.terrain_brief(res)
            assert res.result.los_status == "obstructed" and b.status == CRITICAL


def test_negative_wording_is_explicit():
    res = _res(40)
    r = res.result
    b = T.terrain_brief(res)
    facts = {f.label: f for f in b.key_facts}
    tech = {f.label: f for f in b.technical}
    assert "envelope" in facts["Margin"].comparison and "above the line of sight" in facts["Margin"].comparison
    assert "negative means the terrain is" in facts["Clearance available"].comparison
    assert tech["Clearance ratio"].value.startswith("-") and "terrain is above the line of sight" in tech["Clearance ratio"].meaning
    assert "above the line of sight" in tech["Fresnel zone clear"].meaning
    assert "short by" in b.data["explanation"] and "%" not in b.data["explanation"]


def test_positive_and_shortfall_wording():
    ok = T.terrain_explanation(_res(0).result)
    assert "available vs" in ok and "margin" in ok and "×" in ok and "%" not in ok
    # marginal: positive clearance below the requirement. Hump 20 m gives +4.8 m vs 6.8 m required under the corrected curvature sign
    # (P11); it was 30 m before the correction, when curvature wrongly added clearance.
    short = T.terrain_explanation(_res(20).result)
    assert "short by" in short and "above the line of sight" not in short
    assert "inside the required clearance envelope" in T.margin_phrase(6.2, 6.8)


def test_ask_negative_clearance_is_explicit():
    ctx = AskContext(terrain=T.terrain_brief(_res(40)))
    text = ask("How much clearance do we have?", ctx).text
    assert "negative: the terrain is" in text and "inside the required clearance envelope" in text


# ---- one wording everywhere ---------------------------------------------------

@pytest.mark.parametrize("hump", [0, 20, 30, 40, 100])
def test_no_old_percentage_wording_and_no_contradiction(hump):
    res = _res(hump)
    brief = T.terrain_brief(res)
    sentence = brief.data["explanation"]
    # CSV: the Explanation row carries the shared sentence; the ratio row has a meaning
    body = "".join(l for l in io.StringIO(result_to_csv(res)) if not l.startswith("#"))
    rows = {r[0]: r for r in csv.reader(io.StringIO(body)) if r}
    assert rows["Explanation"][5] == sentence
    assert rows["Clearance ratio"][5].startswith(T.ratio_value(res.result))
    for r in rows.values():
        assert not OLD_WORDING.search(" ".join(r)), r
    # Excel: summary shows the same sentence; the old library wording is only in RAW DATA
    wb = read_workbook(result_to_xlsx(res))
    summary = {r[0]: r for r in wb["SUMMARY"] if r}
    assert summary["Plain comparison"][1] == sentence
    for name, sheet in wb.items():
        for row in sheet:
            text = " ".join(str(c) for c in row if c)
            if name == "RAW DATA" and "library_explanation" in text:
                continue
            assert not OLD_WORDING.search(text), (name, text[:120])
    raw = {r[0]: r for r in wb["RAW DATA"] if r}
    assert raw["terrain.library_explanation"][1] == res.explanation      # kept for audit, unchanged
    # Ask: the numbers it quotes are the Brief's numbers
    ans = ask("How much clearance do we have?", AskContext(terrain=brief)).text
    assert f"{T.fmt(brief.data['terrain_clearance_m'])} m" in ans and f"{T.fmt(brief.data['required_clearance_m'])} m" in ans


def test_exposure_ratio_always_has_its_baseline_and_db():
    res = weather_result()
    body = "".join(l for l in io.StringIO(result_to_csv(res)) if not l.startswith("#"))
    row = next(r for r in csv.reader(io.StringIO(body)) if r and r[0] == "Exposure ratio")
    assert "% of the fade margin (" in row[4] and " dB of 32.0 dB)" in row[4]
    for r in csv.reader(io.StringIO(body)):
        for cell in r[3:5]:
            if re.fullmatch(r"-?\d+(\.\d+)?%", cell.strip()):
                pytest.fail(f"bare percentage: {r}")
