"""Guide links: the address is the guide page plus the registry's message ID; only IDs the registry knows become anchors. Pure stdlib."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import guide, messages  # noqa: E402


def test_guide_url_has_the_registry_id_as_anchor():
    assert guide.guide_url("I-TERRAIN-ELEVATION-SOURCE") == "https://map.velorona.ai/guide#I-TERRAIN-ELEVATION-SOURCE"
    assert guide.guide_url("E-TERRAIN-SERVICE-FAILED") == "https://map.velorona.ai/guide#E-TERRAIN-SERVICE-FAILED"
    assert guide.guide_url() == "https://map.velorona.ai/guide"


def test_unknown_or_malformed_ids_open_the_top_of_the_guide():
    for bad in ("", "terrain", "X-TERRAIN-THING", "I-TERRAIN", "I-terrain-elevation-source", "I-NO-SUCH-MESSAGE", "I-A-B#C", None):
        assert guide.guide_url(bad) == guide.GUIDE_URL, bad


def test_plugin_only_messages_are_one_short_line():
    for mid, (_, _, line) in messages.PLUGIN_ONLY.items():
        assert messages.is_message_id(mid) and "\n" not in line and len(line) <= 110, mid


def test_get_updates_opens_the_sign_up_page_and_sends_nothing():
    assert guide.JOIN_URL == "https://map.velorona.ai/join"
    src = open(guide.__file__, encoding="utf-8").read()
    assert "requests" not in src and "urllib" not in src and "http.client" not in src      # the browser opens the page; the plugin makes no request
