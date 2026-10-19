"""CSV formula-injection safety (core/csvsafe.py) on every CSV path: single-link / single-record exports, selection summary, and the Batch export.

A cell that begins with = + - @ (or tab / CR) is evaluated by a spreadsheet; quoting does not stop it. Untrusted TEXT (names, ids, licensees, source and reason
text) is neutralised with a leading apostrophe; calculated numbers, including negative ones and number-with-unit text, are left exactly as they were. The Excel
export stores plain strings (never formulas) and must not carry the apostrophe."""
import csv
import io
import types
import sys
import zipfile

import pytest

try:
    import qgis.core  # noqa: F401
except ImportError:                                   # no QGIS runtime: a minimal stand-in so core.features imports
    stub = types.ModuleType("qgis.core")
    for name in ("QgsCoordinateReferenceSystem", "QgsCoordinateTransform", "QgsProject"):
        setattr(stub, name, type(name, (), {"__init__": lambda self, *a, **k: None}))
    sys.modules["qgis"] = types.ModuleType("qgis")
    sys.modules["qgis.core"] = stub

from core import batch as B  # noqa: E402
from core import csvsafe  # noqa: E402
from core import export  # noqa: E402
from core.inspector import SelectionSummary  # noqa: E402
from presentation_fixtures import terrain_result  # noqa: E402
import test_terrain_batch as T  # noqa: E402
from test_terrain_batch import elevation_service  # noqa: E402,F401  (autouse offline elevation double)

UNTRUSTED = ["=1+1", "+SUM(A1:A2)", "-1+2", "@SUM(1)", "-1-2", "-1 SUM(A1)", "-A1", "-", "\t=1", "\r=1", "=cmd|' /C calc'!A0",
             "=HYPERLINK(\"http://example.invalid\",\"x\")"]
TRUSTED = ["-34.39 m", "-5.085", "-1e5", "-2 m/s", "+1", "12.5", "7", "", "ISED record -- Highest of 2 published frequencies",
           "Acme-Tel Inc.", "-5.08× the required minimum. Negative: the terrain is above the line of sight, so there is no clearance at all (1× would be exactly the minimum)."]


def cells(text):
    return [c for row in csv.reader(io.StringIO("\n".join(ln for ln in text.splitlines() if not ln.startswith("#")))) for c in row]


@pytest.mark.parametrize("value", UNTRUSTED)
def test_untrusted_text_that_starts_like_a_formula_is_neutralised(value):
    assert csvsafe.neutralize(value) == "'" + value


@pytest.mark.parametrize("value", TRUSTED + [None, 0, -3.2, 12])
def test_numbers_and_ordinary_text_are_unchanged(value):
    assert csvsafe.neutralize(value) == value


def test_the_writer_keeps_structure_quoting_and_columns():
    buf = io.StringIO()
    w = csvsafe.writer(buf, lineterminator="\n")
    w.writerow(["a", "b,c", 'say "hi"'])
    w.writerow(["=1+1", "-34.39 m", "x\ny"])
    rows = list(csv.reader(io.StringIO(buf.getvalue())))
    assert rows == [["a", "b,c", 'say "hi"'], ["'=1+1", "-34.39 m", "x\ny"]]
    with csvsafe.disabled():
        buf2 = io.StringIO()
        csvsafe.writer(buf2).writerow(["=1+1"])
    assert buf2.getvalue().startswith("=1+1")


# ------------------------------------------------------------------ single-record and single-link exports

def test_single_record_exports_neutralise_attribute_text():
    link = {"licensee": "=1+1", "authorization_number": "+SUM(A1)", "frequencies_mhz": "7000", "source": "-1+2", "coverage": "@x"}
    got = cells(export.link_feature_to_csv(link, (50.0, -100.0), (50.1, -100.1)))
    assert "'=1+1" in got and "'+SUM(A1)" in got and "'-1+2" in got and "'@x" in got
    assert "50.0" in got and "-100.0" in got, "numeric coordinates (a negative one included) are untouched"
    site = {"name": "=cmd|' /C calc'!A0", "record_id": "-1+2", "call_signs": "@A", "source": "s"}
    got = cells(export.feature_to_csv(site, 44.5, -79.25))
    assert "'=cmd|' /C calc'!A0" in got and "'-1+2" in got and "'@A" in got and "-79.25" in got


def test_selection_summary_rows_are_neutralised():
    summary = SelectionSummary(kind_label="Fixed Service sites", feature_kind="site", count=1, scanned=1, columns=["Site", "Latitude"],
                               rows=[["=1+1", "-34.5"]])
    got = cells(export.selection_summary_to_csv(summary))
    assert "'=1+1" in got and "-34.5" in got


def test_terrain_export_neutralises_names_and_keeps_calculated_negatives():
    res = terrain_result(ground_m=140.0, hump_m=60.0)               # terrain above the line of sight: negative clearance
    clean = cells(export.result_to_csv(res))
    assert any(c.startswith("-") for c in clean), "the fixture really produces negative calculated values"
    assert not any(c.startswith("'") for c in clean), "no calculated value or ordinary text was touched"
    res.site_a_name, res.site_b_name = "=1+1", "@SUM(1)"
    res.site_a_source = "-1+2"
    dirty = cells(export.result_to_csv(res))
    assert "'-1+2" in dirty, "a cell that IS the untrusted text is neutralised"
    assert "Site A location (=1+1)" in dirty and "Site B location (@SUM(1))" in dirty, "text that merely contains it mid-cell is not a formula and is left as is"
    for c in dirty:
        assert not c.startswith(("=", "@", "+SUM")), c
    assert [c for c in dirty if c.startswith("-")] == [c for c in clean if c.startswith("-")], "the same negative numbers, unchanged"


def test_excel_export_has_no_formulas_and_no_apostrophes():
    res = terrain_result()
    res.site_a_name = "=HYPERLINK(\"http://example.invalid\",\"x\")"
    data = export.result_to_xlsx(res)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        sheets = [z.read(n).decode("utf-8") for n in z.namelist() if n.startswith("xl/worksheets/")]
    assert sheets and not any("<f>" in s or "<f " in s for s in sheets), "a workbook cell is never a formula"
    joined = "".join(sheets)
    assert "=HYPERLINK" in joined, "the original text is kept in the workbook"
    assert "&apos;=HYPERLINK" not in joined and "'=HYPERLINK" not in joined


# ------------------------------------------------------------------ batch export

def test_batch_csv_neutralises_text_fields_and_leaves_numbers_alone():
    fixtures = [f for f in T.FIXTURES if f["terrain"]["mode"] == "samples"][:3]
    benign = [T.to_link(f) for f in fixtures]
    bad = []
    for link, text in zip(benign, ["=1+1", "+SUM(A1:A2)", "@SUM(1)"]):
        attrs = dict(link.attrs, authorization_number=text, source="-1+2")      # `id` stays: the offline elevation double is keyed by it
        bad.append(B.BatchLink(attrs=attrs, site_a=link.site_a, site_b=link.site_b, fid=link.fid))

    def run_csv(links):
        return B.batch_to_csv(T.run(links))

    ok_text, bad_text = run_csv(benign), run_csv(bad)
    table = list(csv.reader(io.StringIO("\n".join(ln for ln in bad_text.splitlines() if not ln.startswith("#")))))
    header, rows = table[0], table[1:]
    assert header == B.COLUMNS and len(rows) == 3 and all(len(r) == len(B.COLUMNS) for r in rows)
    for row, text in zip(rows, ["=1+1", "+SUM(A1:A2)", "@SUM(1)"]):
        assert row[B.COLUMNS.index("authorization_number")] == "'" + text
        assert row[B.COLUMNS.index("source")] == "'-1+2"
    numeric = [c for c in B.COLUMNS if c not in ("link_id", "authorization_number", "source")]
    ok_rows = list(csv.reader(io.StringIO("\n".join(ln for ln in ok_text.splitlines() if not ln.startswith("#")))))[1:]
    for r_bad, r_ok in zip(rows, ok_rows):
        for col in numeric:
            i = B.COLUMNS.index(col)
            assert r_bad[i] == r_ok[i], f"{col} must not change because an identifier was neutralised"


def test_batch_csv_neutralises_identifier_and_error_text():
    link = B.BatchLink(attrs={"id": "=1+1", "authorization_number": "-1+2", "source": "s", "frequencies_mhz": "7000"}, site_a=(50.0, -100.0), site_b=(50.1, -100.1))

    def boom(attrs, a, b, params):
        raise RuntimeError("=cmd|' /C calc'!A0")

    table = list(csv.reader(io.StringIO("\n".join(ln for ln in B.batch_to_csv(B.run_batch([link], analyze=boom)).splitlines() if not ln.startswith("#")))))
    row = dict(zip(table[0], table[1]))
    assert row["status"] == "ERROR" and row["link_id"] == "'=1+1" and row["reason"] == "'=cmd|' /C calc'!A0"


def test_batch_csv_keeps_negative_numbers():
    fx = next(f for f in T.FIXTURES if f["id"] == "ca-clear")
    text = B.batch_to_csv(T.run([T.to_link(fx)]))
    table = list(csv.reader(io.StringIO("\n".join(ln for ln in text.splitlines() if not ln.startswith("#")))))
    row = dict(zip(table[0], table[1]))
    assert float(row["available_clearance_m"]) < 0 or float(row["margin_m"]) < 0, "this fixture has a negative calculated value"
    assert not any(v.startswith("'") for v in row.values())
