"""Credit for Open-Meteo, whose weather and elevation data the plugin uses (Open-Meteo data are licensed CC BY 4.0, which asks for attribution).
Shown in the results panel and written into every export that used it, with a link to Open-Meteo, its licence and the user guide."""

from __future__ import annotations

from . import elevation_source

OPEN_METEO_URL = "https://open-meteo.com/"
LICENCE_URL = "https://open-meteo.com/en/license"
GUIDE_URL = "https://map.velorona.ai/guide#data-types"


def open_meteo_parts(result) -> list:
    """Which Open-Meteo data ``result`` used: [] / ["weather"] / ["elevation"] / both."""
    kind = getattr(result, "kind", "")
    parts = []
    if kind == "terrestrial" and elevation_source.is_online(result):
        parts.append("elevation")
    if kind == "microwave-exposure" or (kind == "link-investigation" and getattr(result, "exposure", None) is not None):
        parts.append("weather")
    return parts


def _what(parts) -> str:
    return " and ".join(p.capitalize() if i == 0 else p for i, p in enumerate(parts)) + " data"


def text(parts) -> str:
    """One plain line for exports, e.g. 'Weather data by Open-Meteo.com (https://open-meteo.com/), CC BY 4.0 (...). Guide: ...'."""
    if not parts:
        return ""
    return f"{_what(parts)} by Open-Meteo.com ({OPEN_METEO_URL}), licensed CC BY 4.0 ({LICENCE_URL}). Guide: {GUIDE_URL}"


def html(parts) -> str:
    if not parts:
        return ""
    return (f"<p class='caveat'>{_what(parts)} by <a href='{OPEN_METEO_URL}'>Open-Meteo.com</a>, "
            f"licensed <a href='{LICENCE_URL}'>CC BY 4.0</a>. <a href='{GUIDE_URL}'>Guide</a></p>")
