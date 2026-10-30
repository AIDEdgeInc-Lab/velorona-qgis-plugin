"""Data-pack verification level (a copy of the Map's ``web/data/packs.json``, schema ``velorona.packs/1``; refresh with ``tools/sync_from_map.py``).

Each pack may state ``verification``: how its records were checked, one of ``source-published`` (as published by the agency, not checked
further), ``cross-checked`` (compared with an independent source) or ``operator-confirmed`` (the operator confirmed them), with
``verified_on`` (YYYY-MM-DD) and ``basis`` (what was done). Accepted shapes: ``"verification": {"level", "verified_on", "basis"}`` or
``"verification": "<level>"`` with ``verified_on`` / ``basis`` beside it. A level applies only to the pack build it was stated for: when the
records loaded in QGIS come from a different build (``generated_date``), no level is shown. Nothing is inferred: no field, no badge level."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional


PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "packs.json")
LEVELS = {"source-published": "Source-published", "cross-checked": "Cross-checked", "operator-confirmed": "Operator-confirmed"}
GUIDE_IDS = {"source-published": "I-PACK-SOURCE-PUBLISHED", "cross-checked": "I-PACK-CROSS-CHECKED", "operator-confirmed": "I-PACK-OPERATOR-CONFIRMED"}
# Layer source keys (core/layers.py SOURCE_*; spelled out so this module needs no QGIS) -> pack id. tests/qgis_ui_polish_e2e.py checks the keys.
SOURCE_TO_PACK = {"fixed_sites": "ca-ised-fixed", "fixed_links": "ca-ised-fixed", "us_fixed_sites": "us-fcc-uls-micro", "us_fixed_links": "us-fcc-uls-micro"}


@dataclass(frozen=True)
class Badge:
    text: str
    tooltip: str
    level: Optional[str]          # one of LEVELS, or None when no level applies


@lru_cache(maxsize=1)
def registry() -> dict:
    with open(PATH, encoding="utf-8") as fh:
        data = json.load(fh)
    return {p["id"]: p for p in data["packs"]}


def verification(pack_id: str) -> Optional[dict]:
    """{"level", "verified_on", "basis"} as stated for the pack, or None (absent, or a level outside the three)."""
    pack = registry().get(pack_id) or {}
    v = pack.get("verification")
    if isinstance(v, str):
        v = {"level": v, "verified_on": pack.get("verified_on"), "basis": pack.get("basis")}
    if not isinstance(v, dict) or v.get("level") not in LEVELS:
        return None
    return {"level": v["level"], "verified_on": v.get("verified_on") or "", "basis": v.get("basis") or ""}


def badge(pack_id: str, loaded_generated_date: Optional[str]) -> Badge:
    pack = registry().get(pack_id)
    if pack is None:
        return Badge("Verification: not stated", "This dataset is not in the Velorona pack registry.", None)
    v = verification(pack_id)
    if v is None:
        return Badge("Verification: not stated", f"The registry states no verification level for {pack['title']}.", None)
    if loaded_generated_date and loaded_generated_date != pack.get("generated_date"):
        return Badge("Verification: not stated for this pack build",
                     f"The level was stated for the build of {pack.get('generated_date')}; the records loaded here were built {loaded_generated_date}.", None)
    when = f" (verified {v['verified_on']})" if v["verified_on"] else ""
    from . import messages
    word = messages.short_text(GUIDE_IDS[v["level"]])          # the registry's word for the level (same as the Map's badge)
    return Badge(f"Verification: {word}{when}", v["basis"] or word, v["level"])


def guide_id(badge: "Badge") -> str:
    """The registry entry explaining the badge's level ("" when no level applies: the "?" is then hidden)."""
    return GUIDE_IDS.get(badge.level or "", "")


@lru_cache(maxsize=1)
def bundled_canada_generated_date() -> Optional[str]:
    from .sources.terrestrial_public import FIXED_SERVICE_SNAPSHOT_PATH
    try:
        with open(FIXED_SERVICE_SNAPSHOT_PATH, encoding="utf-8") as fh:
            return json.load(fh).get("generated_date")
    except (OSError, ValueError):
        return None
