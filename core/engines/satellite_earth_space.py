"""Satellite / Earth-Space Analysis engine -- geometry only (elevation, azimuth, slant range, visibility at an explicit UTC time, and the windows above a
minimum elevation over the next 1-72 h). Same scope and semantics as Velorona Map's 'satellite-earth-space' engine: SGP4 propagation + observer-relative
look angles, no propagation loss, no link budget, no weather exposure, and no claim that a link works.

The calculation is core/engines/satellite_geometry.py (QGIS-free, tested against the Map's own output); this module only adapts QGIS features to it.
Map uses satellite.js, this plugin uses Skyfield -- different SGP4 front ends -- and tests/test_satellite_geometry.py measures their agreement.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from ..features import feature_attr, feature_id_name
from . import satellite_geometry as geom

MIN_ELEVATION_MASK_DEG = geom.DEFAULT_MIN_ELEVATION_DEG   # the default mask (Assumed)
DEFAULT_WINDOW_HOURS = 24.0
STATION_HORIZON_CHOICE = "Use the station's declared horizon"

PARAM_SPEC: list = [
    {"key": "start_offset_hours", "label": "Analysis time: hours from now (UTC)", "type": "float", "default": 0.0, "suffix": " h", "min": 0.0, "max": 72.0,
     "basis": "0 analyses now. A later start is for planning; accuracy falls the further it is from the element-set epoch (the result flags a stale element set)."},
    {"key": "window_hours", "label": "Window to search", "type": "float", "default": DEFAULT_WINDOW_HOURS, "suffix": " h", "min": 1.0, "max": float(geom.MAX_WINDOW_HOURS),
     "basis": "1-72 h. The search scans every 20 s; the limit keeps the calculation fast and the prediction meaningful."},
    {"key": "min_elevation_deg", "label": "Minimum elevation", "type": "float", "default": MIN_ELEVATION_MASK_DEG, "suffix": " deg", "min": 0.0, "max": 60.0,
     "basis": "Default 10 deg, the conservative end of the 5-10 deg standard-practice range; no per-site horizon survey. A value you enter is typed Assumed."},
    {"key": "mask_basis", "label": "Minimum elevation basis", "type": "choice", "default": "Use the value above",
     "choices": ["Use the value above", STATION_HORIZON_CHOICE],
     "basis": "The station's own declared minimum horizon (SatNOGS) is its owner's tracking limit. It is used as the mask only if you choose it here, and then typed Observed."},
]

_SNAPSHOT_DATE = None


def _snapshot_date() -> str:
    """The bundled SatNOGS snapshot's own retrieval date (read once from data/satnogs_snapshot.json)."""
    global _SNAPSHOT_DATE
    if _SNAPSHOT_DATE is None:
        try:
            path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data", "satnogs_snapshot.json")
            with open(path, "r", encoding="utf-8") as fh:
                _SNAPSHOT_DATE = str(json.load(fh).get("retrieved_at") or "date not recorded")
        except (OSError, ValueError):
            _SNAPSHOT_DATE = "date not available"
    return _SNAPSHOT_DATE


@dataclass
class SatelliteLookAngleResult:
    kind: str
    station_name: str
    satellite_name: str
    elevation_deg: float
    azimuth_deg: float
    slant_range_km: float
    visible: bool
    min_elevation_mask_deg: float
    computed_at: str          # wall clock when the calculation ran (not the analysis instant)
    tle_epoch: str
    # --- added with explicit time / windows / data-age (all defaulted so older callers keep working) ---
    analysis_time_utc: str = ""
    time_origin: str = "now"
    mask_origin: str = "default"
    mask_type: str = "Assumed"
    station_latitude: float = 0.0
    station_longitude: float = 0.0
    station_altitude_m: float | None = None
    station_source: str = ""
    station_retrieved: str = ""
    station_status: str | None = None
    station_min_horizon_deg: float | None = None
    station_source_short: str = "SatNOGS Network station listing (static snapshot)"
    satellite_source: str = ""
    norad_cat_id: str = ""
    orbit_category: str = ""
    sat_latitude: float = 0.0
    sat_longitude: float = 0.0
    sat_altitude_km: float = 0.0
    epoch_age_days: float | None = None
    epoch_level: str = "unknown"
    epoch_note: str = ""
    window_hours: float = DEFAULT_WINDOW_HOURS
    window_start_utc: str = ""
    window_end_utc: str = ""
    window_state: str | None = None
    windows: list = field(default_factory=list)
    windows_error: str | None = None
    window_step_sec: int | None = None
    window_refine_sec: int | None = None


def build_params(entries=None) -> dict:
    return {p["key"]: p["default"] for p in PARAM_SPEC}


def analyze(ground_station_entry, satellite_entry, params: dict | None = None, now: datetime | None = None) -> SatelliteLookAngleResult:
    """Look angles at the analysis time and the windows above the minimum elevation. Raises ValueError with a plain message for anything it will not compute.

    params: start_offset_hours (0-72), window_hours (1-72), min_elevation_deg, mask_basis. now: injectable clock for tests."""
    params = {**build_params(), **(params or {})}
    station_layer, station_feat = ground_station_entry
    sat_layer, sat_feat = satellite_entry

    point = station_feat.geometry().centroid().asPoint()
    altitude_m = feature_attr(station_feat, "altitude_m", None)
    _, station_name = feature_id_name(station_feat, "Selected ground station")
    horizon = feature_attr(station_feat, "min_horizon_deg", None)
    station = {"latitude": point.y(), "longitude": point.x(),
               "altitude_m": float(altitude_m) if isinstance(altitude_m, (int, float)) and not isinstance(altitude_m, bool) else None,
               "min_horizon_deg": horizon if isinstance(horizon, (int, float)) and not isinstance(horizon, bool) else None}
    if not geom.valid_station(station):
        raise ValueError("The selected ground station has no valid latitude/longitude.")

    line1, line2 = feature_attr(sat_feat, "tle_line1"), feature_attr(sat_feat, "tle_line2")
    if not line1 or not line2:
        raise ValueError("Selected satellite feature has no TLE data -- re-run 'Load Public Data' to refresh it.")
    _, satellite_name = feature_id_name(sat_feat, "Selected satellite")
    sat = geom.satellite_from_tle(line1, line2, satellite_name)
    if sat is None:
        raise ValueError("The orbital elements for this satellite are not a valid TLE (format or checksum), so its position is not calculated. "
                         "Re-run 'Load Public Data' to refresh them.")
    tle_epoch = feature_attr(sat_feat, "tle_epoch", "unknown")

    offset = params["start_offset_hours"]
    window_hours = params["window_hours"]
    if not isinstance(offset, (int, float)) or not 0 <= offset <= 72:
        raise ValueError("The analysis time offset must be 0 to 72 hours from now.")
    if not isinstance(window_hours, (int, float)) or not 1 <= window_hours <= geom.MAX_WINDOW_HOURS:
        raise ValueError(f"The window must be 1 to {geom.MAX_WINDOW_HOURS} hours.")
    use_station = params["mask_basis"] == STATION_HORIZON_CHOICE
    # The dialog always returns the minimum elevation; an untouched default is the default (so it is not reported as "entered by you"). A user who types 10 gets
    # the same value and the same type (Assumed); only the wording of the origin differs.
    typed = params["min_elevation_deg"]
    mask = geom.resolve_mask(station, None if (use_station or typed == MIN_ELEVATION_MASK_DEG) else typed, use_station)
    if not mask["ok"]:
        raise ValueError(mask["reason"])

    clock = now or datetime.now(timezone.utc)
    when = clock + timedelta(hours=offset)
    look = geom.look_angles_at(sat, station, when)
    if not look["ok"]:
        raise ValueError(look["reason"])
    win = geom.find_windows(sat, station, when, when + timedelta(hours=window_hours), mask["deg"])
    age = geom.epoch_status(tle_epoch, when)
    return SatelliteLookAngleResult(
        kind="satellite-earth-space", station_name=station_name, satellite_name=satellite_name,
        elevation_deg=look["elevation_deg"], azimuth_deg=look["azimuth_deg"], slant_range_km=look["range_km"],
        visible=look["elevation_deg"] >= mask["deg"], min_elevation_mask_deg=mask["deg"],
        computed_at=datetime.now(timezone.utc).isoformat(), tle_epoch=tle_epoch,
        analysis_time_utc=geom.iso_ms(when), time_origin="now" if offset == 0 else "user",
        mask_origin=mask["origin"], mask_type=mask["type"],
        station_latitude=station["latitude"], station_longitude=station["longitude"], station_altitude_m=station["altitude_m"],
        station_source=feature_attr(station_feat, "source", "") or "", station_retrieved=_snapshot_date(),
        station_status=feature_attr(station_feat, "status", None) or None, station_min_horizon_deg=station["min_horizon_deg"],
        satellite_source=feature_attr(sat_feat, "source", "") or "", norad_cat_id=str(feature_attr(sat_feat, "norad_cat_id", "") or ""),
        orbit_category=feature_attr(sat_feat, "orbit_category", "") or "",
        sat_latitude=look["sub_lat_deg"], sat_longitude=look["sub_lon_deg"], sat_altitude_km=look["altitude_km"],
        epoch_age_days=age["age_days"], epoch_level=age["level"], epoch_note=age["note"],
        window_hours=float(window_hours), window_start_utc=win["start_utc"] if win["ok"] else geom.iso_ms(when),
        window_end_utc=win["end_utc"] if win["ok"] else geom.iso_ms(when + timedelta(hours=window_hours)),
        window_state=win["state"] if win["ok"] else None, windows=win["windows"] if win["ok"] else [],
        windows_error=None if win["ok"] else win["reason"],
        window_step_sec=win["step_sec"] if win["ok"] else None, window_refine_sec=win["refine_sec"] if win["ok"] else None,
    )
