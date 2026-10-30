"""Guide links: the address is the guide page plus the message ID, and only well-formed IDs become anchors. Pure stdlib."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import guide  # noqa: E402


def test_guide_url_has_the_message_id_as_anchor():
    assert guide.guide_url("I-terrain-elevation-source") == "https://map.velorona.ai/guide#I-terrain-elevation-source"
    assert guide.guide_url() == "https://map.velorona.ai/guide"


def test_malformed_ids_open_the_top_of_the_guide():
    for bad in ("", "terrain", "X-terrain-thing", "I-terrain", "I-Terrain-Thing", "I-terrain thing", "I-a-b#c", None):
        assert guide.guide_url(bad) == guide.GUIDE_URL, bad


def test_every_plugin_message_id_is_well_formed_and_a_single_short_line():
    for mid, line in guide.PLUGIN_MESSAGE_IDS.items():
        assert guide.is_message_id(mid), mid
        assert line and "\n" not in line and len(line) <= 110, mid
