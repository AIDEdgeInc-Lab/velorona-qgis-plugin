"""Plan limits: the plugin applies only the free plan's limits, from the Map's entitlements.json when present (drift-tested), else built-in."""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import entitlements as E  # noqa: E402

MAP_FILE = os.path.join(os.environ.get("MAP_REPO") or os.path.expanduser("~/velorona-repos/_worktrees/map-sprint2"), "web", "entitlements.json")


@pytest.fixture
def file(tmp_path, monkeypatch):
    def use(data):
        p = tmp_path / "entitlements.json"
        p.write_text(json.dumps(data))
        monkeypatch.setattr(E, "PATH", str(p))
        E._data.cache_clear()
    yield use
    E._data.cache_clear()


def test_free_limits_come_from_the_file(file):
    file({"schema": "velorona.entitlements/1", "plans": {"free": {"limits": {"auto_record_links": 5}}, "pro": {"limits": {"auto_record_links": 100}}}})
    assert E.limit("auto_record_links") == 5 and "copied from Velorona Map" in E.source()


def test_only_the_free_plan_is_ever_read(file):
    file({"schema": "velorona.entitlements/1", "plans": {"pro": {"limits": {"auto_record_links": 100}}}})
    assert E.limit("auto_record_links") == E.FALLBACK_FREE_LIMITS["auto_record_links"]


def test_missing_or_wrong_schema_falls_back_to_the_built_in_free_limits(file, monkeypatch):
    file({"schema": "something/9", "plans": {"free": {"limits": {"auto_record_links": 99}}}})
    assert E.limit("auto_record_links") == 10 and "built-in" in E.source()
    monkeypatch.setattr(E, "PATH", "/nonexistent/entitlements.json")
    E._data.cache_clear()
    assert E.free_limits() == E.FALLBACK_FREE_LIMITS


def test_plugin_copy_equals_the_map_registry_when_present():
    if not os.path.exists(MAP_FILE):
        pytest.skip("no Map checkout with web/entitlements.json")
    assert json.load(open(MAP_FILE, encoding="utf-8")) == json.load(open(E.PATH, encoding="utf-8")), "run tools/sync_from_map.py"


@pytest.mark.skip(reason="PENDING: the Map has not published web/entitlements.json yet (Map sprint2); un-skip when it does")
def test_real_registry_is_the_map_file():
    E._data.cache_clear()
    assert E._data() is not None
