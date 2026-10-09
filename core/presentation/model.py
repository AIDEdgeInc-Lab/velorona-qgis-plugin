"""Shared vocabulary for the operator-facing output layer.

Pure stdlib, no QGIS. Nothing in this package computes engineering values:
every number it shows is read off a result object that aei_link_clearance /
aei_mw_exposure already produced, or is a plain difference/sum of two such
numbers (a margin is available - required). The only judgment this layer adds is
the *wording* and the mapping of existing library classifications onto five
operator statuses -- both documented in docs/OPERATIONAL_OUTPUT.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

CLEAR = "CLEAR"
WATCH = "WATCH"
AT_RISK = "AT RISK"
CRITICAL = "CRITICAL"
NO_DATA = "NO DATA"

# Worst first, so max-by-rank picks the most serious. NO DATA outranks CLEAR on
# purpose: an unknown must never be reported as "fine" in a combined verdict.
_RANK = {CLEAR: 0, NO_DATA: 1, WATCH: 2, AT_RISK: 3, CRITICAL: 4}

NOT_DETERMINED = "Not determined"


def worst(*statuses: str) -> str:
    return max(statuses, key=_RANK.__getitem__)


@dataclass(frozen=True)
class Fact:
    """One number with its context: what it is, what it is compared against and
    what that means. `value` already carries its unit."""
    label: str
    value: str
    comparison: str = ""
    meaning: str = ""


@dataclass(frozen=True)
class Change:
    """One quantity compared with an earlier time, with the baseline explicit."""
    label: str
    unit: str
    current: float
    previous: float
    delta: float
    direction: str          # "up" | "down" | "flat"
    baseline: str           # "vs 1 hour ago"
    current_time: str
    previous_time: str
    decimals: int = 1
    variable: str = ""      # "rain" | "temperature" | "wind"

    @property
    def arrow(self) -> str:
        return {"up": "↑", "down": "↓", "flat": "→"}[self.direction]

    @property
    def delta_text(self) -> str:
        if self.direction == "flat":
            return f"{self.arrow} No change"
        return f"{self.arrow} {signed(self.delta, self.decimals)} {self.unit}"

    @property
    def text(self) -> str:
        return f"{fmt(self.current, self.decimals)} {self.unit}   {self.delta_text} {self.baseline}"


@dataclass(frozen=True)
class SiteWeather:
    """Where one endpoint's weather came from and why that record was used."""
    site_label: str
    site_point: Optional[tuple]
    source: str
    kind: str               # "Model-derived" -- see weather.py
    timestamp: str
    selection: str
    temperature_c: Optional[float]
    wind_kmh: Optional[float]
    rain_mm_h: Optional[float]
    station_name: Optional[str]
    station_point: Optional[tuple]
    station_distance_km: Optional[float]
    station_time: Optional[str]
    station_rain_mm_h: Optional[float]
    station_reports_rain: Optional[bool]
    radar_rain_mm_h: Optional[float]
    representativeness: str
    representativeness_note: str
    precip_total_mm_h: Optional[float] = None
    precip_basis: str = ""


@dataclass
class Brief:
    """Everything a person needs, in the order they need it. The dock's
    Summary/Details views, the Ask answers and the workbook's SUMMARY sheet are
    all rendered from this one object, so they cannot disagree."""
    kind: str               # "terrain" | "weather"
    title: str
    location: str
    status: str
    reason: str             # one line, why this status
    answer: str             # plain-language answer for a non-specialist
    key_facts: List[Fact] = field(default_factory=list)
    technical: List[Fact] = field(default_factory=list)
    evidence: List[Fact] = field(default_factory=list)
    changes: List[Change] = field(default_factory=list)
    sites: List[SiteWeather] = field(default_factory=list)
    caveats: List[str] = field(default_factory=list)
    inspect: str = ""       # what a technician should look at
    # Raw numbers behind the text, un-rounded, for Ask and for the workbook's
    # exact-match test. Keys are stable identifiers.
    data: Dict[str, Any] = field(default_factory=dict)


def fmt(value: float, decimals: int = 1) -> str:
    """Fixed decimals, without a negative zero ("-0.0")."""
    text = f"{value:.{decimals}f}"
    return text[1:] if text.startswith("-") and float(text) == 0 else text


def signed(value: float, decimals: int = 1) -> str:
    text = fmt(value, decimals)
    return text if text.startswith("-") or float(text) == 0 else f"+{text}"


def exact(value: float) -> str:
    """An operator-entered or record-published value reproduced exactly (7.25
    stays 7.25, 18.0 reads 18) -- same principle as core.export._exact."""
    text = repr(float(value))
    return text[:-2] if text.endswith(".0") else text
