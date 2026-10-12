"""Orbital-data ingestion and cache -- QGIS-free, no network of its own.

Python counterpart of Velorona Map's web/orbitdata.js: the same record classification, the same duplicate rule, the same request policy, the same
result fields, tested against the Map's own output on a shared fixture (tests/test_orbit_data.py). It does not fetch anything itself: the caller
passes a `fetch(url) -> FetchResult` (the QGIS network stack in the plugin; a fake in tests), so nothing here depends on `requests` or QGIS.

What it does
  * parses OMM JSON (the format that carries catalog ids above 99999) and classifies every record: valid / incomplete (a required field absent) /
    invalid (present but unusable). Missing is never filled in; nothing is invented.
  * keeps ONE record per catalog id: the NEWEST epoch wins (not the last record read).
  * counts what was retrieved, what is valid and unique, what was rejected, and the age of the element sets.
  * a persistent cache that stores a response ONLY after it parsed, with the real retrieval time; a response older than the refresh interval is
    returned as "stale", never as fresh.
  * request policy (CelesTrak's published rules as last seen in search excerpts; not re-read from the source): at most one request per call;
    after ANY non-200 answer, unusable body, network error or timeout the source is not asked again until a back-off has passed
    (Retry-After, else 15 min; network error or timeout 60 s). The back-off is stored in the cache directory so a restart does not skip it.

What it does not do: it does not wire into the plugin's UI or network stack (that needs a real QGIS to verify), propagate orbits, or accept CSV/TLE.
Orbit records are untrusted input: names are cleaned of control characters and nothing is evaluated.
"""

from __future__ import annotations

import json
import math
import os
import re
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, List, Optional, Tuple

SCHEMA_VERSION = "1.0"
SOURCE_ID = "celestrak-gp"
SOURCE_NAME = "CelesTrak GP element sets"
SOURCE_ENDPOINT = "https://celestrak.org/NORAD/elements/gp.php"
MAX_PAYLOAD_CHARS = 30 * 1024 * 1024
MAX_RECORDS = 60000
DEFAULT_TTL_S = 2 * 3600
BACKOFF_HTTP_S = 15 * 60
BACKOFF_NETWORK_S = 60

# id used by the plugin -> the CelesTrak GROUP value. Kept equal to GROUP_REGISTRY in the Map's web/orbitdata.js (the names are UNVERIFIED there too).
GROUPS: Dict[str, str] = {
    "geo": "geo", "intelsat": "intelsat", "ses": "ses", "eutelsat": "eutelsat", "telesat": "telesat",
    "starlink": "starlink", "oneweb": "oneweb", "kuiper": "kuiper", "iridium-next": "iridium-NEXT", "globalstar": "globalstar", "orbcomm": "orbcomm", "planet": "planet",
}

_ORBIT_FIELDS = ("MEAN_MOTION", "ECCENTRICITY", "INCLINATION", "RA_OF_ASC_NODE", "ARG_OF_PERICENTER", "MEAN_ANOMALY", "BSTAR")
_RANGES = {"MEAN_MOTION": (0.0001, 20.0), "ECCENTRICITY": (0.0, 1.0), "INCLINATION": (0.0, 180.0), "RA_OF_ASC_NODE": (0.0, 360.0),
           "ARG_OF_PERICENTER": (0.0, 360.0), "MEAN_ANOMALY": (0.0, 360.0)}
_OPTIONAL = ("MEAN_MOTION_DOT", "MEAN_MOTION_DDOT", "ELEMENT_SET_NO", "REV_AT_EPOCH", "EPHEMERIS_TYPE")
_EPOCH_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?\s*(Z|[+-]\d{2}:?\d{2})?$", re.I)
_CTRL = re.compile(r"[\x00-\x1f\x7f]")


class GpPayloadError(Exception):
    """The response as a whole is unusable (per-record problems are classified, not raised). `code` is one of bad_payload, too_large, malformed."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _blank(v) -> bool:
    return v is None or (isinstance(v, str) and v.strip() == "")


def parse_epoch_utc(value) -> Optional[datetime]:
    """OMM epochs carry no zone: they are UTC, never local time. None if unparseable."""
    if not isinstance(value, str):
        return None
    m = _EPOCH_RE.match(value.strip())
    if not m:
        return None
    y, mo, d, h, mi, s, frac, zone = m.groups()
    try:
        dt = datetime(int(y), int(mo), int(d), int(h), int(mi), int(s), int((frac or "0").ljust(6, "0")[:6]), tzinfo=timezone.utc)
    except ValueError:
        return None
    if zone and zone.upper() != "Z":
        sign = 1 if zone[0] == "+" else -1
        digits = zone[1:].replace(":", "")
        dt -= sign * timedelta(hours=int(digits[:2]), minutes=int(digits[2:4]))
    return dt


def iso_ms(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_catalog_id(value) -> dict:
    """1-9 digits. Ids above 99999 are valid in OMM but cannot be written as a TLE."""
    if _blank(value):
        return {"missing": True}
    s = str(value).strip()
    if isinstance(value, bool) or not re.fullmatch(r"\d{1,9}", s):
        return {"invalid": True}
    return {"value": int(s), "text": s, "legacy_tle_compatible": int(s) <= 99999}


def _num(raw: dict, key: str, issues: list):
    v = raw.get(key)
    if _blank(v):
        return {"missing": True}
    if isinstance(v, bool):
        issues.append({"field": key, "kind": "invalid", "detail": "not a finite number"})
        return {"invalid": True}
    try:
        n = float(v) if isinstance(v, (int, float)) else float(str(v).strip())
    except ValueError:
        n = math.nan
    if not math.isfinite(n):
        issues.append({"field": key, "kind": "invalid", "detail": "not a finite number"})
        return {"invalid": True}
    return {"value": n}


def normalize_record(raw, source: Optional[str] = None, retrieved_at: Optional[str] = None, group: Optional[str] = None) -> dict:
    """{status: valid|incomplete|invalid, record|None, issues[]} -- the same rules as the Map's normalizeOmmRecord()."""
    issues: list = []
    if not isinstance(raw, dict):
        return {"status": "invalid", "record": None, "issues": [{"field": "(record)", "kind": "invalid", "detail": "not an object"}]}
    missing = invalid = False
    cid = parse_catalog_id(raw.get("NORAD_CAT_ID"))
    if cid.get("missing"):
        missing = True; issues.append({"field": "NORAD_CAT_ID", "kind": "missing", "detail": "no catalog id"})
    elif cid.get("invalid"):
        invalid = True; issues.append({"field": "NORAD_CAT_ID", "kind": "invalid", "detail": "not a 1-9 digit integer"})
    epoch = None
    if _blank(raw.get("EPOCH")):
        missing = True; issues.append({"field": "EPOCH", "kind": "missing", "detail": "no epoch"})
    else:
        epoch = parse_epoch_utc(str(raw.get("EPOCH")))
        if epoch is None:
            invalid = True; issues.append({"field": "EPOCH", "kind": "invalid", "detail": "unparseable epoch"})
    el: Dict[str, float] = {}
    for k in _ORBIT_FIELDS:
        r = _num(raw, k, issues)
        if r.get("missing"):
            missing = True; issues.append({"field": k, "kind": "missing", "detail": "required for propagation"}); continue
        if r.get("invalid"):
            invalid = True; continue
        el[k] = r["value"]
        rng = _RANGES.get(k)
        if rng and (r["value"] < rng[0] or r["value"] > rng[1] or (k == "ECCENTRICITY" and r["value"] >= 1)):
            invalid = True; issues.append({"field": k, "kind": "invalid", "detail": f"outside {rng[0]:g}..{rng[1]:g}"})
    optional = {}
    for k in _OPTIONAL:
        r = _num(raw, k, issues)
        if "value" in r:
            optional[k] = r["value"]
    name = None if _blank(raw.get("OBJECT_NAME")) else _CTRL.sub(" ", str(raw["OBJECT_NAME"])).strip()[:100]
    if not name:
        name = None
        issues.append({"field": "OBJECT_NAME", "kind": "missing", "detail": "no name (record still usable)"})
    if invalid:
        return {"status": "invalid", "record": None, "issues": issues}
    if missing:
        return {"status": "incomplete", "record": None, "issues": issues}
    return {"status": "valid", "issues": issues, "record": {
        "schema_version": SCHEMA_VERSION, "satellite_id": cid["value"], "satellite_id_text": cid["text"], "legacy_tle_compatible": cid["legacy_tle_compatible"],
        "satellite_name": name, "international_designator": None if _blank(raw.get("OBJECT_ID")) else str(raw["OBJECT_ID"]).strip(),
        "orbit_epoch_utc": iso_ms(epoch), "orbit_source": source, "retrieved_at_utc": retrieved_at, "group": group, "elements": {**el, **optional}, "gp": raw}}


def parse_gp_json(text) -> list:
    """The response body as a list of record dicts; [] for an empty body or the provider's plain 'No GP data found'."""
    if not isinstance(text, str):
        raise GpPayloadError("bad_payload", "payload is not text")
    if len(text) > MAX_PAYLOAD_CHARS:
        raise GpPayloadError("too_large", "payload exceeds size limit")
    body = text.strip()
    if not body or re.match(r"^no gp data found", body, re.I):
        return []
    try:
        data = json.loads(body)
    except ValueError:
        raise GpPayloadError("malformed", "malformed JSON") from None
    if not isinstance(data, list):
        raise GpPayloadError("malformed", "JSON root is not an array")
    if len(data) > MAX_RECORDS:
        raise GpPayloadError("too_large", "record count exceeds limit")
    return data


def ingest(raw_records: list, now: datetime, source: Optional[str] = None, retrieved_at: Optional[str] = None, group: Optional[str] = None) -> Tuple[List[dict], dict]:
    """(unique valid records, report). Duplicates resolve to the NEWEST epoch; ties keep the first."""
    counts = {"retrieved": len(raw_records), "valid": 0, "incomplete": 0, "invalid": 0, "duplicates": 0, "unique_valid": 0, "beyond_legacy_tle": 0}
    by_id: Dict[int, dict] = {}
    rejected: list = []
    for index, raw in enumerate(raw_records):
        r = normalize_record(raw, source, retrieved_at, group)
        if r["status"] != "valid":
            counts[r["status"]] += 1
            if len(rejected) < 50:
                rejected.append({"index": index, "status": r["status"], "issues": [i for i in r["issues"] if i["kind"] != "missing" or r["status"] == "incomplete"]})
            continue
        counts["valid"] += 1
        rec = r["record"]
        prev = by_id.get(rec["satellite_id"])
        if prev is not None:
            counts["duplicates"] += 1
            if parse_epoch_utc(rec["orbit_epoch_utc"]) > parse_epoch_utc(prev["orbit_epoch_utc"]):
                by_id[rec["satellite_id"]] = rec
        else:
            by_id[rec["satellite_id"]] = rec
    records = list(by_id.values())
    counts["unique_valid"] = len(records)
    counts["beyond_legacy_tle"] = sum(1 for r in records if not r["legacy_tle_compatible"])
    ages = sorted((now - parse_epoch_utc(r["orbit_epoch_utc"])).total_seconds() / 86400.0 for r in records)

    def q(p: float):
        return round(ages[min(len(ages) - 1, int(p * len(ages)))], 3) if ages else None
    report = {"counts": counts, "epoch_age_days": {"min": round(ages[0], 3) if ages else None, "median": q(0.5), "p95": q(0.95), "max": round(ages[-1], 3) if ages else None},
              "rejected_sample": rejected,
              "note": "unique_valid counts records that PARSED and passed range checks; it is not a count of satellites validated through propagation or any workflow."}
    return records, report


@dataclass
class FetchResult:
    """What the caller's network layer returns. status None means the request did not complete (error is then 'timeout' or 'network')."""
    status: Optional[int] = None
    text: Optional[str] = None
    headers: Dict[str, str] = field(default_factory=dict)
    error: Optional[str] = None


class OrbitCache:
    """One JSON file per group in `directory` (the plugin passes its own settings folder; never a shared, predictable temp path).
    A cache entry is written only for a response that parsed; writes are atomic; a corrupt or unreadable file behaves as empty."""

    def __init__(self, directory: str):
        self.directory = directory

    def _path(self, group: str) -> str:
        if group not in GROUPS:
            raise ValueError(f"unknown group {group!r}")        # also keeps any path component out of the file name
        return os.path.join(self.directory, f"orbit_{group}.json")

    def read(self, group: str) -> Optional[dict]:
        try:
            with open(self._path(group), encoding="utf-8") as fh:
                e = json.load(fh)
        except (OSError, ValueError):
            return None
        return e if isinstance(e, dict) and e.get("schema_version") == SCHEMA_VERSION and e.get("group") == group else None

    def write(self, group: str, entry: dict) -> bool:
        entry = {**entry, "schema_version": SCHEMA_VERSION, "group": group}
        if entry.get("raw") is not None and (not isinstance(entry["raw"], list) or parse_epoch_utc(entry.get("retrieved_at_utc")) is None):
            return False                                        # never store something that is not a parsed record list with a real retrieval time
        try:
            os.makedirs(self.directory, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=self.directory, prefix=".orbit_", suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(entry, fh)
            os.replace(tmp, self._path(group))
            return True
        except OSError:
            return False


def _result(status: str, entry: dict, now: datetime, extra: Optional[dict] = None) -> dict:
    records, report = ingest(entry["raw"], now, SOURCE_ID, entry["retrieved_at_utc"], entry["group"])
    out = {"status": status, "group": entry["group"], "retrieved_at_utc": entry["retrieved_at_utc"],
           "age_seconds": round((now - parse_epoch_utc(entry["retrieved_at_utc"])).total_seconds()), "source_path": "qgis-direct", "request_url": entry.get("request_url"),
           "upstream_status": entry.get("upstream_status"), "records": records, "report": report, "warnings": []}
    out.update(extra or {})
    return out


def load_group(group: str, fetch: Callable[[str], FetchResult], cache: OrbitCache, now: datetime, ttl_s: int = DEFAULT_TTL_S) -> dict:
    """status: fresh | stale | unavailable -- the same semantics as the Map's provider.loadGroup()."""
    if group not in GROUPS:
        return {"status": "unavailable", "group": group, "records": [], "report": None, "warnings": [f'unknown group "{group}"'], "reason": "unknown_group"}
    cached = cache.read(group)
    t = now.timestamp()
    has_data = bool(cached and cached.get("raw") is not None and parse_epoch_utc(cached.get("retrieved_at_utc")))
    if has_data and t - parse_epoch_utc(cached["retrieved_at_utc"]).timestamp() < ttl_s:
        return _result("fresh", cached, now, {"from_cache": True})
    not_before = (cached or {}).get("not_before")
    if has_data and not_before and t < not_before:
        return _result("stale", cached, now, {"from_cache": True, "reason": "backoff", "warnings": [f"not asking the source again until {iso_ms(datetime.fromtimestamp(not_before, timezone.utc))}"]})
    if not has_data and not_before and t < not_before:
        return {"status": "unavailable", "group": group, "records": [], "report": None, "reason": "backoff",
                "warnings": [f"not asking the source again until {iso_ms(datetime.fromtimestamp(not_before, timezone.utc))} (it did not give usable data last time)"]}

    url = f"{SOURCE_ENDPOINT}?GROUP={GROUPS[group]}&FORMAT=json"

    def fail(reason: str, warning: str, block_s: int, extra: Optional[dict] = None):
        cache.write(group, {**(cached if has_data else {}), "not_before": t + block_s})
        if has_data:
            return _result("stale", cached, now, {"from_cache": True, "reason": reason, "warnings": [warning, "showing cached data older than its refresh interval"], **(extra or {})})
        return {"status": "unavailable", "group": group, "records": [], "report": None, "warnings": [warning], "reason": reason, "request_url": url, **(extra or {})}

    r = fetch(url)
    if r.status is None:
        return fail(r.error or "network", "request timed out" if r.error == "timeout" else "network error", BACKOFF_NETWORK_S)
    if r.status != 200:
        try:
            ra = float((r.headers or {}).get("Retry-After", ""))
        except ValueError:
            ra = 0.0
        return fail(f"http_{r.status}", f"source refused the request (HTTP {r.status})" if r.status in (403, 429) else f"source returned HTTP {r.status}",
                    int(ra) if ra > 0 else BACKOFF_HTTP_S, {"upstream_status": r.status})
    try:
        raw = parse_gp_json(r.text)
    except GpPayloadError as e:
        return fail(e.code, f"response could not be parsed ({e})", BACKOFF_HTTP_S, {"upstream_status": 200})
    entry = {"raw": raw, "retrieved_at_utc": iso_ms(now), "request_url": url, "upstream_status": 200, "not_before": None, "source": SOURCE_ID}
    cache.write(group, entry)
    out = _result("fresh", {**entry, "group": group}, now, {"from_cache": False})
    c = out["report"]["counts"]
    if c["retrieved"] == 0:
        out["warnings"].append("source returned an empty group")
    if c["invalid"] + c["incomplete"]:
        out["warnings"].append(f"{c['invalid'] + c['incomplete']} of {c['retrieved']} records were rejected (see report)")
    return out
