"""Terrestrial public infrastructure sources -- ports of
aei-link-clearance/web/publicdata.js's fetch/parse functions (same URLs,
same field mapping, same provenance strings), `requests` instead of
`fetch`. No new data, no new engineering: this module only moves the
existing fetch/parse logic from JS to Python so it can build native QGIS
layers.

fixed_service and ground_stations below read the existing static
snapshots checked into aei-link-clearance/web/ read-only -- never
modified, never copied.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple

import requests
from qgis.PyQt.QtCore import QVariant

GEOHUB_URL = "https://ws.lioservices.lrc.gov.on.ca/arcgis2/rest/services/LIO_OPEN_DATA/LIO_Open10/MapServer/14/query"
ISED_CELLULAR_URL = "https://services.arcgis.com/wjcPoefzjpzCgffS/ArcGIS/rest/services/Spectrum_Licences_Site_Data/FeatureServer/0/query"
RELEVANT_TOWER_SUBTYPES = ["Communication Tower", "Microwave Tower", "Radio Tower"]

SOURCE_GEOHUB = "Ontario GeoHub -- Tower dataset (MNRF), Open Government Licence - Ontario"
SOURCE_ISED_CELLULAR = "ISED Spectrum Licences Site Data (cellular/mobile), via Esri Canada mirror, Open Government Licence - Canada"
SOURCE_ISED_FIXED = "ISED SMS Authorization Data Extract: Fixed Service, Open Government Licence - Canada"

# Read-only inputs -- the exact static snapshots aei-link-clearance's own
# web app already ships and maintains. Never modified, never duplicated.
FIXED_SERVICE_SNAPSHOT_PATH = "/Users/aidedgeinc./velorona-repos/aei-link-clearance/web/fixed_service_snapshot.json"

TOWER_FIELDS = [
    ("id", QVariant.String), ("name", QVariant.String), ("source", QVariant.String),
    ("feature_type", QVariant.String), ("record_id", QVariant.String),
    ("height_above_ground_m", QVariant.Double), ("radio_call_sign", QVariant.String),
    ("purpose", QVariant.String), ("coverage", QVariant.String),
]

CELLULAR_FIELDS = [
    ("id", QVariant.String), ("name", QVariant.String), ("source", QVariant.String),
    ("feature_type", QVariant.String), ("record_id", QVariant.String),
    ("licensee", QVariant.String), ("service_bands", QVariant.String),
    ("channel_count", QVariant.Int), ("coverage", QVariant.String),
]

FIXED_SITE_FIELDS = [
    ("id", QVariant.String), ("name", QVariant.String), ("source", QVariant.String),
    ("feature_type", QVariant.String), ("record_id", QVariant.String),
    ("call_signs", QVariant.String), ("authorizations", QVariant.String),
    ("frequencies_mhz", QVariant.String), ("licensee", QVariant.String),
    ("province", QVariant.String), ("coverage", QVariant.String),
]

FIXED_LINK_FIELDS = [
    ("id", QVariant.String), ("source", QVariant.String), ("authorization_number", QVariant.String),
    ("licensee", QVariant.String), ("in_service_date", QVariant.String),
    ("frequencies_mhz", QVariant.String), ("coverage", QVariant.String),
]


def _query_arcgis(url: str, bbox: Tuple[float, float, float, float], where: str = "1=1") -> Tuple[List[dict], bool]:
    min_lon, min_lat, max_lon, max_lat = bbox
    params = {
        "where": where,
        "geometry": f"{min_lon},{min_lat},{max_lon},{max_lat}",
        "geometryType": "esriGeometryEnvelope",
        "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "*",
        "returnGeometry": "true",
        "f": "json",
        "resultRecordCount": "1000",
    }
    resp = requests.get(url, params=params, timeout=15.0)
    resp.raise_for_status()
    data = resp.json()
    if data.get("error"):
        raise RuntimeError(data["error"].get("message", "Public data service returned an error."))
    return data.get("features", []), bool(data.get("exceededTransferLimit"))


def fetch_geohub_towers(bbox: Tuple[float, float, float, float]) -> Tuple[List[dict], bool]:
    where = "CLASS_SUBTYPE IN (" + ",".join(f"'{s}'" for s in RELEVANT_TOWER_SUBTYPES) + ")"
    features, exceeded = _query_arcgis(GEOHUB_URL, bbox, where)
    sites = []
    for f in features:
        geom = f.get("geometry") or {}
        if geom.get("x") is None or geom.get("y") is None:
            continue
        a = f.get("attributes") or {}
        sites.append({
            "id": f"geohub-{a.get('TOWER_IDENT') or a.get('OBJECTID')}",
            "latitude": geom["y"], "longitude": geom["x"],
            "source": SOURCE_GEOHUB,
            "name": a.get("OFFICIAL_NAME") or f"{a.get('CLASS_SUBTYPE') or 'Tower'} (OGF {a.get('OGF_ID') or a.get('OBJECTID')})",
            "feature_type": a.get("CLASS_SUBTYPE"),
            "record_id": str(a.get("OGF_ID") or a.get("OBJECTID") or ""),
            "height_above_ground_m": a.get("HEIGHT_ABOVE_GROUND_NUM"),
            "radio_call_sign": a.get("RADIO_CALL_SIGN"),
            "purpose": a.get("PURPOSE_OF_TOWER_DESCR"),
            "coverage": "Ontario",
        })
    return sites, exceeded


def fetch_ised_cellular(bbox: Tuple[float, float, float, float]) -> Tuple[List[dict], bool]:
    features, exceeded = _query_arcgis(ISED_CELLULAR_URL, bbox)
    groups: Dict[str, Dict[str, Any]] = {}
    for f in features:
        a = f.get("attributes") or {}
        geom = f.get("geometry") or {}
        lat, lon = geom.get("y"), geom.get("x")
        if lat is None or lon is None:
            lat, lon = a.get("LATITUDE"), a.get("LONGITUDE")
        if lat is None or lon is None:
            continue
        key = f"{round(lat, 5)},{round(lon, 5)}"
        groups.setdefault(key, {"lat": lat, "lon": lon, "rows": []})["rows"].append(a)

    sites = []
    for key, group in groups.items():
        rows = group["rows"]
        licensees = sorted({r.get("LICENSEE") for r in rows if r.get("LICENSEE")})
        bands = sorted({r.get("SERVICE") for r in rows if r.get("SERVICE")})
        location = rows[0].get("LOCATION")
        sites.append({
            "id": f"ised-cell-{key}",
            "latitude": group["lat"], "longitude": group["lon"],
            "source": SOURCE_ISED_CELLULAR,
            "name": (" / ".join(licensees) or "Unknown licensee") + (f" -- {location}" if location else ""),
            "feature_type": "Cellular/Mobile site",
            "record_id": str(rows[0].get("OBJECTID") or ""),
            "licensee": " / ".join(licensees) or None,
            "service_bands": ", ".join(bands) or None,
            "channel_count": len(rows),
            "coverage": "Canada (mirror last confirmed updated approx. twice yearly; host-flagged deprecated -- currency not guaranteed)",
        })
    return sites, exceeded


def load_fixed_service_snapshot(path: str = FIXED_SERVICE_SNAPSHOT_PATH) -> Tuple[List[dict], List[dict]]:
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    sites_by_id: Dict[str, dict] = {}
    for s in raw["sites"]:
        sites_by_id[s["id"]] = {
            "id": s["id"], "latitude": s["latitude"], "longitude": s["longitude"],
            "source": SOURCE_ISED_FIXED,
            "name": s.get("location_description") or (s.get("call_signs") or [s["id"]])[0],
            "feature_type": f"Fixed Service station ({'/'.join(s.get('roles', []))})",
            "record_id": ", ".join(s.get("authorizations", [])),
            "call_signs": ", ".join(s.get("call_signs", [])) or None,
            "authorizations": ", ".join(s.get("authorizations", [])) or None,
            "frequencies_mhz": ", ".join(str(v) for v in s.get("frequencies_mhz", [])) or None,
            "licensee": " / ".join(s.get("licensees", [])) or None,
            "province": s.get("province"),
            "coverage": "National (Canada-wide) -- snapshot, not a live query",
        }

    links = []
    for l in raw["links"]:
        site_a = sites_by_id.get(l["site_a_id"])
        site_b = sites_by_id.get(l["site_b_id"])
        if not site_a or not site_b:
            continue
        links.append({
            "id": f"ised-fixed-link-{l['authorization_number']}",
            "source": SOURCE_ISED_FIXED,
            "authorization_number": l["authorization_number"],
            "licensee": l.get("licensee"),
            "in_service_date": l.get("in_service_date"),
            "frequencies_mhz": ", ".join(str(v) for v in l.get("frequencies_mhz", [])),
            "site_a": site_a, "site_b": site_b,
            "coverage": "National (Canada-wide) -- snapshot, not a live query",
        })

    return list(sites_by_id.values()), links
