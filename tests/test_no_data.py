"""NO DATA rules (owner-approved P5, R3, R4, R5, R9) at the plugin's decision boundary. Explicit validation raises NoDataError; unexpected
exceptions are NOT converted (they must surface). The engine modules import qgis.core at module level; this file installs an empty stand-in
only when real QGIS is absent (nothing in the decision path uses it)."""
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

from core import validation as V
from core.engines import microwave_exposure as MW
from core.engines import terrestrial as TR
from core.validation import NoDataError

GOOD_T = {"site_a_height_m": 30.0, "site_b_height_m": 30.0, "frequency_ghz": 7.0}
GOOD_W = {"frequency_ghz": 18.0, "polarization": "V", "fade_margin_db": 32.0}


# ---- pure validators -------------------------------------------------------
@pytest.mark.parametrize("a,b,needle", [
    ((95.0, -79.0), (44.0, -79.0), "invalid coordinates"),
    ((44.0, -79.0), (44.0, 181.0), "invalid coordinates"),
    ((float("nan"), -79.0), (44.0, -79.0), "invalid coordinates"),
    ((None, -79.0), (44.0, -79.0), "invalid coordinates"),
    ((44.0, -79.0), (44.0, -79.0), "zero-length"),
])
def test_path_reasons(a, b, needle):
    assert any(needle in r for r in V.path_reasons(*a, *b))


def test_valid_path_has_no_reasons():
    assert V.path_reasons(44.0, -79.0, 44.1, -79.0) == []
    assert V.path_reasons(0.0, 0.0, 0.0, 0.0001) == []          # very short but non-zero stays analysable (R9: only exactly zero)


@pytest.mark.parametrize("f,ok", [(0.99, False), (1.0, True), (100.0, True), (100.01, False), (0.94, False), (float("nan"), False), ("18", False)])
def test_weather_frequency_range_is_inclusive_1_to_100(f, ok):
    reasons = V.weather_input_reasons(44.0, -79.0, 44.1, -79.0, dict(GOOD_W, frequency_ghz=f))
    assert (reasons == []) is ok


@pytest.mark.parametrize("f,ok", [(0.09, False), (0.1, True), (100.0, True), (100.5, False)])
def test_terrain_frequency_range(f, ok):
    assert (V.terrain_input_reasons(44, -79, 44.1, -79, 30, 30, f) == []) is ok


@pytest.mark.parametrize("interval,ok", [(900, True), (3600, True), (None, False), (0, False), (-900, False), ("900", False), (float("nan"), False)])
def test_interval_reason(interval, ok):
    assert (V.interval_reason(interval) is None) is ok


# ---- terrain boundary ------------------------------------------------------
class _Resp:
    def __init__(self, body): self.body = body
    def raise_for_status(self): pass
    def json(self): return self.body


def _elev(monkeypatch, values):
    monkeypatch.setattr(requests, "get", lambda *a, **k: _Resp({"elevation": values}))


def _terrain(a=(44.0, -79.4), b=(44.4, -79.4), params=GOOD_T):
    return TR.analyze_endpoints(a[0], a[1], b[0], b[1], params, "t")


def test_terrain_ok(monkeypatch):
    _elev(monkeypatch, [200.0] * 50)
    assert _terrain().los_status in ("clear", "marginal", "obstructed")


def test_invalid_coordinates_are_refused_before_any_network_call(monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **k: pytest.fail("network must not be reached"))
    for b in ((95.0, -79.4), (44.4, 181.0)):
        with pytest.raises(NoDataError) as e:
            _terrain(b=b)
        assert e.value.domain == "terrain" and e.value.status == "NO DATA"


def test_identical_endpoints_never_produce_a_result(monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **k: pytest.fail("network must not be reached"))
    with pytest.raises(NoDataError, match="zero-length"):
        _terrain(b=(44.0, -79.4))


@pytest.mark.parametrize("bad", [None, float("nan"), "12"])
def test_null_or_nonnumeric_elevation_is_refused_never_zero(monkeypatch, bad):
    vals = [200.0] * 50; vals[10] = bad
    _elev(monkeypatch, vals)
    with pytest.raises(NoDataError, match="never treated as 0 m|elevation data unavailable"):
        _terrain()


def test_elevation_http_failure_is_no_data(monkeypatch):
    def boom(*a, **k): raise requests.exceptions.ConnectionError("down")
    monkeypatch.setattr(requests, "get", boom)
    with pytest.raises(NoDataError, match="T1"):
        _terrain()


def test_unexpected_exception_surfaces_unchanged(monkeypatch):
    def boom(*a, **k): raise RuntimeError("bug")
    monkeypatch.setattr(requests, "get", boom)
    with pytest.raises(RuntimeError, match="bug") as e:
        _terrain()
    assert not isinstance(e.value, NoDataError)


# ---- weather boundary ------------------------------------------------------
def _provider(current):
    return MW.TypedPrecipitationProvider(get=lambda url, params=None, timeout=None: types.SimpleNamespace(
        raise_for_status=lambda: None, json=lambda: {"current": current}))


def _no_station(monkeypatch):
    monkeypatch.setattr(MW.eccc, "find_nearest_station", lambda *a, **k: None)
    monkeypatch.setattr(MW.eccc, "get_radar_precipitation", lambda *a, **k: None)


def _weather(monkeypatch, a=(44.0, -79.4), b=(44.1, -79.4), params=GOOD_W, current=None):
    _no_station(monkeypatch)
    current = current if current is not None else {"time": "t", "interval": 900, "rain": 0.0, "showers": 0.0, "snowfall": 0.0, "precipitation": 0.0}
    def no_history(*a_, **k): raise RuntimeError("history is context only")
    return MW.analyze_link_record(a, b, {"authorization_number": "X-1", "source": "t"}, params, provider=_provider(current), history_fetcher=no_history)


def test_weather_ok(monkeypatch):
    assert _weather(monkeypatch).exposure.severity == "low"


@pytest.mark.parametrize("kw,needle", [
    (dict(b=(95.0, -79.4)), "invalid coordinates"),
    (dict(b=(44.0, -79.4)), "zero-length"),
    (dict(params=dict(GOOD_W, frequency_ghz=0.94)), "outside 1-100 GHz"),
    (dict(params=dict(GOOD_W, frequency_ghz=100.5)), "outside 1-100 GHz"),
    (dict(params=dict(GOOD_W, fade_margin_db=0)), "fade margin"),
    (dict(current={"time": "t", "rain": 0.0, "precipitation": 0.0}), "interval"),
    (dict(current={"time": "t", "interval": 0, "rain": 0.0, "precipitation": 0.0}), "interval"),
])
def test_weather_no_data(monkeypatch, kw, needle):
    with pytest.raises(NoDataError) as e:
        _weather(monkeypatch, **kw)
    assert e.value.domain == "weather" and any(needle in r for r in e.value.reasons)


def test_dry_sub_ghz_link_is_no_data_not_clear(monkeypatch):
    """Before the rule QGIS returned CLEAR for a dry 0.94 GHz link because the library only rejects the frequency when it rains."""
    with pytest.raises(NoDataError, match="outside 1-100 GHz"):
        _weather(monkeypatch, params=dict(GOOD_W, frequency_ghz=0.94))


def test_provider_failure_is_no_data(monkeypatch):
    _no_station(monkeypatch)
    prov = MW.TypedPrecipitationProvider(get=lambda *a, **k: (_ for _ in ()).throw(requests.exceptions.ConnectionError("down")))
    with pytest.raises(NoDataError, match="T3"):
        MW.analyze_link_record((44.0, -79.4), (44.1, -79.4), {"authorization_number": "X-1"}, GOOD_W, provider=prov, history_fetcher=lambda *a, **k: None)
