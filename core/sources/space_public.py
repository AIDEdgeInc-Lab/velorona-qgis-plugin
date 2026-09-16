"""Space domain public sources -- ports of aei-link-clearance/web/space.js's
CelesTrak + SatNOGS logic. Same groups, same dedup rule, same orbit
classification thresholds. `satellite.js` (browser) -> `skyfield`
(Python, wraps the same SGP4 algorithm) -- not a re-derivation, a
same-algorithm library swap, verified against a live/known TLE before use.

ground_stations reads the existing static snapshot checked into
aei-link-clearance/web/ read-only -- never modified, never copied.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Dict, List, Tuple

import requests
from qgis.PyQt.QtCore import QVariant
from skyfield.api import EarthSatellite, load

CELESTRAK_URL = "https://celestrak.org/NORAD/elements/gp.php"
CELESTRAK_GROUPS = ["geo", "intelsat", "ses", "eutelsat", "telesat"]
SOURCE_CELESTRAK = "CelesTrak GP element sets (geo/intelsat/ses/eutelsat/telesat groups, deduplicated by NORAD catalog number), Public Domain"

GROUND_STATIONS_SNAPSHOT_PATH = "/Users/aidedgeinc./velorona-repos/aei-link-clearance/web/satnogs_snapshot.json"
SOURCE_SATNOGS = "SatNOGS Network -- Ground Stations, static snapshot"

LEO_MAX_ALTITUDE_KM = 2000
GEO_PERIOD_MIN = 1436.07
GEO_PERIOD_TOLERANCE_MIN = 30

_TS = load.timescale()

SATELLITE_FIELDS = [
    ("id", QVariant.String), ("name", QVariant.String), ("source", QVariant.String),
    ("norad_cat_id", QVariant.String), ("orbit_category", QVariant.String),
    ("period_minutes", QVariant.Double), ("altitude_km", QVariant.Double),
    ("tle_epoch", QVariant.String), ("coverage", QVariant.String),
    # TLE lines themselves -- carried as plain attributes (not just an
    # internal/computation-time value) so the satellite-earth-space engine
    # can re-propagate at analysis time directly from the selected
    # feature, without needing a separate in-memory cache tied to session
    # state.
    ("tle_line1", QVariant.String), ("tle_line2", QVariant.String),
]

GROUND_STATION_FIELDS = [
    ("id", QVariant.String), ("name", QVariant.String), ("source", QVariant.String),
    ("record_id", QVariant.String), ("licensee", QVariant.String), ("status", QVariant.String),
    ("frequencies_mhz", QVariant.String), ("altitude_m", QVariant.Double),
    ("qthlocator", QVariant.String), ("observations", QVariant.Int),
    ("success_rate", QVariant.Double), ("min_horizon_deg", QVariant.Double),
    ("coverage", QVariant.String),
]


def _classify_orbit(altitude_km: float, period_minutes: float) -> str:
    if altitude_km < LEO_MAX_ALTITUDE_KM:
        return "LEO"
    if abs(period_minutes - GEO_PERIOD_MIN) <= GEO_PERIOD_TOLERANCE_MIN:
        return "GEO"
    return "MEO"


def _fetch_celestrak_group_tle(group: str) -> str:
    resp = requests.get(CELESTRAK_URL, params={"GROUP": group, "FORMAT": "tle"}, timeout=15.0)
    resp.raise_for_status()
    return resp.text


def fetch_celestrak_satellites() -> Dict[str, Tuple[str, str, str]]:
    """Returns {norad_cat_id: (name, line1, line2)}, deduplicated across
    all 5 groups, same as space.js's loadCelestrakElements()."""
    by_id: Dict[str, Tuple[str, str, str]] = {}
    for group in CELESTRAK_GROUPS:
        try:
            text = _fetch_celestrak_group_tle(group)
        except Exception:
            continue  # live public service -- degrade, don't crash the whole layer
        lines = [ln for ln in text.splitlines() if ln.strip()]
        for i in range(0, len(lines) - 2, 3):
            name, line1, line2 = lines[i].strip(), lines[i + 1], lines[i + 2]
            norad_id = line1[2:7].strip()
            if norad_id:
                by_id[norad_id] = (name, line1, line2)
    return by_id


def build_satellite_records(elements: Dict[str, Tuple[str, str, str]], when: datetime = None) -> List[dict]:
    when = when or datetime.now(timezone.utc)
    t = _TS.from_datetime(when)
    records = []
    for norad_id, (name, line1, line2) in elements.items():
        try:
            sat = EarthSatellite(line1, line2, name, _TS)
            geocentric = sat.at(t)
            subpoint = geocentric.subpoint()
            period_minutes = (2 * 3.141592653589793) / sat.model.no_kozai
        except Exception:
            continue  # a malformed/decayed element set -- skip, don't crash the layer
        altitude_km = subpoint.elevation.km
        records.append({
            "id": f"sat-{norad_id}",
            "latitude": subpoint.latitude.degrees, "longitude": subpoint.longitude.degrees,
            "altitude_km": altitude_km,
            "norad_cat_id": norad_id,
            "name": name.strip() or f"NORAD {norad_id}",
            "orbit_category": _classify_orbit(altitude_km, period_minutes),
            "period_minutes": period_minutes,
            "tle_epoch": sat.epoch.utc_iso(),
            "source": SOURCE_CELESTRAK,
            "coverage": "CelesTrak GP element sets: geo, intelsat, ses, eutelsat, telesat groups, deduplicated by NORAD catalog number. Live query, recomputed on demand.",
            "tle_line1": line1, "tle_line2": line2,
        })
    return records


def load_ground_station_snapshot(path: str = GROUND_STATIONS_SNAPSHOT_PATH) -> List[dict]:
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    stations = []
    for s in raw["stations"]:
        freq_ranges = []
        for antenna in s.get("antenna") or []:
            if antenna.get("frequency_hz") is None:
                continue
            lo = antenna["frequency_hz"] / 1e6
            hi = antenna.get("frequency_max_hz", antenna["frequency_hz"]) / 1e6
            band = f" {antenna['band']}" if antenna.get("band") else ""
            freq_ranges.append(f"{lo:.1f} MHz{band}" if lo == hi else f"{lo:.1f}-{hi:.1f} MHz{band}")

        success_rate = s.get("success_rate")
        stations.append({
            "id": f"satnogs-{s['id']}",
            "latitude": s["lat"], "longitude": s["lng"],
            "source": SOURCE_SATNOGS,
            "name": s.get("name") or f"SatNOGS station {s['id']}",
            "record_id": str(s["id"]),
            "licensee": s.get("owner"),
            "status": s.get("status"),
            "frequencies_mhz": "; ".join(freq_ranges) or None,
            "altitude_m": s.get("altitude_m"),
            "qthlocator": s.get("qthlocator"),
            "observations": s.get("observations"),
            "success_rate": success_rate if isinstance(success_rate, (int, float)) else None,
            "min_horizon_deg": s.get("min_horizon_deg"),
            "coverage": raw.get("coverage_note"),
        })
    return stations
