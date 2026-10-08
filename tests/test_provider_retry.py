"""Bounded backoff and honest failure classification for the live data services (core/provider_retry.py). No network; the sleep is recorded, not slept."""
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

from core import provider_retry as PR  # noqa: E402
from core.engines import terrestrial as TR  # noqa: E402
from core.sources.open_meteo_rain import TypedPrecipitationProvider  # noqa: E402
from core.validation import NoDataError  # noqa: E402

PARAMS = {"site_a_height_m": 30.0, "site_b_height_m": 30.0, "frequency_ghz": 7.0}
A, B = (43.70, -79.40), (43.80, -79.20)
DAILY = '{"error":true,"reason":"Daily API request limit exceeded. Please try again tomorrow."}'


class Resp:
    def __init__(self, status=200, body=None, text="", headers=None):
        self.status_code, self.body, self.text, self.headers = status, body, text, headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(f"{self.status_code} Client Error: fake", response=self)

    def json(self):
        return self.body


def serve(monkeypatch, *responses):
    """requests.get returns the given responses in order, repeating the last one; returns the call log."""
    calls = []

    def get(*a, **k):
        calls.append(1)
        r = responses[min(len(calls) - 1, len(responses) - 1)]
        if isinstance(r, Exception):
            raise r
        return r
    monkeypatch.setattr(requests, "get", get)
    return calls


OK = Resp(200, {"elevation": [100.0] * 50})


# --- classification ----------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("resp,kind,transient,daily", [
    (Resp(429, text="slow down"), "rate limit", True, False),
    (Resp(429, text=DAILY), "daily limit", True, True),
    (Resp(503), "server error", True, False),
    (Resp(502), "server error", True, False),
    (Resp(404), "client error", False, False),
    (Resp(400), "client error", False, False),
])
def test_http_classification(resp, kind, transient, daily):
    f = PR.classify(requests.exceptions.HTTPError("x", response=resp))
    assert (f.kind, f.transient, f.daily) == (kind, transient, daily)


def test_network_errors_are_transient_and_unknown_errors_are_not():
    assert PR.classify(requests.exceptions.ConnectionError("down")).transient
    assert PR.classify(requests.exceptions.Timeout("slow")).kind == "network"
    assert not PR.classify(ValueError("bad value")).transient


def test_status_is_read_from_the_message_when_there_is_no_response():
    assert PR.classify(requests.exceptions.HTTPError("429 Client Error: Too Many Requests for url: x")).kind == "rate limit"


def test_only_the_listed_exception_types_are_inspected():
    calls = []

    def boom():
        calls.append(1)
        raise KeyError("a real bug")
    with pytest.raises(KeyError):
        PR.call_with_backoff(boom, retryable=(requests.exceptions.RequestException,))
    assert calls == [1]


# --- backoff -----------------------------------------------------------------------------------------------------------------------
def test_recovers_after_a_transient_failure(monkeypatch, no_real_backoff_sleep):
    calls = serve(monkeypatch, Resp(429, text="slow"), Resp(503), OK)
    r = TR.analyze_endpoints(A[0], A[1], B[0], B[1], PARAMS, "t")
    assert r.distance_km > 0 and len(calls) == 3 and no_real_backoff_sleep == [1.0, 3.0]


def test_persistent_rate_limit_is_no_data_marked_transient_with_the_real_cause(monkeypatch, no_real_backoff_sleep):
    calls = serve(monkeypatch, Resp(429, text="slow down"))
    with pytest.raises(NoDataError) as exc:
        TR.analyze_endpoints(A[0], A[1], B[0], B[1], PARAMS, "t")
    assert exc.value.transient is True and exc.value.domain == "terrain"
    assert "rate-limiting" in exc.value.reasons[0] and "(T1/R5)" in exc.value.reasons[0]
    assert len(calls) == 3 and no_real_backoff_sleep == [1.0, 3.0]          # bounded: 1 try + 2 retries


def test_daily_limit_is_not_retried_at_all(monkeypatch, no_real_backoff_sleep):
    calls = serve(monkeypatch, Resp(429, text=DAILY))
    with pytest.raises(NoDataError) as exc:
        TR.analyze_endpoints(A[0], A[1], B[0], B[1], PARAMS, "t")
    assert len(calls) == 1 and no_real_backoff_sleep == []
    assert "daily request limit" in exc.value.reasons[0] and "00:00 UTC" in exc.value.reasons[0] and exc.value.transient


def test_client_error_is_not_retried_and_not_transient(monkeypatch, no_real_backoff_sleep):
    calls = serve(monkeypatch, Resp(404))
    with pytest.raises(NoDataError) as exc:
        TR.analyze_endpoints(A[0], A[1], B[0], B[1], PARAMS, "t")
    assert len(calls) == 1 and no_real_backoff_sleep == [] and exc.value.transient is False


def test_wrong_value_count_is_deterministic_and_not_retried(monkeypatch, no_real_backoff_sleep):
    calls = serve(monkeypatch, Resp(200, {"elevation": [100.0] * 7}))
    with pytest.raises(NoDataError) as exc:
        TR.analyze_endpoints(A[0], A[1], B[0], B[1], PARAMS, "t")
    assert len(calls) == 1 and no_real_backoff_sleep == [] and exc.value.transient is False


def test_retry_after_is_honoured_and_capped(monkeypatch, no_real_backoff_sleep):
    serve(monkeypatch, Resp(429, text="x", headers={"Retry-After": "5"}), OK)
    TR.analyze_endpoints(A[0], A[1], B[0], B[1], PARAMS, "t")
    assert no_real_backoff_sleep == [5.0]
    no_real_backoff_sleep.clear()
    calls = serve(monkeypatch, Resp(429, text="x", headers={"Retry-After": "999"}))
    with pytest.raises(NoDataError):
        TR.analyze_endpoints(A[0], A[1], B[0], B[1], PARAMS, "t")
    assert len(calls) == 1 and no_real_backoff_sleep == []             # waiting 999 s is refused: reported, not waited


def test_a_failed_fetch_never_becomes_a_result(monkeypatch):
    serve(monkeypatch, Resp(503))
    with pytest.raises(NoDataError):
        TR.analyze_endpoints(A[0], A[1], B[0], B[1], PARAMS, "t")       # an exception, not a LinkClearanceResult with any status


def test_weather_provider_retries_then_succeeds(no_real_backoff_sleep):
    from aei_mw_exposure import MicrowaveSite, Provenance
    site = MicrowaveSite(id="s", name="s", latitude=44.0, longitude=-79.0, provenance=Provenance.USER_PROVIDED, source="t")
    seq = [Resp(429, text="slow"),
           Resp(200, {"current": {"time": "2026-10-08T12:00", "interval": 900, "precipitation": 0.0, "rain": 0.0, "showers": 0.0, "snowfall": 0.0,
                                  "weather_code": 1, "temperature_2m": 10.0, "wind_speed_10m": 5.0}})]
    it = iter(seq)
    p = TypedPrecipitationProvider(get=lambda *a, **k: next(it))
    obs = p.get_current(site)
    assert obs.rain_rate_mm_h == 0.0 and no_real_backoff_sleep == [1.0]


def test_weather_provider_gives_up_after_the_bound(no_real_backoff_sleep):
    from aei_mw_exposure import MicrowaveSite, Provenance
    site = MicrowaveSite(id="s", name="s", latitude=44.0, longitude=-79.0, provenance=Provenance.USER_PROVIDED, source="t")
    n = []
    p = TypedPrecipitationProvider(get=lambda *a, **k: (n.append(1), Resp(503))[1])
    with pytest.raises(requests.exceptions.HTTPError):
        p.get_current(site)
    assert len(n) == 3 and no_real_backoff_sleep == [1.0, 3.0]
