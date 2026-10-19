"""The US overview (core/countries/usa_overview.py): reading, validation and grouping of Velorona Map's us-overview.json. Pure stdlib, no QGIS."""
import json
import os
import tempfile

import pytest

from core.countries import usa_overview as O
from core.countries.base import PackCorruptError, PackMissingError, PackVersionError


def doc(cells, schema=O.OVERVIEW_SCHEMA):
    return json.dumps({"schema": schema, "cell_degrees": 2, "cells": cells}).encode()


def test_parent_source_is_the_sibling_location_of_the_pack():
    assert O.parent_source("https://map.velorona.ai/data/us/") == "https://map.velorona.ai/data/"
    assert O.parent_source("https://map.velorona.ai/data/us") == "https://map.velorona.ai/data/"
    assert O.parent_source("/tmp/x/us/") == os.path.dirname(os.path.realpath("/tmp/x/us"))


def test_cells_are_read_and_malformed_ones_dropped_not_guessed():
    cells = O.parse_overview(doc([[40.5, -105.4, 3, 2], [91.0, 0, 1, 1], [40, -105, -1, 0], ["x", 1, 1, 1], [10, 10], [10, 10, 0, 0], [41, -104, 5, 0]]))
    assert cells == [(40.5, -105.4, 3, 2), (41.0, -104.0, 5, 0)]


def test_wrong_schema_or_shape_is_refused_with_a_typed_error():
    with pytest.raises(PackVersionError):
        O.parse_overview(doc([], schema="velorona.us-overview/2"))
    with pytest.raises(PackCorruptError):
        O.parse_overview(b"not json")
    with pytest.raises(PackCorruptError):
        O.parse_overview(json.dumps({"schema": O.OVERVIEW_SCHEMA}).encode())


def test_a_folder_pack_without_an_overview_is_a_missing_overview_not_a_crash():
    with tempfile.TemporaryDirectory() as root:
        os.makedirs(os.path.join(root, "us"))
        with pytest.raises(PackMissingError):
            O.load_overview(os.path.join(root, "us"))
        with open(os.path.join(root, O.OVERVIEW_FILE), "wb") as fh:
            fh.write(doc([[40.5, -105.4, 3, 2]]))
        assert O.load_overview(os.path.join(root, "us")) == [(40.5, -105.4, 3, 2)]


def test_compact_counts():
    assert [O.compact(n) for n in (5, 999, 1000, 1234, 12345, 999999, 1500000)] == ["5", "999", "1k", "1.2k", "12k", "1M", "1.5M"]


def test_bins_sum_nearby_cells_and_separate_far_ones():
    cells = [(40.0, -100.0, 10, 1), (40.5, -99.5, 20, 2), (30.0, -90.0, 7, 7)]
    far = O.bin_cells(cells, 3.0, (-130.0, 20.0, -60.0, 55.0))                  # zoomed far out: the first two share a 130 px bin
    assert sorted(b["n"] for b in far) == [7, 30] and sum(b["ns"] for b in far) == 37
    near = O.bin_cells(cells, 9.0, (-101.0, 39.0, -98.0, 41.0))                 # zoomed in: separate bubbles, only those in the padded view
    assert sorted(b["n"] for b in near) == [10, 20]
    merged = next(b for b in far if b["n"] == 30)
    assert merged["label"] == "30" and 40.0 < merged["latitude"] < 40.5 and -100.0 < merged["longitude"] < -99.5
    assert O.bin_cells(cells, 3.0, (-130.0, 20.0, -60.0, 55.0), want_sites=False, want_links=True)[0]["n"] in (3, 7)
    assert O.bin_cells(cells, 3.0, (-130.0, 20.0, -60.0, 55.0), want_sites=False, want_links=False) == []
