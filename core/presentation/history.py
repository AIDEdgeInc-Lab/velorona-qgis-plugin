"""Hourly weather history for one site, and "what changed" comparisons.

The plugin's engine only ever sees the *current* observation, so there was no
history to compare against. This module fetches the preceding hours from the
same provider (Open-Meteo, model data at the site's coordinates) and compares
hourly values with hourly values -- never a current 15-minute reading with an
hourly one, which would be two different products.

Open-Meteo's hourly `rain` (plus `showers`) for hour H is the amount that fell in the hour
before H, so it reads directly as mm/h.

"No meaningful change" means *equal at the precision the value is displayed
at* (0.1). It is not a physical threshold; it only stops a 0.04 difference
being drawn as an arrow.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

from .model import Change
from .precip import liquid_hourly

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
SOURCE = "Open-Meteo (model-derived hourly values at the site coordinates; not station observations)"
DEFAULT_HOURS = 6

# variable -> (label, unit, attribute on HourlyPoint)
VARIABLES = {
    "rain": ("Hourly rain", "mm/h", "rain_mm_h"),
    "temperature": ("Temperature", "°C", "temperature_c"),
    "wind": ("Wind", "km/h", "wind_kmh"),
}


@dataclass(frozen=True)
class HourlyPoint:
    time: str                       # provider-local ISO time, e.g. 2026-10-06T20:00
    temperature_c: Optional[float]
    rain_mm_h: Optional[float]
    wind_kmh: Optional[float]


@dataclass(frozen=True)
class WeatherHistory:
    site_id: str
    latitude: float
    longitude: float
    source: str
    timezone: str
    fetched_at: float
    points: Tuple[HourlyPoint, ...]   # ascending; the last is the latest hour, <= now

    @property
    def latest(self) -> Optional[HourlyPoint]:
        return self.points[-1] if self.points else None


def parse_history(data: dict, site_id: str, latitude: float, longitude: float, fetched_at: float) -> WeatherHistory:
    """Build a WeatherHistory from an Open-Meteo response. Points after the
    provider's own `current.time` are dropped: they are forecast, not history."""
    hourly = data.get("hourly") or {}
    times = hourly.get("time") or []
    now = (data.get("current") or {}).get("time")

    def column(name):
        values = hourly.get(name)
        return values if values is not None and len(values) == len(times) else [None] * len(times)

    temps, winds = column("temperature_2m"), column("wind_speed_10m")
    # liquid rain = rain + showers; snowfall is never counted as rain (core/presentation/precip.py)
    rains = [liquid_hourly(r, s) for r, s in zip(column("rain"), column("showers"))]
    points = []
    for t, temp, rain, wind in zip(times, temps, rains, winds):
        if now is not None and t > now:
            continue
        points.append(HourlyPoint(t, _f(temp), _f(rain), _f(wind)))
    return WeatherHistory(site_id=site_id, latitude=latitude, longitude=longitude, source=SOURCE,
                          timezone=str(data.get("timezone") or ""), fetched_at=fetched_at, points=tuple(points))


def fetch_weather_history(site_id: str, latitude: float, longitude: float, hours: int = DEFAULT_HOURS,
                          get: Optional[Callable] = None, timeout: float = 8.0) -> WeatherHistory:
    """`get` is injectable (requests.get signature) so tests never hit the network."""
    import time as _time
    if get is None:
        import requests
        get = requests.get
    params = {
        "latitude": latitude, "longitude": longitude,
        "current": "temperature_2m",
        "hourly": "temperature_2m,rain,showers,wind_speed_10m",
        "past_hours": hours, "forecast_hours": 1, "timezone": "auto",
    }
    resp = get(OPEN_METEO_URL, params=params, timeout=timeout)
    resp.raise_for_status()
    return parse_history(resp.json(), site_id, latitude, longitude, _time.time())


def _f(value) -> Optional[float]:
    return None if value is None else float(value)


def _decimals_equal(a: float, b: float, decimals: int = 1) -> bool:
    return round(a, decimals) == round(b, decimals)


def compare(history: WeatherHistory, variable: str, hours_back: int) -> Optional[Change]:
    """Latest hour vs `hours_back` hours earlier, or None when either value is
    missing (never filled in)."""
    label, unit, attr = VARIABLES[variable]
    pts = history.points
    if len(pts) <= hours_back:
        return None
    cur, prev = pts[-1], pts[-1 - hours_back]
    a, b = getattr(cur, attr), getattr(prev, attr)
    if a is None or b is None:
        return None
    delta = a - b
    if _decimals_equal(a, b):
        direction = "flat"
    else:
        direction = "up" if delta > 0 else "down"
    baseline = "vs 1 hour ago" if hours_back == 1 else f"vs {hours_back} hours ago"
    return Change(label=label, unit=unit, current=a, previous=b, delta=delta, direction=direction,
                  baseline=baseline, current_time=cur.time, previous_time=prev.time, variable=variable)


def changes(history: WeatherHistory, hours_back: int) -> List[Change]:
    out = []
    for variable in ("rain", "temperature", "wind"):
        c = compare(history, variable, hours_back)
        if c is not None:
            out.append(c)
    return out


def available_hours(history: WeatherHistory) -> int:
    """How far back a comparison can reach with the points actually fetched."""
    return max(len(history.points) - 1, 0)
