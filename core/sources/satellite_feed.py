"""Satellite layer feed: validated OMM ingestion -> layer rows. QGIS-free (skyfield/sgp4/requests only), so it is unit-testable without a QGIS runtime.

What this replaces: space_public.fetch_celestrak_satellites(), which fetched five groups as TLE on every refresh (no cache, no back-off after a failure,
catalog id cut from TLE columns 3-7) and refreshed every 10 minutes. This module reuses orbit_data (validation, newest-epoch dedupe, persistent cache,
stop-after-any-non-200 back-off) and adds: one request per group per cache window, no further group requests after a failed one in the same run, and
rows that carry provenance (source, retrieval time, element-set epoch, data status).

Design ideas (not code) come from reading Zenith's CelesTrak provider (GPL-2.0-or-later; a read-only study, nothing copied): fetch a group once,
keep a local cache so repeated use does not re-ask the provider, propagate locally with SGP4, report a clear status. Differences: validated cache,
persisted back-off, explicit stale/unavailable status, provenance on every row.

Not verified: no live CelesTrak response has been obtained in the build environment; the group names are the ones the plugin already used.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Sequence

from . import orbit_data
from .orbit_data import FetchResult, OrbitCache

GEO_GROUPS = ("geo", "intelsat", "ses", "eutelsat", "telesat")
USER_AGENT = "VeloronaQGIS (+https://velorona.ai)"
TIMEOUT = (5.0, 20.0)                      # (connect, read) seconds, as before
REFRESH_SECONDS = orbit_data.DEFAULT_TTL_S  # the cache window; the plugin must not ask the provider more often than this

LEO_MAX_ALTITUDE_KM = 2000
GEO_PERIOD_MIN = 1436.07
GEO_PERIOD_TOLERANCE_MIN = 30


def http_fetch(url: str) -> FetchResult:
    """One attempt, no retry. Any outcome is returned as data; the caller (orbit_data.load_group) decides the back-off."""
    import requests
    try:
        resp = requests.get(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}, timeout=TIMEOUT)
    except requests.exceptions.Timeout:
        return FetchResult(status=None, error="timeout")
    except requests.exceptions.RequestException:
        return FetchResult(status=None, error="network")
    return FetchResult(status=resp.status_code, text=resp.text if resp.status_code == 200 else None, headers=dict(resp.headers))


def classify_orbit(altitude_km: float, period_minutes: float) -> str:
    if altitude_km < LEO_MAX_ALTITUDE_KM:
        return "LEO"
    if abs(period_minutes - GEO_PERIOD_MIN) <= GEO_PERIOD_TOLERANCE_MIN:
        return "GEO"
    return "MEO"


def load_groups(groups: Sequence[str], cache: OrbitCache, now: datetime, fetch: Callable[[str], FetchResult] = http_fetch,
                ttl_s: int = REFRESH_SECONDS) -> dict:
    """Loads every group through orbit_data.load_group.

    After the first group whose request FAILED (no response, or a non-200), no further request is made in this run: the provider's policy is to stop after
    any non-200, and the remaining groups are the same host. Those groups are served from their cache if they have one, otherwise reported unavailable.

    Returns {status, records, per_group, warnings, next_refresh_s}. status:
      fresh        every group is within its cache window
      stale        at least one group is served from cache older than the window (or in back-off)
      partial      some groups have no data at all, the rest are usable
      unavailable  no usable record from any group
    Records are de-duplicated across groups by catalog id, newest element-set epoch wins (ties keep the first group listed)."""
    halted = {"flag": False}

    def guarded(url: str) -> FetchResult:
        if halted["flag"]:
            return FetchResult(status=None, error="skipped")
        r = fetch(url)
        if r.status != 200:
            halted["flag"] = True
        return r

    per_group: Dict[str, dict] = {}
    warnings: List[str] = []
    for g in groups:
        res = orbit_data.load_group(g, guarded, cache, now, ttl_s)
        per_group[g] = {k: res.get(k) for k in ("status", "reason", "retrieved_at_utc", "age_seconds", "from_cache", "upstream_status", "warnings")}
        per_group[g]["record_count"] = len(res.get("records") or [])
        if res.get("reason") == "skipped":
            per_group[g]["warnings"] = ["not requested: an earlier group failed in this run (stop after any failure)"]
        for w in per_group[g]["warnings"] or []:
            warnings.append(f"{g}: {w}")
        per_group[g]["_records"] = res.get("records") or []

    by_id: Dict[int, dict] = {}
    for g in groups:
        status = per_group[g]["status"]
        for rec in per_group[g].pop("_records"):
            rec = {**rec, "data_status": "stale" if status == "stale" else "fresh", "retrieved_at_utc": per_group[g]["retrieved_at_utc"]}
            prev = by_id.get(rec["satellite_id"])
            if prev is None or orbit_data.parse_epoch_utc(rec["orbit_epoch_utc"]) > orbit_data.parse_epoch_utc(prev["orbit_epoch_utc"]):
                by_id[rec["satellite_id"]] = rec
    records = sorted(by_id.values(), key=lambda r: r["satellite_id"])

    statuses = [per_group[g]["status"] for g in groups]
    if not records:
        overall = "unavailable"
    elif "stale" in statuses:
        overall = "stale"
    elif "unavailable" in statuses:
        overall = "partial"
    else:
        overall = "fresh"
    return {"status": overall, "records": records, "per_group": per_group, "warnings": warnings}


def build_rows(records: Sequence[dict], when: Optional[datetime] = None, source_label: str = orbit_data.SOURCE_NAME) -> dict:
    """Layer rows (the shape space_public.SATELLITE_FIELDS expects) computed with SGP4 from validated OMM records.

    A record that cannot be propagated, or whose catalog id does not fit the TLE lines the satellite-earth-space engine re-propagates from, is skipped
    and counted -- never silently kept with invented values. Returns {rows, skipped: {propagation_failed, beyond_legacy_tle}}."""
    from sgp4 import exporter, omm
    from sgp4.api import Satrec, jday
    from skyfield.api import EarthSatellite, load
    ts = load.timescale()
    when = when or datetime.now(timezone.utc)
    t = ts.from_datetime(when)
    utc = when.astimezone(timezone.utc)
    jd, fr = jday(utc.year, utc.month, utc.day, utc.hour, utc.minute, utc.second + utc.microsecond / 1e6)
    rows: List[dict] = []
    skipped = {"propagation_failed": 0, "beyond_legacy_tle": 0}
    for rec in records:
        if not rec.get("legacy_tle_compatible"):
            skipped["beyond_legacy_tle"] += 1
            continue
        try:
            satrec = Satrec()
            omm.initialize(satrec, rec["gp"])
            line1, line2 = exporter.export_tle(satrec)
            name = rec.get("satellite_name") or f"NORAD {rec['satellite_id_text']}"
            if satrec.sgp4(jd, fr)[0] != 0:               # SGP4's own error code (e.g. 6 = decayed): skyfield would still return a number
                skipped["propagation_failed"] += 1
                continue
            sat = EarthSatellite.from_satrec(satrec, ts)
            sub = sat.at(t).subpoint()
            period = (2 * 3.141592653589793) / satrec.no_kozai
        except (ValueError, KeyError, TypeError, ZeroDivisionError):
            skipped["propagation_failed"] += 1
            continue
        alt = float(sub.elevation.km)
        lat, lon = float(sub.latitude.degrees), float(sub.longitude.degrees)
        if not (lat == lat and lon == lon and alt == alt) or alt < 0:   # NaN or below the surface: not a valid position
            skipped["propagation_failed"] += 1
            continue
        rows.append({
            "id": f"sat-{rec['satellite_id_text']}", "latitude": lat, "longitude": lon, "altitude_km": alt,
            "norad_cat_id": rec["satellite_id_text"], "name": name,
            "orbit_category": classify_orbit(alt, period), "period_minutes": period,
            "tle_epoch": rec["orbit_epoch_utc"],
            "source": f"{source_label} ({rec.get('group')}), retrieved {rec.get('retrieved_at_utc')}",
            "retrieved_at": rec.get("retrieved_at_utc"), "data_status": rec.get("data_status", "fresh"),
            "coverage": "CelesTrak GP element sets, cached up to 2 hours; positions recomputed locally with SGP4 at the time shown. "
                        "Element-set age is the difference between that time and the epoch.",
            "tle_line1": line1, "tle_line2": line2,
        })
    return {"rows": rows, "skipped": skipped}
