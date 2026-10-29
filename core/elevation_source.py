"""Where a terrain analysis gets its ground heights from, and how a failure to get them is reported. Pure Python (no QGIS), so it is unit-testable.

The library seam (aei-link-clearance >= 0.3: ``analyze_link(elevation_provider=)``) owns caching and 429 backoff for the online service. A
library older than that cannot take a provider: the plugin then keeps its previous behaviour (one online request wrapped in
``provider_retry.call_with_backoff``) and the local-DEM choice is unavailable, with the reason stated.
"""

from __future__ import annotations

from typing import Optional

ONLINE_LABEL = "Online (Open-Meteo, 90 m surface model)"
# What the library 0.2.x constant says; used only for a result that predates the ``elevation_source`` field.
ONLINE_SOURCE_TEXT = "Open-Meteo Elevation API (Copernicus DEM GLO-90, 90 m surface model)"

_online = None


def providers_supported() -> bool:
    """True when the installed aei_link_clearance has the elevation-provider seam."""
    try:
        import aei_link_clearance
    except ImportError:
        return False
    return hasattr(aei_link_clearance, "OpenMeteoProvider") and hasattr(aei_link_clearance, "LocalDEMProvider")


def online_provider():
    """The one shared online provider (cache + cool-down live in it, so they must be shared by every analysis), or None for an old library."""
    global _online
    if not providers_supported():
        return None
    if _online is None:
        from aei_link_clearance import OpenMeteoProvider
        from . import provider_retry
        # Waits go through provider_retry._sleep, the one place the plugin (and its tests) control how backoff sleeps.
        _online = OpenMeteoProvider(sleep=lambda seconds: provider_retry._sleep(seconds))
    return _online


def reset_online_provider() -> None:
    """Forget the cached heights and any cool-down (tests, and 'Clear elevation cache')."""
    global _online
    _online = None


def source_of(result) -> str:
    """The elevation source a library result (or a plugin result wrapping one) names; the online text for a result that does not say."""
    r = getattr(result, "result", result)
    return str(getattr(r, "elevation_source", None) or ONLINE_SOURCE_TEXT)


def is_online(result) -> bool:
    """True for the online default. Everything that is not is a user-chosen raster, whose own description must replace the online wording."""
    text = source_of(result)
    if text == ONLINE_SOURCE_TEXT:
        return True
    try:
        from aei_link_clearance.elevation import SOURCE
    except ImportError:
        return False
    return text == SOURCE


def failure_reason(exc: BaseException) -> Optional[tuple]:
    """(reason, transient) for the library's elevation errors, or None for anything else. The reason is written to the user; for a failure of
    the SERVICE it says so and never presents it as a property of the link."""
    try:
        from aei_link_clearance import DEMCrsMismatchError, ElevationCoverageError, ElevationServiceUnavailable
    except ImportError:
        return None
    if isinstance(exc, ElevationServiceUnavailable):
        return f"elevation data unavailable (T1/R5): {exc}", bool(exc.transient)
    if isinstance(exc, DEMCrsMismatchError):
        return f"the chosen elevation raster cannot be used (T1): {exc}", False
    if isinstance(exc, ElevationCoverageError):
        return f"the chosen elevation raster does not cover this path (T1): {exc}", False
    return None
