"""Everything the USA data setup dialog needs that is not a widget: checking a chosen source and turning every failure into a plain-language message with
the next step. Pure stdlib -- runs without QGIS, fully unit-tested.

``check_source`` never raises for a data problem; it returns a ``SetupCheck`` whose ``state`` is one of NOT_CONFIGURED / LOADED / ERROR. "Loaded" is only
reported after the pack's index AND one real tile were read and validated, and the record count shown comes from that pack's own index, never a guess.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable, Optional

from . import usa
from .base import (PackCorruptError, PackError, PackMissingError, PackNotConfiguredError, PackUnavailableError, PackVersionError)

NOT_CONFIGURED, LOADED, ERROR = "not_configured", "loaded", "error"
# The pack Velorona Map itself serves (OBSERVED 2026-10-09: index.json + tiles, HTTP 200); the user opts in by pressing the button.
VELORONA_ONLINE_PACK = "https://map.velorona.ai/data/us/"
HELP_DOC = "https://github.com/AIDEdgeInc-Lab/velorona-qgis-plugin/blob/main/docs/USA.md"


@dataclass
class SetupCheck:
    state: str
    source: str = ""
    message: str = ""          # one friendly sentence for the status line
    next_step: str = ""        # what to do about it (empty when loaded)
    link_count: Optional[int] = None
    source_date: str = ""
    pack_date: str = ""
    note: str = ""             # e.g. "Using the 'us' folder inside the folder you chose."

    @property
    def ok(self) -> bool:
        return self.state == LOADED


def normalise(text: str):
    """(source, note). Forgives the usual slips: surrounding spaces/quotes, 'file://', a trailing 'index.json', and choosing the parent of the pack folder."""
    note = ""
    src = (text or "").strip().strip('"').strip("'").strip()
    if src.lower().endswith("/index.json") or src.lower().endswith("\\index.json"):
        src = src[: -len("index.json")].rstrip("/\\")
        note = "Removed the trailing 'index.json': the folder or address that contains it is what Velorona needs."
    if src.startswith("file://"):
        src = src[len("file://"):]
    if src and "://" not in src:
        src = os.path.expanduser(src)
        if os.path.isdir(src) and not os.path.isfile(os.path.join(src, "index.json")):
            children = [d for d in sorted(os.listdir(src)) if os.path.isfile(os.path.join(src, d, "index.json"))]
            if len(children) == 1:
                src = os.path.join(src, children[0])
                note = f"Using the '{children[0]}' folder inside the folder you chose: that is where index.json is."
    return src, note


def _friendly(exc: PackError, source: str, is_url: bool):
    """(message, next_step) for a pack error."""
    text = str(exc)
    if isinstance(exc, PackNotConfiguredError):
        if "https" in text:
            return ("Web addresses must start with https://.", "Check the address, or choose a folder on this computer instead.")
        return ("Nothing chosen yet.", "Choose a folder or use Velorona's online data.")
    if isinstance(exc, PackMissingError):
        if "index.json" in text:
            return ("This doesn't look like a Velorona USA data pack: index.json was not found there.",
                    "Choose the folder (or address) that directly contains index.json and a 'tiles' folder.")
        if "tiles/" in text or "tile" in text.lower():
            return ("The pack is incomplete: a data tile it lists is missing.", "Download the pack again, or choose a complete copy.")
        return ("That location doesn't exist.", "Check the folder or address, then try again.")
    if isinstance(exc, PackUnavailableError):
        if is_url:
            return ("Velorona couldn't reach that address.",
                    "Check your internet connection and the address, then press Check again. If it keeps failing, try again later.")
        return ("Velorona couldn't read that folder.", "Check that you have permission to open it.")
    if isinstance(exc, PackVersionError):
        return ("This data pack is a different version from the one this Velorona release understands.",
                "Update Velorona, or use a pack built for this version. " + text)
    if isinstance(exc, PackCorruptError):
        return ("The data in this pack is damaged or not what Velorona expects.", "Download the pack again. Details: " + text)
    return (text, "Check the folder or address and try again.")


def check_source(text: str, get: Optional[Callable] = None) -> SetupCheck:
    """Validate a chosen source end to end: index.json, then one real tile (the smallest listed). No network for a local folder."""
    source, note = normalise(text)
    if not source:
        return SetupCheck(NOT_CONFIGURED, message="Not set up yet.", next_step="Choose a folder on this computer, or use Velorona's online USA data.")
    is_url = source.lower().startswith(("http://", "https://"))
    try:
        provider = usa.make_provider(source, get=get)
        provider.index()
        attribution = provider.attribution()
        if isinstance(provider, usa.UsaPackProvider):
            index = provider.index()
            smallest = min((k for k, v in index.tiles.items() if v[1] > 0), key=lambda k: index.tiles[k][1], default=None)
            if smallest is not None:
                provider._tile(smallest)               # reads + validates a real tile: catches a pack whose index is fine but whose tiles are missing/damaged
        links = provider.link_count
    except PackError as exc:
        message, step = _friendly(exc, source, is_url)
        return SetupCheck(ERROR, source=source, message=message, next_step=step, note=note)
    return SetupCheck(LOADED, source=source, message=f"Ready: {links:,} US links available (source file dated {attribution.source_file_updated}).",
                      link_count=links, source_date=attribution.source_file_updated, pack_date=attribution.pack_generated, note=note)


def help_html() -> str:
    return f"""
<h3>What is the USA data pack?</h3>
<p>US radio links come from the FCC's public licence records (Universal Licensing System, microwave services). Velorona turns them into a
<b>separate data pack</b>: a folder with an <code>index.json</code> file and a <code>tiles</code> folder (about 14&nbsp;MB).
It is <b>not included in the plugin</b> because of its size and because the FCC
refreshes the data weekly. Canada works without it.</p>
<h3>Easiest: use Velorona's online data</h3>
<p>Press <b>Use Velorona's online USA data</b>. Velorona then reads only the small tiles under the map view you ask for (never the whole country), from
<code>{VELORONA_ONLINE_PACK}</code>. Nothing is downloaded until you press <i>Load USA Links in View</i>.</p>
<h3>Or keep a copy on your computer</h3>
<ol><li>Get a Velorona USA data pack (the Velorona Map project builds it from the FCC file; see the guide linked below).</li>
<li>Unzip it so you have one folder that <b>directly contains</b> <code>index.json</code> and <code>tiles/</code>.</li>
<li>Press <b>Choose a folder…</b> and select that folder.</li></ol>
<h3>Good to know</h3>
<ul><li>It is <b>licensee-reported record data</b> from a public register, not a field
measurement. Source and dates are shown on the layer and in every export.</li>
<li>US antenna heights are <b>assumed to be 30&nbsp;m</b> and are labelled "Assumed": the FCC's field documentation does not state the unit or
reference of its height field.</li>
<li>A view that would load more than 20,000 links is refused with a request to zoom in.</li></ul>
<p><a href="{HELP_DOC}">Full guide (docs/USA.md)</a></p>
"""
