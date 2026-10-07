"""The workbook: eight sheets, valid names, and every exported number exactly the
number the engine produced."""
import re
import zipfile
from io import BytesIO

import pytest
from presentation_fixtures import terrain_result, weather_result
from test_presentation_weather import _history

from core.export import NotExportable, result_to_csv, result_to_xlsx
from core.presentation import registry
from core.presentation.workbook import raw_rows
from core.presentation.xlsx import Cell, Sheet, header, read_workbook, sheet_name, write_workbook

SHEETS = ["SUMMARY", "LINK ANALYSIS", "WEATHER", "WEATHER HISTORY", "ELEVATION-TERRAIN", "EVIDENCE", "RAW DATA",
          "DATA DICTIONARY"]


def _terrain_book(**kw):
    res = terrain_result(**kw)
    return res, read_workbook(result_to_xlsx(res))


def _weather_book(**kw):
    res = weather_result(history={"A": _history("A"), "B": _history("B")}, **kw)
    return res, read_workbook(result_to_xlsx(res))


def _table(rows, key_col=0):
    return {r[key_col]: r for r in rows if r and r[key_col] is not None}


def test_sheet_names_are_valid_excel_names():
    assert sheet_name("ELEVATION / TERRAIN") == "ELEVATION - TERRAIN"
    for name in SHEETS:
        assert len(name) <= 31 and not re.search(r"[\\/*?:\[\]]", name)


def test_all_eight_sheets_in_order_for_both_kinds():
    assert list(_terrain_book()[1]) == SHEETS
    assert list(_weather_book()[1]) == SHEETS


def test_file_is_a_well_formed_package():
    data = result_to_xlsx(terrain_result())
    with zipfile.ZipFile(BytesIO(data)) as z:
        assert z.testzip() is None
        names = set(z.namelist())
    assert {"[Content_Types].xml", "xl/workbook.xml", "xl/styles.xml", "xl/worksheets/sheet8.xml"} <= names


def test_terrain_raw_data_equals_engine_values_exactly():
    res, book = _terrain_book(hump_m=20.0)
    r = res.result
    raw = _table(book["RAW DATA"])
    expect = {
        "terrain.terrain_clearance_m": r.terrain_clearance_m, "terrain.required_clearance_m": r.required_clearance_m,
        "terrain.first_fresnel_radius_m": r.first_fresnel_radius_m, "terrain.clearance_ratio": r.clearance_ratio,
        "terrain.distance_km": r.distance_km, "terrain.bearing_deg": r.bearing_deg,
        "terrain.frequency_ghz": r.frequency_ghz, "terrain.percent_fresnel_clear": r.percent_fresnel_clear,
        "terrain.margin_m": r.terrain_clearance_m - r.required_clearance_m, "terrain.samples": len(r.profile),
    }
    for key, value in expect.items():
        assert raw[key][1] == value, key           # exact float equality, no tolerance
    assert raw["terrain.los_status"][1] == r.los_status


def test_link_analysis_numbers_equal_engine_values_exactly():
    res, book = _terrain_book()
    r = res.result
    rows = _table(book["LINK ANALYSIS"])
    assert rows["Clearance available"][1] == r.terrain_clearance_m
    assert rows["Clearance required"][1] == r.required_clearance_m
    assert rows["Clearance margin"][1] == r.terrain_clearance_m - r.required_clearance_m
    assert rows["Path distance"][1] == r.distance_km
    assert rows["Status"][1] == "CLEAR"


def test_elevation_sheet_is_every_sample_exactly():
    res, book = _terrain_book(hump_m=10.0)
    r = res.result
    rows = book["ELEVATION-TERRAIN"][1:]
    assert len(rows) == len(r.profile) == 50
    for row, p in zip(rows, r.profile):
        assert row[1] == p.distance_from_a_km and row[4] == p.ground_elevation_m
        assert row[6] == p.terrain_adjusted_m and row[7] == p.los_height_m
        assert row[8] == p.fresnel_radius_m and row[9] == p.clearance_m
    assert sum(1 for row in rows if row[11] == "YES") == 1


def test_weather_raw_data_equals_engine_values_exactly():
    res, book = _weather_book()
    e = res.exposure
    raw = _table(book["RAW DATA"])
    assert raw["weather.predicted_attenuation_db"][1] == e.attenuation.predicted_attenuation_db
    assert raw["weather.rain_rate_mm_h"][1] == e.rain_rate_mm_h
    assert raw["weather.fade_margin_db"][1] == e.link.fade_margin_db
    assert raw["weather.exposure_ratio"][1] == e.exposure_ratio
    assert raw["weather.fade_remaining_db"][1] == e.link.fade_margin_db - e.attenuation.predicted_attenuation_db
    assert raw["weather.Site A.station_distance_km"][1] == 4.8
    assert raw["weather.Site A.model_rain_mm_h"][1] == 2.4


def test_weather_sheet_states_source_station_and_selection():
    _, book = _weather_book()
    rows = _table(book["WEATHER"])
    assert rows["Nearest station"][1] == "BRAMPTON"
    assert rows["Distance, site to station (km)"][1] == 4.8
    assert "Model-derived" in rows["Kind of value"][1]
    assert "Nearest ECCC station" in str(rows["Why this record"][1]) or "Weather model value" in str(rows["Why this record"][1])
    assert rows["Rain rate, model-derived (mm/h)"][1] == 2.4


def test_history_sheet_has_changes_with_explicit_baselines():
    _, book = _weather_book()
    rows = book["WEATHER HISTORY"]
    flat = [r for r in rows if len(r) > 7 and r[7] in ("vs 1 hour ago", "vs 2 hours ago", "vs 3 hours ago")]
    assert flat
    temp = next(r for r in flat if r[1] == 1.0 and str(r[2]).startswith("Temperature"))
    assert (temp[3], temp[4]) == (10.9, 11.5) and temp[5] == pytest.approx(-0.6) and "decrease" in temp[6]


def test_summary_leads_with_status_and_plain_language():
    _, book = _terrain_book()
    rows = _table(book["SUMMARY"])
    assert rows["Link status"][1] == "CLEAR"
    assert "well above" in rows["Link status"][2]
    assert rows["Available clearance"][1].endswith(" m") and rows["Clearance margin"][1].startswith("+")
    _, wbook = _weather_book()
    assert "Weather status" in _table(wbook["SUMMARY"])


def test_sheets_that_do_not_apply_say_so():
    _, book = _terrain_book()
    assert "Not part of this analysis" in book["WEATHER"][1][0]
    assert "Not part of this analysis" in book["WEATHER HISTORY"][1][0]
    _, wbook = _weather_book()
    assert "Not part of this analysis" in wbook["LINK ANALYSIS"][1][0]
    assert "Not part of this analysis" in wbook["ELEVATION-TERRAIN"][1][0]


def test_evidence_sheet_is_the_csv_export():
    res, book = _terrain_book()
    import csv, io
    body = "".join(l for l in io.StringIO(result_to_csv(res)) if not l.startswith("#"))
    table = [r for r in csv.reader(io.StringIO(body)) if r]
    # the reader returns an empty cell as None; the CSV has an empty string
    sheet = [[c or "" for c in r] + [""] * (len(table[0]) - len(r)) for r in book["EVIDENCE"] if r]
    assert sheet[-len(table):] == table


def test_every_raw_key_is_in_the_dictionary():
    res, book = _terrain_book()
    in_dictionary = {r[0] for r in book["DATA DICTIONARY"] if r}
    for key in registry.FIELDS:
        assert key in in_dictionary
    calc_ids = {c.id for c in registry.CALCULATIONS}
    for f in registry.FIELDS.values():
        assert f.calc == "" or f.calc in calc_ids, f.key
    for row in raw_rows(__import__("core.presentation.workbook", fromlist=["x"]).context_for(res)):
        assert row[5] == "" or row[5] in calc_ids


def test_xml_hostile_text_is_escaped():
    data = write_workbook([Sheet("S", [header("a"), ["<b>&\x01 x"]])])
    assert read_workbook(data)["S"][1] == ["<b>& x"]


def test_unsupported_kinds_are_refused():
    from types import SimpleNamespace
    with pytest.raises(NotExportable):
        result_to_xlsx(SimpleNamespace(kind="satellite-earth-space"))


def test_infinite_ratio_does_not_corrupt_the_file():
    data = write_workbook([Sheet("S", [[Cell(float("inf")), Cell(float("nan"))]])])
    assert read_workbook(data)["S"][0] == ["inf", "NaN"]
