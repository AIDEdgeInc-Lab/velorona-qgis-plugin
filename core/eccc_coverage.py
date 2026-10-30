"""Where the ECCC radar is used: Canada only (Velorona Map says the same: "ECCC covers Canada only; elsewhere the evidence is reported as insufficient").

The radar mosaic (RADAR_1KM_RRAI) is a North American composite. Over the US, Mexico, Cuba or Hawaii the service answers a point query with a
value of 0.0 mm/h, which is indistinguishable from "no rain in Canadian coverage". The plugin therefore does not ask it, and never shows or
stores such a value, for a site outside Canada: the result says "not covered" instead (``NOT_COVERED``).

``covers`` uses a coarse ring of Canada's southern border (the other sides are far past the land; offshore and arctic points get no answer
from the service anyway). It is accurate to a few tens of km: a site on the border itself, or across a border river, can fall either side.
Pure stdlib."""

from __future__ import annotations

from typing import Tuple

NOT_COVERED = "not covered: the ECCC radar is used for sites in Canada only"

# (latitude, longitude) ring, west -> east along the southern border, then north, then back down the Yukon/Alaska border and the Pacific coast.
_RING: Tuple[Tuple[float, float], ...] = (
    (48.3, -124.8), (48.4, -123.3), (48.75, -123.1), (49.0, -123.1), (49.0, -95.15), (49.38, -95.15), (48.95, -94.7), (48.6, -93.4),
    (48.35, -92.2), (48.2, -90.9), (48.0, -89.55), (48.2, -88.3), (47.0, -85.5), (46.5, -84.6), (46.5, -84.3), (46.0, -83.9),
    (45.3, -82.5), (44.0, -82.1), (43.0, -82.42), (42.45, -82.7), (42.3, -83.1), (41.9, -83.0), (42.2, -81.5), (42.45, -80.0),
    (42.9, -78.9), (43.26, -79.07), (43.6, -77.6), (44.0, -76.5), (44.45, -75.8), (45.0, -74.75), (45.0, -71.5), (45.35, -71.0),
    (45.65, -70.4), (46.4, -70.0), (47.1, -69.05), (47.45, -69.0), (47.3, -68.35), (47.05, -67.8), (45.85, -67.8), (45.2, -67.4),
    (44.8, -66.95), (44.5, -66.8), (43.0, -66.0), (43.0, -52.0), (84.0, -52.0), (84.0, -141.0), (60.3, -141.0), (60.0, -139.05),
    (59.5, -137.5), (59.2, -136.0), (58.6, -134.2), (57.6, -133.0), (56.6, -131.8), (55.9, -130.0), (55.0, -129.95), (54.7, -130.6),
    (54.7, -133.6), (50.5, -130.5), (48.3, -125.5),
)


def covers(latitude: float, longitude: float) -> bool:
    """True when the point lies inside the ring (ray casting)."""
    inside = False
    n = len(_RING)
    for i in range(n):
        (y1, x1), (y2, x2) = _RING[i], _RING[(i + 1) % n]
        if (y1 > latitude) != (y2 > latitude) and longitude < x1 + (latitude - y1) * (x2 - x1) / (y2 - y1):
            inside = not inside
    return inside
