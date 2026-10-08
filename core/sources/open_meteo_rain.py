"""Open-Meteo weather provider that does not present snow as rain.

Subclasses aei_mw_exposure's OpenMeteoProvider and changes only how the rain rate
is derived (see core/presentation/precip.py). Everything else -- the observation
type, temperature, wind, the calculation that consumes it -- is the library's.
The breakdown is kept per site so the views can say what was excluded.
"""

from __future__ import annotations

import time
from typing import Dict

from aei_mw_exposure.providers.open_meteo import OPEN_METEO_URL, SOURCE, OpenMeteoProvider, _optional_float
from aei_mw_exposure.weather import WeatherObservation

from ..presentation import precip
from ..validation import NoDataError, interval_reason


class TypedPrecipitationProvider(OpenMeteoProvider):
    def __init__(self, timeout: float = 8.0, get=None) -> None:
        super().__init__(timeout)
        self._get = get
        self.precipitation: Dict[str, precip.Precipitation] = {}

    def get_current(self, site) -> WeatherObservation:
        get = self._get
        if get is None:
            import requests
            get = requests.get
        resp = get(OPEN_METEO_URL, params={
            "latitude": site.latitude, "longitude": site.longitude,
            "current": "precipitation,rain,showers,snowfall,temperature_2m,wind_speed_10m",
            "timezone": "auto",
        }, timeout=self.timeout)
        resp.raise_for_status()
        current = resp.json()["current"]
        reason = interval_reason(current.get("interval"))
        if reason:
            raise NoDataError("weather", [reason])
        p = precip.classify(current)
        self.precipitation[site.id] = p
        return WeatherObservation(
            latitude=site.latitude, longitude=site.longitude, timestamp=current["time"],
            rain_rate_mm_h=p.rate_mm_h, source=SOURCE,
            temperature_c=_optional_float(current.get("temperature_2m")),
            wind_speed_kmh=_optional_float(current.get("wind_speed_10m")),
            fetched_at=time.time(), site_id=site.id,
        )
