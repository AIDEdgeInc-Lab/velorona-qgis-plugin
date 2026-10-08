"""Explicit input validation and dependency checks for the decision path. Pure stdlib, no QGIS.

Nothing here catches exceptions: a check either passes or raises a typed error with a reason. Unexpected exceptions elsewhere must still
surface; they are never converted into NO DATA.
"""

from __future__ import annotations

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
            "twice the earth bulge. Upgrade aei-link-clearance to a release that contains the correction.")
