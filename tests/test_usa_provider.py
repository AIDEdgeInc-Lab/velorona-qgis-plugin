"""USA pack provider: loading, tile-boundary de-duplication, extent-aware loading, attribution, explicit error states.

No network and no QGIS: packs are built in a temp folder (SYNTHETIC test data, labelled as such -- these are not analysis fixtures) or served by
an injected HTTP getter. One optional test reads a real pack when VELORONA_US_PACK points at one.
"""

import gzip
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.countries import usa  # noqa: E402
from core.countries.base import (PackCorruptError, PackError, PackMissingError, PackNotConfiguredError,  # noqa: E402
                                 PackUnavailableError, PackVersionError, ViewTooLargeError)
from core.validation import NoDataError  # noqa: E402

from usa_pack_builder import ATTRIBUTION, L1, L2, S_FAR, S_HIGH, S_LOW, index, link, site, tiles, write_pack  # noqa: E402,F401


@pytest.fixture
def pack(tmp_path):
    return write_pack(tmp_path)


class Counting:
    """Wraps a fetcher and records every relative path read."""
    def __init__(self, inner):
        self.inner, self.paths, self.label = inner, [], inner.label

    def fetch(self, rel, limit):
        self.paths.append(rel)
        return self.inner.fetch(rel, limit)


def provider(path, **kw):
    return usa.UsaPackProvider(path, fetcher=Counting(usa.make_fetcher(path)), **kw)


# --- loading ----------------------------------------------------------------------------------------------------------------------
def test_loads_records_in_the_plugin_record_shape(pack):
    r = provider(pack).load_bbox((-106.0, 40.0, -105.0, 40.9))
    link_rec = next(x for x in r.links if x["id"] == "fcc-link-1-1")
    assert link_rec["authorization_number"] == "WAAA001-1"
    assert link_rec["source"] == usa.SOURCE_FCC_ULS and link_rec["country"] == "US"
    assert link_rec["frequencies_mhz"] == "11245, 6078.625"            # MHz as published; integer-valued floats printed without ".0"
    assert link_rec["site_a"]["latitude"] == 40.5 and link_rec["site_b"]["latitude"] == 41.5
    assert link_rec["call_sign"] == "WAAA001" and link_rec["expiration_date"] == "2031-02-01"
    assert {"id", "latitude", "longitude", "source", "licensee", "province"} <= set(link_rec["site_a"])


def test_site_frequencies_are_the_union_over_loaded_links(pack):
    r = provider(pack).load_bbox((-106.0, 40.0, -105.0, 40.9))
    s = next(x for x in r.sites if x["id"] == S_LOW["i"])
    assert s["frequencies_mhz"] == "6078.625, 11245, 18700"


def test_attribution_carries_source_dates_and_the_not_a_measurement_statement(pack):
    a = provider(pack).attribution()
    assert a.attribution_text == ATTRIBUTION
    assert a.source_file_updated == "2026-09-27" and a.pack_generated == "2026-10-03"
    line = a.one_line()
    assert "Federal Communications Commission" in line and "2026-09-27" in line and "not a field measurement" in line


# --- tile-boundary de-duplication ---------------------------------------------------------------------------------------------------
def test_link_straddling_a_tile_edge_is_returned_once(pack):
    r = provider(pack).load_bbox((-106.0, 40.0, -105.0, 42.0))        # touches both the 40 and the 41 tile
    ids = [x["id"] for x in r.links]
    assert sorted(ids) == ["fcc-link-1-1", "fcc-link-2-1"] and len(ids) == len(set(ids))
    assert r.duplicate_links_dropped == 1
    assert r.duplicate_sites_dropped == 2          # S_LOW and S_HIGH appear in both tiles
    assert len({x["id"] for x in r.sites}) == len(r.sites) == 3


def test_deduplicated_endpoints_are_the_same_site_objects_the_sites_list_holds(pack):
    r = provider(pack).load_bbox((-106.0, 40.0, -105.0, 42.0))
    by_id = {s["id"]: s for s in r.sites}
    for lk in r.links:
        assert by_id[lk["site_a"]["id"]] is lk["site_a"] and by_id[lk["site_b"]["id"]] is lk["site_b"]


# --- extent-aware loading ---------------------------------------------------------------------------------------------------------
def test_only_tiles_touching_the_extent_are_read(pack):
    p = provider(pack)
    p.load_bbox((-105.9, 40.1, -105.1, 40.9))
    tile_reads = [x for x in p._fetcher.paths if x.startswith("tiles/")]
    assert tile_reads == ["tiles/40_-106.json.gz"]


def test_estimate_needs_no_tile_download(pack):
    p = provider(pack)
    assert p.estimate((-106.0, 40.0, -105.0, 42.0)) == (2, 3)          # upper bound counts the straddling link in both tiles
    assert [x for x in p._fetcher.paths if x.startswith("tiles/")] == []


def test_second_load_of_the_same_extent_is_served_from_memory(pack):
    p = provider(pack)
    first = p.load_bbox((-106.0, 40.0, -105.0, 40.9))
    second = p.load_bbox((-106.0, 40.0, -105.0, 40.9))
    assert first.tiles_fetched == 1 and second.tiles_fetched == 0
    assert len([x for x in p._fetcher.paths if x.startswith("tiles/")]) == 1


def test_tile_cache_is_bounded(pack):
    p = provider(pack, cache_size=1)
    p.load_bbox((-106.0, 40.0, -105.0, 40.9))
    p.load_bbox((10.0, 10.0, 11.0, 11.0))
    assert len(p._cache) == 1 and list(p._cache) == ["10_10"]


def test_extent_over_the_budget_is_refused_before_any_tile_is_fetched(pack):
    p = provider(pack, max_links=2)
    with pytest.raises(ViewTooLargeError) as exc:
        p.load_bbox((-106.0, 40.0, -105.0, 42.0))
    assert "Zoom in" in str(exc.value) and "3" in str(exc.value)
    assert [x for x in p._fetcher.paths if x.startswith("tiles/")] == []
    with pytest.raises(ViewTooLargeError):
        provider(pack, max_tiles=1).load_bbox((-106.0, 40.0, -105.0, 42.0))


def test_extent_with_no_tiles_is_an_empty_result_not_an_error(pack):
    r = provider(pack).load_bbox((100.0, 0.0, 101.0, 1.0))
    assert r.links == [] and r.sites == [] and r.tiles_requested == 0


def test_extent_is_clamped_and_validated(pack):
    p = provider(pack)
    assert sorted(p.tile_keys((-200.0, -95.0, 200.0, 95.0))) == ["10_10", "40_-106", "41_-106"]
    for bad in [(1, 2, 0, 3), (0, 3, 1, 2), (float("nan"), 0, 1, 1), (0, 0, 1)]:
        with pytest.raises(PackError):
            p.tile_keys(bad)


# --- explicit error states (never silent NO DATA) --------------------------------------------------------------------------------
def test_no_source_configured():
    with pytest.raises(PackNotConfiguredError) as exc:
        usa.UsaPackProvider("")
    assert "No USA data pack is configured" in str(exc.value)


def test_missing_folder(tmp_path):
    with pytest.raises(PackMissingError) as exc:
        usa.UsaPackProvider(str(tmp_path / "nope"))
    assert "does not exist" in str(exc.value)


def test_missing_index(tmp_path):
    with pytest.raises(PackMissingError) as exc:
        usa.UsaPackProvider(str(tmp_path)).index()
    assert "index.json" in str(exc.value)


def test_missing_tile_named_in_the_message(tmp_path):
    root = write_pack(tmp_path)
    os.remove(os.path.join(root, "tiles", "40_-106.json.gz"))
    with pytest.raises(PackMissingError) as exc:
        provider(root).load_bbox((-106.0, 40.0, -105.0, 40.9))
    assert "40_-106" in str(exc.value)


def test_corrupt_gzip_tile(tmp_path):
    root = write_pack(tmp_path)
    with open(os.path.join(root, "tiles", "40_-106.json.gz"), "wb") as fh:
        fh.write(b"\x1f\x8b\x08\x00garbage-not-gzip")
    with pytest.raises(PackCorruptError) as exc:
        provider(root).load_bbox((-106.0, 40.0, -105.0, 40.9))
    assert "40_-106" in str(exc.value) and "corrupt" in str(exc.value)


def test_tile_that_is_not_json(tmp_path):
    root = write_pack(tmp_path)
    with open(os.path.join(root, "tiles", "40_-106.json.gz"), "wb") as fh:
        fh.write(gzip.compress(b"{not json"))
    with pytest.raises(PackCorruptError):
        provider(root).load_bbox((-106.0, 40.0, -105.0, 40.9))


def test_tile_with_a_link_pointing_at_a_missing_site_slot(tmp_path):
    bad = tiles()
    bad["40_-106"]["links"][0]["b"] = 99
    root = write_pack(tmp_path, bad)
    with pytest.raises(PackCorruptError) as exc:
        provider(root).load_bbox((-106.0, 40.0, -105.0, 40.9))
    assert "invalid link record" in str(exc.value)


def test_tile_with_an_impossible_coordinate(tmp_path):
    bad = tiles()
    bad["40_-106"]["sites"][0]["la"] = 123.0
    root = write_pack(tmp_path, bad)
    with pytest.raises(PackCorruptError):
        provider(root).load_bbox((-106.0, 40.0, -105.0, 40.9))


def test_oversized_tile_is_refused(tmp_path, monkeypatch):
    root = write_pack(tmp_path)
    monkeypatch.setattr(usa, "MAX_TILE_BYTES", 10)
    with pytest.raises(PackCorruptError):
        usa.UsaPackProvider(root).load_bbox((-106.0, 40.0, -105.0, 40.9))


def test_index_that_is_not_a_us_pack(tmp_path):
    root = write_pack(tmp_path, idx=index(tiles(), pack="something-else"))
    with pytest.raises(PackCorruptError) as exc:
        provider(root).index()
    assert "not a Velorona USA pack" in str(exc.value)


@pytest.mark.parametrize("schema", ["velorona.us-fcc-uls-micro/2", "velorona.us-fcc-uls-micro/10"])
def test_newer_schema_is_a_version_error(tmp_path, schema):
    root = write_pack(tmp_path, idx=index(tiles(), schema=schema))
    with pytest.raises(PackVersionError) as exc:
        provider(root).index()
    assert schema in str(exc.value) and "Update the plugin" in str(exc.value)


def test_unrecognisable_schema_string_is_a_version_error(tmp_path):
    root = write_pack(tmp_path, idx=index(tiles(), schema="v1"))
    with pytest.raises(PackVersionError):
        provider(root).index()


def test_other_tile_size_is_a_version_error(tmp_path):
    root = write_pack(tmp_path, idx=index(tiles(), tile_degrees=2))
    with pytest.raises(PackVersionError):
        provider(root).index()


@pytest.mark.parametrize("missing", ["attribution", "source_file_updated", "generated_date"])
def test_pack_that_cannot_say_where_its_data_came_from_is_refused(tmp_path, missing):
    idx = index(tiles())
    del idx[missing]
    root = write_pack(tmp_path, idx=idx)
    with pytest.raises(PackCorruptError) as exc:
        provider(root).index()
    assert missing in str(exc.value)


def test_index_with_a_path_traversal_tile_key_is_refused(tmp_path):
    idx = index(tiles())
    idx["tiles"]["../../etc/passwd"] = [1, 1]
    root = write_pack(tmp_path, idx=idx)
    with pytest.raises(PackCorruptError):
        provider(root).index()


def test_pack_errors_are_not_no_data():
    """Owner rule: NO DATA only through explicit validation at the analysis boundary. A pack problem must never look like a per-link NO DATA."""
    for cls in (PackCorruptError, PackMissingError, PackNotConfiguredError, PackUnavailableError, PackVersionError, ViewTooLargeError):
        assert issubclass(cls, PackError) and not issubclass(cls, NoDataError)


# --- URL sources (injected getter: no network) -----------------------------------------------------------------------------------
class Resp:
    def __init__(self, status, body=b""):
        self.status_code, self.content = status, body


def getter_for(pack_root, log=None, status_override=None):
    def get(url, timeout=None, **kw):
        if log is not None:
            log.append(url)
        if status_override:
            return Resp(status_override)
        rel = url.split("pack/", 1)[1]
        path = os.path.join(pack_root, rel)
        return Resp(200, open(path, "rb").read()) if os.path.exists(path) else Resp(404)
    return get


def test_url_source_loads_through_the_getter(pack):
    log = []
    p = usa.UsaPackProvider("https://example.invalid/pack", get=getter_for(pack, log))
    r = p.load_bbox((-106.0, 40.0, -105.0, 40.9))
    assert len(r.links) == 2
    assert log[0] == "https://example.invalid/pack/index.json" and log[1].endswith("/tiles/40_-106.json.gz")


def test_url_404_is_missing_not_unavailable(pack):
    p = usa.UsaPackProvider("https://example.invalid/pack", get=getter_for(pack))
    os.remove(os.path.join(pack, "tiles", "40_-106.json.gz"))
    with pytest.raises(PackMissingError):
        p.load_bbox((-106.0, 40.0, -105.0, 40.9))


def test_url_server_error_and_transport_error_are_unavailable(pack):
    with pytest.raises(PackUnavailableError) as exc:
        usa.UsaPackProvider("https://example.invalid/pack", get=getter_for(pack, status_override=503)).index()
    assert "503" in str(exc.value)

    def boom(url, timeout=None, **kw):
        raise ConnectionError("timed out")
    with pytest.raises(PackUnavailableError) as exc:
        usa.UsaPackProvider("https://example.invalid/pack", get=boom).index()
    assert "timed out" in str(exc.value)


def test_rate_limit_is_unavailable_and_never_a_status(pack):
    with pytest.raises(PackUnavailableError):
        usa.UsaPackProvider("https://example.invalid/pack", get=getter_for(pack, status_override=429)).index()


def test_plain_http_is_refused_except_for_localhost(pack):
    with pytest.raises(PackNotConfiguredError):
        usa.make_fetcher("http://example.invalid/pack")
    assert usa.make_fetcher("http://localhost:8000/pack").label.startswith("http://localhost")
    with pytest.raises(PackNotConfiguredError):
        usa.make_fetcher("ftp://example.invalid/pack")


def test_file_url_source(pack):
    assert usa.UsaPackProvider("file://" + pack).index().link_count == 3


# --- optional: the real pack -----------------------------------------------------------------------------------------------------
@pytest.mark.skipif(not os.environ.get("VELORONA_US_PACK"), reason="set VELORONA_US_PACK to the real pack folder (e.g. the Map repo's web/data/us)")
def test_real_pack_dedup_matches_the_index():
    p = usa.UsaPackProvider(os.environ["VELORONA_US_PACK"])
    idx = p.index()
    bbox = (-119.0, 34.0, -117.0, 35.0)                        # Los Angeles basin, the densest tiles
    r = p.load_bbox(bbox)
    assert len(r.links) == len({lk["id"] for lk in r.links})
    assert len(r.links) + r.duplicate_links_dropped == sum(idx.tiles[k][1] for k in p.tile_keys(bbox))
    assert all(lk["site_a"]["id"] != lk["site_b"]["id"] for lk in r.links)


# --- regional extract (velorona.usa-extract/1): carries FCC antenna heights ---------------------------------------------------------------------
from usa_pack_builder import extract, write_extract  # noqa: E402


def test_extract_loads_records_but_ignores_fcc_heights(tmp_path):
    """FCC 'Height to Center RAAT' has no stated unit/reference (Map HEIGHTS_CONTRACT.md section 2): the extract's values are NOT used, every US height stays the Assumed default."""
    p = usa.make_provider(write_extract(str(tmp_path)))
    assert isinstance(p, usa.UsaExtractProvider)
    r = p.load_bbox((-79.0, 42.0, -76.0, 44.0))
    one = next(x for x in r.links if x["id"] == "fcc-link-1-1")
    assert one["authorization_number"] == "WAAA001-1" and one["frequencies_mhz"] == "11245, 6078.625"
    assert one["site_a_height_m"] is None and one["site_b_height_m"] is None and one["height_source"] is None
    assert one["attribution"] == ATTRIBUTION and one["country"] == "US"
    assert all(x["site_a_height_m"] is None and x["site_b_height_m"] is None for x in r.links)


def test_extract_view_filter_and_budget(tmp_path):
    path = write_extract(str(tmp_path))
    assert [x["id"] for x in usa.make_provider(path).load_bbox((-78.1, 42.9, -77.95, 43.05)).links] == ["fcc-link-1-1"]
    assert usa.make_provider(path).load_bbox((100.0, 0.0, 101.0, 1.0)).links == []
    with pytest.raises(ViewTooLargeError):
        usa.UsaExtractProvider(path, max_links=1).load_bbox((-79.0, 42.0, -76.0, 44.0))


def test_extract_nature_and_dates_come_from_the_extract(tmp_path):
    a = usa.make_provider(write_extract(str(tmp_path))).attribution()
    assert a.nature == "Licensee-reported record data from a public record; not a field measurement."
    assert a.source_file_updated == "2026-09-27" and a.pack_generated == "2026-10-03"


def test_pack_nature_comes_from_the_pack_licence_block(tmp_path):
    idx = index(tiles())
    idx["licence"] = {"nature": "Licensee-reported record data from a public record; not a field measurement."}
    assert usa.UsaPackProvider(write_pack(str(tmp_path), idx=idx)).attribution().nature.startswith("Licensee-reported record data from a public record")


def test_extract_errors_are_pack_errors(tmp_path):
    with pytest.raises(PackMissingError):
        usa.make_provider(str(tmp_path / "nope.json"))
    with pytest.raises(PackVersionError):
        usa.make_provider(write_extract(str(tmp_path), {**extract(), "schema": "velorona.usa-extract/2"})).load_bbox((0, 0, 1, 1))
    bad = extract()
    bad["links"][0]["site_b"] = "fcc-site-missing"
    with pytest.raises(PackCorruptError):
        usa.make_provider(write_extract(str(tmp_path), bad, "b.json")).load_bbox((0, 0, 1, 1))
    dup = extract()
    dup["links"][1]["id"] = dup["links"][0]["id"]
    with pytest.raises(PackCorruptError):
        usa.make_provider(write_extract(str(tmp_path), dup, "d.json")).load_bbox((0, 0, 1, 1))
    nometa = extract()
    del nometa["meta"]["attribution"]
    with pytest.raises(PackCorruptError):
        usa.make_provider(write_extract(str(tmp_path), nometa, "m.json")).load_bbox((0, 0, 1, 1))
    with open(tmp_path / "junk.json", "w") as fh:
        fh.write("{nope")
    with pytest.raises(PackCorruptError):
        usa.make_provider(str(tmp_path / "junk.json")).load_bbox((0, 0, 1, 1))


@pytest.mark.skipif(not os.environ.get("VELORONA_US_EXTRACT"), reason="set VELORONA_US_EXTRACT to the Map's parity/contract/usa/usa_extract_wny.json")
def test_real_extract_loads_whole_with_contract_counts():
    p = usa.make_provider(os.environ["VELORONA_US_EXTRACT"])
    r = p.load_bbox((-80.0, 42.0, -77.0, 44.0))
    assert len(r.links) == 1403 and len(r.sites) == 892                                    # contract section 4
    assert all(x["site_a_height_m"] is None for x in r.links)


def test_https_pack_that_redirects_to_plain_http_is_refused(pack):
    class R(Resp):
        url = "http://evil.example/pack/index.json"

    with pytest.raises(PackUnavailableError) as exc:
        usa.UsaPackProvider("https://example.invalid/pack", get=lambda url, timeout=None, **kw: R(200, b"{}")).index()
    assert "non-https" in str(exc.value)


def test_streamed_download_is_cut_off_at_the_size_guard():
    class Big(Resp):
        def iter_content(self, chunk_size=0):
            for _ in range(1000):
                yield b"x" * 65536
    read = []

    class Counting2(Big):
        def iter_content(self, chunk_size=0):
            for c in super().iter_content(chunk_size):
                read.append(len(c))
                yield c

    with pytest.raises(PackCorruptError):
        usa.UsaPackProvider("https://example.invalid/pack", get=lambda url, timeout=None, **kw: Counting2(200)).index()
    assert sum(read) < 5 * 1024 * 1024                 # stopped just past the 4 MiB index guard, not 64 MB
