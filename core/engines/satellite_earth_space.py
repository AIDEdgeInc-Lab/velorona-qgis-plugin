"""Satellite / Earth-Space Analysis engine -- Phase 1, geometry only
(elevation, azimuth, slant range, visibility). Same scope as
aei-link-clearance/web/space.js's registered 'satellite-earth-space'
engine: SGP4 propagation + observer-relative look angles, no propagation
loss, no link budget, no weather exposure.

satellite.js's ecfToLookAngles() -> skyfield's topocentric .altaz(), same
published geometry (ECI/ECEF -> topocentric transform), not re-derived.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from skyfield.api import EarthSatellite, wgs84, load

from ..features import feature_attr, feature_id_name

MIN_ELEVATION_MASK_DEG = 10  # same convention as space.js: standard-practice 5-10 deg range, conservative end

_TS = load.timescale()

PARAM_SPEC: list = []  # unambiguous match (1 ground-station + 1 satellite) -- no parameters to collect


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
    computed_at: str
    tle_epoch: str


def analyze(ground_station_entry, satellite_entry) -> SatelliteLookAngleResult:
    station_layer, station_feat = ground_station_entry
    sat_layer, sat_feat = satellite_entry

    station_point = station_feat.geometry().centroid().asPoint()
    altitude_m = feature_attr(station_feat, "altitude_m", 0.0) or 0.0
    _, station_name = feature_id_name(station_feat, "Selected ground station")
    observer = wgs84.latlon(station_point.y(), station_point.x(), elevation_m=float(altitude_m))

    line1 = feature_attr(sat_feat, "tle_line1")
    line2 = feature_attr(sat_feat, "tle_line2")
    if not line1 or not line2:
        raise ValueError("Selected satellite feature has no TLE data -- re-run 'Load Public Data' to refresh it.")
    _, satellite_name = feature_id_name(sat_feat, "Selected satellite")
    tle_epoch = feature_attr(sat_feat, "tle_epoch", "unknown")

    sat = EarthSatellite(line1, line2, satellite_name, _TS)
    when = datetime.now(timezone.utc)
    t = _TS.from_datetime(when)
    topocentric = (sat - observer).at(t)
    alt, az, distance = topocentric.altaz()

    elevation_deg = alt.degrees
    return SatelliteLookAngleResult(
        kind="satellite-earth-space",
        station_name=station_name, satellite_name=satellite_name,
        elevation_deg=elevation_deg, azimuth_deg=az.degrees, slant_range_km=distance.km,
        visible=elevation_deg >= MIN_ELEVATION_MASK_DEG,
        min_elevation_mask_deg=MIN_ELEVATION_MASK_DEG,
        computed_at=when.isoformat(), tle_epoch=tle_epoch,
    )
