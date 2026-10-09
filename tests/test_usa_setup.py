"""USA data setup logic (core/countries/usa_setup.py): every state the guided dialog can show.
SYNTHETIC packs (tests/usa_pack_builder.py). No network, no QGIS."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.countries import usa_setup as U  # noqa: E402
from usa_pack_builder import index, tiles, write_pack  # noqa: E402


@pytest.fixture
def pack(tmp_path):
    return write_pack(tmp_path / "pack")


def test_empty_source_is_not_configured_and_says_what_to_do():
    for text in ("", "   ", None):
        r = U.check_source(text)
        assert r.state == U.NOT_CONFIGURED and not r.ok and "Choose a folder" in r.next_step


def test_valid_local_pack_is_ready_with_the_packs_own_count_and_dates(pack):
    r = U.check_source(pack)
    assert r.ok and r.state == U.LOADED and r.link_count == 3 and r.source_date == "2026-09-27" and r.pack_date == "2026-10-03"
    assert "3 US links" in r.message and "2026-09-27" in r.message and r.next_step == ""


def test_count_comes_from_the_pack_not_from_the_checker(tmp_path):
    idx = index(tiles())
    idx["counts"] = {"links": 250874}
    r = U.check_source(write_pack(tmp_path / "p", idx=idx))
    assert r.link_count == 250874 and "250,874 US links" in r.message


def test_missing_folder(tmp_path):
    r = U.check_source(str(tmp_path / "nope"))
    assert r.state == U.ERROR and "doesn't exist" in r.message and r.next_step and r.link_count is None


def test_folder_without_index_json(tmp_path):
    (tmp_path / "empty").mkdir()
    r = U.check_source(str(tmp_path / "empty"))
    assert r.state == U.ERROR and "index.json was not found" in r.message and "directly contains index.json" in r.next_step


def test_choosing_the_parent_of_the_pack_finds_it(tmp_path):
    inner = write_pack(tmp_path / "data" / "us")
    r = U.check_source(str(tmp_path / "data"))
    assert r.ok and r.source == inner and "'us' folder inside the folder you chose" in r.note


def test_ambiguous_parent_is_not_guessed(tmp_path):
    write_pack(tmp_path / "data" / "a")
    write_pack(tmp_path / "data" / "b")
    r = U.check_source(str(tmp_path / "data"))
    assert r.state == U.ERROR and r.source == str(tmp_path / "data")


def test_typing_index_json_or_quotes_is_forgiven(pack):
    for text in (pack + "/index.json", f'"{pack}"', f"  {pack}  ", "file://" + pack):
        assert U.check_source(text).ok, text
    assert "trailing 'index.json'" in U.check_source(pack + "/index.json").note


def test_damaged_tile_is_found_even_though_the_index_is_fine(tmp_path):
    root = write_pack(tmp_path / "p")
    for name in os.listdir(os.path.join(root, "tiles")):
        with open(os.path.join(root, "tiles", name), "wb") as fh:
            fh.write(b"\x1f\x8b\x08garbage")
    r = U.check_source(root)
    assert r.state == U.ERROR and "damaged" in r.message and "Download the pack again" in r.next_step


def test_missing_tile_is_reported_as_an_incomplete_pack(tmp_path):
    root = write_pack(tmp_path / "p")
    for name in os.listdir(os.path.join(root, "tiles")):
        os.remove(os.path.join(root, "tiles", name))
    r = U.check_source(root)
    assert r.state == U.ERROR and "incomplete" in r.message


def test_malformed_index(tmp_path):
    root = tmp_path / "p"
    root.mkdir()
    (root / "index.json").write_text("{nope")
    r = U.check_source(str(root))
    assert r.state == U.ERROR and "damaged" in r.message


def test_newer_schema_says_update_or_use_another_pack(tmp_path):
    r = U.check_source(write_pack(tmp_path / "p", idx=index(tiles(), schema="velorona.us-fcc-uls-micro/2")))
    assert r.state == U.ERROR and "different version" in r.message and "Update Velorona" in r.next_step


def test_not_a_us_pack_at_all(tmp_path):
    r = U.check_source(write_pack(tmp_path / "p", idx=index(tiles(), pack="something-else")))
    assert r.state == U.ERROR and r.link_count is None


# --- web addresses (injected getter; no network) ---------------------------------------------------------------------------------------
class Resp:
    def __init__(self, status, body=b""):
        self.status_code, self.content = status, body


def server(pack_root, status=None):
    def get(url, timeout=None, **kw):
        if status:
            return Resp(status)
        rel = url.split("/pack/", 1)[1]
        path = os.path.join(pack_root, rel)
        return Resp(200, open(path, "rb").read()) if os.path.exists(path) else Resp(404)
    return get


def test_valid_https_address(pack):
    r = U.check_source("https://example.invalid/pack/", get=server(pack))
    assert r.ok and r.link_count == 3 and r.source == "https://example.invalid/pack/"


def test_plain_http_is_refused_with_a_clear_reason():
    r = U.check_source("http://example.invalid/pack/")
    assert r.state == U.ERROR and "https://" in r.message


def test_address_that_is_not_a_pack_404(pack):
    r = U.check_source("https://example.invalid/pack/", get=server(pack, 404))
    assert r.state == U.ERROR and "index.json was not found" in r.message


def test_unreachable_server_and_rate_limit_are_connection_problems_not_data_problems(pack):
    for status in (503, 429):
        r = U.check_source("https://example.invalid/pack/", get=server(pack, status))
        assert r.state == U.ERROR and "couldn't reach" in r.message and "try again" in r.next_step.lower()

    def boom(url, timeout=None, **kw):
        raise ConnectionError("timed out")
    r = U.check_source("https://example.invalid/pack/", get=boom)
    assert r.state == U.ERROR and "couldn't reach" in r.message


def test_check_never_raises_for_data_problems(tmp_path):
    for bad in ("\x00", "ftp://x/y", "https://", "/definitely/not/here", str(tmp_path)):
        assert U.check_source(bad).state in (U.ERROR, U.NOT_CONFIGURED)


def test_help_text_is_honest_and_actionable():
    h = U.help_html()
    for needle in ("not included in the plugin", "Canada works without it", "Use Velorona's online USA data", U.VELORONA_ONLINE_PACK, "index.json", "tiles",
                   "assumed to be 30", "licensee-reported", "20,000"):
        assert needle in h, needle
    assert "RAAT" not in h                       # no invented FCC height semantics


def test_help_links_are_present_and_escaped_for_html(monkeypatch):
    h = U.help_html()
    assert f'<code>{U.VELORONA_ONLINE_PACK}</code>' in h and f'<a href="{U.HELP_DOC}">Full guide (docs/USA.md)</a>' in h
    assert "${" not in h and "$online_pack" not in h
    monkeypatch.setattr(U, "HELP_DOC", 'https://x.test/a?b=1&c="2"<script>')
    out = U.help_html()
    assert '<a href="https://x.test/a?b=1&amp;c=&quot;2&quot;&lt;script&gt;">' in out and "<script>" not in out
