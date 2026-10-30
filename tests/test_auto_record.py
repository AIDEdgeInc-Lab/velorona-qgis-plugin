"""Automatic recording: off by default, capped, interval 15-240 min, per link as in Velorona Map: a busy source doubles that link's wait (up to
8x), three failures in a row stop that link (W-RECORD-STOPPED); forgets everything on stop."""
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import auto_record as A, messages  # noqa: E402


def w(i, public=True):
    return A.Watched(key=(("l", i),), label=f"L{i}", public=public, include_names=False, request={})


def rec(max_links=10):
    return A.Recorder(max_links=max_links, rng=random.Random(1))


def test_off_by_default_and_nothing_is_due():
    r = rec()
    r.add(w(1))
    assert r.enabled is False and r.status_id == A.OFF and not r.due(10 ** 9)


def test_switching_on_makes_every_link_due_at_once_then_every_interval_with_jitter():
    r = rec()
    r.add(w(1))
    r.set_enabled(True, now=1000)
    taken = r.due_links(1000)
    assert [x.label for x in taken] == ["L1"]
    r.hold(taken)
    assert not r.due(1000)                               # held while its fetch runs
    r.link_done(taken[0].key, 1000, ok=True)
    assert not r.due(1000 + 15 * 60 - 1) and r.due(1000 + 15 * 60 + A.JITTER_S)


def test_a_link_added_while_on_is_due_at_once():
    r = rec()
    r.set_enabled(True, now=0)
    r.add(w(1), now=5)
    assert r.due(5)


def test_interval_is_between_15_and_240_min():
    r = rec()
    r.set_interval(5)
    assert r.interval_min == 15
    r.set_interval(1000)
    assert r.interval_min == 240
    r.set_interval(60)
    assert r.interval_min == 60


def test_free_limit_caps_the_links():
    r = rec(max_links=2)
    assert [r.add(w(i)) for i in range(3)] == [A.ADDED, A.ADDED, A.LIMIT] and len(r.links) == 2
    assert r.add(w(0)) == A.ALREADY


def test_busy_doubles_only_that_links_wait_and_three_failures_stop_only_that_link():
    r = rec()
    r.add(w(1)); r.add(w(2))
    r.set_enabled(True, now=0)
    k1, k2 = (("l", 1),), (("l", 2),)
    assert r.link_done(k1, 0, ok=False, busy=True) == A.BUSY and r.links[k1].backoff == 2 and r.links[k2].backoff == 1
    assert r.links[k1].next_due >= 2 * 15 * 60
    assert r.link_done(k1, 0, ok=False, busy=True) == A.BUSY and r.links[k1].backoff == 4
    assert r.link_done(k1, 0, ok=False) == A.STOPPED and r.links[k1].stopped
    assert r.enabled and r.round_finished() == A.STOPPED
    assert [x.key for x in r.due_links(10 ** 9)] == [k2]       # the other link goes on


def test_backoff_is_capped_at_8x_and_a_success_resets_it():
    r = rec()
    r.add(w(1))
    r.set_enabled(True, now=0)
    k = (("l", 1),)
    for _ in range(2):
        r.link_done(k, 0, ok=False, busy=True)
    r.link_done(k, 0, ok=True)
    assert r.links[k].backoff == 1 and r.links[k].failures == 0 and r.round_finished() == A.ON
    r.links[k].backoff = 8
    r.link_done(k, 0, ok=False, busy=True)
    assert r.links[k].backoff == A.MAX_BACKOFF_FACTOR


def test_links_a_round_did_not_reach_wait_one_interval_without_a_failure():
    r = rec()
    r.add(w(1))
    r.set_enabled(True, now=0)
    taken = r.due_links(0)
    r.hold(taken)
    r.skipped(taken, 100)
    assert r.links[(("l", 1),)].failures == 0 and r.links[(("l", 1),)].next_due >= 100 + 15 * 60


def test_switching_on_again_restarts_stopped_links():
    r = rec()
    r.add(w(1))
    r.set_enabled(True, now=0)
    for _ in range(3):
        r.link_done((("l", 1),), 0, ok=False)
    r.set_enabled(True, now=50)
    assert not r.links[(("l", 1),)].stopped and r.due(50)


def test_stop_forgets_everything():
    r = rec()
    r.add(w(1))
    r.set_enabled(True, now=0)
    r.stop()
    assert not r.enabled and not r.links and r.status_id == A.OFF


def test_busy_detection_uses_the_providers_wording():
    assert A.is_busy_failure("the service is rate-limiting requests (HTTP 429); try again in a minute.")
    assert A.is_busy_failure("the service's daily request limit is used up (HTTP 429)")
    assert A.is_busy_failure("the service answered a server error (HTTP 503); try again later.")
    assert not A.is_busy_failure("Could not fetch live weather (Open-Meteo) for: A (timeout) (T3)")


def test_registry_ids_and_wording():
    for mid in (A.OFF, A.ON, A.LIMIT, A.BUSY, A.STOPPED, A.ADDED, A.ALREADY, A.NEEDS_WEATHER):
        assert messages.has(mid), mid
    for mid in (A.ON, A.LIMIT, A.BUSY, A.STOPPED):                 # the Map's own entries, not plugin copies
        assert mid not in messages.PLUGIN_ONLY, mid
    assert messages.text(A.ON, N=3, M=15) == "Recording on: 3 links every 15 min."
    for _, (_, _, text) in messages.PLUGIN_ONLY.items():
        assert "QGIS" not in text and " tab" not in text            # product-neutral, so the Map can register the same words
