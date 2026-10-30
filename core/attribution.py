"""Credit for Open-Meteo, whose weather and elevation data the plugin uses (Open-Meteo data are licensed CC BY 4.0, which asks for attribution),
and for the Copernicus DEM GLO-90 surface model behind its elevation (the Copernicus licence asks for its own notice).
Shown in the results panel and written into every export that used it, with a link to Open-Meteo, its licence and the user guide.
Terrain from a local raster of the user's credits neither (open_meteo_parts is then empty)."""

from __future__ import annotations

from . import elevation_source

OPEN_METEO_URL = "https://open-meteo.com/"
LICENCE_URL = "https://open-meteo.com/en/license"
GUIDE_URL = "https://map.velorona.ai/guide#data-types"
COPERNICUS_URL = "https://spacedata.copernicus.eu/collections/copernicus-digital-elevation-model"
# The notice the Copernicus DEM licence asks for (GLO-90 is what Open-Meteo's elevation API serves; Velorona only samples and interpolates it).
COPERNICUS_NOTICE = ("Contains modified Copernicus DEM GLO-90 data, \u00a9 DLR e.V. 2010-2014 and \u00a9 Airbus Defence and Space GmbH 2014-2018 "
                     "provided under COPERNICUS by the European Union and ESA; all rights reserved.")


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
    line = f"{_what(parts)} by Open-Meteo.com ({OPEN_METEO_URL}), licensed CC BY 4.0 ({LICENCE_URL}). Guide: {GUIDE_URL}"
    return f"{line} {COPERNICUS_NOTICE} ({COPERNICUS_URL})" if "elevation" in parts else line


def html(parts) -> str:
    if not parts:
        return ""
    copernicus = f" {COPERNICUS_NOTICE.replace(' Copernicus DEM', ' <a href=%r>Copernicus DEM</a>' % COPERNICUS_URL, 1)}" if "elevation" in parts else ""
    return (f"<p class='caveat'>{_what(parts)} by <a href='{OPEN_METEO_URL}'>Open-Meteo.com</a>, "
            f"licensed <a href='{LICENCE_URL}'>CC BY 4.0</a>. <a href='{GUIDE_URL}'>Guide</a>.{copernicus}</p>")
