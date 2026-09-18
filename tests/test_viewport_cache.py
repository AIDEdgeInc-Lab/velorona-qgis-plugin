"""Expiry/eviction rules for the viewport fetch cache.

Pure stdlib -- runs without QGIS. The cache takes an injected clock so TTL
behaviour is asserted deterministically instead of by sleeping.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.viewport_cache import FAILED, MISS, ViewportCache  # noqa: E402

TOWERS = ("https://example.invalid/towers", "CLASS_SUBTYPE IN ('Radio Tower')")
CELLULAR = ("https://example.invalid/cellular", "1=1")
BBOX = (-80.0, 43.0, -79.0, 44.0)
OTHER_BBOX = (-75.0, 45.0, -74.0, 46.0)


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def make_cache(**kwargs):
    clock = FakeClock()
    defaults = dict(ttl_seconds=300.0, failure_ttl_seconds=20.0, max_entries=24, clock=clock)
    defaults.update(kwargs)
    return ViewportCache(**defaults), clock


def test_miss_when_empty():
    cache, _ = make_cache()
    assert cache.get(TOWERS, BBOX) is MISS


def test_hit_returns_stored_records():
    cache, _ = make_cache()
    records = [{"id": "a"}, {"id": "b"}]
    cache.put(TOWERS, BBOX, records)
    assert cache.get(TOWERS, BBOX) == records


def test_hit_survives_until_ttl_then_expires():
    cache, clock = make_cache(ttl_seconds=300.0)
    cache.put(TOWERS, BBOX, [{"id": "a"}])

    clock.advance(299.0)
    assert cache.get(TOWERS, BBOX) == [{"id": "a"}]

    clock.advance(2.0)  # now past the 300s TTL
    assert cache.get(TOWERS, BBOX) is MISS


def test_expired_entry_is_dropped_not_just_hidden():
    cache, clock = make_cache(ttl_seconds=10.0)
    cache.put(TOWERS, BBOX, [{"id": "a"}])
    clock.advance(11.0)
    cache.get(TOWERS, BBOX)
    assert len(cache) == 0


def test_failure_is_negatively_cached_then_retried():
    cache, clock = make_cache(failure_ttl_seconds=20.0)
    cache.put_failure(TOWERS, BBOX)

    assert cache.get(TOWERS, BBOX) is FAILED  # caller skips, service not hammered

    clock.advance(21.0)
    assert cache.get(TOWERS, BBOX) is MISS  # caller retries


def test_failure_ttl_is_shorter_than_success_ttl():
    cache, clock = make_cache(ttl_seconds=300.0, failure_ttl_seconds=20.0)
    cache.put(TOWERS, BBOX, [{"id": "a"}])
    cache.put_failure(CELLULAR, BBOX)
    clock.advance(25.0)
    assert cache.get(TOWERS, BBOX) == [{"id": "a"}]
    assert cache.get(CELLULAR, BBOX) is MISS


def test_success_replaces_an_earlier_failure():
    cache, _ = make_cache()
    cache.put_failure(TOWERS, BBOX)
    cache.put(TOWERS, BBOX, [{"id": "a"}])
    assert cache.get(TOWERS, BBOX) == [{"id": "a"}]


def test_sources_do_not_collide_on_the_same_bbox():
    cache, _ = make_cache()
    cache.put(TOWERS, BBOX, [{"id": "tower"}])
    cache.put(CELLULAR, BBOX, [{"id": "cell"}])
    assert cache.get(TOWERS, BBOX) == [{"id": "tower"}]
    assert cache.get(CELLULAR, BBOX) == [{"id": "cell"}]


def test_query_variant_is_part_of_the_key():
    cache, _ = make_cache()
    changed_where = (TOWERS[0], "CLASS_SUBTYPE IN ('Microwave Tower')")
    cache.put(TOWERS, BBOX, [{"id": "old-query"}])
    assert cache.get(changed_where, BBOX) is MISS


def test_different_bboxes_do_not_collide():
    cache, _ = make_cache()
    cache.put(TOWERS, BBOX, [{"id": "here"}])
    assert cache.get(TOWERS, OTHER_BBOX) is MISS


def test_bbox_rounding_absorbs_float_jitter():
    cache, _ = make_cache()
    cache.put(TOWERS, BBOX, [{"id": "a"}])
    jittered = (BBOX[0] + 1e-9, BBOX[1] - 1e-9, BBOX[2] + 1e-9, BBOX[3] - 1e-9)
    assert cache.get(TOWERS, jittered) == [{"id": "a"}]


def test_bbox_rounding_does_not_merge_distinct_viewports():
    cache, _ = make_cache()
    cache.put(TOWERS, BBOX, [{"id": "a"}])
    shifted = (BBOX[0] + 0.01, BBOX[1], BBOX[2], BBOX[3])
    assert cache.get(TOWERS, shifted) is MISS


def test_cache_is_bounded():
    cache, _ = make_cache(max_entries=4)
    for i in range(10):
        cache.put(TOWERS, (float(i), 0.0, float(i) + 1.0, 1.0), [{"i": i}])
    assert len(cache) == 4


def test_eviction_is_least_recently_used():
    cache, _ = make_cache(max_entries=3)
    a = (0.0, 0.0, 1.0, 1.0)
    b = (10.0, 0.0, 11.0, 1.0)
    c = (20.0, 0.0, 21.0, 1.0)
    d = (30.0, 0.0, 31.0, 1.0)
    cache.put(TOWERS, a, ["a"])
    cache.put(TOWERS, b, ["b"])
    cache.put(TOWERS, c, ["c"])

    cache.get(TOWERS, a)  # a is now the most recently used
    cache.put(TOWERS, d, ["d"])  # evicts the least recently used, b

    assert cache.get(TOWERS, a) == ["a"]
    assert cache.get(TOWERS, b) is MISS
    assert cache.get(TOWERS, c) == ["c"]
    assert cache.get(TOWERS, d) == ["d"]


def test_clear_empties_the_cache():
    cache, _ = make_cache()
    cache.put(TOWERS, BBOX, [{"id": "a"}])
    cache.clear()
    assert len(cache) == 0
    assert cache.get(TOWERS, BBOX) is MISS


def test_pan_away_and_back_hits_within_ttl():
    """The navigation pattern the cache exists for."""
    cache, clock = make_cache()
    cache.put(TOWERS, BBOX, [{"id": "home"}])

    clock.advance(5.0)
    assert cache.get(TOWERS, OTHER_BBOX) is MISS  # panned away: fetch
    cache.put(TOWERS, OTHER_BBOX, [{"id": "away"}])

    clock.advance(5.0)
    assert cache.get(TOWERS, BBOX) == [{"id": "home"}]  # panned back: no fetch
