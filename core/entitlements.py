"""Plan limits shared with Velorona Map (a copy of the Map's ``web/entitlements.json``, schema ``velorona.entitlements/1``; refresh with
``tools/sync_from_map.py``). The plugin has no accounts, so it only ever applies the FREE plan's limits; it never unlocks anything.

Expected shape (the Map's file is the authority; this module reads only ``plans.free.limits``):
    {"schema": "velorona.entitlements/1", "plans": {"free": {"limits": {"auto_record_links": 10, ...}}, "pro": {...}}}
Until the Map publishes the file, ``FALLBACK_FREE_LIMITS`` (the owner's stated free limits) apply and ``source()`` says so."""

from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Dict

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "entitlements.json")
FALLBACK_FREE_LIMITS: Dict[str, int] = {"auto_record_links": 10, "auto_record_min_interval_min": 15}


@lru_cache(maxsize=1)
def _data():
    try:
        with open(PATH, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    return data if data.get("schema") == "velorona.entitlements/1" else None


def free_limits() -> Dict[str, int]:
    data = _data()
    limits = ((data or {}).get("plans", {}).get("free", {}) or {}).get("limits") or {}
    return {**FALLBACK_FREE_LIMITS, **{k: v for k, v in limits.items() if isinstance(v, int) and not isinstance(v, bool)}}


def limit(name: str) -> int:
    return free_limits()[name]


def source() -> str:
    return "web/entitlements.json (copied from Velorona Map)" if _data() else "built-in free limits (the Map has not published web/entitlements.json yet)"
