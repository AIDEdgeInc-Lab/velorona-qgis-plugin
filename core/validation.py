"""Explicit input validation and dependency checks for the decision path. Pure stdlib, no QGIS.

Nothing here catches exceptions: a check either passes or raises a typed error with a reason. Unexpected exceptions elsewhere must still
surface; they are never converted into NO DATA.
"""

from __future__ import annotations

import math

# Owner decision P11 (CONFIRMED PHYSICS CORRECTION): effective-earth bulge is subtracted from geometric clearance. aei_link_clearance
# announces the convention it implements; the plugin refuses a library that still has the pre-correction sign rather than show
# clearance numbers that are wrong by twice the bulge.
REQUIRED_CLEARANCE_CONVENTION = "bulge-added-to-terrain"


class LibraryOutOfDateError(RuntimeError):
    """The installed aei-link-clearance predates the earth-curvature correction."""


def require_corrected_clearance(terrain_module) -> None:
    found = getattr(terrain_module, "CLEARANCE_CONVENTION", None)
    if found != REQUIRED_CLEARANCE_CONVENTION:
        raise LibraryOutOfDateError(
            "The installed aei-link-clearance uses the pre-correction earth-curvature sign "
            f"(CLEARANCE_CONVENTION={found!r}, required {REQUIRED_CLEARANCE_CONVENTION!r}). Terrain clearance would be overstated by "
            "twice the earth bulge. Upgrade aei-link-clearance to a release that contains the correction (needs "
            "aei-link-clearance>=0.2.0,<0.3): in QGIS, Plugins > Python Console, run:  from pip._internal.cli.main import main; "
            "main(['install', '-U', 'aei-link-clearance>=0.2.0,<0.3'])  then restart QGIS.")


# ---------------------------------------------------------------------------------------------------------------------------------
# NO DATA (owner-approved P5, R3, R4, R5, R9). Each validator returns a list of reasons; an empty list means the inputs are usable. A
# caller that gets reasons raises NoDataError. Nothing here (or at the call sites) wraps unexpected exceptions into NO DATA.
# ---------------------------------------------------------------------------------------------------------------------------------
TERRAIN_FREQ_GHZ = (0.1, 100.0)   # CARRIED OVER: terrestrial.PARAM_SPEC / Map evidence.js TERRESTRIAL_BOUNDS
WEATHER_FREQ_GHZ = (1.0, 100.0)   # CARRIED OVER: ITU-R P.838-3 table range enforced by aei_mw_exposure.physics (MIN_FREQ_GHZ/MAX_FREQ_GHZ)
HEIGHT_M = (0.1, 1000.0)          # CARRIED OVER: terrestrial.PARAM_SPEC
FADE_DB = (0.1, 100.0)            # CARRIED OVER: microwave_exposure.PARAM_SPEC


class NoDataError(ValueError):
    """A required input is missing or invalid, so no decision is made. Carries the domain ('terrain' | 'weather') and the reasons.

    ``transient`` is True when the cause is a live service that may work on a retry (provider unreachable), False when it is deterministic
    input validation (invalid coordinates, a frequency outside the rain model's range, ...): callers may cache the former as a recent
    failure but must report the latter as what it is, every time."""

    status = "NO DATA"

    def __init__(self, domain, reasons, transient=False):
        self.domain = domain
        self.reasons = list(reasons)
        self.transient = transient
        super().__init__(f"NO DATA ({domain}): " + "; ".join(self.reasons))


def is_finite_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def valid_coordinate(lat, lon) -> bool:
    return is_finite_number(lat) and is_finite_number(lon) and -90 <= lat <= 90 and -180 <= lon <= 180


def path_reasons(lat_a, lon_a, lat_b, lon_b) -> list:
    """R4 (invalid coordinates) and R9 (zero-length link: identical endpoints). Identical endpoints never produce CLEAR."""
    if not (valid_coordinate(lat_a, lon_a) and valid_coordinate(lat_b, lon_b)):
        return ["invalid coordinates (R4)"]
    if lat_a == lat_b and lon_a == lon_b:
        return ["zero-length link: identical endpoints (R4, R9)"]
    return []


def _range_reason(value, bounds, label, unit):
    if not is_finite_number(value) or not (bounds[0] <= value <= bounds[1]):
        return f"{label} outside {bounds[0]:g}-{bounds[1]:g} {unit}"
    return None


def terrain_input_reasons(lat_a, lon_a, lat_b, lon_b, height_a, height_b, frequency_ghz) -> list:
    reasons = path_reasons(lat_a, lon_a, lat_b, lon_b)
    for label, value in (("antenna height A", height_a), ("antenna height B", height_b)):
        r = _range_reason(value, HEIGHT_M, label, "m")
        if r:
            reasons.append(r)
    r = _range_reason(frequency_ghz, TERRAIN_FREQ_GHZ, "frequency", "GHz")
    if r:
        reasons.append(r)
    return reasons


def weather_input_reasons(lat_a, lon_a, lat_b, lon_b, params) -> list:
    reasons = path_reasons(lat_a, lon_a, lat_b, lon_b)
    r = _range_reason(params.get("frequency_ghz"), WEATHER_FREQ_GHZ, "frequency", "GHz (ITU-R P.838-3 range)")
    if r:
        reasons.append(r)
    r = _range_reason(params.get("fade_margin_db"), FADE_DB, "fade margin", "dB")
    if r:
        reasons.append(r)
    if params.get("polarization") not in ("V", "H"):
        reasons.append("polarization must be V or H")
    return reasons


def interval_reason(interval):
    """R3: without a valid averaging interval the provider value cannot be converted to a rate; no default is assumed."""
    if not is_finite_number(interval) or interval <= 0:
        return "Open-Meteo `current.interval` missing or invalid (R3)"
    return None
