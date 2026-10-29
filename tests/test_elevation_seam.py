"""The plugin's use of the library's elevation-provider seam (aei-link-clearance >= 0.3, unreleased): a local DEM, caching, failure wording.
Needs that library; against the released 0.2.x the whole module is skipped (allowlisted in tools/check_skips.py) and tools/gate.sh runs it in
the seam lane."""
import math
import sys
import types

import pytest
import requests

if "qgis" not in sys.modules:
    try:
        import qgis.core  # noqa: F401
    except ImportError:
        class _P:
            def __init__(self, *a, **k): pass
        _q, _qc = types.ModuleType("qgis"), types.ModuleType("qgis.core")
        for _n in ("QgsCoordinateReferenceSystem", "QgsCoordinateTransform", "QgsProject"):
            setattr(_qc, _n, _P)
        _q.core = _qc
        sys.modules["qgis"], sys.modules["qgis.core"] = _q, _qc

from core import elevation_source
from core.engines import terrestrial as TR
from core.validation import NoDataError

if not elevation_source.providers_supported():
    pytest.skip("needs aei-link-clearance >= 0.3 (the elevation-provider seam), not yet released", allow_module_level=True)

from aei_link_clearance import DEMCrsMismatchError, LocalDEMProvider  # noqa: E402

PARAMS = {"site_a_height_m": 30.0, "site_b_height_m": 30.0, "frequency_ghz": 7.0}
A, B = (43.70, -79.40), (43.80, -79.20)


def ground(lat, lon):
    return 100.0 + 50.0 * math.sin((lat - 43.7) * 40)


def test_local_dem_result_names_the_raster_not_open_meteo(monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **k: pytest.fail("a local DEM must not touch the network"))
    r = TR.analyze_endpoints(*A, *B, PARAMS, "t", elevation_provider=LocalDEMProvider(ground, "toronto.tif"))
    assert r.elevation_source == "Local DEM: toronto.tif"
    assert not elevation_source.is_online(r) and elevation_source.source_of(r) == "Local DEM: toronto.tif"


def test_raster_that_does_not_cover_the_path_is_no_data_not_transient_and_says_nothing_was_substituted():
    dem = LocalDEMProvider(lambda la, lo: ground(la, lo) if lo < -79.3 else None, "small.tif")
    with pytest.raises(NoDataError) as e:
        TR.analyze_endpoints(*A, *B, PARAMS, "t", elevation_provider=dem)
    assert e.value.transient is False
    assert "does not cover this path" in e.value.reasons[0] and "nothing was substituted" in e.value.reasons[0]


def test_nodata_cells_are_never_zero():
    with pytest.raises(NoDataError) as e:
        TR.analyze_endpoints(*A, *B, PARAMS, "t", elevation_provider=LocalDEMProvider(lambda la, lo: float("nan"), "holes.tif"))
    assert "T1" in e.value.reasons[0]


def test_crs_mismatch_is_reported_as_no_data_with_the_cause():
    # The provider refuses at construction; the plugin's DEM reader turns that into the same NO DATA wording.
    with pytest.raises(DEMCrsMismatchError):
        LocalDEMProvider(ground, "utm.tif", dem_crs="EPSG:32617")
    reason, transient = elevation_source.failure_reason(DEMCrsMismatchError("The DEM is in EPSG:32617"))
    assert "cannot be used" in reason and transient is False


class Resp:
    def __init__(self, status=200, body=None, text="", headers=None):
        self.status_code, self.body, self.text, self.headers = status, body, text, headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(f"{self.status_code} error", response=self)

    def json(self):
        return self.body


def test_online_default_caches_the_second_run(monkeypatch):
    calls = []

    def fake(url, params=None, timeout=None):
        calls.append(1)
        return Resp(200, {"elevation": [120.0] * len(params["latitude"].split(","))})

    monkeypatch.setattr(requests, "get", fake)
    first = TR.analyze_endpoints(*A, *B, PARAMS, "t")
    second = TR.analyze_endpoints(*A, *B, {**PARAMS, "site_a_height_m": 45.0}, "t")     # what-if: other height, same path
    assert len(calls) == 1
    assert first.elevation_source == second.elevation_source
    assert elevation_source.is_online(first) and elevation_source.is_online(second)


def test_429_storm_gives_transient_no_data_then_fails_fast_without_the_service(monkeypatch, no_real_backoff_sleep):
    calls = []
    monkeypatch.setattr(requests, "get", lambda *a, **k: calls.append(1) or Resp(429, text="slow down"))
    with pytest.raises(NoDataError) as first:
        TR.analyze_endpoints(*A, *B, PARAMS, "t")
    assert first.value.transient and "rate-limiting" in first.value.reasons[0] and len(calls) == 3 and no_real_backoff_sleep == [1.0, 3.0]
    for _ in range(4):                                       # a batch keeps asking
        with pytest.raises(NoDataError) as again:
            TR.analyze_endpoints(*A, *B, PARAMS, "t")
        assert again.value.transient
    assert len(calls) == 3


def test_online_provider_down_is_service_wording_never_link_wording(monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **k: (_ for _ in ()).throw(requests.exceptions.ConnectionError("down")))
    with pytest.raises(NoDataError) as e:
        TR.analyze_endpoints(*A, *B, PARAMS, "t")
    assert e.value.transient and "could not be reached" in e.value.reasons[0]


def test_old_library_with_a_local_dem_is_refused_clearly(monkeypatch):
    monkeypatch.setattr(elevation_source, "providers_supported", lambda: False)
    with pytest.raises(NoDataError) as e:
        TR.analyze_endpoints(*A, *B, PARAMS, "t", elevation_provider=object())
    assert "0.3 or newer" in e.value.reasons[0]


def _wrapped(result):
    from types import SimpleNamespace
    return SimpleNamespace(kind="terrestrial", site_a_name="A", site_b_name="B", site_a_source="s", site_b_source="s", site_a_height_m=30.0,
                           site_b_height_m=30.0, site_a_height_from_feature=False, site_b_height_from_feature=False, result=result,
                           explanation="", frequency_origin=None, height_origins=None, record=None)


def test_every_surface_names_the_chosen_raster_and_not_the_90m_online_model():
    from core import export
    from core.presentation import terrain as pterrain
    res = _wrapped(TR.analyze_endpoints(*A, *B, PARAMS, "t", elevation_provider=LocalDEMProvider(ground, "toronto.tif")))
    brief = pterrain.terrain_brief(res)
    text = " ".join(f"{f.label} {f.value}" for f in brief.evidence) + " ".join(brief.caveats)
    assert "Local DEM: toronto.tif" in text and "surface or bare-earth" in text and "90 m surface model" not in text
    assert brief.data["elevation_source"] == "Local DEM: toronto.tif"
    assert "toronto.tif" in export._elevation_source_text(res) and "Copernicus" not in export._elevation_source_text(res)
