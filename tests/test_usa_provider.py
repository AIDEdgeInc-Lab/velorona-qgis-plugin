"""USA pack provider: loading, tile-boundary de-duplication, extent-aware loading, attribution, explicit error states.

No network and no QGIS: packs are built in a temp folder (SYNTHETIC test data, labelled as such -- these are not analysis fixtures) or served by
an injected HTTP getter. One optional test reads a real pack when VELORONA_US_PACK points at one.
"""

import copy
import gzip
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.countries import usa  # noqa: E402
from core.countries.base import (PackCorruptError, PackError, PackMissingError, PackNotConfiguredError,  # noqa: E402
                                 PackUnavailableError, PackVersionError, ViewTooLargeError)
from core.validation import NoDataError  # noqa: E402

ATTRIBUTION = ("Source: U.S. Federal Communications Commission, Universal Licensing System (ULS) public access database, microwave "
               "services (l_micro). Data as published; not endorsed by the FCC.")


def site(lat, lon, call, name=""):
    return {"i": f"fcc-site-{lat:.5f},{lon:.5f}", "la": lat, "lo": lon, "n": name, "c": [call], "s": "CO", "l": ["Test Licensee"]}


def link(lid, call, k, a, b, freqs, **extra):
    d = {"i": lid, "u": lid.split("-")[2], "k": k, "c": call, "a": a, "b": b, "l": "Test Licensee", "f": freqs,
         "t": ["Fixed Point-to-Point"], "np": 1, "g": "2021-01-26", "x": "2031-02-01"}
    d.update(extra)
    return d


# SYNTHETIC geometry: the link L1 crosses the 40/41 degree edge, so it is written into both tiles (as the real builder does).
S_LOW = site(40.5, -105.5, "WAAA001")
S_HIGH = site(41.5, -105.5, "WAAA001")
S_FAR = site(40.7, -105.2, "WBBB002")
L1 = link("fcc-link-1-1", "WAAA001", 1, 0, 1, [11245.0, 6078.625])
L2 = link("fcc-link-2-1", "WBBB002", 1, 0, 1, [18700.0])


def tiles():
    return copy.deepcopy({
        "40_-106": {"sites": [S_LOW, S_HIGH, S_FAR], "links": [L1, link("fcc-link-2-1", "WBBB002", 1, 0, 2, [18700.0])]},
        "41_-106": {"sites": [S_LOW, S_HIGH], "links": [L1]},
        "10_10": {"sites": [site(10.5, 10.5, "WCCC003"), site(10.6, 10.6, "WCCC003")], "links": [link("fcc-link-3-1", "WCCC003", 1, 0, 1, [7000])]},
    })


def index(tile_map, **over):
    d = {"pack": "us-fcc-uls-micro", "schema": "velorona.us-fcc-uls-micro/1", "builder_version": "1.0.0", "generated_date": "2026-10-03",
         "source_file_updated": "2026-09-27", "source": {"agency": "Federal Communications Commission", "system": "Universal Licensing System (ULS)"},
         "attribution": ATTRIBUTION, "tile_degrees": 1, "min_zoom_hint": 8, "counts": {"links": 3},
         "tiles": {k: [len(t["sites"]), len(t["links"])] for k, t in tile_map.items()}}
    d.update(over)
    return d


def write_pack(root, tile_map=None, idx=None):
    tile_map = tile_map if tile_map is not None else tiles()
    os.makedirs(os.path.join(root, "tiles"), exist_ok=True)
    with open(os.path.join(root, "index.json"), "w") as fh:
        json.dump(idx if idx is not None else index(tile_map), fh)
    for key, tile in tile_map.items():
        with open(os.path.join(root, "tiles", f"{key}.json.gz"), "wb") as fh:
            fh.write(gzip.compress(json.dumps(tile).encode(), mtime=0))
    return str(root)


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
    for l in r.links:
        assert by_id[l["site_a"]["id"]] is l["site_a"] and by_id[l["site_b"]["id"]] is l["site_b"]


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
    def get(url, timeout=None):
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

    def boom(url, timeout=None):
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
    assert len(r.links) == len({l["id"] for l in r.links})
    assert len(r.links) + r.duplicate_links_dropped == sum(idx.tiles[k][1] for k in p.tile_keys(bbox))
    assert all(l["site_a"]["id"] != l["site_b"]["id"] for l in r.links)
