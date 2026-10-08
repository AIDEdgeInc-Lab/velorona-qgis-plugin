"""USA provider: FCC ULS microwave links from the Velorona USA pack (schema ``velorona.us-fcc-uls-micro/1``). Pure stdlib (+ ``requests`` only
when the source is a URL) -- runs without QGIS.

The pack is NOT shipped inside the plugin: it is ~14 MB gzip / 250,874 links, refreshed weekly by the FCC. The user points the plugin at a
pack source -- a local directory or an https URL -- and the provider reads ``index.json`` plus the 1 x 1 degree tiles that touch the
requested extent. Nothing is read for the rest of the country.

Schema: PROVISIONAL. It is derived from the files the Velorona Map builder (``scripts/build_us_fcc_pack.py`` 1.0.0) actually produced and
from the Map's loader (``web/uspack.js``); the Map agent's ``parity/contract/USA_PACK_SCHEMA.md`` did not exist when this was written.
Reconcile with it when published (parity/handoff/QGIS_STATUS.md). Pack layout:

    <source>/index.json                 {pack, schema, generated_date, source_file_updated, source{...}, attribution, tile_degrees,
                                         min_zoom_hint, counts{...}, tiles{"<lat>_<lon>": [n_sites, n_links]}}
    <source>/tiles/<lat>_<lon>.json.gz  {sites:[{i,la,lo,n,c[],s,l[],q?}], links:[{i,u,k,c,a,b,l,f[],t[],np,g,x,q?}]}

``a``/``b`` index into the same tile's ``sites``. A link is written into the tile of each of its endpoints, so a link whose endpoints
straddle a tile edge appears in more than one tile: it is de-duplicated by its id (``i``). Frequencies ``f`` are MHz.
"""

from __future__ import annotations

import gzip
import io
import json
import math
import os
import re
import zlib
from collections import OrderedDict
from typing import Callable, Dict, List, Optional, Tuple
from urllib.parse import quote, urlparse

from .base import (Attribution, LoadResult, PackCorruptError, PackError, PackMissingError, PackNotConfiguredError,
                   PackUnavailableError, PackVersionError, ViewTooLargeError)

PACK_ID = "us-fcc-uls-micro"
SUPPORTED_SCHEMA_MAJORS = (1,)
SCHEMA_RE = re.compile(r"^velorona\.us-fcc-uls-micro/(\d+)$")
TILE_KEY_RE = re.compile(r"^-?\d{1,3}_-?\d{1,3}$")

# Same string the Velorona Map (web/uspack.js SOURCE_FCC_ULS) puts on every US record, so the record's `source` is identical across products.
SOURCE_FCC_ULS = "FCC ULS public access database: Microwave (l_micro), U.S. Federal Communications Commission"
COVERAGE_US = "United States -- snapshot, not a live query"

# --- Budgets. PROPOSED engineering limits, not sourced: they bound memory and GUI-blocking time, nothing else. ---------------------
MAX_LINKS_PER_LOAD = 20000      # PROPOSED. Precedent: the plugin already holds Canada's 16,956 links in one memory layer (OBSERVED).
MAX_TILES_PER_LOAD = 36         # PROPOSED. A 6 x 6 degree window.
TILE_CACHE_SIZE = 16            # PROPOSED. Densest real tile is 4,292 links / 1.30 MB of JSON (OBSERVED), so memory stays bounded.
MAX_INDEX_BYTES = 4 * 1024 * 1024        # PROPOSED. Real index.json is 39 KB.
MAX_TILE_BYTES = 16 * 1024 * 1024        # PROPOSED. Decompressed size guard (gzip bomb); densest real tile is 1.30 MB.
HTTP_TIMEOUT_S = 15.0           # same as the plugin's other public-data calls

_LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")


# ---------------------------------------------------------------------------------------------------------------------------------
# Fetchers: bytes by relative path. Failures are typed, never swallowed.
# ---------------------------------------------------------------------------------------------------------------------------------
class LocalFetcher:
    def __init__(self, root: str):
        self.root = os.path.realpath(os.path.expanduser(root))
        self.label = self.root

    def fetch(self, rel: str, limit: int) -> bytes:
        path = os.path.realpath(os.path.join(self.root, rel))
        if os.path.commonpath([self.root, path]) != self.root:
            raise PackCorruptError(f"Refusing to read '{rel}': it resolves outside the pack folder.")
        try:
            size = os.path.getsize(path)
            if size > limit:
                raise PackCorruptError(f"'{rel}' is {size} bytes, over the {limit}-byte guard; the pack looks corrupt.")
            with open(path, "rb") as fh:
                return fh.read()
        except FileNotFoundError:
            raise PackMissingError(f"The USA pack at {self.root} has no '{rel}'. Check the pack source setting.") from None
        except OSError as exc:
            raise PackUnavailableError(f"Could not read '{rel}' from {self.root}: {exc}") from exc


class HttpFetcher:
    def __init__(self, base_url: str, get: Optional[Callable] = None, timeout: float = HTTP_TIMEOUT_S):
        self.base = base_url if base_url.endswith("/") else base_url + "/"
        self.label = self.base
        self._get = get
        self.timeout = timeout

    def fetch(self, rel: str, limit: int) -> bytes:
        get = self._get
        if get is None:
            import requests   # imported lazily: a local pack never needs it
            get = requests.get
        url = self.base + quote(rel, safe="/")
        try:
            resp = get(url, timeout=self.timeout)
        except Exception as exc:    # any transport failure: say so, name the URL; the caller maps it to a clear message
            raise PackUnavailableError(f"Could not reach the USA pack at {url}: {exc}") from exc
        status = getattr(resp, "status_code", None)
        if status in (404, 410):
            raise PackMissingError(f"The USA pack at {self.base} has no '{rel}' (HTTP {status}). Check the pack source setting.")
        if status is None or status >= 400:
            raise PackUnavailableError(f"The USA pack server answered HTTP {status} for {url}. Try again later.")
        body = resp.content
        if len(body) > limit:
            raise PackCorruptError(f"'{rel}' from {self.base} is {len(body)} bytes, over the {limit}-byte guard.")
        return body


def make_fetcher(source: str, get: Optional[Callable] = None):
    """Local directory, ``file://`` URL, or https URL (plain http only for localhost, for testing)."""
    text = (source or "").strip()
    if not text:
        raise PackNotConfiguredError(
            "No USA data pack is configured. Set the pack source (a folder on this computer or an https address) to load US links.")
    parsed = urlparse(text)
    if parsed.scheme in ("http", "https"):
        if parsed.scheme == "http" and (parsed.hostname or "") not in _LOCAL_HOSTS:
            raise PackNotConfiguredError("The USA pack source must be https (plain http is accepted only for localhost).")
        return HttpFetcher(text, get=get)
    if parsed.scheme == "file":
        text = parsed.path
    elif parsed.scheme and len(parsed.scheme) > 1:    # e.g. ftp:// ; a one-letter scheme is a Windows drive
        raise PackNotConfiguredError(f"Unsupported USA pack source '{text}': use a folder path or an https address.")
    root = os.path.expanduser(text)
    if not os.path.isdir(root):
        raise PackMissingError(f"The USA pack folder '{root}' does not exist. Check the pack source setting.")
    return LocalFetcher(root)


# ---------------------------------------------------------------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------------------------------------------------------------
def _num(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _fmt_mhz(value: float) -> str:
    return str(int(value)) if float(value) == int(value) else str(value)


def _json(raw: bytes, what: str):
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise PackCorruptError(f"{what} is not valid JSON ({exc}); the pack looks corrupt. Re-download it.") from exc


def _gunzip(raw: bytes, what: str) -> bytes:
    if raw[:2] != b"\x1f\x8b":
        return raw          # a host or proxy may already have decoded it (the Map accepts both); it is then validated as JSON
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(raw)) as gz:
            out = gz.read(MAX_TILE_BYTES + 1)
    except (OSError, EOFError, zlib.error) as exc:
        raise PackCorruptError(f"{what} is not a valid gzip file ({exc}); the pack looks corrupt. Re-download it.") from exc
    if len(out) > MAX_TILE_BYTES:
        raise PackCorruptError(f"{what} expands beyond {MAX_TILE_BYTES} bytes; refusing it (corrupt or hostile pack).")
    return out


class PackIndex:
    def __init__(self, data: dict):
        self.data = data
        self.tiles: Dict[str, Tuple[int, int]] = {k: (v[0], v[1]) for k, v in data["tiles"].items()}
        self.attribution = Attribution(
            country="US",
            source_name=f"{data['source'].get('agency', 'FCC')}, {data['source'].get('system', 'ULS')}",
            attribution_text=data["attribution"],
            source_file_updated=data["source_file_updated"],
            pack_generated=data["generated_date"],
        )

    @property
    def schema(self) -> str:
        return self.data["schema"]

    @property
    def link_count(self) -> int:
        return self.data["counts"]["links"]


def parse_index(raw: bytes) -> PackIndex:
    data = _json(raw, "The USA pack index.json")
    if not isinstance(data, dict):
        raise PackCorruptError("The USA pack index.json is not a JSON object.")
    if data.get("pack") != PACK_ID:
        raise PackCorruptError(f"This is not a Velorona USA pack (pack id {data.get('pack')!r}, expected {PACK_ID!r}).")
    match = SCHEMA_RE.match(str(data.get("schema", "")))
    if not match:
        raise PackVersionError(f"The USA pack declares an unknown schema {data.get('schema')!r}; this plugin reads '{PACK_ID}' schema "
                               f"velorona.us-fcc-uls-micro/{SUPPORTED_SCHEMA_MAJORS[0]}.")
    if int(match.group(1)) not in SUPPORTED_SCHEMA_MAJORS:
        raise PackVersionError(f"The USA pack uses schema {data['schema']}; this plugin version reads major version(s) "
                               f"{', '.join(map(str, SUPPORTED_SCHEMA_MAJORS))} only. Update the plugin or use a compatible pack.")
    if data.get("tile_degrees") != 1:
        raise PackVersionError(f"The USA pack uses {data.get('tile_degrees')!r}-degree tiles; this plugin reads 1-degree tiles only.")
    for key in ("attribution", "source_file_updated", "generated_date"):
        if not isinstance(data.get(key), str) or not data[key]:
            raise PackCorruptError(f"The USA pack index has no '{key}'; refusing a pack that cannot state where its data came from.")
    if not isinstance(data.get("source"), dict) or not isinstance(data.get("counts"), dict) or not _num(data["counts"].get("links")):
        raise PackCorruptError("The USA pack index is missing its 'source' or 'counts' block.")
    tiles = data.get("tiles")
    if not isinstance(tiles, dict) or not tiles:
        raise PackCorruptError("The USA pack index lists no tiles.")
    for key, val in tiles.items():
        if (not TILE_KEY_RE.match(key) or not isinstance(val, list) or len(val) != 2
                or not all(isinstance(n, int) and not isinstance(n, bool) and n >= 0 for n in val)):
            raise PackCorruptError(f"The USA pack index has an invalid tile entry {key!r}.")
    return PackIndex(data)


def _validate_tile(tile, key: str) -> dict:
    where = f"USA pack tile {key}"
    if not isinstance(tile, dict) or not isinstance(tile.get("sites"), list) or not isinstance(tile.get("links"), list):
        raise PackCorruptError(f"{where} has no 'sites'/'links' lists; the pack looks corrupt.")
    sites = tile["sites"]
    for s in sites:
        if (not isinstance(s, dict) or not isinstance(s.get("i"), str) or not _num(s.get("la")) or not _num(s.get("lo"))
                or not -90 <= s["la"] <= 90 or not -180 <= s["lo"] <= 180
                or not isinstance(s.get("c"), list) or not isinstance(s.get("l"), list)):
            raise PackCorruptError(f"{where} has an invalid site record ({str(s)[:80]}).")
    for lk in tile["links"]:
        if (not isinstance(lk, dict) or not isinstance(lk.get("i"), str) or not isinstance(lk.get("c"), str)
                or not isinstance(lk.get("a"), int) or not isinstance(lk.get("b"), int)
                or not 0 <= lk["a"] < len(sites) or not 0 <= lk["b"] < len(sites)
                or not isinstance(lk.get("f"), list) or not all(_num(f) and f > 0 for f in lk["f"])):
            raise PackCorruptError(f"{where} has an invalid link record ({str(lk)[:80]}).")
    return tile


# ---------------------------------------------------------------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------------------------------------------------------------
class UsaPackProvider:
    country = "US"

    def __init__(self, source: str, fetcher=None, get: Optional[Callable] = None,
                 max_links: int = MAX_LINKS_PER_LOAD, max_tiles: int = MAX_TILES_PER_LOAD, cache_size: int = TILE_CACHE_SIZE):
        self.source = source
        self._fetcher = fetcher if fetcher is not None else make_fetcher(source, get=get)
        self.max_links, self.max_tiles, self.cache_size = max_links, max_tiles, cache_size
        self._index: Optional[PackIndex] = None
        self._cache: "OrderedDict[str, dict]" = OrderedDict()     # tile key -> validated raw tile

    # -- metadata ------------------------------------------------------------------------------------------------------------
    def index(self) -> PackIndex:
        if self._index is None:
            self._index = parse_index(self._fetcher.fetch("index.json", MAX_INDEX_BYTES))
        return self._index

    def attribution(self) -> Attribution:
        return self.index().attribution

    # -- extent -> tiles -----------------------------------------------------------------------------------------------------
    def tile_keys(self, bbox: Tuple[float, float, float, float]) -> List[str]:
        """Tiles of the pack that touch ``bbox`` = (west, south, east, north) in degrees. Longitude/latitude are clamped to the valid
        range; a view that crosses the antimeridian is NOT split (Guam/CNMI and American Samoa tiles are reached from their own side)."""
        if not isinstance(bbox, (tuple, list)) or len(bbox) != 4 or not all(_num(v) for v in bbox):
            raise PackError(f"The requested extent {bbox!r} is not a valid west/south/east/north box.")
        west, south, east, north = bbox
        if west > east or south > north:
            raise PackError(f"The requested extent {bbox!r} is not a valid west/south/east/north box.")
        west, east = max(-180.0, west), min(180.0, east)
        south, north = max(-90.0, south), min(90.0, north)
        index = self.index()
        keys = []
        for la in range(math.floor(south), math.floor(north) + 1):
            for lo in range(math.floor(west), math.floor(east) + 1):
                key = f"{la}_{lo}"
                if key in index.tiles:
                    keys.append(key)
        return keys

    def estimate(self, bbox) -> Tuple[int, int]:
        """(tiles, upper bound of link records) for ``bbox`` from the index alone, before any tile is downloaded. The bound counts a
        link once per tile it appears in, so it never under-counts."""
        keys = self.tile_keys(bbox)
        return len(keys), sum(self.index().tiles[k][1] for k in keys)

    # -- loading -------------------------------------------------------------------------------------------------------------
    def _tile(self, key: str) -> Tuple[dict, bool]:
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key], False
        raw = self._fetcher.fetch(f"tiles/{key}.json.gz", MAX_TILE_BYTES)
        tile = _validate_tile(_json(_gunzip(raw, f"USA pack tile {key}"), f"USA pack tile {key}"), key)
        self._cache[key] = tile
        while len(self._cache) > self.cache_size:
            self._cache.popitem(last=False)
        return tile, True

    def load_bbox(self, bbox) -> LoadResult:
        index = self.index()
        keys = self.tile_keys(bbox)
        upper = sum(index.tiles[k][1] for k in keys)
        if len(keys) > self.max_tiles or upper > self.max_links:
            raise ViewTooLargeError(
                f"This view covers {len(keys)} map tiles and up to {upper:,} US links; Velorona loads at most {self.max_links:,} links "
                f"({self.max_tiles} tiles) at a time. Zoom in and load again.")
        result = LoadResult(attribution=index.attribution, tiles_requested=len(keys))
        sites_by_id: Dict[str, dict] = {}
        site_freqs: Dict[str, set] = {}
        links_by_id: Dict[str, dict] = {}
        meta = index.attribution
        input_sha = index.data["source"].get("input_zip_sha256")
        for key in keys:
            tile, fetched = self._tile(key)
            result.tiles_fetched += 1 if fetched else 0
            slot_sites = []
            for s in tile["sites"]:
                rec = sites_by_id.get(s["i"])
                if rec is None:
                    call = ", ".join(s["c"])
                    rec = sites_by_id[s["i"]] = {
                        "id": s["i"], "latitude": s["la"], "longitude": s["lo"], "source": SOURCE_FCC_ULS, "country": "US",
                        "name": s.get("n") or s["i"], "feature_type": "Fixed Service station (FCC ULS microwave)",
                        "record_id": call or None, "call_signs": call or None, "authorizations": call or None,
                        "frequencies_mhz": None, "licensee": " / ".join(s["l"]) or None, "province": s.get("s"),
                        "coverage": COVERAGE_US, "flags": ", ".join(s["q"]) if isinstance(s.get("q"), list) else s.get("q"),
                        "attribution": meta.attribution_text, "pack_generated": meta.pack_generated,
                        "source_file_updated": meta.source_file_updated, "pack_input_sha256": input_sha,
                    }
                    site_freqs[s["i"]] = set()
                else:
                    result.duplicate_sites_dropped += 1
                slot_sites.append(rec)
            for lk in tile["links"]:
                if lk["i"] in links_by_id:
                    result.duplicate_links_dropped += 1
                    continue
                a, b = slot_sites[lk["a"]], slot_sites[lk["b"]]
                freqs = ", ".join(_fmt_mhz(f) for f in lk["f"])
                links_by_id[lk["i"]] = {
                    "id": lk["i"], "source": SOURCE_FCC_ULS, "country": "US", "authorization_number": f"{lk['c']}-{lk.get('k')}",
                    "call_sign": lk["c"], "licensee": lk.get("l"), "in_service_date": None, "grant_date": lk.get("g"),
                    "expiration_date": lk.get("x"), "path_type": ", ".join(lk.get("t") or []) or None, "frequencies_mhz": freqs,
                    "site_a": a, "site_b": b, "coverage": COVERAGE_US,
                    "flags": ", ".join(lk["q"]) if isinstance(lk.get("q"), list) else lk.get("q"),
                    "attribution": meta.attribution_text, "pack_generated": meta.pack_generated,
                    "source_file_updated": meta.source_file_updated, "pack_input_sha256": input_sha,
                }
                for site in (a, b):
                    site_freqs[site["id"]].update(lk["f"])
        for sid, freqs in site_freqs.items():     # a site's frequency list = the union over the loaded links that end there (as the Map)
            if freqs:
                sites_by_id[sid]["frequencies_mhz"] = ", ".join(_fmt_mhz(f) for f in sorted(freqs))
        result.sites = list(sites_by_id.values())
        result.links = list(links_by_id.values())
        return result

    def clear_cache(self) -> None:
        self._cache.clear()
        self._index = None
