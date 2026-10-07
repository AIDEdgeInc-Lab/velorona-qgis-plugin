"""The calculation and field registry: what every exported number is, where it
comes from and which calculation produced it. Feeds the workbook's DATA
DICTIONARY and RAW DATA sheets, so an analyst can trace any value without
reading the code. docs/OPERATIONAL_OUTPUT.md carries the same audit in prose.

Calculation ids are stable identifiers (`terrain.fresnel_radius`), not code
paths: they let a reader quote exactly which calculation they mean.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

OBSERVED, MODEL, CALCULATED, INPUT, INFERRED = "Observed", "Model-derived", "Calculated", "Input", "Inferred"


@dataclass(frozen=True)
class Calculation:
    id: str
    name: str
    formula: str
    inputs: str
    unit: str
    source: str
    threshold: str
    interpretation: str


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    unit: str
    kind: str
    source: str
    calc: str       # Calculation id, or "" for an input/observation
    definition: str


_LIB_T = "aei_link_clearance.terrain.analyze_link"
_LIB_X = "aei_mw_exposure"

CALCULATIONS: List[Calculation] = [
    Calculation("terrain.distance", "Path distance", "haversine(A, B)", "Site A/B lat, lon", "km",
                "aei_geo_features.haversine_distance", "none", "Great-circle length of the link."),
    Calculation("terrain.bearing", "Bearing", "initial great-circle bearing A->B", "Site A/B lat, lon", "degrees",
                "aei_link_clearance.geometry.bearing_deg", "none", "Compass direction from Site A to Site B."),
    Calculation("terrain.earth_bulge", "Earth bulge", "h = d1*d2 / (2*k*R)  (d in km, result in m)",
                "d1, d2 distances to each end, k = 4/3, R = earth radius", "m", _LIB_T + " (earth_bulge_m)",
                "none", "Height the curved earth adds at a point; subtracted from ground elevation."),
    Calculation("terrain.fresnel_radius", "First Fresnel radius", "r1 = 17.3 * sqrt(d1*d2 / (f*(d1+d2)))",
                "d1, d2 in km, f in GHz", "m", "aei_link_clearance.fresnel.fresnel_radius_m (ITU-R P.526)",
                "none", "Radius of the zone around the line of sight that should stay mostly obstacle-free."),
    Calculation("terrain.clearance", "Clearance at a sample", "line-of-sight height - (ground elevation - earth bulge)",
                "antenna tops, ground elevation, earth bulge", "m", _LIB_T, "none",
                "Height of the line of sight above the curvature-adjusted terrain."),
    Calculation("terrain.critical_point", "Critical (tightest) point", "interior sample with the lowest clearance / first Fresnel radius (fraction), NOT the lowest absolute clearance in metres",
                "profile samples", "-", _LIB_T, "endpoints excluded (Fresnel radius is 0 there)",
                "The point that decides the link's result; it can differ from the point with the fewest metres of clearance."),
    Calculation("terrain.required_clearance", "Required clearance", "0.60 * first Fresnel radius at the critical point",
                "first Fresnel radius", "m", _LIB_T, "0.60 (standard microwave practice, not an ITU-R compliance figure)",
                "Minimum clearance the link should have."),
    Calculation("terrain.clearance_ratio", "Clearance ratio", "available clearance / required clearance",
                "terrain clearance, required clearance", "ratio", _LIB_T, "1.0 = exactly the minimum",
                "How many times the minimum is available. Shown only as technical detail."),
    Calculation("terrain.los_status", "Line-of-sight class", "clear if clearance/r1 >= 0.60; marginal if >= 0.30; else obstructed",
                "percent Fresnel clear", "class", _LIB_T, "0.60 standard practice; 0.30 is the project's own judgment call",
                "Library classification the operator status is mapped from."),
    Calculation("terrain.near_threshold", "Near threshold", "15 m / r1 swing straddles the 0.60 or 0.30 boundary",
                "percent Fresnel clear, first Fresnel radius", "flag", _LIB_T,
                "15 m elevation uncertainty (round-up of a measured ~13-14 m DEM disagreement)",
                "True when a different DEM could change the class."),
    Calculation("weather.rain_rate_used", "Rain rate used", "max(rain rate at Site A, rain rate at Site B)",
                "model-derived liquid rain rate per site (rain + showers)", "mm/h", _LIB_X + ".exposure.calculate_exposure", "none",
                "Conservative stand-in for rain along the path; neither site observes the path."),
    Calculation("weather.specific_attenuation", "Specific attenuation", "gamma = k * R^alpha", "rain rate R, frequency, polarization",
                "dB/km", _LIB_X + ".physics (ITU-R P.838-3)", "frequency 1-100 GHz (table range)", "Rain loss per kilometre."),
    Calculation("weather.effective_path", "Effective path length", "d_eff = d / (1 + d/d0), d0 = 35*exp(-0.015*R), R capped at 100",
                "path length, rain rate", "km", _LIB_X + ".physics (ITU-R P.530)", "none",
                "Rain cells are smaller than long hops, so the wet path is shorter than the geometric one."),
    Calculation("weather.attenuation", "Predicted rain fade", "gamma * d_eff", "specific attenuation, effective path length", "dB",
                _LIB_X + ".physics.estimate_rain_attenuation", "none", "Signal the rain is predicted to remove."),
    Calculation("weather.exposure_ratio", "Exposure ratio", "predicted fade / fade margin (rounded to 3 decimals)",
                "predicted fade, fade margin", "ratio", _LIB_X + ".exposure.calculate_exposure", "moderate >= 0.3, high >= 0.7 (library conventions, not a validated risk model)",
                "Share of the fade margin the rain would use."),
    Calculation("weather.fade_remaining", "Fade margin remaining", "fade margin - predicted fade", "fade margin, predicted fade", "dB",
                "Velorona presentation layer (difference of two library values)", "CRITICAL when <= 0", "Room left before the margin is used up."),
    Calculation("weather.station_distance", "Station distance", "haversine(site, station)", "site and station coordinates", "km",
                _LIB_X + ".providers.eccc.find_nearest_station", "50 km search radius, 90 min window",
                "How far the corroborating station is from the site."),
    Calculation("weather.representativeness", "Representativeness", "station vs model rain difference and station distance",
                "station rain, model rain, station distance", "class", _LIB_X + ".representativeness",
                "50 km, 2.0 mm/h (stated conventions)", "Whether independent sources support the model value."),
    Calculation("history.change", "Change vs earlier hour (model-derived)", "latest hourly value - value N hours earlier; flat when equal at 0.1",
                "hourly model-derived series (Open-Meteo), not station observations", "unit of the variable", "Velorona presentation layer (core.presentation.history)",
                "flat = equal at displayed precision (not a physical threshold)", "Direction the weather is moving."),
    Calculation("status.terrain", "Terrain status", "obstructed->CRITICAL; marginal->AT RISK; clear & (near threshold or ratio<1.3)->WATCH; else CLEAR",
                "library class, near_threshold, ratio", "status", "Velorona presentation layer", "1.3 = library COMFORTABLE_MARGIN_RATIO",
                "Operator status for terrain."),
    Calculation("status.weather", "Weather status", "fade>=margin->CRITICAL; high->AT RISK; moderate->WATCH; low->CLEAR",
                "predicted fade, fade margin, severity", "status", "Velorona presentation layer", "library 0.3 / 0.7 bands",
                "Operator status for weather."),
    Calculation("satellite.look_angles", "Satellite look angles", "SGP4 propagation, topocentric alt/az/range", "TLE, station lat/lon/altitude, now (UTC)",
                "deg, km", "skyfield (core.engines.satellite_earth_space)", "visible if elevation >= 10 deg mask",
                "Geometry only; not exported."),
]

_FIELD_LIST = [
    Field("distance_km", "Path distance", "km", CALCULATED, "aei_link_clearance", "terrain.distance", "Great-circle link length"),
    Field("bearing_deg", "Bearing", "degrees", CALCULATED, "aei_link_clearance", "terrain.bearing", "Direction from Site A to Site B"),
    Field("frequency_ghz", "Frequency", "GHz", INPUT, "User dialog or ISED record", "", "Analysis frequency"),
    Field("k_factor", "Earth radius factor k", "-", INPUT, "aei_link_clearance default (ITU-R P.530 median)", "", "Effective earth radius factor"),
    Field("first_fresnel_radius_m", "First Fresnel radius", "m", CALCULATED, "aei_link_clearance", "terrain.fresnel_radius", "At the tightest point"),
    Field("required_clearance_m", "Clearance required", "m", CALCULATED, "aei_link_clearance", "terrain.required_clearance", "60% of the first Fresnel radius"),
    Field("terrain_clearance_m", "Clearance available", "m", CALCULATED, "aei_link_clearance", "terrain.clearance", "Line-of-sight height above terrain at the tightest point"),
    Field("margin_m", "Clearance margin", "m", CALCULATED, "Velorona presentation layer", "terrain.clearance", "Available minus required"),
    Field("clearance_ratio", "Clearance ratio", "ratio", CALCULATED, "aei_link_clearance", "terrain.clearance_ratio", "Available / required"),
    Field("percent_fresnel_clear", "Fresnel zone clear", "fraction", CALCULATED, "aei_link_clearance", "terrain.los_status", "Available clearance / first Fresnel radius (1.0 = 100%)"),
    Field("los_status", "Line-of-sight class", "class", INFERRED, "aei_link_clearance", "terrain.los_status", "clear / marginal / obstructed"),
    Field("near_threshold", "Near threshold", "flag", INFERRED, "aei_link_clearance", "terrain.near_threshold", "Result could change with another elevation source"),
    Field("explanation", "Plain comparison", "text", INFERRED, "Velorona presentation of the library result", "status.terrain", "Available vs required clearance in metres, ratio as a multiple"),
    Field("library_explanation", "Library explain() text", "text", INFERRED, "aei_link_clearance.explain", "", "The library's own one-line wording, kept for audit; it expresses the margin as a percentage"),
    Field("samples", "Elevation samples", "count", OBSERVED, "Open-Meteo Elevation API (Copernicus DEM GLO-90)", "", "Points sampled along the path"),
    Field("critical_distance_from_a_km", "Critical point, distance from Site A", "km", CALCULATED, "aei_link_clearance", "terrain.critical_point", "Where clearance is lowest"),
    Field("critical_latitude", "Critical point latitude", "degrees", CALCULATED, "aei_link_clearance", "terrain.critical_point", "WGS84"),
    Field("critical_longitude", "Critical point longitude", "degrees", CALCULATED, "aei_link_clearance", "terrain.critical_point", "WGS84"),
    Field("rain_rate_mm_h", "Rain rate used", "mm/h", MODEL, "Open-Meteo weather model (liquid rain = rain + showers; snow excluded)", "weather.rain_rate_used", "Higher of the two sites' model rain rate"),
    Field("predicted_attenuation_db", "Predicted rain fade", "dB", CALCULATED, "aei_mw_exposure", "weather.attenuation", "Signal removed by rain"),
    Field("fade_margin_db", "Fade margin", "dB", INPUT, "User dialog or engine default (not published by ISED)", "", "Signal the link can lose before failing"),
    Field("fade_remaining_db", "Fade margin remaining", "dB", CALCULATED, "Velorona presentation layer", "weather.fade_remaining", "Fade margin minus predicted fade"),
    Field("exposure_ratio", "Exposure ratio", "ratio", CALCULATED, "aei_mw_exposure", "weather.exposure_ratio", "Predicted fade / fade margin"),
    Field("severity", "Library severity", "class", INFERRED, "aei_mw_exposure", "weather.exposure_ratio", "low / moderate / high"),
    Field("path_length_km", "Path length", "km", CALCULATED, "aei_mw_exposure", "terrain.distance", "Great-circle link length"),
    Field("specific_attenuation_db_km", "Specific attenuation", "dB/km", CALCULATED, "aei_mw_exposure", "weather.specific_attenuation", "Rain loss per km"),
    Field("effective_path_length_km", "Effective path length", "km", CALCULATED, "aei_mw_exposure", "weather.effective_path", "Wet path length"),
    Field("k", "Rain coefficient k", "-", CALCULATED, "aei_mw_exposure (ITU-R P.838-3 table)", "weather.specific_attenuation", "Regression coefficient"),
    Field("alpha", "Rain coefficient alpha", "-", CALCULATED, "aei_mw_exposure (ITU-R P.838-3 table)", "weather.specific_attenuation", "Regression exponent"),
]

FIELDS: Dict[str, Field] = {f.key: f for f in _FIELD_LIST}

STATUS_DEFINITIONS = [
    ("CLEAR", "Nothing needs attention."),
    ("WATCH", "Within limits, but the margin is small or the data is uncertain enough that it could change."),
    ("AT RISK", "Below the required minimum (terrain), or most of the fade margin is predicted to be used (weather)."),
    ("CRITICAL", "Far below the required minimum (terrain), or predicted rain fade exceeds the fade margin (weather)."),
    ("NO DATA", "The data needed to decide could not be retrieved. Nothing was substituted."),
]
