"""ISED column-29 antenna heights, read by column position (core/countries/ised_heights.py). All rows below are SYNTHETIC test data in the documented 61-column
layout; one optional test reads the real raw extract (VELORONA_ISED_RAW) and checks the counts the QGIS workstream measured offline."""
import csv
import io
import json
import os
import sys
import zipfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.countries import canada, ised_heights as IH  # noqa: E402
from core.countries.base import PackCorruptError, PackMissingError, PackVersionError  # noqa: E402


def row(auth="010000001-001", lat=43.0, lon=-79.0, h="30", fn="TX", freq="6000.5"):
    r = [""] * 61
    r[0], r[1], r[28], r[40], r[41], r[47] = fn, freq, h, f"{lat:.8f}", f"{lon:.8f}", auth
    return r


def write_csv(path, rows, bom=True):
    buf = io.StringIO()
    csv.writer(buf, lineterminator="\n").writerows(rows)
    with open(path, "w", encoding="utf-8-sig" if bom else "utf-8", newline="") as fh:
        fh.write(buf.getvalue())
    return str(path)


def test_reads_height_by_position_and_keys_by_authorization_and_coordinate(tmp_path):
    p = write_csv(tmp_path / "x.csv", [row(h="32.5"), row(fn="RX", lat=43.1, lon=-79.1, h="45")])
    d = IH.build_sidecar(p, "2026-09-01")
    assert d["endpoints"]["010000001-001|43.00000|-79.00000"] == [32.5, 1, True]
    assert d["endpoints"]["010000001-001|43.10000|-79.10000"][0] == 45.0
    assert d["source"]["rows"] == 2 and d["source"]["columns"] == 61 and d["source"]["file_sha256"]
    assert d["field"]["column"] == 29 and "Height above ground level" in d["field"]["name"] and d["field"]["document_sha256"] == IH.FIELD_DOC_SHA256


def test_zip_input_and_missing_file(tmp_path):
    csvp = write_csv(tmp_path / "TAFL.csv", [row()])
    z = tmp_path / "a.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.write(csvp, "TAFL.csv")
    assert IH.build_sidecar(str(z), "2026-09-01")["counts"]["endpoints_with_height"] == 1
    with pytest.raises(PackMissingError):
        IH.build_sidecar(str(tmp_path / "nope.csv"), "2026-09-01")


@pytest.mark.parametrize("mutate,needle", [
    (lambda r: r.append("extra"), "62 columns"),
    (lambda r: r.pop(), "60 columns"),
    (lambda r: r.__setitem__(0, "A"), "columns look shifted"),
    (lambda r: r.__setitem__(28, "tall"), "column 29"),
    (lambda r: r.__setitem__(40, "north"), "columns 2/41/42"),
    (lambda r: r.__setitem__(41, "-200"), "columns 2/41/42"),
])
def test_layout_violation_is_an_explicit_pack_error_never_a_shifted_read(tmp_path, mutate, needle):
    bad = row()
    mutate(bad)
    with pytest.raises(PackCorruptError) as exc:
        IH.build_sidecar(write_csv(tmp_path / "x.csv", [row(), bad]), "2026-09-01")
    assert needle in str(exc.value) and "Row 2" in str(exc.value)


def test_a_column_shift_is_caught_on_the_first_row(tmp_path):
    shifted = [""] + row()[:60]                 # everything moved one column to the right: 61 columns, wrong content
    with pytest.raises(PackCorruptError):
        IH.build_sidecar(write_csv(tmp_path / "x.csv", [shifted]), "2026-09-01")


def test_empty_height_is_absent_not_zero(tmp_path):
    d = IH.build_sidecar(write_csv(tmp_path / "x.csv", [row(h="")]), "2026-09-01")
    assert d["endpoints"] == {}


def test_several_values_use_the_lowest_in_range_and_say_so(tmp_path):
    p = write_csv(tmp_path / "x.csv", [row(h="60"), row(h="0"), row(h="25"), row(h="1500")])
    d = IH.build_sidecar(p, "2026-09-01")
    e = d["endpoints"]["010000001-001|43.00000|-79.00000"]
    assert e == [25.0, 4, True]
    out = tmp_path / "s.json"
    out.write_text(json.dumps(d))
    h, note = IH.load_sidecar(str(out)).lookup("010000001-001", 43.0, -79.0)
    assert h == 25.0 and "4 distinct values" in note and "column 29" in note and "record-reported" in note and "2026-09-01" in note


def test_no_in_range_value_returns_the_raw_value_so_the_analysis_says_no_data(tmp_path):
    d = IH.build_sidecar(write_csv(tmp_path / "x.csv", [row(h="0"), row(h="2000")]), "2026-09-01")
    assert d["endpoints"]["010000001-001|43.00000|-79.00000"] == [0.0, 2, False] and d["counts"]["endpoints_out_of_range"] == 1


def test_sidecar_validation(tmp_path):
    good = IH.build_sidecar(write_csv(tmp_path / "x.csv", [row()]), "2026-09-01")

    def save(d, name):
        (tmp_path / name).write_text(json.dumps(d))
        return str(tmp_path / name)
    IH.load_sidecar(save(good, "ok.json"))
    with pytest.raises(PackMissingError):
        IH.load_sidecar(str(tmp_path / "none.json"))
    with pytest.raises(PackVersionError):
        IH.load_sidecar(save({**good, "schema": "velorona.ca-heights/2"}, "v.json"))
    with pytest.raises(PackVersionError):
        IH.load_sidecar(save({**good, "field": {**good["field"], "column": 28}}, "c.json"))
    with pytest.raises(PackCorruptError):
        IH.load_sidecar(save({**good, "endpoints": {"k": ["x", 1, True]}}, "e.json"))
    (tmp_path / "j.json").write_text("{nope")
    with pytest.raises(PackCorruptError):
        IH.load_sidecar(str(tmp_path / "j.json"))
    src = dict(good["source"])
    src["source_file_updated"] = ""
    with pytest.raises(PackCorruptError):
        IH.load_sidecar(save({**good, "source": src}, "d.json"))


def _links():
    a = {"latitude": 43.0, "longitude": -79.0}
    b = {"latitude": 43.1, "longitude": -79.1}
    return [{"authorization_number": "010000001-001", "site_a": a, "site_b": b}, {"authorization_number": "010000002-001", "site_a": a, "site_b": b}]


def test_attach_requires_both_ends_and_labels_the_source(tmp_path):
    d = IH.build_sidecar(write_csv(tmp_path / "x.csv", [row(h="30"), row(fn="RX", lat=43.1, lon=-79.1, h="40"), row(auth="010000002-001", h="30")]), "2026-09-01")
    (tmp_path / "s.json").write_text(json.dumps(d))
    links = _links()
    assert canada.attach_heights(links, IH.load_sidecar(str(tmp_path / "s.json"))) == 1
    assert links[0]["site_a_height_m"] == 30.0 and links[0]["site_b_height_m"] == 40.0 and "Height above ground level" in links[0]["height_source"]
    assert "site_a_height_m" not in links[1]                        # only one end known: neither is attached


def test_provider_default_attaches_nothing_and_never_looks_in_the_repo(monkeypatch):
    monkeypatch.delenv(canada.HEIGHTS_ENV, raising=False)
    assert canada.find_heights_file() is None or canada.find_heights_file() == canada.BUNDLED_HEIGHTS
    assert not os.path.exists(canada.BUNDLED_HEIGHTS)               # nothing is shipped until the owner decides (D-Q11)


def test_an_unusable_sidecar_is_a_pack_error_from_the_index(tmp_path):
    (tmp_path / "bad.json").write_text("{nope")
    p = canada.CanadaProvider(heights=str(tmp_path / "bad.json"))
    with pytest.raises(PackCorruptError):
        p._height_index()


def test_record_height_becomes_observed_through_the_existing_channel(tmp_path):
    from core.record_source import height_origin
    assert height_origin(30.0, 30.0, "ISED ... column 29 ...")[0] == "Observed"
    assert height_origin(30.0, 45.0, "ISED ... column 29 ...")[0] == "Assumed"


@pytest.mark.skipif(not os.environ.get("VELORONA_ISED_RAW"), reason="set VELORONA_ISED_RAW to the raw TAFL_LTAF_Fixe zip/csv")
def test_real_extract_counts():
    d = IH.build_sidecar(os.environ["VELORONA_ISED_RAW"], "2026-09-01")
    assert d["source"]["rows"] == 109292 and d["source"]["columns"] == 61
