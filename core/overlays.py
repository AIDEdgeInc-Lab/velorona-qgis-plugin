"""Hero result-overlay layers -- Weather Evidence and Terrain/Elevation.

Neither is a pre-loadable public data source (there is no 'weather
evidence' or 'terrain' dataset independent of a specific analyzed link);
both are built from data an engine already computed, visualized as a QGIS
layer in addition to the results dock. Weather Evidence mirrors the
nearest-station marker + dashed distance line aei_mw_exposure's own
Streamlit Explorer (app.py) already draws on its map. Terrain/Elevation
visualizes aei_link_clearance's own ProfilePoint samples. No new
engineering -- both are already-computed data, just also rendered as a
layer here.
"""

from __future__ import annotations

from qgis.PyQt.QtCore import QVariant

from .colors import COLORS
from .layers import build_link_layer, build_point_layer

WEATHER_STATION_FIELDS = [
    ("site_name", QVariant.String), ("station_source", QVariant.String),
    ("distance_km", QVariant.Double), ("rain_rate_mm_h", QVariant.Double),
    ("station_timestamp", QVariant.String),
]

WEATHER_LINE_FIELDS = [
    ("site_name", QVariant.String), ("distance_km", QVariant.Double), ("note", QVariant.String),
]

TERRAIN_FIELDS = [
    ("link_id", QVariant.String), ("distance_from_a_km", QVariant.Double),
    ("ground_elevation_m", QVariant.Double), ("terrain_adjusted_m", QVariant.Double),
    ("los_height_m", QVariant.Double), ("fresnel_radius_m", QVariant.Double),
    ("clearance_m", QVariant.Double), ("percent_fresnel_clear", QVariant.Double),
]

NOT_A_MICROWAVE_LINK_NOTE = "Distance between infrastructure and weather observation -- not a microwave link."


def build_weather_evidence_layers(microwave_result):
    """Returns (stations_layer, distance_lines_layer) built from the
    result's WeatherRepresentativeness per site. Only sites with a nearest
    station produce a marker/line -- never fabricated."""
    station_records = []
    line_records = []
    for rep in microwave_result.representativeness.values():
        station = rep.nearest_station
        if station is None:
            continue
        station_records.append({
            "latitude": station.latitude, "longitude": station.longitude,
            "site_name": rep.site.name, "station_source": station.source,
            "distance_km": rep.station_distance_km,
            "rain_rate_mm_h": station.rain_rate_mm_h if rep.station_reports_precipitation else None,
            "station_timestamp": station.timestamp,
        })
        line_records.append({
            "site_a": {"latitude": rep.site.latitude, "longitude": rep.site.longitude},
            "site_b": {"latitude": station.latitude, "longitude": station.longitude},
            "site_name": rep.site.name, "distance_km": rep.station_distance_km,
            "note": NOT_A_MICROWAVE_LINK_NOTE,
        })

    stations_layer = build_point_layer(
        "Weather Evidence -- Stations", station_records, WEATHER_STATION_FIELDS, COLORS["weather-evidence"],
        kind="weather-evidence",
        abstract="Nearest ECCC observing station per analyzed site. Evidence of weather, not a hardware diagnosis.",
    )
    lines_layer = build_link_layer(
        "Weather Evidence -- Distance", line_records, WEATHER_LINE_FIELDS, "#777777",
        line_style="dash",
        abstract=NOT_A_MICROWAVE_LINK_NOTE,
    )
    return stations_layer, lines_layer


def build_terrain_layer(terrestrial_result):
    """One point per elevation-profile sample already computed inside
    aei_link_clearance.analyze_link()'s LinkClearanceResult.profile."""
    r = terrestrial_result.result
    records = []
    for p in r.profile:
        records.append({
            "latitude": p.latitude, "longitude": p.longitude,
            "link_id": r.link_id, "distance_from_a_km": p.distance_from_a_km,
            "ground_elevation_m": p.ground_elevation_m, "terrain_adjusted_m": p.terrain_adjusted_m,
            "los_height_m": p.los_height_m, "fresnel_radius_m": p.fresnel_radius_m,
            "clearance_m": p.clearance_m, "percent_fresnel_clear": p.percent_fresnel_clear,
        })
    return build_point_layer(
        "Terrain / Elevation", records, TERRAIN_FIELDS, COLORS["terrain"],
        kind="terrain",
        abstract="Elevation profile sampled along the analyzed path (Open-Meteo Elevation API, Copernicus DEM GLO-90), "
                  "from aei_link_clearance's own terrain-clearance calculation.",
    )
