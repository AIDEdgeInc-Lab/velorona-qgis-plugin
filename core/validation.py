"""Explicit input validation and dependency checks for the decision path. Pure stdlib, no QGIS.

Nothing here catches exceptions: a check either passes or raises a typed error with a reason. Unexpected exceptions elsewhere must still
surface; they are never converted into NO DATA.
"""

from __future__ import annotations

import math

from . import messages

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
            "aei-link-clearance>=0.3.0,<0.5): in QGIS, Plugins > Python Console, run:  from pip._internal.cli.main import main; "
            "main(['install', '-U', 'aei-link-clearance>=0.3.0,<0.5'])  then restart QGIS.")


def require_elevation_seam(library_module) -> None:
    """The plugin needs aei-link-clearance >= 0.3 (the elevation-provider seam: cache, 429 backoff, local raster). An older release is refused with the
    install instruction, never a raw ImportError and never a silent different behaviour (the plugin has no fallback for the old library)."""
    if not (hasattr(library_module, "OpenMeteoProvider") and hasattr(library_module, "LocalDEMProvider")):
        raise LibraryOutOfDateError(
            "The installed aei-link-clearance is older than this Velorona version needs (it has no elevation provider: caching, rate-limit backoff, local "
            "elevation raster). Upgrade aei-link-clearance>=0.3.0,<0.5: in QGIS, Plugins > Python Console, run:  from pip._internal.cli.main import main; "
            "main(['install', '-U', 'aei-link-clearance>=0.3.0,<0.5'])  then restart QGIS.")


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
        return [messages.short_text("E-PATH-COORDINATES")]
    if lat_a == lat_b and lon_a == lon_b:
        return [messages.short_text("E-PATH-ZERO-LENGTH")]
    return []


def _range_reason(value, bounds, label, unit):
    if not is_finite_number(value) or not (bounds[0] <= value <= bounds[1]):
        return f"{label} outside {bounds[0]:g}-{bounds[1]:g} {unit}"
    return None


def terrain_input_reasons(lat_a, lon_a, lat_b, lon_b, height_a, height_b, frequency_ghz) -> list:
    reasons = path_reasons(lat_a, lon_a, lat_b, lon_b)
    for site, value in (("A", height_a), ("B", height_b)):
        if not is_finite_number(value) or not (HEIGHT_M[0] <= value <= HEIGHT_M[1]):
            shown = f"{value:g} m" if is_finite_number(value) else "no value"
            # The Map's wording (registry E-TERRAIN-HEIGHT-RANGE): the height is refused, never clamped or replaced by a default.
            reasons.append(f"record antenna height at Site {site} ({shown}) is outside {HEIGHT_M[0]:g}-{HEIGHT_M[1]:g} m (R5); "
                           "it is not clamped and not replaced by a default")
    r = _range_reason(frequency_ghz, TERRAIN_FREQ_GHZ, "frequency", "GHz")
    if r:
        reasons.append(r)
    return reasons


def weather_input_reasons(lat_a, lon_a, lat_b, lon_b, params) -> list:
    reasons = path_reasons(lat_a, lon_a, lat_b, lon_b)
    # The Map's wording (mwexposure.js validateMwParams, registry E-WEATHER-PARAMS): refused, never clamped.
    for key, label, unit, (lo, hi), basis in (
            ("frequency_ghz", "Frequency", "GHz", WEATHER_FREQ_GHZ, "Derived and library-enforced: ITU-R P.838-3's tabulated range (1-100 GHz)."),
            ("fade_margin_db", "Fade margin", "dB", FADE_DB, "Lower bound derived: the link model rejects a fade margin <= 0.")):
        v = params.get(key)
        if not is_finite_number(v):
            reasons.append(f"{label} must be a number.")
        elif not lo <= v <= hi:
            reasons.append(f"{label} {v:g} {unit} is outside {lo:g}-{hi:g} {unit}. {basis}")
    if params.get("polarization") not in ("V", "H"):
        reasons.append("Polarization must be one of V, H.")
    return reasons


def interval_reason(interval):
    """R3: without a valid averaging interval the provider value cannot be converted to a rate; no default is assumed."""
    if not is_finite_number(interval) or interval <= 0:
        return messages.short_text("E-WEATHER-INTERVAL")
    return None
