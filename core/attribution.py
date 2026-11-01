"""Data credits the plugin shows and writes: Open-Meteo (CC BY 4.0) for its weather and elevation data, and the Copernicus DEM GLO-90 notice that the
ESA licence asks for the elevation behind it. Shown under the results panel and written into every export that used the data; terrain from a raster of the
user's own credits neither (``credit_parts`` is then empty). Wording of the Copernicus notice: _private/audit/REVIEW_HOTFIX_RADAR.md section 3, which is
Articles 6(b) (adapted data) and 6(c) (no liability) of the ESA licence for COP-DEM-GLO-90, word for word. No logos, no endorsement (Art. 6(d), Art. 9)."""

from __future__ import annotations

from . import elevation_source

OPEN_METEO_URL = "https://open-meteo.com/"
LICENCE_URL = "https://open-meteo.com/en/license"
GUIDE_URL = "https://map.velorona.ai/guide#attribution"
COPERNICUS_URL = "https://doi.org/10.5270/ESA-c5d3d65"
COPERNICUS_NOTICE = ("Elevation: produced using Copernicus WorldDEM™-90 © DLR e.V. 2010-2014 and © Airbus Defence and Space GmbH 2014-2018 "
                     "provided under COPERNICUS by the European Union and ESA; all rights reserved. The organisations in charge of the Copernicus programme "
                     "by law or by delegation do not incur any liability for any use of the Copernicus WorldDEM™-90.")


def credit_parts(result) -> list:
    """Which data ``result`` used: [] / ["weather"] / ["elevation"] / both ("elevation" also means the Copernicus notice)."""
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
    """The credit as plain lines for exports ('' when nothing was used)."""
    if not parts:
        return ""
    line = f"{_what(parts)} by Open-Meteo.com ({OPEN_METEO_URL}), CC BY 4.0 ({LICENCE_URL}). Guide: {GUIDE_URL}"
    return f"{line} {COPERNICUS_NOTICE} ({COPERNICUS_URL})" if "elevation" in parts else line


def html(parts) -> str:
    if not parts:
        return ""
    out = (f"<p class='caveat'>{_what(parts)} by <a href='{OPEN_METEO_URL}'>Open-Meteo.com</a>, "
           f"<a href='{LICENCE_URL}'>CC BY 4.0</a>. <a href='{GUIDE_URL}'>Guide</a></p>")
    if "elevation" in parts:
        out += f"<p class='caveat'>{COPERNICUS_NOTICE} <a href='{COPERNICUS_URL}'>Dataset citation (DOI)</a></p>"
    return out
