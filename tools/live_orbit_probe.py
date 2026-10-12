"""LIVE check of the orbital source from a GitHub-hosted runner, through the plugin's own QGIS-free feed code (core/sources/satellite_feed.py).

One request per GEO group (the five groups the Satellites layer uses). Then a second load_groups call that must be answered from the cache with ZERO
requests. Then build_rows (SGP4) on the real records and a TLE-vs-OMM position comparison. Nothing the source returns is committed; only counts and a
few ids are printed. This is NOT a QGIS runtime test: it proves the ingestion/cache/propagation code against a real response, not the plugin UI."""
import json
import sys
import tempfile
from datetime import datetime, timezone

sys.path.insert(0, ".")
from core.sources import orbit_data, satellite_feed as sf  # noqa: E402
from skyfield.api import load  # noqa: E402

calls = []
statuses = {}


def counting_fetch(url):
    calls.append(url)
    r = sf.http_fetch(url)
    statuses[url] = {"status": r.status, "error": r.error, "headers": {k: v for k, v in (r.headers or {}).items() if k.lower() in ("access-control-allow-origin", "content-type", "content-length", "retry-after", "date")}}
    return r


import os  # noqa: E402
cache = orbit_data.OrbitCache(os.environ.get("ORBIT_CACHE_DIR") or tempfile.mkdtemp())   # the real-QGIS test reuses this directory
now = datetime.now(timezone.utc)
feed = sf.load_groups(sf.GEO_GROUPS, cache, now, counting_fetch)
n_first = len(calls)
feed2 = sf.load_groups(sf.GEO_GROUPS, cache, datetime.now(timezone.utc), counting_fetch)
built = sf.build_rows(feed["records"], now)
ts = load.timescale()
t = ts.from_datetime(now)
worst = 0.0
compared = 0
for row in built["rows"]:
    if row["tle_line1"]:
        a = sf.earth_satellite(row["tle_line1"], row["tle_line2"], None, "a", ts)
        b = sf.earth_satellite(None, None, row["omm_json"], "b", ts)
        d = ((a.at(t).position.km - b.at(t).position.km) ** 2).sum() ** 0.5
        worst = max(worst, float(d))
        compared += 1
ids = [int(r["norad_cat_id"]) for r in built["rows"]]
print(json.dumps({
    "probe_time_utc": now.isoformat(), "requests_first_call": n_first, "requests_second_call": len(calls) - n_first,
    "per_request": statuses,
    "first": {"status": feed["status"], "per_group": {g: {k: v for k, v in d.items() if k in ("status", "reason", "record_count", "upstream_status", "age_seconds")} for g, d in feed["per_group"].items()}, "warnings": feed["warnings"]},
    "second_call_status": feed2["status"], "second_call_all_from_cache": all(d.get("from_cache") for d in feed2["per_group"].values()),
    "records_unique": len(feed["records"]), "rows": len(built["rows"]), "skipped": built["skipped"], "omm_only": built["omm_only"],
    "max_catalog_id": max(ids) if ids else None, "duplicate_row_ids": len(ids) - len(set(ids)),
    "tle_vs_omm_compared": compared, "tle_vs_omm_worst_position_diff_km": round(worst, 4),
    "lat_lon_all_finite": all(r["latitude"] == r["latitude"] and r["longitude"] == r["longitude"] for r in built["rows"]),
    "orbit_categories": {k: sum(1 for r in built["rows"] if r["orbit_category"] == k) for k in ("LEO", "MEO", "GEO")},
    "sample": [{"id": r["norad_cat_id"], "name": r["name"], "epoch": r["tle_epoch"], "cat": r["orbit_category"]} for r in built["rows"][:3]],
}, indent=1))
sys.exit(0 if built["rows"] and len(calls) - n_first == 0 else 1)
