"""Terrain clearance batch (core/batch.py) -- QGIS-free.

Acceptance: each batch row equals the independent single-link analysis of the same link (compared field by field on the shared Map/QGIS parity fixtures, real engine
and library code; only the HTTP edge for elevation is replaced), a failing link never stops the batch, every row states its status and reason, input is not mutated,
and an empty input is an empty result. The QGIS Processing wrapper is NOT exercised here (it needs a QGIS runtime: tests/qgis_batch_e2e.py)."""
import copy
import csv
import glob
import io
import json
import os
import sys
import types

import pytest

try:
    import qgis.core  # noqa: F401
except ImportError:                                   # no QGIS runtime: a minimal stand-in so core.features imports
    stub = types.ModuleType("qgis.core")
    for name in ("QgsCoordinateReferenceSystem", "QgsCoordinateTransform", "QgsProject"):
        setattr(stub, name, type(name, (), {"__init__": lambda self, *a, **k: None}))
    sys.modules["qgis"] = types.ModuleType("qgis")
    sys.modules["qgis.core"] = stub

import requests  # noqa: E402

from core import batch as B  # noqa: E402
from core import provider_retry  # noqa: E402
from core.engines import terrestrial as tr  # noqa: E402
from core.presentation import terrain as pterrain  # noqa: E402
from core.validation import LibraryOutOfDateError, NoDataError  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = []
for path in sorted(glob.glob(os.path.join(ROOT, "parity", "fixtures", "*.json"))):
    fx = json.load(open(path, encoding="utf-8"))
    if isinstance(fx, dict) and "terrain" in fx and "link" in fx:
        FIXTURES.append(fx)
assert len(FIXTURES) > 50, "parity fixtures not found"


def link_attrs(fx):
    us = fx["selection"].get("pack") == "us-fcc-uls-micro"
    rec = {"id": fx["id"], "authorization_number": fx["id"],
           "source": ("FCC ULS public access database: Microwave (l_micro), U.S. Federal Communications Commission" if us else "ISED Fixed Service record"),
           "frequencies_mhz": ", ".join(str(v) for v in fx["selection"].get("published_frequencies_mhz", []))}
    if us:
        rec["country"] = "US"
    for key, site in (("site_a_height_m", fx["link"]["site_a"]), ("site_b_height_m", fx["link"]["site_b"])):
        if site.get("height_origin") == "Observed":
            rec[key] = site["height_m"]
            rec["height_source"] = site.get("height_source", "")
    return rec


def to_link(fx, fid=None):
    a, b = fx["link"]["site_a"], fx["link"]["site_b"]
    return B.BatchLink(attrs=link_attrs(fx), site_a=(a["lat"], a["lon"]), site_b=(b["lat"], b["lon"]), fid=fid)


class _Resp:
    def __init__(self, body, err=None):
        self.body, self.err = body, err

    def raise_for_status(self):
        if self.err:
            raise requests.exceptions.HTTPError(self.err)

    def json(self):
        return self.body


CURRENT = [None]       # the id of the link being analysed: several parity fixtures share endpoints but have different synthetic terrain
BY_ID = {fx["id"]: fx for fx in FIXTURES}


@pytest.fixture(autouse=True)
def elevation_service(monkeypatch):
    """Replaces only requests.get: the library's own get_elevations() runs (count check, float check). The response is the synthetic terrain of the link being analysed."""
    calls = []

    def fake_get(url, params=None, timeout=None):
        t = BY_ID[CURRENT[0]]["terrain"]
        calls.append(CURRENT[0])
        if t["mode"] == "error":
            return _Resp(None, t["error"])
        return _Resp({"elevation": [s[2] for s in t["samples"]]})   # nulls included, as a provider could return them

    monkeypatch.setattr(requests, "get", fake_get)
    monkeypatch.setattr(provider_retry, "_sleep", lambda s: None)
    return calls


def tracked(attrs, a, b, params):
    CURRENT[0] = attrs["id"]
    return tr.analyze_link_record(attrs, a, b, params)


def run(links, **kw):
    kw.setdefault("analyze", tracked)
    return B.run_batch(links, **kw)


def independent_single(link):
    """The single-link flow, written out separately from core/batch.py: what plugin.py _run_terrestrial_for_link does with the dialog's pre-filled values accepted."""
    params, _ghz, _note = tr.build_link_params(link.attrs)
    res = tracked(link.attrs, link.site_a, link.site_b, params)
    r = res.result
    status, reason, _ = pterrain.terrain_status(r)
    return res, r, status, reason


# --------------------------------------------------------------------- equality with the independent single-link analysis

def test_one_link_equals_the_independent_single_link_result():
    link = to_link(next(f for f in FIXTURES if f["id"] == "ca-clear"))
    batch = run([link])
    assert len(batch.rows) == 1
    row = batch.rows[0]
    res, r, status, reason = independent_single(link)
    assert row.status == status and row.reason == reason and row.terrain_class == r.los_status
    assert row.distance_km == r.distance_km and row.bearing_deg == r.bearing_deg and row.frequency_ghz == r.frequency_ghz
    assert row.available_clearance_m == r.terrain_clearance_m and row.required_clearance_m == r.required_clearance_m
    assert row.margin_m == r.terrain_clearance_m - r.required_clearance_m and row.first_fresnel_radius_m == r.first_fresnel_radius_m
    assert row.frequency_origin == res.frequency_origin[0] == "Observed"
    assert row.elevation_samples == len(r.profile) and row.near_threshold == bool(r.near_threshold)


def test_every_parity_fixture_in_one_batch_equals_its_own_single_link_analysis():
    links = [to_link(fx, fid=i + 100) for i, fx in enumerate(FIXTURES)]
    batch = run(links, max_links=B.HARD_MAX_LINKS)
    assert len(batch.rows) == len(links) > 50
    compared = ran = 0
    for i, (link, row) in enumerate(zip(links, batch.rows)):
        assert row.batch_index == i and row.source_fid == 100 + i and row.link_id == link.attrs["id"], "order and identity preserved"
        try:
            res, r, status, reason = independent_single(link)
        except Exception as exc:                      # the single-link flow could not produce a result for this link: the batch row must say NO DATA (or ERROR) with a reason
            assert row.status in (B.NO_DATA, B.STATUS_ERROR) and row.reason, f"{link.attrs['id']}: {exc}"
            compared += 1
            continue
        ran += 1
        assert (row.status, row.reason, row.terrain_class) == (status, reason, r.los_status), link.attrs["id"]
        for col, ref in (("distance_km", r.distance_km), ("bearing_deg", r.bearing_deg), ("frequency_ghz", r.frequency_ghz), ("available_clearance_m", r.terrain_clearance_m),
                         ("required_clearance_m", r.required_clearance_m), ("first_fresnel_radius_m", r.first_fresnel_radius_m), ("percent_fresnel_clear", r.percent_fresnel_clear)):
            assert getattr(row, col) == ref, f"{link.attrs['id']} {col}"
        assert row.frequency_origin == res.frequency_origin[0]
        assert (row.site_a_height_m, row.site_a_height_origin) == (res.site_a_height_m, res.height_origins["a"][0])
        assert (row.site_b_height_m, row.site_b_height_origin) == (res.site_b_height_m, res.height_origins["b"][0])
        compared += 1
    assert compared == len(links) and ran > 40
    # more than one terrain class occurs, so equality is not trivially one status
    assert len({r.status for r in batch.rows if r.status in B.RESULT_STATUSES}) >= 3


# --------------------------------------------------------------------- one link, many links, incomplete input, one failing link, empty

def test_a_failing_elevation_service_for_one_link_does_not_stop_the_batch():
    err_fx = next(f for f in FIXTURES if f["terrain"]["mode"] == "error")
    ok_fx = [f for f in FIXTURES if f["terrain"]["mode"] == "samples"][:3]
    batch = run([to_link(ok_fx[0]), to_link(err_fx), to_link(ok_fx[1]), to_link(ok_fx[2])])
    st = [r.status for r in batch.rows]
    assert st[1] == B.NO_DATA and "elevation data unavailable" in batch.rows[1].reason
    with pytest.raises(NoDataError) as single:                       # the single-link flow refuses this link the same way, with the same reason and transient flag
        independent_single(to_link(err_fx))
    assert batch.rows[1].reason == "; ".join(single.value.reasons) and batch.rows[1].transient == single.value.transient
    assert all(s in B.RESULT_STATUSES for i, s in enumerate(st) if i != 1)
    assert batch.counts()[B.NO_DATA] == 1


def test_an_unexpected_exception_for_one_link_is_an_error_row_and_the_rest_continue():
    fxs = [f for f in FIXTURES if f["terrain"]["mode"] == "samples"][:3]
    real = tracked

    def flaky(attrs, a, b, params):
        if attrs["id"] == fxs[1]["id"]:
            raise RuntimeError("boom")
        return real(attrs, a, b, params)

    batch = run([to_link(f) for f in fxs], analyze=flaky)
    assert [r.status in B.RESULT_STATUSES for r in batch.rows] == [True, False, True]
    bad = batch.rows[1]
    assert bad.status == B.STATUS_ERROR and bad.reason == "boom" and bad.error_type == "RuntimeError"


def test_a_library_too_old_for_the_corrected_convention_stops_the_batch_not_row_by_row():
    def old(attrs, a, b, params):
        raise LibraryOutOfDateError("aei-link-clearance is too old")

    with pytest.raises(LibraryOutOfDateError):
        run([to_link(FIXTURES[0]), to_link(FIXTURES[1])], analyze=old)


def test_incomplete_input_is_no_data_with_a_reason_never_a_guess():
    fx = next(f for f in FIXTURES if f["id"] == "ca-clear")
    good = to_link(fx)
    no_geom = B.BatchLink(attrs=dict(good.attrs), site_a=None, site_b=(1.0, 1.0))
    no_freq = B.BatchLink(attrs={**good.attrs, "frequencies_mhz": ""}, site_a=good.site_a, site_b=good.site_b)
    bad_coord = B.BatchLink(attrs=dict(good.attrs), site_a=(91.0, 0.0), site_b=good.site_b)
    same_pt = B.BatchLink(attrs=dict(good.attrs), site_a=good.site_a, site_b=good.site_a)
    batch = run([good, no_geom, no_freq, bad_coord, same_pt])
    s = batch.rows
    assert s[0].status in B.RESULT_STATUSES
    assert s[1].status == B.NO_DATA and "no usable endpoint geometry" in s[1].reason
    assert s[2].status == B.NO_DATA and "no usable frequency" in s[2].reason and "none is assumed" in s[2].reason and s[2].frequency_ghz is None
    assert s[3].status == B.NO_DATA and s[3].reason and s[3].transient is False
    assert s[4].status == B.NO_DATA and s[4].reason
    assert all(r.distance_km is None for r in s[1:]), "no numbers are invented for NO DATA rows"


def test_a_fallback_frequency_is_used_only_where_the_record_has_none_and_is_typed_assumed():
    fx = next(f for f in FIXTURES if f["id"] == "ca-clear")
    good = to_link(fx)
    no_freq = B.BatchLink(attrs={**good.attrs, "frequencies_mhz": ""}, site_a=good.site_a, site_b=good.site_b)
    batch = run([good, no_freq], fallback_frequency_ghz=7.0)
    assert batch.rows[0].frequency_origin == "Observed" and batch.rows[0].frequency_ghz == 6.22689, "the record's own value is untouched by the fallback"
    assert batch.rows[1].status in B.RESULT_STATUSES and batch.rows[1].frequency_ghz == 7.0 and batch.rows[1].frequency_origin == "Assumed"
    for bad in (0.01, 150, "7"):
        with pytest.raises(ValueError):
            run([good], fallback_frequency_ghz=bad)


def test_empty_input_is_an_empty_result_and_a_valid_export():
    batch = run([])
    assert batch.rows == [] and sum(batch.counts().values()) == 0 and batch.canceled is False
    text = B.batch_to_csv(batch)
    assert "Batch: 0 link(s)" in text and next(csv.reader(io.StringIO("\n".join(ln for ln in text.splitlines() if not ln.startswith("#"))))) == B.COLUMNS


def test_the_limit_and_cancel_report_not_run_never_drop_links(elevation_service):
    links = [to_link(f) for f in [f for f in FIXTURES if f["terrain"]["mode"] == "samples"][:5]]
    batch = run(links, max_links=2)
    assert [r.status in B.RESULT_STATUSES for r in batch.rows] == [True, True, False, False, False]
    assert all(r.status == B.STATUS_NOT_RUN and "limit of 2" in r.reason for r in batch.rows[2:])
    assert len(elevation_service) == 2, "links over the limit make no request"
    seen = []
    cancelled = run(links, is_canceled=lambda: len(seen) >= 2, progress=lambda i, n, row: seen.append(i))
    assert cancelled.canceled and [r.status == B.STATUS_NOT_RUN for r in cancelled.rows] == [False, False, True, True, True]
    assert all("cancelled" in r.reason for r in cancelled.rows[2:]) and len(seen) == 5
    for bad in (0, -1, B.HARD_MAX_LINKS + 1, "5", 2.5, True):
        with pytest.raises(ValueError):
            run(links, max_links=bad)


def test_the_input_is_not_modified_and_the_pause_is_applied_between_links():
    links = [to_link(f) for f in [f for f in FIXTURES if f["terrain"]["mode"] == "samples"][:3]]
    before = copy.deepcopy([(l.attrs, l.site_a, l.site_b, l.fid) for l in links])
    slept = []
    run(links, pause_s=0.5, sleep=slept.append)
    assert [(l.attrs, l.site_a, l.site_b, l.fid) for l in links] == before
    assert slept == [0.5, 0.5], "a pause between links, not before the first"


def test_the_batch_is_deterministic():
    links = [to_link(f) for f in FIXTURES[:8]]
    a, b = run(links), run(links)
    assert [r.as_dict() for r in a.rows] == [r.as_dict() for r in b.rows]


# --------------------------------------------------------------------- export

def test_csv_export_has_the_preamble_one_row_per_link_and_the_counts():
    links = [to_link(f) for f in FIXTURES[:12]]
    batch = run(links)
    text = B.batch_to_csv(batch)
    comments = [ln for ln in text.splitlines() if ln.startswith("# ")]
    assert any("Terrain clearance, batch export" in ln for ln in comments) and any(ln.startswith("# Product: Velorona for QGIS") for ln in comments)
    assert any("same calculation as selecting that link" in ln for ln in comments) and any("WATCH = clearance ratio below a provisional 1.3" in ln for ln in comments)
    table = list(csv.reader(io.StringIO("\n".join(ln for ln in text.splitlines() if not ln.startswith("#")))))
    assert table[0] == B.COLUMNS and len(table) == 1 + len(links)
    assert all(len(r) == len(B.COLUMNS) for r in table)
    status_col = B.COLUMNS.index("status")
    counts = batch.counts()
    for s in B.ALL_STATUSES:
        assert sum(1 for r in table[1:] if r[status_col] == s) == counts[s]
    batch_line = next(ln for ln in comments if ln.startswith("# Batch:"))
    assert f"Batch: {len(links)} link(s)" in batch_line
    # a number in the CSV is the row's own number, at full precision
    first = next(r for r in batch.rows if r.status in B.RESULT_STATUSES)
    row = next(r for r in table[1:] if r[B.COLUMNS.index("batch_index")] == str(first.batch_index))
    assert float(row[B.COLUMNS.index("available_clearance_m")]) == first.available_clearance_m
    assert row[B.COLUMNS.index("frequency_origin")] == first.frequency_origin


def test_nan_or_infinite_ratio_is_reported_as_unbounded_not_as_a_number():
    fx = next(f for f in FIXTURES if f["id"] == "ca-clear")
    link = to_link(fx)
    real = tracked(link.attrs, link.site_a, link.site_b, tr.build_link_params(link.attrs)[0])
    import dataclasses
    real = dataclasses.replace(real, result=dataclasses.replace(real.result, clearance_ratio=float("inf")))
    row = B.analyze_one(0, link, analyze=lambda *a: real)
    assert row.clearance_ratio is None and row.clearance_ratio_text == "unbounded"
    assert "unbounded" in B.batch_to_csv(B.BatchResult([row], "t0", "t1", 100, None))
