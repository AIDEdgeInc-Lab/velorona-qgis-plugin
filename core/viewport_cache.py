"""Short-lived, bounded cache for the viewport-scoped public service fetches
(Ontario GeoHub towers, ISED cellular).

Pure stdlib -- no QGIS, no network -- so the expiry/eviction rules are
testable directly. The clock is injected for the same reason.

Scope is deliberately narrow: only the two live viewport queries go through
here. Analysis results, user data, satellite positions and QGIS layers are
never cached by this module.

Entries are matched on an exact (source, rounded bbox) key rather than by
containment. A larger bbox is not a valid superset of a smaller one: the
ArcGIS services cap a response at 1000 records and flag the truncation, so
serving a zoomed-in view from a wider cached response could silently hide
records that only appear at the tighter extent.
"""

from __future__ import annotations

import time
from collections import OrderedDict

# Live public infrastructure registries whose underlying data moves on a scale
# of months (the ISED mirror's own coverage note says roughly twice yearly).
# Five minutes is therefore far shorter than any real update cadence, so a hit
# cannot misrepresent stale data as live, while still covering the pan-away /
# pan-back navigation that the cache exists to make cheap. The cache lives on
# the plugin instance only -- nothing is written to disk and nothing survives
# a session.
CACHE_TTL_SECONDS = 300.0

# A failed fetch is remembered only briefly: long enough that a dead or very
# slow service is not re-hit on every settled viewport during continuous
# panning, short enough that a transient blip recovers on the next move or two.
FAILURE_TTL_SECONDS = 20.0

# One entry holds up to ~1000 records, so the bound is about memory, not hit
# rate: 24 entries covers roughly a dozen viewports across both layers.
MAX_ENTRIES = 24

# ~11 m at these latitudes -- absorbs float jitter in the canvas extent
# without merging genuinely different viewports.
BBOX_PRECISION = 4

MISS = object()  # nothing usable cached -- caller should fetch
FAILED = object()  # a recent fetch failed -- caller should skip this round


class ViewportCache:
    def __init__(
        self,
        ttl_seconds: float = CACHE_TTL_SECONDS,
        failure_ttl_seconds: float = FAILURE_TTL_SECONDS,
        max_entries: int = MAX_ENTRIES,
        clock=time.monotonic,
    ):
        self._ttl = ttl_seconds
        self._failure_ttl = failure_ttl_seconds
        self._max_entries = max_entries
        self._clock = clock
        self._entries: "OrderedDict[tuple, tuple]" = OrderedDict()

    @staticmethod
    def key(source, bbox) -> tuple:
        """`source` identifies both the service and the query variant, so a
        changed where-clause cannot collide with a cached earlier one."""
        return (source, tuple(round(float(v), BBOX_PRECISION) for v in bbox))

    def get(self, source, bbox):
        """Returns cached records, FAILED if a recent fetch failed, or MISS."""
        key = self.key(source, bbox)
        entry = self._entries.get(key)
        if entry is None:
            return MISS
        expires_at, value = entry
        if self._clock() >= expires_at:
            del self._entries[key]
            return MISS
        self._entries.move_to_end(key)
        return value

    def put(self, source, bbox, records) -> None:
        self._store(self.key(source, bbox), records, self._ttl)

    def put_failure(self, source, bbox) -> None:
        self._store(self.key(source, bbox), FAILED, self._failure_ttl)

    def _store(self, key, value, ttl: float) -> None:
        self._entries[key] = (self._clock() + ttl, value)
        self._entries.move_to_end(key)
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)  # evict least recently used

    def clear(self) -> None:
        self._entries.clear()

    def __len__(self) -> int:
        return len(self._entries)
