"""Data-pack verification badge (core/packs.py). The Map has not published the `verification` field yet: the shape tests run against a
temporary registry; the test that reads the real copy is marked pending until the Map's packs.json carries the field."""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import packs  # noqa: E402

MAP_PACKS = os.path.join(os.environ.get("MAP_REPO") or os.path.expanduser("~/velorona-repos/_worktrees/map-sprint2"), "web", "data", "packs.json")


@pytest.fixture
def registry(tmp_path, monkeypatch):
    def use(*entries):
        p = tmp_path / "packs.json"
        p.write_text(json.dumps({"schema": "velorona.packs/1", "packs": list(entries)}))
        monkeypatch.setattr(packs, "PATH", str(p))
        packs.registry.cache_clear()
    yield use
    packs.registry.cache_clear()


def pack(**extra):
    return {"id": "ca-ised-fixed", "title": "Canada: ISED Fixed Service sites and links", "generated_date": "2026-09-09", **extra}


def test_each_level_has_its_label_date_and_basis(registry):
    for level, label in packs.LEVELS.items():
        registry(pack(verification={"level": level, "verified_on": "2026-10-30", "basis": "Compared with the ISED extract row by row."}))
        b = packs.badge("ca-ised-fixed", "2026-09-09")
        assert (b.text, b.tooltip, b.level) == (f"Verification: {label} (verified 2026-10-30)", "Compared with the ISED extract row by row.", level)
        assert packs.guide_id(b) == {"source-published": "I-PACK-SOURCE-PUBLISHED", "cross-checked": "I-PACK-CROSS-CHECKED",
                                     "operator-confirmed": "I-PACK-OPERATOR-CONFIRMED"}[level]


def test_flat_shape_is_accepted_too(registry):
    registry(pack(verification="cross-checked", verified_on="2026-10-30", basis="b"))
    assert packs.badge("ca-ised-fixed", None).level == "cross-checked"


def test_no_field_or_unknown_level_states_nothing_and_never_guesses(registry):
    for extra in ({}, {"verification": {"level": "field-verified"}}, {"verification": None}):
        registry(pack(**extra))
        b = packs.badge("ca-ised-fixed", "2026-09-09")
        assert b.level is None and b.text == "Verification: not stated" and packs.guide_id(b) == ""


def test_a_level_does_not_carry_over_to_another_pack_build(registry):
    registry(pack(verification={"level": "operator-confirmed", "verified_on": "2026-10-30", "basis": "b"}))
    b = packs.badge("ca-ised-fixed", "2026-10-15")
    assert b.level is None and "this pack build" in b.text and "2026-10-15" in b.tooltip


def test_unknown_pack_is_not_stated(registry):
    registry(pack())
    assert packs.badge("xx-unknown", None).level is None


def test_every_layer_source_maps_to_a_registered_pack():
    packs.registry.cache_clear()
    assert set(packs.SOURCE_TO_PACK.values()) <= set(packs.registry())


def test_plugin_copy_equals_the_map_registry_when_present():
    if not os.path.exists(MAP_PACKS):
        pytest.skip("no Map checkout")
    assert json.load(open(MAP_PACKS, encoding="utf-8")) == json.load(open(packs.PATH, encoding="utf-8")), "run tools/sync_from_map.py"


def test_real_registry_states_a_level_for_every_pack():
    packs.registry.cache_clear()
    for pid, p in packs.registry().items():
        v = packs.verification(pid)
        assert v is not None and v["verified_on"] and v["basis"], pid
        assert packs.badge(pid, p["generated_date"]).text.startswith("Verification: Source-published"), pid   # today both packs are source-published
