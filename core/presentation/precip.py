"""Splitting Open-Meteo precipitation into liquid rain and everything else (owner-approved P7; conversion FROZEN as P8).

aei_mw_exposure's OpenMeteoProvider uses ``current.rain or current.precipitation``. Open-Meteo's ``precipitation`` is the total of rain,
showers and the water equivalent of snowfall, so when ``rain`` is exactly 0 that fallback turns a snow-only hour into "rain" and feeds it to
the rain-attenuation model; it also ignores ``showers`` (liquid rain). The type fields are reported by the API, so the split is not a guess:

    liquid rain  = rain + showers                      -> the ONLY classes that feed the rain-fade model (RAIN, SHOWERS, and the liquid part of MIXED/FREEZING)
    snow (w.e.)  = snowfall_cm / 7                     -> never rain; a separate signal (SOURCED: Open-Meteo docs, open-meteo.com/en/docs)
    rate (mm/h)  = liquid mm x 3600 / interval seconds -> Open-Meteo `current` values are millimetres accumulated over `interval` s

Classes: NONE, RAIN, SHOWERS, SNOW, MIXED, FREEZING (WMO weather_code 56/57/66/67). UNKNOWN (neither ``rain`` nor ``showers`` reported) is not
rain and not a guess: it raises NoDataError (the weather domain is NO DATA). R1/R2 are NOT approved, so no class changes a status here; the
class and flags are exposed as evidence only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

from ..validation import NoDataError, interval_reason, is_finite_number

BASIS_SPLIT = "rain + showers (liquid)"
BASIS_RAIN_ONLY = "rain (showers not reported)"
BASIS_SHOWERS_ONLY = "showers (rain not reported)"

_EPS = 0.005                      # CARRIED OVER (mm; Open-Meteo reports to 0.01 mm)
SNOW_WE_DIVISOR = 7.0             # SOURCED: Open-Meteo documentation, "divide by 7"
FREEZING_CODES = (56, 57, 66, 67)  # SOURCED: WMO table in the Open-Meteo documentation


@dataclass(frozen=True)
class Precipitation:
    total_mm: Optional[float]       # mm over interval_s
    rain_mm: Optional[float]
    showers_mm: Optional[float]
    snowfall_cm: Optional[float]
    rate_mm_h: float                # the value the rain-attenuation model receives (liquid only, converted to mm/h)
    basis: str
    precip_class: str = "NONE"
    flags: Tuple[str, ...] = ()
    interval_s: float = 900.0
    liquid_mm: float = 0.0
    weather_code: Optional[int] = None

    @property
    def snow_mm(self) -> float:
        """Snow water equivalent in mm (snowfall cm / 7)."""
        return (self.snowfall_cm or 0.0) / SNOW_WE_DIVISOR

    @property
    def frozen_mm(self) -> float:
        return self.snow_mm

    @property
    def has_frozen(self) -> bool:
        return "frozen_present" in self.flags

    @property
    def has_freezing(self) -> bool:
        return "freezing" in self.flags


def classify(current: dict) -> Precipitation:
    """From an Open-Meteo ``current`` block. Raises NoDataError for a missing/invalid interval (R3), an invalid value (W4) or an unreported
    rain/showers split (W1)."""
    reason = interval_reason(current.get("interval"))
    if reason:
        raise NoDataError("weather", [reason])

    def num(key):
        v = current.get(key)
        if v is None:
            return None
        if not is_finite_number(v) or v < 0:
            raise NoDataError("weather", [f"invalid {key} value (W4)"])
        return float(v)

    total, rain, showers, snow = num("precipitation"), num("rain"), num("showers"), num("snowfall")
    if rain is None and showers is None:
        raise NoDataError("weather", ["precipitation type not reported: rain and showers absent (W1)"])
    liquid = (rain or 0.0) + (showers or 0.0)
    frozen = (snow or 0.0) / SNOW_WE_DIVISOR > _EPS
    code = current.get("weather_code")
    if code in FREEZING_CODES: cls = "FREEZING"
    elif liquid > _EPS and frozen: cls = "MIXED"
    elif frozen: cls = "SNOW"
    elif (rain or 0.0) > _EPS: cls = "RAIN"
    elif (showers or 0.0) > _EPS: cls = "SHOWERS"
    else: cls = "NONE"
    flags = []
    if frozen: flags.append("frozen_present")
    if cls == "FREEZING":
        flags.append("freezing")
        if liquid <= _EPS: flags.append("freezing_unquantified")
    if rain is not None and showers is not None: basis = BASIS_SPLIT
    elif rain is not None: basis = BASIS_RAIN_ONLY
    else: basis = BASIS_SHOWERS_ONLY
    interval = float(current["interval"])
    return Precipitation(total, rain, showers, snow, liquid * 3600.0 / interval, basis, cls, tuple(flags), interval, liquid, code)


def liquid_hourly(rain: Optional[float], showers: Optional[float]) -> Optional[float]:
    """Hourly liquid rain; None when neither type is reported."""
    if rain is None and showers is None:
        return None
    return (rain or 0.0) + (showers or 0.0)
