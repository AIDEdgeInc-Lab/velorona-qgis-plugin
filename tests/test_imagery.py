"""Optional USA imagery definitions: pure data, no QGIS needed."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import imagery  # noqa: E402


def test_sources_are_usgs_https_and_declare_us_only():
    assert len(imagery.IMAGERY_SOURCES) == 2
    keys = [k for k, *_ in imagery.IMAGERY_SOURCES]
    assert len(set(keys)) == 2
    for key, name, service, abstract in imagery.IMAGERY_SOURCES:
        assert "US only" in name and "USGS" in name
        assert "United States only" in abstract and "public domain" in abstract
        uri = imagery.tile_uri(service)
        assert uri.startswith("type=xyz&url=https://basemap.nationalmap.gov/")
        assert "%7Bz%7D/%7By%7D/%7Bx%7D" in uri          # ArcGIS cache order is z/y/x
        assert f"zmax={imagery.IMAGERY_MAX_ZOOM}" in uri


def test_max_zoom_matches_what_the_service_serves():
    assert imagery.IMAGERY_MAX_ZOOM == 16               # verified live: HTTP 404 at 17
