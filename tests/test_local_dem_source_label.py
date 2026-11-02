"""The 'source' text of a local-DEM result shows a raster's file name and never a URL query, credentials or URI options (they can carry tokens/passwords).
core/local_dem.py imports qgis.core; this test loads it under a private name with a stand-in qgis.core, so it needs no QGIS and touches no other module."""
import importlib.util
import os
import sys
import types

import pytest

PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core", "local_dem.py")


@pytest.fixture(scope="module")
def basename():
    names = ("QgsCoordinateReferenceSystem", "QgsCoordinateTransform", "QgsPointXY", "QgsProject", "QgsRasterLayer")
    fake = types.ModuleType("qgis.core")
    for n in names:
        setattr(fake, n, type(n, (), {"__init__": lambda self, *a, **k: None}))
    saved = {k: sys.modules.get(k) for k in ("qgis", "qgis.core")}
    sys.modules["qgis"], sys.modules["qgis.core"] = types.ModuleType("qgis"), fake
    try:
        spec = importlib.util.spec_from_file_location("_local_dem_under_test", PATH)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v
    return mod._basename


@pytest.mark.parametrize("source,expected", [
    ("/Users/me/Documents/dem/toronto.tif", "toronto.tif"),
    ("/data/my dem 2026.tif", "my dem 2026.tif"),                       # spaces in a real file name are kept
    ("/data/dem.gpkg|layername=dem", "dem.gpkg"),
    ("C:\\Users\\me\\dem.tif", "dem.tif"),
    ("/vsicurl/https://host.example/dems/dem.tif", "dem.tif"),
    ("/vsicurl/https://user:PASSWORD@host.example/dem.tif", "dem.tif"),  # credentials sit before the path, never in the file name
])
def test_a_plain_file_name_is_kept(basename, source, expected):
    assert basename(source) == expected


@pytest.mark.parametrize("source,secret", [
    ("/vsicurl/https://bucket.example/dems/dem.tif?sig=SECRETVALUE123&expires=99", "SECRETVALUE123"),
    ("/vsicurl/https://host.example/dem.tif#access_token=TOKEN456", "TOKEN456"),
    ("dpiMode=7 url=https://host.example/wcs username=bob password=PASSWORD123 identifier=dem", "PASSWORD123"),
    ("url=https://host.example/wcs&password=PASSWORD789", "PASSWORD789"),
])
def test_queries_fragments_and_uri_options_never_reach_the_label(basename, source, secret):
    assert secret not in basename(source)


@pytest.mark.parametrize("source", ["", "/", "?only=query", "key=value", "user@host"])
def test_nothing_safe_to_show_gives_empty_so_the_layer_name_is_used(basename, source):
    assert basename(source) == ""
