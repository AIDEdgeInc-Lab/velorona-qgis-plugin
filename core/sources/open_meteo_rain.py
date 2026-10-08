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
from ..provider_retry import call_with_backoff


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
        import requests

        def fetch():
            r = get(OPEN_METEO_URL, params={
                "latitude": site.latitude, "longitude": site.longitude,
                "current": "precipitation,rain,showers,snowfall,weather_code,temperature_2m,wind_speed_10m",
                "timezone": "auto",
            }, timeout=self.timeout)
            r.raise_for_status()
            return r
        # Bounded backoff for a rate limit / server error / network failure only (core/provider_retry.py); the caller turns a final failure into
        # NO DATA (transient), never into a status.
        resp = call_with_backoff(fetch, retryable=(requests.exceptions.RequestException,))
        current = resp.json()["current"]
        p = precip.classify(current)
        self.precipitation[site.id] = p
        return WeatherObservation(
            latitude=site.latitude, longitude=site.longitude, timestamp=current["time"],
            rain_rate_mm_h=p.rate_mm_h, source=SOURCE,
            temperature_c=_optional_float(current.get("temperature_2m")),
            wind_speed_kmh=_optional_float(current.get("wind_speed_10m")),
            fetched_at=time.time(), site_id=site.id,
        )
