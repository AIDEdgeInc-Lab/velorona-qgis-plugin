"""Open-Meteo attribution (CC BY 4.0): stated with links in every export that used its data, never where it was not used."""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import presentation_fixtures as F  # noqa: E402
from core import attribution, export, study_export  # noqa: E402

CREDIT = "by Open-Meteo.com (https://open-meteo.com/), licensed CC BY 4.0 (https://open-meteo.com/en/license). Guide: https://map.velorona.ai/guide#data-types"


def test_weather_exports_credit_open_meteo():
    text = export.export_csv(F.weather_result(), include_names=True)
    assert f"# Data credit: Weather data {CREDIT}" in text


def test_online_terrain_credits_elevation_and_a_local_raster_does_not():
    t = F.terrain_result()
    assert f"# Data credit: Elevation data {CREDIT}" in export.export_csv(t, include_names=True)
    local = F.terrain_result()
    local.result = SimpleNamespace(elevation_source="Local DEM: my.tif")
    assert attribution.open_meteo_parts(local) == []


def test_study_credits_both_and_a_record_without_weather_credits_nothing():
    text = study_export.study_to_csv([F.terrain_result(), F.weather_result()])
    assert f"# Data credit: Weather and elevation data {CREDIT}" in text
    assert attribution.open_meteo_parts(SimpleNamespace(kind="link-investigation", exposure=None)) == []


def test_panel_html_links_the_source_licence_and_guide():
    h = attribution.html(["weather"])
    for url in ("https://open-meteo.com/", "https://open-meteo.com/en/license", "https://map.velorona.ai/guide#data-types"):
        assert f"href='{url}'" in h
    assert attribution.html([]) == ""


def test_online_elevation_also_carries_the_copernicus_notice_and_weather_alone_does_not():
    assert attribution.COPERNICUS_NOTICE in attribution.text(["elevation"])
    assert attribution.COPERNICUS_NOTICE in export.export_csv(F.terrain_result(), include_names=True)
    assert attribution.COPERNICUS_NOTICE in study_export.study_to_csv([F.terrain_result(), F.weather_result()])
    assert "Copernicus" not in attribution.text(["weather"]) and "Copernicus" not in export.export_csv(F.weather_result(), include_names=True)
    h = attribution.html(["elevation"])
    assert "Copernicus DEM</a> GLO-90" in h and f"href='{attribution.COPERNICUS_URL}'" in h
    local = F.terrain_result()
    local.result = SimpleNamespace(elevation_source="Local DEM: my.tif")
    assert "Copernicus" not in attribution.text(attribution.open_meteo_parts(local)) and "Copernicus" not in attribution.html(attribution.open_meteo_parts(local))
