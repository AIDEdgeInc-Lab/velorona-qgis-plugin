"""Plan limits shared with Velorona Map (a copy of the Map's ``web/data/entitlements.json``, schema ``velorona.entitlements/1``; refresh with
``tools/sync_from_map.py``). The plugin has no accounts, so it only ever applies the FREE plan's limits; it never unlocks anything.

Shape (the Map's file is the authority; this module reads only ``plans.free.limits``):
    {"schema": "velorona.entitlements/1", "default_plan": "free", "plans": {"free": {"limits": {"auto_record_links": 10, ...}}, "enterprise": {...}}}"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Dict

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "entitlements.json")
FALLBACK_FREE_LIMITS: Dict[str, int] = {"auto_record_links": 10, "auto_record_min_minutes": 15}   # only if the file cannot be read


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
    return "web/data/entitlements.json (copied from Velorona Map)" if _data() else "built-in free limits (the plan file could not be read)"
