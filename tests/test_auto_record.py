"""Automatic recording: off by default, capped, one interval of at least 15 min, backs off on 429, pauses after 3 busy rounds, forgets on stop."""
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


def test_switching_on_runs_a_round_at_once_then_every_interval_with_jitter():
    r = rec()
    r.add(w(1))
    r.set_enabled(True, now=1000)
    assert r.due(1000)
    r.finish_round(1000, busy=False)
    assert not r.due(1000 + 15 * 60 - 1) and r.due(1000 + 15 * 60 + A.JITTER_S)


def test_interval_is_never_below_15_min():
    r = rec()
    r.set_interval(5)
    assert r.interval_min == 15
    r.set_interval(60)
    assert r.interval_min == 60


def test_free_limit_caps_the_links():
    r = rec(max_links=2)
    assert [r.add(w(i)) for i in range(3)] == [A.ADDED, A.ADDED, A.LIMIT] and len(r.links) == 2
    assert r.add(w(0)) == A.ALREADY


def test_busy_doubles_the_wait_and_three_busy_rounds_pause():
    r = rec()
    r.add(w(1))
    r.set_enabled(True, now=0)
    assert r.finish_round(0, busy=True) == A.BUSY and r.backoff == 2
    assert r.next_due >= 2 * 15 * 60
    assert r.finish_round(0, busy=True) == A.BUSY and r.backoff == 4
    assert r.finish_round(0, busy=True) == A.PAUSED and not r.enabled and not r.due(10 ** 9)


def test_a_good_round_resets_the_backoff():
    r = rec()
    r.add(w(1))
    r.set_enabled(True, now=0)
    r.finish_round(0, busy=True)
    assert r.finish_round(0, busy=False) == A.ON and r.backoff == 1 and r.busy_rounds == 0


def test_stop_forgets_everything():
    r = rec()
    r.add(w(1))
    r.set_enabled(True, now=0)
    r.stop()
    assert not r.enabled and not r.links and r.status_id == A.OFF


def test_busy_detection_uses_the_providers_wording():
    assert A.is_busy_failure("the service is rate-limiting requests (HTTP 429); try again in a minute.")
    assert A.is_busy_failure("the service's daily request limit is used up (HTTP 429)")
    assert not A.is_busy_failure("Could not fetch live weather (Open-Meteo) for: A (timeout) (T3)")


def test_every_status_has_a_registry_message():
    for mid in (A.OFF, A.ON, A.LIMIT, A.BUSY, A.PAUSED, A.ADDED, A.ALREADY, A.NEEDS_WEATHER):
        assert messages.has(mid), mid
    assert messages.text(A.ON, N=3, M=15) == "Recording 3 links every 15 min while QGIS is open. Values stay on this computer."
