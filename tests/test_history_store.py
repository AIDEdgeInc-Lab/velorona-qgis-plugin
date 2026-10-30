"""Local history store: retention, caps, CONTRACT columns, CSV, clearing, and the documented failure modes (locked, disk full, corrupt, clock skew)."""
import csv
import io
import os
import sqlite3

import aei_history_contract as contract
import pytest

from core import history_store as H
from core.history_store import HistoryError, HistoryRecord, HistoryStore

NOW = 1_790_000_000.0       # a fixed 'now'


def ts(hours_ago):
    return H.utc_text(NOW - hours_ago * 3600)


def rec(hours_ago=0.0, value=1.2, metric="rain_rate", kind="model", source="open-meteo", entity="s1", unit="mm/h", **kw):
    return HistoryRecord(ts=ts(hours_ago), fetched_ts=ts(0), source=source, entity_id=entity, metric=metric, value=value, unit=unit, kind=kind,
                         data_version="aei-mw-exposure 0.2.0", **kw)


@pytest.fixture
def store(tmp_path):
    clock = [NOW]
    s = HistoryStore(str(tmp_path / "velorona" / "history.sqlite"), clock=lambda: clock[0])
    s.clock = clock
    return s


def test_write_read_roundtrip_keeps_every_contract_field(store):
    r = rec(value=None, nodata_reason="the provider did not report it", derived=True, entity_type="link")
    assert store.add_many([r, rec(1, 0.0), rec(2, "CLEAR", metric="status", unit="enum")]).written == 3
    got = {(x.metric, x.ts): x for x in store.records()}
    assert got[("rain_rate", ts(0))] == r                      # NULL stays NULL, never 0
    assert got[("status", ts(2))].value == "CLEAR"
    assert got[("rain_rate", ts(1))].value == 0.0


def test_the_same_value_is_not_stored_twice(store):
    store.add_many([rec()])
    rep = store.add_many([rec()])
    assert (rep.written, rep.duplicates) == (0, 1) and len(store.records()) == 1


def test_default_retention_is_24h_and_prunes_on_write(store):
    assert store.retention_hours() == 24
    store.add_many([rec(30), rec(23), rec(0)])
    assert [r.ts for r in store.records()] == [ts(23), ts(0)]


def test_retention_is_configurable_within_1h_to_7d_and_refuses_other_values(store):
    store.add_many([rec(30), rec(2), rec(0)])
    assert store.set_retention_hours(1) == 1
    assert [r.ts for r in store.records()] == [ts(0)]
    for bad in (0, 169, 2.5, True):
        with pytest.raises(HistoryError):
            store.set_retention_hours(bad)
    assert store.retention_hours() == 1                        # unchanged by the refusals


def test_row_cap_drops_the_oldest_first(tmp_path):
    s = HistoryStore(str(tmp_path / "h.sqlite"), clock=lambda: NOW, max_rows=5)
    s.add_many([rec(i / 10, value=float(i), source=f"s{i}") for i in range(10)])
    rows = s.records()
    assert len(rows) == 5 and sorted(r.value for r in rows) == [0.0, 1.0, 2.0, 3.0, 4.0]    # i/10 h ago: larger i = older = dropped


def test_byte_cap_is_the_contracts_counted_size_and_bounds_the_file(tmp_path):
    s = HistoryStore(str(tmp_path / "h.sqlite"), clock=lambda: NOW, max_bytes=64 * 1024)
    s.add_many([rec(i / 1000, value=float(i), source="x" * 100 + str(i)) for i in range(2000)])
    # The cap is the contract's measure (UTF-8 length of each row's canonical text); the SQLite file carries index/page overhead on top (about 2.5x here).
    assert s.stats().bytes <= 64 * 1024 and 0 < s.stats().rows < 2000 and os.path.getsize(s.path) <= 4 * 64 * 1024


def test_invalid_records_are_counted_not_stored(store):
    bad = [rec(metric="bogus"), rec(kind="prediction"), HistoryRecord(ts="2026-10-29 14:00", source="a", entity_id="e", metric="rain_rate",
                                                                      value=1.0, unit="mm/h", kind="model", data_version="v"), rec(value=float("nan"))]
    rep = store.add_many(bad + [rec()])
    assert rep.invalid == 4 and rep.written == 1


def test_entity_hash_is_stable_salted_and_hides_the_id(store):
    a, b = store.entity_hash("my-site"), store.entity_hash("my-site")
    assert a == b and a.startswith("h:") and "my-site" not in a and store.entity_hash("other") != a


# --- failure modes -----------------------------------------------------------------------------------------------------------------------

def test_database_locked_by_another_process_is_reported_and_loses_nothing(store, monkeypatch):
    store.add_many([rec(1)])
    monkeypatch.setattr(H, "BUSY_TIMEOUT_S", 0.05)
    blocker = sqlite3.connect(store.path, timeout=0.05)
    blocker.execute("BEGIN EXCLUSIVE")
    try:
        rep = store.add_many([rec(0, value=9.9)])
        assert rep.error == "locked" and rep.written == 0 and "in use by another process" in rep.user_text()
        with pytest.raises(HistoryError) as e:
            store.records()
        assert e.value.code == "locked"
    finally:
        blocker.rollback(); blocker.close()
    assert [r.value for r in store.records()] == [1.2]            # the earlier row is intact; the blocked write never half-happened


def test_disk_full_rolls_back_and_says_so(store, monkeypatch):
    store.add_many([rec(1)])
    real = sqlite3.connect

    class Full:
        def __init__(self, con): self._c = con
        def execute(self, sql, *a):
            if sql.lstrip().startswith("INSERT OR IGNORE INTO history"):
                raise sqlite3.OperationalError("database or disk is full")
            return self._c.execute(sql, *a)
        def __getattr__(self, name): return getattr(self._c, name)
    monkeypatch.setattr(sqlite3, "connect", lambda *a, **k: Full(real(*a, **k)))
    rep = store.add_many([rec(0, value=9.9)])
    assert rep.error == "disk_full" and rep.written == 0 and "disk is full" in rep.user_text()
    monkeypatch.undo()
    assert [r.value for r in store.records()] == [1.2]


def test_corrupt_file_is_set_aside_not_deleted_and_a_new_one_started(store):
    os.makedirs(os.path.dirname(store.path), exist_ok=True)
    with open(store.path, "wb") as f:
        f.write(b"this is not a sqlite database" * 50)
    rep = store.add_many([rec()])
    assert rep.ok and rep.written == 1 and rep.recovered and os.path.exists(rep.recovered)
    assert b"this is not a sqlite database" in open(rep.recovered, "rb").read()
    assert "set aside" in rep.user_text()


def test_newer_schema_is_left_untouched(store):
    store.add_many([rec()])
    con = sqlite3.connect(store.path)
    con.execute("UPDATE meta SET value='99' WHERE key='schema_version'"); con.commit(); con.close()
    before = open(store.path, "rb").read()
    rep = store.add_many([rec(0, value=7.0)])
    assert rep.error == "invalid" and open(store.path, "rb").read() == before


def test_values_from_the_future_are_rejected_as_clock_skew(store):
    rep = store.add_many([rec(-1), rec(-0.1), rec(0)])            # 1 h ahead is skew; 6 min ahead is tolerated
    assert rep.rejected_future == 1 and rep.skew_suspected and rep.written == 2
    assert "clock" in rep.user_text()


def test_forecasts_may_be_in_the_future(store):
    assert store.add_many([rec(-3, kind="forecast")]).written == 1


def test_a_clock_set_back_does_not_resurrect_old_rows(store):
    store.add_many([rec(0)])
    store.clock[0] = NOW - 48 * 3600            # computer clock jumps back 2 days
    store.add_many([HistoryRecord(ts=H.utc_text(NOW - 49 * 3600), fetched_ts=H.utc_text(NOW - 48 * 3600), source="a", entity_id="s1", metric="rain_rate",
                                  value=1.0, unit="mm/h", kind="model", data_version="v")])
    assert [r.ts for r in store.records()] == [ts(0)]      # the old row relative to the NEWEST fetch time was pruned, the real one kept


# --- CSV and clearing --------------------------------------------------------------------------------------------------------------------

def test_csv_has_the_contract_columns_utc_rfc4180_and_a_formula_guard(store):
    store.add_many([rec(0, value=-3.5, metric="temperature", unit="degC", source="=cmd|' /C calc'!A0"), rec(1, value=None, nodata_reason='no "data", sorry')])
    name, text = store.export_csv("s1")
    assert name.startswith("velorona-history-s1-") and name.endswith("Z.csv") and "\r" not in text
    rows = list(csv.reader(io.StringIO(text)))
    assert rows[0] == list(contract.CSV_COLUMNS)
    col = {c: i for i, c in enumerate(rows[0])}
    body = {r[col["metric"]]: r for r in rows[1:]}
    assert body["temperature"][col["source"]].startswith("'=") and body["temperature"][col["value"]] == "-3.5"      # injected source neutralised, negative number kept
    assert body["rain_rate"][col["value"]] == "" and body["rain_rate"][col["nodata_reason"]] == 'no "data", sorry'    # NO DATA is empty, never 0
    assert all(r[col["entity_label"]] == "" for r in rows[1:])                                                         # names are written only on request


def test_csv_carries_the_users_own_name_next_to_the_hashed_id(store):
    store.add_many([rec(0, entity="h:abc"), rec(1, entity="h:other")])
    store.set_labels({"h:abc": 'Toronto, "north" =link'})
    _, plain = store.export_csv()
    assert all(r[list(csv.reader(io.StringIO(plain)))[0].index("entity_label")] == "" for r in list(csv.reader(io.StringIO(plain)))[1:])   # default: no names
    _, text = store.export_csv(include_names=True)
    rows = list(csv.reader(io.StringIO(text)))
    col = {c: i for i, c in enumerate(rows[0])}
    assert rows[0][col["entity_id"] + 1] == "entity_label"
    by_id = {r[col["entity_id"]]: r[col["entity_label"]] for r in rows[1:]}
    assert by_id == {"h:abc": 'Toronto, "north" =link', "h:other": ""}      # only entities that have a stored name; the hashed id is still there


def test_clear_this_entity_and_clear_all(store):
    store.add_many([rec(entity="a"), rec(1, entity="a"), rec(entity="b")])
    assert store.clear_entity("a") == 2 and {r.entity_id for r in store.records()} == {"b"}
    assert store.clear_all() == 1 and not os.path.exists(store.path)
    assert store.add_many([rec()]).written == 1                  # starts again cleanly


def test_stats_report_rows_bytes_oldest_newest(store):
    store.add_many([rec(5), rec(0)])
    s = store.stats()
    assert (s.rows, s.oldest, s.newest, s.retention_hours) == (2, ts(5), ts(0), 24) and s.bytes > 0 and s.max_rows == 20000 and s.max_bytes == 5 * 1024 * 1024


def test_nothing_in_the_module_can_reach_the_network():
    src = open(H.__file__).read()
    for word in ("requests", "urllib", "socket", "http.client"):
        assert word not in src


def test_an_unwritable_profile_folder_is_a_reported_error_not_an_exception(tmp_path):
    (tmp_path / "file").write_text("x")
    rep = HistoryStore(str(tmp_path / "file" / "sub" / "h.sqlite"), clock=lambda: NOW).add_many([rec()])
    assert rep.error == "disk_full" and "cannot be created or written" in rep.message


# --- names kept on this computer; the shared contract is required ---------------------------------------------------------------------------

def test_display_names_are_kept_locally_next_to_the_hashed_id_and_cleared_with_it(store):
    hashed = store.entity_hash("my-site")
    store.add_many([rec(entity=hashed, entity_type="site"), rec(entity="public-1")])
    store.set_labels({hashed: "Hilltop North", "public-1": "FCC 1"})
    assert store.labels() == {hashed: "Hilltop North", "public-1": "FCC 1"} and hashed not in "Hilltop North"
    store.set_labels({hashed: "Hilltop N."})                               # a rename replaces, not duplicates
    assert store.labels()[hashed] == "Hilltop N."
    store.clear_entity(hashed)
    assert hashed not in store.labels() and "public-1" in store.labels()
    store.set_labels({})                                                   # nothing to do, no error


def test_labels_of_pruned_entities_are_dropped_with_their_rows(tmp_path):
    s = HistoryStore(str(tmp_path / "h.sqlite"), clock=lambda: NOW)
    s.add_many([rec(23, entity="old"), rec(0, entity="new")])
    s.set_labels({"old": "Old site", "new": "New site"})
    s.set_retention_hours(12)                                              # prunes "old"
    assert s.labels() == {"new": "New site"}


def test_a_name_is_capped_and_a_file_without_labels_table_gets_one(tmp_path):
    path = str(tmp_path / "h.sqlite")
    s = HistoryStore(path, clock=lambda: NOW)
    s.add_many([rec()])
    con = sqlite3.connect(path); con.execute("DROP TABLE entity_labels"); con.commit(); con.close()    # a file from before names were stored
    s.set_labels({"s1": "x" * 500})
    assert len(s.labels()["s1"]) == 200


def test_without_the_shared_contract_history_is_off_with_a_plain_instruction_and_nothing_raises(tmp_path, monkeypatch):
    def missing():
        raise H.HistoryUnavailable()
    monkeypatch.setattr(H, "_contract", missing)
    s = HistoryStore(str(tmp_path / "h.sqlite"), clock=lambda: NOW)
    report = s.add_many([rec()])
    assert report.error == "unavailable" and report.written == 0 and "aei-history-contract" in report.user_text() and "Python Console" in report.user_text()
    assert not H.contract_available()
