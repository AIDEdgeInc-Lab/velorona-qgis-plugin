"""The plugin's copy of the Map message registry: well-formed, every ID the code uses exists, and (when a Map checkout is present) it is the Map's file."""
import json
import os
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT.parent) if False else str(ROOT))

from core import messages  # noqa: E402

_USED = re.compile(r"""["']([EWI]-[A-Z0-9]+(?:-[A-Z0-9]+)+)["']""")


def test_registry_is_well_formed():
    reg = messages.registry()
    assert len(reg) >= 67
    for mid, m in reg.items():
        assert messages.is_message_id(mid) and m["level"] == {"E": "error", "W": "warn", "I": "info"}[mid[0]], mid
        assert m["short_text"].strip(), mid


def test_every_id_used_in_the_code_is_in_the_registry():
    used = {}
    for f in list(ROOT.glob("*.py")) + list((ROOT / "core").rglob("*.py")) + list((ROOT / "ui").rglob("*.py")):
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            for mid in _USED.findall(line):
                used.setdefault(mid, f"{f.relative_to(ROOT)}:{n}")
    missing = {k: v for k, v in used.items() if not messages.has(k)}
    assert used and not missing, missing


def test_text_fills_the_registry_placeholders():
    assert messages.text("I-SELECT-SITES", N=3) == "3 sites are selected, but path clearance and weather exposure use exactly two."
    assert messages.text("I-EXPORT-DONE", file="a.csv") == "Exported a.csv."
    assert messages.text("E-SATELLITE-DOWN", reason="timeout") == "Satellite data unavailable -- timeout"


def test_plugin_copy_equals_the_map_registry_when_a_map_checkout_is_present():
    path = os.environ.get("MAP_MESSAGES") or os.path.expanduser("~/velorona-repos/_worktrees/map-p0-20261029/web/messages.json")
    if not os.path.exists(path):
        import pytest
        pytest.skip("no Map checkout")
    theirs = {m["id"]: m for m in json.load(open(path, encoding="utf-8"))["messages"]}
    ours = {m["id"]: m for m in json.load(open(messages.PATH, encoding="utf-8"))["messages"]}
    drift = [i for i in theirs if i in ours and (theirs[i]["short_text"], theirs[i]["level"]) != (ours[i]["short_text"], ours[i]["level"])]
    assert not drift, f"core/messages.json drifted from the Map for {drift}; run tools/sync_messages.py"
    for mid, (level, _, text) in messages.PLUGIN_ONLY.items():
        if mid in theirs:
            assert (theirs[mid]["short_text"], theirs[mid]["level"]) == (text, level), f"{mid}: the Map's entry differs from PLUGIN_ONLY; align one"


# --- the plugin's own texts for situations the Map also has: same ID, same short_text ------------------------------------------------------

def test_path_and_input_reasons_are_the_registrys_text_and_resolve_to_its_ids():
    from core import validation as V
    assert V.path_reasons(91, 0, 0, 0) == [messages.short_text("E-PATH-COORDINATES")]
    assert V.path_reasons(44, -79, 44, -79) == [messages.short_text("E-PATH-ZERO-LENGTH")]
    assert V.interval_reason(None) == messages.short_text("E-WEATHER-INTERVAL")
    reasons = V.terrain_input_reasons(44, -79, 45, -80, 2000, 30, 11)
    assert len(reasons) == 1 and reasons[0].startswith("record antenna height at Site A (2000 m) is outside 0.1-1000 m (R5)")
    # (the Map's own pattern order resolves the height text to E-TERRAIN-VALUE-MISSING: reported to the Map agent, see CHANGES.md)
    for reason, expected in ((V.path_reasons(91, 0, 0, 0)[0], "E-PATH-COORDINATES"),
                             (V.path_reasons(44, -79, 44, -79)[0], "E-PATH-ZERO-LENGTH"), ("elevation request failed (T1): HTTP 503", "E-TERRAIN-SERVICE-FAILED"),
                             (messages.short_text("E-TERRAIN-SERVICE-BAD-REPLY"), "E-TERRAIN-SERVICE-BAD-REPLY"),
                             ("Could not fetch live weather (Open-Meteo) for: A (x) (T3)", "E-WEATHER-FETCH-FAILED"), ("frequency outside 1-100 GHz", "E-WEATHER-PARAMS")):
        assert messages.id_for_reason(reason) == expected, reason


def test_elevation_failures_use_the_maps_wording():
    from core import elevation_source as E
    assert E.request_failed("HTTP 503") == "elevation request failed (T1): HTTP 503"
    assert E.bad_reply(ValueError("returned 3 values for 5 requested points")) == messages.short_text("E-TERRAIN-SERVICE-BAD-REPLY")
    assert E.bad_reply(ValueError("returned a missing or non-numeric elevation")) == "the elevation service returned a missing or non-numeric value (R5)"

