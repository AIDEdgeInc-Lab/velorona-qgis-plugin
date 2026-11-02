"""Where ECCC radar may be shown as an observed value: inside Canada only, as in Velorona Map (web/eccc_coverage.js, message I-WEATHER-RADAR-NOT-COVERED).

ECCC's radar mosaic (RADAR_1KM_RRAI) covers most of North America because it includes NOAA's US radars, and it answers 0 mm/h "Undetected" both where
there is no echo and where no radar can see. So a value outside Canada is not an observation by the network the plugin names (Phoenix showed an
"observed" 0.0). Outside the outline the radar is not asked, no value is shown or stored, and the result says "not covered" (``NOT_COVERED``).

The outline is the Map's own (``eccc_coverage.json``, copied by tools/sync_eccc_coverage.py): Natural Earth 1:50m Canada, cut back about 1 km from the US
border, so a point right at the border is "not covered" rather than the other way round (accuracy about 2 km). ``covers`` is the Map's ray-casting
function unchanged, so the two products give the same answer for the same place (tests/test_eccc_coverage.py). Pure stdlib."""

from __future__ import annotations

import json
import math
import os
from functools import lru_cache
from typing import List

from . import messages

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "eccc_coverage.json")
MESSAGE_ID = "I-WEATHER-RADAR-NOT-COVERED"
# The Map's evidence-row wording for this situation (mwexposureRepresentativenessRows), word for word.
NOT_COVERED = "Not covered: ECCC radar is used only inside Canada, so no radar value is shown or stored for this location."


@lru_cache(maxsize=1)
def _rings() -> List[list]:
    with open(PATH, encoding="utf-8") as fh:
        return json.load(fh)["rings"]


def _number(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def covers(latitude, longitude) -> bool:
    """True when (latitude, longitude) is inside the outline. Never raises; anything that is not a pair of finite numbers is not covered."""
    if not (_number(latitude) and _number(longitude)):
        return False
    for ring in _rings():
        inside = False
        j = len(ring) - 1
        for i in range(len(ring)):
            xi, yi = ring[i]
            xj, yj = ring[j]
            if (yi > latitude) != (yj > latitude) and longitude < ((xj - xi) * (latitude - yi)) / (yj - yi) + xi:
                inside = not inside
            j = i
        if inside:
            return True
    return False


def short_text() -> str:
    return messages.short_text(MESSAGE_ID)
