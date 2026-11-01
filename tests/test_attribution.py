"""Data credits: Open-Meteo (CC BY 4.0) and the Copernicus DEM GLO-90 notice (ESA licence Art. 6(b) + 6(c), wording from REVIEW_HOTFIX_RADAR.md section 3):
in the panel and in every export that used the data, never where it was not used."""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import presentation_fixtures as F  # noqa: E402
from core import attribution, export  # noqa: E402
from xlsx_reader import read_workbook  # noqa: E402

LICENCE_NOTICE = ("produced using Copernicus WorldDEM™-90 © DLR e.V. 2010-2014 and © Airbus Defence and Space GmbH 2014-2018 provided under COPERNICUS "
                  "by the European Union and ESA; all rights reserved. The organisations in charge of the Copernicus programme by law or by delegation do not incur "
                  "any liability for any use of the Copernicus WorldDEM™-90")


def test_the_copernicus_notice_is_the_licence_text_with_the_liability_sentence():
    assert attribution.COPERNICUS_NOTICE.startswith("Elevation: ") and LICENCE_NOTICE in attribution.COPERNICUS_NOTICE
    assert "Contains modified" not in attribution.COPERNICUS_NOTICE


def test_weather_exports_credit_open_meteo_and_not_copernicus():
    text = export.result_to_csv(F.weather_result())
    assert "# Data credit: Weather data by Open-Meteo.com (https://open-meteo.com/), CC BY 4.0 (https://open-meteo.com/en/license)" in text
    assert "Copernicus" not in text


def test_online_terrain_credits_open_meteo_and_the_copernicus_notice():
    text = export.result_to_csv(F.terrain_result())
    assert "# Data credit: Elevation data by Open-Meteo.com (https://open-meteo.com/), CC BY 4.0" in text
    assert LICENCE_NOTICE in text


def test_a_local_raster_credits_nothing():
    local = F.terrain_result()
    local.result = SimpleNamespace(elevation_source="Local DEM: my.tif")
    assert attribution.credit_parts(local) == []
    assert attribution.text([]) == "" and attribution.html([]) == ""


def test_both_data_kinds_are_credited_together():
    assert "Weather and elevation data by Open-Meteo.com" in attribution.text(["weather", "elevation"])


def test_the_workbook_summary_carries_the_credit():
    book = read_workbook(export.result_to_xlsx(F.terrain_result()))
    cells = [str(c) for sheet in book.values() for row in sheet for c in row]
    assert any(LICENCE_NOTICE in c for c in cells)


def test_panel_html_links_the_source_licence_guide_and_dataset_citation():
    h = attribution.html(["elevation"])
    for url in ("https://open-meteo.com/", "https://open-meteo.com/en/license", "https://map.velorona.ai/guide#attribution", "https://doi.org/10.5270/ESA-c5d3d65"):
        assert f"href='{url}'" in h
    assert LICENCE_NOTICE in h and "Copernicus" not in attribution.html(["weather"])
