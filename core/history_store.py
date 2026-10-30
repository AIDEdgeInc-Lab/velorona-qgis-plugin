"""Customer-owned local history: what the weather analyses fetched and computed, kept in a SQLite file on THIS machine and nowhere else.

Implements the HistoryRecord of the shared CONTRACT (schema 1): one row per (entity, metric, kind, source, time); the time is the time the value
is FOR (UTC, ``...Z``), not when it was fetched; ``value`` NULL means NO DATA, never 0. ``kind`` is observed | forecast | model (nothing writes
``forecast`` today: the plugin does not use a forecast).

Nothing here touches the network, QGIS or the user's project: the file is ``<QGIS profile>/velorona/history.sqlite``. No function takes or
returns anything that is sent anywhere.

Failure modes (each returns a ``WriteReport``/raises ``HistoryError`` with a plain reason; history never makes an analysis fail):
* database locked by another process: a 2 s busy timeout, then ``error="locked"``, nothing written, existing rows untouched;
* disk full / read-only: ``error="disk_full"`` (SQLite rolls the transaction back, so the file is never left half-written);
* corrupt or foreign file: the file is renamed ``history.corrupt-<UTC>.sqlite`` (kept, not deleted) and a new one started; ``recovered`` says so;
* clock skew: values whose UTC time is more than 10 minutes AHEAD of this computer's clock (and are not forecasts) are NOT stored and are
  counted in ``rejected_future`` with ``skew_suspected=True``; pruning never uses a clock that is behind the newest stored row.
"""

from __future__ import annotations

import os
import re
import secrets
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple


SCHEMA_VERSION = 1
DEFAULT_RETENTION_HOURS = 24
MIN_RETENTION_HOURS, MAX_RETENTION_HOURS = 1, 24 * 7
DEFAULT_MAX_ROWS = 20_000
DEFAULT_MAX_BYTES = 5 * 1024 * 1024
FUTURE_TOLERANCE_S = 10 * 60
BUSY_TIMEOUT_S = 2.0
TS_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
_TS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class HistoryError(Exception):
    """A history operation could not be done; ``code`` is locked | disk_full | corrupt | invalid | unavailable | other. The message is for the user."""

    def __init__(self, message: str, code: str = "other"):
        super().__init__(message)
        self.code = code


class HistoryUnavailable(HistoryError):
    """The shared ``aei-history-contract`` package is not installed, so history is switched off (analyses are not affected)."""

    def __init__(self):
        super().__init__("Local history needs the Python package aei-history-contract. In QGIS: Plugins > Python Console, run:  from pip._internal.cli.main "
                         "import main; main(['install', '-U', 'aei-history-contract>=0.2.0,<0.3'])  then restart QGIS. Your analyses are not affected.",
                         "unavailable")


def _contract():
    try:
        import aei_history_contract
    except ImportError as exc:
        raise HistoryUnavailable() from exc
    return aei_history_contract


def contract_available() -> bool:
    try:
        _contract()
        return True
    except HistoryUnavailable:
        return False


def utc_text(epoch_s: float) -> str:
    return datetime.fromtimestamp(float(epoch_s), timezone.utc).strftime(TS_FORMAT)


def parse_utc(text: str) -> float:
    if not isinstance(text, str) or not _TS.match(text):
        raise ValueError(f"not a UTC time like 2026-10-29T14:00:00Z: {text!r}")
    return datetime.strptime(text, TS_FORMAT).replace(tzinfo=timezone.utc).timestamp()


def to_utc_text(local_text: str, utc_offset_seconds: int) -> str:
    """A provider time written in the site's local time ("2026-10-29T14:00") plus its offset east of UTC -> UTC text."""
    t = datetime.strptime(local_text[:16], "%Y-%m-%dT%H:%M") - timedelta(seconds=int(utc_offset_seconds))
    return t.strftime(TS_FORMAT)


@dataclass(frozen=True)
class HistoryRecord:
    ts: str
    source: str
    entity_id: str
    metric: str
    value: object                      # float | str | None (None = NO DATA)
    unit: str
    kind: str
    data_version: str
    fetched_ts: Optional[str] = None
    entity_type: str = "site"
    derived: bool = False
    nodata_reason: Optional[str] = None

    def to_dict(self) -> dict:
        """The contract's plain-dict form of a HistoryRecord (optional fields only when set)."""
        d = {"ts": self.ts, "source": self.source, "entity_id": self.entity_id, "entity_type": self.entity_type, "metric": self.metric,
             "value": self.value, "unit": self.unit, "kind": self.kind, "derived": bool(self.derived), "data_version": self.data_version}
        if self.fetched_ts is not None:
            d["fetched_ts"] = self.fetched_ts
        if self.nodata_reason is not None:
            d["nodata_reason"] = self.nodata_reason
        return d

    def check(self) -> None:
        """Validated by the shared contract (``validate_record``), the same rules the Map applies."""
        if isinstance(self.value, float) and self.value != self.value:
            raise ValueError("NaN is not a value; use None for NO DATA")
        problems = _contract().validate_record(self.to_dict())
        if problems:
            raise ValueError("; ".join(problems))


@dataclass
class WriteReport:
    written: int = 0
    duplicates: int = 0
    rejected_future: int = 0
    invalid: int = 0
    skew_suspected: bool = False
    pruned: int = 0
    error: Optional[str] = None            # locked | disk_full | corrupt | other
    message: str = ""
    recovered: Optional[str] = None        # path the corrupt file was moved to

    @property
    def ok(self) -> bool:
        return self.error is None

    def user_text(self) -> str:
        parts = []
        if self.error:
            parts.append(f"History was not saved: {self.message}")
        if self.skew_suspected:
            parts.append(f"{self.rejected_future} value(s) were not stored because their time is ahead of this computer's clock; check the clock.")
        if self.recovered:
            parts.append(f"The history file was unreadable and was set aside as {os.path.basename(self.recovered)}; a new one was started.")
        return " ".join(parts)


@dataclass(frozen=True)
class Stats:
    rows: int
    bytes: int
    oldest: Optional[str]
    newest: Optional[str]
    retention_hours: int
    max_rows: int
    max_bytes: int


_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS history (
    ts TEXT NOT NULL, fetched_ts TEXT, source TEXT NOT NULL, entity_id TEXT NOT NULL, entity_type TEXT NOT NULL DEFAULT 'site',
    metric TEXT NOT NULL, value_num REAL, value_text TEXT, unit TEXT NOT NULL, kind TEXT NOT NULL, derived INTEGER NOT NULL DEFAULT 0,
    data_version TEXT NOT NULL, nodata_reason TEXT,
    PRIMARY KEY (entity_id, metric, kind, source, ts)
);
CREATE INDEX IF NOT EXISTS history_ts ON history (ts);
CREATE TABLE IF NOT EXISTS entity_labels (entity_id TEXT PRIMARY KEY, label TEXT NOT NULL, updated_ts TEXT NOT NULL);
"""


class HistoryStore:
    """One SQLite file. A connection is opened per operation (analyses run in worker threads); every write is one transaction."""

    def __init__(self, path: str, clock: Callable[[], float] = time.time,
                 max_rows: int = DEFAULT_MAX_ROWS, max_bytes: int = DEFAULT_MAX_BYTES):
        self.path, self._clock = path, clock
        self.max_rows, self.max_bytes = int(max_rows), int(max_bytes)
        self.recovered: Optional[str] = None

    # -- connection ---------------------------------------------------------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        except OSError as exc:
            raise HistoryError(f"the history folder cannot be created or written ({exc.strerror or exc})", "disk_full") from exc
        try:
            con = sqlite3.connect(self.path, timeout=BUSY_TIMEOUT_S)
            con.executescript(_SCHEMA)
            row = con.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
            if row is None:
                con.execute("INSERT INTO meta VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
                con.execute("INSERT OR IGNORE INTO meta VALUES ('salt', ?)", (secrets.token_hex(16),))
                con.commit()
            elif int(row[0]) > SCHEMA_VERSION:
                con.close()
                raise HistoryError(f"this history file was written by a newer Velorona (schema {row[0]}); it is left untouched", "invalid")
            return con
        except sqlite3.DatabaseError as exc:
            if self._is_locked(exc):
                raise HistoryError("the history database is in use by another process; try again in a moment", "locked") from exc
            if self._is_full(exc):
                raise HistoryError("the disk is full or the profile folder is read-only", "disk_full") from exc
            return self._recover(exc)

    @staticmethod
    def _is_locked(exc) -> bool:
        return isinstance(exc, sqlite3.OperationalError) and ("locked" in str(exc).lower() or "busy" in str(exc).lower())

    @staticmethod
    def _is_full(exc) -> bool:
        text = str(exc).lower()
        return isinstance(exc, sqlite3.OperationalError) and ("full" in text or "readonly" in text or "read-only" in text or "disk i/o" in text)

    def _recover(self, exc) -> sqlite3.Connection:
        """Not a database (or damaged): keep the file under a new name, never delete it, start a fresh one."""
        aside = f"{os.path.splitext(self.path)[0]}.corrupt-{time.strftime('%Y%m%dT%H%M%S', time.gmtime(self._clock()))}.sqlite"
        try:
            os.replace(self.path, aside)
        except OSError as os_exc:
            raise HistoryError(f"the history file is unreadable ({exc}) and could not be set aside ({os_exc})", "corrupt") from exc
        self.recovered = aside
        return self._connect()

    # -- settings -----------------------------------------------------------------------------------------------------------------------

    def retention_hours(self) -> int:
        with self._open() as con:
            row = con.execute("SELECT value FROM meta WHERE key='retention_hours'").fetchone()
        return int(row[0]) if row else DEFAULT_RETENTION_HOURS

    def set_retention_hours(self, hours: int) -> int:
        """Refuses a value outside 1 h to 7 d instead of clamping it (a clamped value would not be the one the user chose)."""
        if isinstance(hours, bool) or int(hours) != hours or not MIN_RETENTION_HOURS <= hours <= MAX_RETENTION_HOURS:
            raise HistoryError(f"retention must be a whole number of hours from {MIN_RETENTION_HOURS} to {MAX_RETENTION_HOURS}", "invalid")
        with self._open() as con:
            con.execute("INSERT OR REPLACE INTO meta VALUES ('retention_hours', ?)", (str(int(hours)),))
            con.commit()
            self._prune(con, WriteReport())
        return int(hours)

    def entity_hash(self, raw_id: str) -> str:
        """A salted hash for an entity the user supplied (their own sites/links): the id itself is not stored (CONTRACT: private entities)."""
        import hashlib
        with self._open() as con:
            salt = con.execute("SELECT value FROM meta WHERE key='salt'").fetchone()[0]
        return "h:" + hashlib.sha256((salt + "|" + raw_id).encode("utf-8")).hexdigest()[:16]

    # -- writing ------------------------------------------------------------------------------------------------------------------------

    def add_many(self, records: Iterable[HistoryRecord]) -> WriteReport:
        report = WriteReport()
        try:
            _contract()
        except HistoryUnavailable as exc:
            report.error, report.message = exc.code, str(exc)
            return report
        now = self._clock()
        good: List[HistoryRecord] = []
        for r in records:
            try:
                r.check()
            except ValueError:
                report.invalid += 1
                continue
            if r.kind != "forecast" and parse_utc(r.ts) > now + FUTURE_TOLERANCE_S:
                report.rejected_future += 1
                report.skew_suspected = True
                continue
            good.append(r)
        if not good:
            return report
        try:
            with self._open() as con:
                for r in good:
                    num = r.value if isinstance(r.value, (int, float)) else None
                    text = r.value if isinstance(r.value, str) else None
                    cur = con.execute(
                        "INSERT OR IGNORE INTO history (ts, fetched_ts, source, entity_id, entity_type, metric, value_num, value_text, unit, kind, derived,"
                        " data_version, nodata_reason) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (r.ts, r.fetched_ts, r.source, r.entity_id, r.entity_type, r.metric, num, text, r.unit, r.kind, int(r.derived),
                         r.data_version, r.nodata_reason))
                    if cur.rowcount:
                        report.written += 1
                    else:
                        report.duplicates += 1
                con.commit()
                self._prune(con, report)
        except HistoryError as exc:
            report.error, report.message = exc.code, str(exc)
        except sqlite3.DatabaseError as exc:
            report.error = "locked" if self._is_locked(exc) else "disk_full" if self._is_full(exc) else "other"
            report.message = {"locked": "the history database is in use by another process; try again in a moment",
                              "disk_full": "the disk is full or the profile folder is read-only; nothing was changed"}.get(report.error, str(exc))
            report.written = 0
        report.recovered = self.recovered
        return report

    def _open(self):
        """Context-managed connection that always closes (sqlite3's own context manager only commits)."""
        store = self

        class _Ctx:
            def __enter__(self_inner):
                self_inner.con = store._connect()
                return self_inner.con

            def __exit__(self_inner, *exc):
                self_inner.con.close()
                return False
        return _Ctx()

    def _reference_time(self, con) -> float:
        """'Now' for pruning. Never earlier than the newest stored fetch time, so a clock set back cannot make old rows look new for ever
        or stop pruning from ever happening."""
        now = self._clock()
        row = con.execute("SELECT MAX(fetched_ts) FROM history").fetchone()
        if row and row[0]:
            now = max(now, parse_utc(row[0]))
        return now

    def _prune(self, con, report: WriteReport) -> None:
        """Retention and the row/size caps are the contract's ``prune`` (one definition, shared with the Map); this only applies its answer to SQLite.
        The size cap is the contract's: the UTF-8 length of each row's canonical text, not the SQLite file size (the file is a few times larger)."""
        retention = con.execute("SELECT value FROM meta WHERE key='retention_hours'").fetchone()
        hours = int(retention[0]) if retention else DEFAULT_RETENTION_HOURS
        rows = self._rows(con)
        kept, dropped = _contract().prune([r.to_dict() for r in rows], utc_text(self._reference_time(con)), hours, self.max_rows, self.max_bytes)
        if dropped:
            keep = {(k["entity_id"], k["metric"], k["kind"], k["source"], k["ts"]) for k in kept}
            gone = [(r.entity_id, r.metric, r.kind, r.source, r.ts) for r in rows if (r.entity_id, r.metric, r.kind, r.source, r.ts) not in keep]
            con.executemany("DELETE FROM history WHERE entity_id=? AND metric=? AND kind=? AND source=? AND ts=?", gone)
            report.pruned += len(gone)
            con.execute("DELETE FROM entity_labels WHERE entity_id NOT IN (SELECT DISTINCT entity_id FROM history)")
            con.commit()
            con.execute("VACUUM")

    @staticmethod
    def _file_bytes(con) -> int:
        return con.execute("PRAGMA page_count").fetchone()[0] * con.execute("PRAGMA page_size").fetchone()[0]

    # -- display names (local only) -----------------------------------------------------------------------------------------------------

    def set_labels(self, labels: Dict[str, str]) -> None:
        """Remember the names the user sees for their own sites and links (the stored id is a salted hash). They stay in this file, on this computer."""
        clean = {k: str(v)[:200] for k, v in (labels or {}).items() if k and v}
        if not clean:
            return
        now = utc_text(self._clock())
        with self._open() as con:
            con.executemany("INSERT OR REPLACE INTO entity_labels VALUES (?,?,?)", [(k, v, now) for k, v in clean.items()])
            con.commit()

    def labels(self) -> Dict[str, str]:
        with self._open() as con:
            return dict(con.execute("SELECT entity_id, label FROM entity_labels").fetchall())

    # -- reading ------------------------------------------------------------------------------------------------------------------------

    @staticmethod
    def _rows(con, entity_id: Optional[str] = None, since_ts: Optional[str] = None) -> List[HistoryRecord]:
        sql = ("SELECT ts, fetched_ts, source, entity_id, entity_type, metric, value_num, value_text, unit, kind, derived, data_version, nodata_reason "
               "FROM history")
        where, args = [], []
        if entity_id is not None:
            where.append("entity_id = ?"); args.append(entity_id)
        if since_ts is not None:
            where.append("ts >= ?"); args.append(since_ts)
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY ts ASC, entity_id, metric, kind, source"
        return [HistoryRecord(ts=r[0], fetched_ts=r[1], source=r[2], entity_id=r[3], entity_type=r[4], metric=r[5],
                              value=(r[6] if r[6] is not None else r[7]), unit=r[8], kind=r[9], derived=bool(r[10]), data_version=r[11],
                              nodata_reason=r[12]) for r in con.execute(sql, args).fetchall()]

    def records(self, entity_id: Optional[str] = None, since_ts: Optional[str] = None) -> List[HistoryRecord]:
        with self._open() as con:
            return self._rows(con, entity_id, since_ts)

    def entities(self) -> List[Tuple[str, str, int, str]]:
        """[(entity_id, entity_type, rows, newest ts)], most recently updated first."""
        with self._open() as con:
            return con.execute("SELECT entity_id, entity_type, COUNT(*), MAX(ts) FROM history GROUP BY entity_id, entity_type ORDER BY MAX(ts) DESC").fetchall()

    def stats(self) -> Stats:
        with self._open() as con:
            rows, oldest, newest = con.execute("SELECT COUNT(*), MIN(ts), MAX(ts) FROM history").fetchone()
            size = sum(_contract().approx_bytes(r.to_dict()) for r in self._rows(con)) if rows else 0   # the contract's size measure, as used by the cap
        return Stats(rows, size, oldest, newest, self.retention_hours(), self.max_rows, self.max_bytes)

    # -- clearing -----------------------------------------------------------------------------------------------------------------------

    def clear_entity(self, entity_id: str) -> int:
        with self._open() as con:
            n = con.execute("DELETE FROM history WHERE entity_id = ?", (entity_id,)).rowcount
            con.execute("DELETE FROM entity_labels WHERE entity_id = ?", (entity_id,))
            con.commit()
        return n

    def clear_all(self) -> int:
        """Deletes every row AND the file (with its salt), then the next write starts a new one."""
        n = self.stats().rows if os.path.exists(self.path) else 0
        for suffix in ("", "-journal", "-wal", "-shm"):
            try:
                os.remove(self.path + suffix)
            except FileNotFoundError:
                pass
            except OSError as exc:
                raise HistoryError(f"could not delete {os.path.basename(self.path + suffix)}: {exc}", "other") from exc
        return n

    # -- export -------------------------------------------------------------------------------------------------------------------------

    def export_csv(self, entity_id: Optional[str] = None) -> Tuple[str, str]:
        """(file name, CSV text) from the contract's ``to_csv`` / ``csv_filename``: schema-order columns (incl. the optional entity_label), UTC, RFC 4180 quoting, formula-injection guard.
        A local file only."""
        c = _contract()
        names = self.labels()
        rows = []
        for r in self.records(entity_id):
            d = r.to_dict()
            if names.get(r.entity_id):
                d["entity_label"] = names[r.entity_id]   # the user's own name for the site/link, next to the hashed id (contract 0.2.0)
            rows.append(d)
        text = c.to_csv(rows)
        return c.csv_filename(entity_id or "all", utc_text(self._clock())), text


def default_path(profile_dir: str) -> str:
    return os.path.join(profile_dir, "velorona", "history.sqlite")
