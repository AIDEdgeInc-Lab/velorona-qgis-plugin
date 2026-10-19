"""The United States overview: presence, not records -- Velorona Map's design (web/app.js "United States overview", scripts/build_us_overview.py).

Below the zoom at which the pack's detailed tiles can be drawn, the Map shows the US as a few quiet counts built from ``data/us-overview.json`` (2 degree
cells of UNIQUE sites and links). No individual site or link comes from it, nothing in it is selectable, and from the detailed zoom on the detailed tiles replace
it. QGIS does the same: this module reads and validates that file (the sibling of the pack folder: ``.../data/us/`` -> ``.../data/us-overview.json``) and
groups its cells into screen-sized bins. Pure stdlib, no QGIS.
"""

from __future__ import annotations

import json
import math
import os
from typing import Callable, List, Optional, Sequence, Tuple
from urllib.parse import urlparse

from . import usa
from .base import PackCorruptError, PackVersionError

OVERVIEW_SCHEMA = "velorona.us-overview/1"
OVERVIEW_FILE = "us-overview.json"
MAX_OVERVIEW_BYTES = 1024 * 1024        # PROPOSED guard; the real file is about 9 KB
CELL_PX = 130                           # the Map's US_OVERVIEW_CELL_PX: coarser than Canada's 80 px, so the secondary country is drawn with fewer, quieter marks

Cell = Tuple[float, float, int, int]    # latitude, longitude, unique sites, unique links


def parent_source(source: str) -> str:
    """The folder / address that holds the overview file: the parent of the pack folder (the Map serves data/us/ and data/us-overview.json side by side)."""
    text = (source or "").strip()
    parsed = urlparse(text)
    if parsed.scheme in ("http", "https"):
        path = parsed.path.rstrip("/")
        return parsed._replace(path=path.rsplit("/", 1)[0] + "/" if "/" in path else "/").geturl()
    if parsed.scheme == "file":
        text = parsed.path
    return os.path.dirname(os.path.realpath(os.path.expanduser(text)).rstrip("/\\"))


def parse_overview(raw: bytes) -> List[Cell]:
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise PackCorruptError(f"The US overview is not valid JSON: {exc}") from exc
    if not isinstance(doc, dict) or not isinstance(doc.get("cells"), list):
        raise PackCorruptError("The US overview is not the expected format.")
    if doc.get("schema") != OVERVIEW_SCHEMA:
        raise PackVersionError(f"The US overview has schema {doc.get('schema')!r}; this release reads {OVERVIEW_SCHEMA!r}.")
    cells: List[Cell] = []
    for row in doc["cells"]:
        try:
            lat, lon, ns, nl = float(row[0]), float(row[1]), int(row[2]), int(row[3])
        except (TypeError, ValueError, IndexError):
            continue                                   # a malformed cell is dropped, never guessed
        if not (math.isfinite(lat) and math.isfinite(lon)) or not (-90 <= lat <= 90 and -180 <= lon <= 180) or ns < 0 or nl < 0 or (ns == 0 and nl == 0):
            continue
        cells.append((lat, lon, ns, nl))
    return cells


def load_overview(source: str, get: Optional[Callable] = None) -> List[Cell]:
    """The overview cells for a pack source. Raises PackMissingError when the source has no overview (a folder pack without it): the caller shows nothing."""
    fetcher = usa.make_fetcher(parent_source(source), get=get)
    return parse_overview(fetcher.fetch(OVERVIEW_FILE, MAX_OVERVIEW_BYTES))


def compact(n: int) -> str:
    """1,234 -> '1.2k' (the Map's fmtCompact)."""
    if n < 1000:
        return str(n)
    if n < 10000:
        return f"{n / 1000:.1f}k".replace(".0k", "k")
    if n < 999_500:
        return f"{round(n / 1000)}k"
    return f"{n / 1_000_000:.1f}M".replace(".0M", "M")


def bin_cells(cells: Sequence[Cell], zoom: float, bbox: Tuple[float, float, float, float], want_sites: bool = True, want_links: bool = True,
              cell_px: int = CELL_PX) -> List[dict]:
    """Groups the cells of the (padded) view into screen-sized bins, as the Map does: Web-Mercator pixel cells of ``cell_px`` at this zoom; the count is the
    sum of the chosen cells, the position their count-weighted mean. Returns dicts with lat, lon, n, ns, nl, label."""
    west, south, east, north = bbox
    pad_x, pad_y = (east - west) * 0.25, (north - south) * 0.25
    scale = 256.0 * (2.0 ** zoom)
    bins = {}
    for lat, lon, ns, nl in cells:
        if not (west - pad_x <= lon <= east + pad_x and south - pad_y <= lat <= north + pad_y):
            continue
        n = ns if want_sites else nl if want_links else 0
        if not n:
            continue
        sin = math.sin(math.radians(max(-85.0511, min(85.0511, lat))))
        x = (lon + 180.0) / 360.0 * scale
        y = (0.5 - math.log((1 + sin) / (1 - sin)) / (4 * math.pi)) * scale
        key = (int(x // cell_px), int(y // cell_px))
        b = bins.setdefault(key, {"n": 0, "ns": 0, "nl": 0, "lat": 0.0, "lon": 0.0})
        b["n"] += n
        b["ns"] += ns
        b["nl"] += nl
        b["lat"] += lat * n
        b["lon"] += lon * n
    out = []
    for b in bins.values():
        out.append({"latitude": b["lat"] / b["n"], "longitude": b["lon"] / b["n"], "n": b["n"], "ns": b["ns"], "nl": b["nl"], "label": compact(b["n"])})
    return out
