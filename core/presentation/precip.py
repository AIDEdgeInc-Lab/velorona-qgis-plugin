"""Splitting Open-Meteo precipitation into liquid rain and the rest.

aei_mw_exposure's OpenMeteoProvider uses ``current.rain or current.precipitation``.
Open-Meteo's ``precipitation`` is the total of rain, showers and the water
equivalent of snowfall, so when ``rain`` is exactly 0 that fallback turns a
snow-only hour into "rain" and feeds it to the rain-attenuation model. It also
ignores ``showers``, which is liquid rain.

The type fields are reported by the API, so the split is not a guess:

    liquid rain = rain + showers
    frozen part = total precipitation - liquid rain  (snowfall water equivalent)

If the response carries neither ``rain`` nor ``showers`` the type cannot be told
apart; the value is then TOTAL precipitation and is labelled as such, never as rain.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

BASIS_SPLIT = "rain + showers (liquid)"
BASIS_RAIN_ONLY = "rain (showers not reported)"
BASIS_SHOWERS_ONLY = "showers (rain not reported)"
BASIS_TOTAL = "total precipitation (type not reported by the source; may include snow)"
BASIS_NONE = "no precipitation reported"

_EPS = 0.005  # Open-Meteo reports to 0.01 mm


@dataclass(frozen=True)
class Precipitation:
    total_mm: Optional[float]
    rain_mm: Optional[float]
    showers_mm: Optional[float]
    snowfall_cm: Optional[float]
    rate_mm_h: float        # the value the rain-attenuation model receives
    basis: str

    @property
    def frozen_mm(self) -> float:
        """Water equivalent that is not liquid rain. 0 when it cannot be known."""
        if self.basis in (BASIS_TOTAL, BASIS_NONE) or self.total_mm is None:
            return 0.0
        return max(self.total_mm - self.rate_mm_h, 0.0)

    @property
    def has_frozen(self) -> bool:
        return self.frozen_mm > _EPS or (self.snowfall_cm or 0.0) > _EPS

    @property
    def type_unknown(self) -> bool:
        return self.basis == BASIS_TOTAL


def classify(current: dict) -> Precipitation:
    """From an Open-Meteo ``current`` block."""
    def num(key):
        v = current.get(key)
        return None if v is None else float(v)

    total, rain, showers, snow = num("precipitation"), num("rain"), num("showers"), num("snowfall")
    if rain is None and showers is None:
        if total is None:
            return Precipitation(None, None, None, snow, 0.0, BASIS_NONE)
        return Precipitation(total, None, None, snow, total, BASIS_TOTAL)
    if rain is not None and showers is not None:
        basis, rate = BASIS_SPLIT, rain + showers
    elif rain is not None:
        basis, rate = BASIS_RAIN_ONLY, rain
    else:
        basis, rate = BASIS_SHOWERS_ONLY, showers
    return Precipitation(total, rain, showers, snow, rate, basis)


def liquid_hourly(rain: Optional[float], showers: Optional[float]) -> Optional[float]:
    """Hourly liquid rain; None when neither type is reported."""
    if rain is None and showers is None:
        return None
    return (rain or 0.0) + (showers or 0.0)
