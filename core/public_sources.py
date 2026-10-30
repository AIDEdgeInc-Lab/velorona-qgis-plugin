"""Which site sources are public registers, so their names are public data (kept in exports) rather than the user's own (left out unless ticked).

A source is public when it is one of the datasets in the synced pack registry (core/packs.json: each pack's agency or the dataset name before
its first comma/parenthesis, e.g. "SMS Authorization Data Extract", "ULS public access database", "U.S. Federal Communications Commission") or
one of the other public datasets the plugin loads itself (towers, cellular sites, ground stations, satellites). A new pack in packs.json is
public without a code change as long as the plugin's source text names its agency or dataset; tests/qgis_ui_polish_e2e.py checks every pack
is matched by the plugin's own source text.

The text alone is not trusted: ``feature_source`` takes it only from a layer Velorona created, so a user layer with a "source" column saying
"ISED" is still the user's own."""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Tuple

USER_SOURCE = "Selected QGIS feature"
# Public datasets the plugin loads that are not data packs (core/sources/*: SOURCE_GEOHUB, SOURCE_ISED_CELLULAR, SOURCE_SATNOGS, SOURCE_CELESTRAK).
OTHER_PUBLIC_MARKERS = ("Ontario GeoHub", "ISED Spectrum Licences Site Data", "SatNOGS Network", "CelesTrak GP element sets")


@lru_cache(maxsize=1)
def pack_markers() -> Tuple[str, ...]:
    from . import packs
    out = []
    for p in packs.registry().values():
        src = p.get("source") or {}
        for text in (src.get("agency"), src.get("dataset")):
            head = re.split(r"[,(]", text or "", maxsplit=1)[0].strip()
            if len(head) >= 6:
                out.append(head)
    return tuple(out)


def is_public(source) -> bool:
    text = str(source or "").lower()
    if not text or text == USER_SOURCE.lower():
        return False
    return any(m.lower() in text for m in pack_markers() + OTHER_PUBLIC_MARKERS)


def feature_source(layer, feature) -> str:
    """The feature's "source" text when the layer is one Velorona created, else USER_SOURCE (never read from a user's own layer)."""
    from .features import feature_attr
    from .layers import is_velorona_owned
    if layer is not None and is_velorona_owned(layer):
        return str(feature_attr(feature, "source", USER_SOURCE))
    return USER_SOURCE
