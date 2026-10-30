"""The message registry shared with Velorona Map (``messages.json`` = a copy of the Map's ``web/messages.json``, schema ``velorona.messages/1``).

Same situation -> same ID and the same ``short_text`` here and in the Map; the ID is also the anchor in the user guide
(``https://map.velorona.ai/guide#<ID>``, upper case). The plugin shows the registry's short_text, with the placeholders the registry uses
(``N``, ``M``, ``<file>``, ``<reason>``, ``<site>``, ``<layer>``, ``<field>``) filled in. A situation that exists only in QGIS has an entry in
``PLUGIN_ONLY`` until the Map registry carries it; when it does, the registry's entry wins and ``tests/test_messages.py`` checks the two agree.
Refresh the copy with ``tools/sync_messages.py <path to the Map's web/messages.json>``; never edit ``messages.json`` by hand."""

from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from typing import Dict

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "messages.json")

# QGIS-only situations not (yet) in the Map registry: id -> (level, area, short_text).
PLUGIN_ONLY: Dict[str, tuple] = {
    "I-TERRAIN-ELEVATION-SOURCE": ("info", "Terrain", "Ground heights: Velorona's online 90 m elevation data, or a raster of yours."),
    "I-USA-DATA-SOURCE": ("info", "Layers", "USA data is Velorona's online data, not included in the plugin. Canada works without it."),
}

_ID = re.compile(r"^[EWI]-[A-Z0-9]+(?:-[A-Z0-9]+)+$")


@lru_cache(maxsize=1)
def registry() -> Dict[str, dict]:
    with open(PATH, encoding="utf-8") as fh:
        data = json.load(fh)
    table = {m["id"]: m for m in data["messages"]}
    for mid, (level, area, text) in PLUGIN_ONLY.items():
        table.setdefault(mid, {"id": mid, "level": level, "area": area, "short_text": text})
    return table


def is_message_id(message_id) -> bool:
    return isinstance(message_id, str) and bool(_ID.match(message_id))


def has(message_id: str) -> bool:
    return message_id in registry()


def short_text(message_id: str) -> str:
    return registry()[message_id]["short_text"]


def level(message_id: str) -> str:
    return registry()[message_id]["level"]


@lru_cache(maxsize=1)
def _rules():
    return [(mid, re.compile(m["match"], re.IGNORECASE)) for mid, m in registry().items() if m.get("match")]


def id_for_reason(reason: str):
    """The ID of the registry entry whose ``match`` pattern fits a NO DATA reason (the Map's ``idForReason``), or None."""
    reason = str(reason or "")
    for mid, rx in _rules():
        if rx.search(reason):
            return mid
    return None


def text(message_id: str, **fill) -> str:
    """The registry's short_text with ``N=3``, ``file="x.csv"``... filled in (``N``/``M`` replace the bare letters, the rest replace ``<name>``).
    A placeholder that is not given stays visible rather than being guessed."""
    out = short_text(message_id)
    for key, value in fill.items():
        if key in ("N", "M"):
            out = re.sub(rf"\b{key}\b", str(value), out)
        else:
            out = re.sub(rf"<{key}(?: or [^>]*)?>", lambda _m: str(value), out)   # "<file or N records>" is one placeholder
    return out
