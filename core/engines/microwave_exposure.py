"""Microwave Weather Exposure engine -- calls aei_mw_exposure's
calculate_exposure() and assess_representativeness() unmodified. Carried
over from M1, generalized to work on any 2 selected 'site' features
(public or imported), not just a specific CSV fixture.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict

from aei_mw_exposure import LinkExposure, MicrowaveLink, MicrowaveSite, Provenance, calculate_exposure
from aei_mw_exposure.providers import eccc
from aei_mw_exposure.providers.open_meteo import OpenMeteoProvider
from aei_mw_exposure.representativeness import WeatherRepresentativeness, assess_representativeness

from ..features import feature_id_name, feature_to_latlon

PARAM_SPEC = [
    {"key": "frequency_ghz", "label": "Frequency", "type": "float", "default": 18.0, "suffix": " GHz"},
    {"key": "polarization", "label": "Polarization", "type": "choice", "default": "V", "choices": ["V", "H"]},
    {"key": "fade_margin_db", "label": "Fade margin", "type": "float", "default": 32.0, "suffix": " dB"},
]


@dataclass
class MicrowaveAnalysisResult:
    kind: str
    exposure: LinkExposure
    representativeness: Dict[str, WeatherRepresentativeness]
    weather_errors: Dict[str, str] = field(default_factory=dict)


def build_params(entries) -> dict:
    (layer_a, feat_a), (layer_b, feat_b) = entries
    defaults = {p["key"]: p["default"] for p in PARAM_SPEC}
    for feat in (feat_a, feat_b):
        fields = feat.fields().names()
        for key in ("frequency_ghz", "polarization", "fade_margin_db"):
            if key in fields and feat[key] not in (None, ""):
                defaults[key] = feat[key]
    return defaults


def _build_site(layer, feature, fallback_label: str) -> MicrowaveSite:
    lat, lon = feature_to_latlon(layer, feature)
    site_id, name = feature_id_name(feature, fallback_label)
    return MicrowaveSite(
        id=site_id, name=name, latitude=lat, longitude=lon,
        provenance=Provenance.USER_PROVIDED, source="Selected QGIS feature",
    )


def analyze(entries, params: dict) -> MicrowaveAnalysisResult:
    (layer_a, feat_a), (layer_b, feat_b) = entries
    site_a = _build_site(layer_a, feat_a, "Selected site A")
    site_b = _build_site(layer_b, feat_b, "Selected site B")
    if site_a.id == site_b.id:
        site_a = MicrowaveSite(**{**site_a.__dict__, "id": f"{site_a.id}-a"})
        site_b = MicrowaveSite(**{**site_b.__dict__, "id": f"{site_b.id}-b"})

    link = MicrowaveLink(
        id=f"{site_a.id}__{site_b.id}", site_a=site_a, site_b=site_b,
        frequency_ghz=params["frequency_ghz"], polarization=params["polarization"],
        fade_margin_db=params["fade_margin_db"], provenance=Provenance.USER_PROVIDED,
        source="Velorona QGIS plugin -- link parameters entered by user",
    )

    provider = OpenMeteoProvider()
    weather_errors: Dict[str, str] = {}
    weather_by_site = {}
    for site in (site_a, site_b):
        try:
            weather_by_site[site.id] = provider.get_current(site)
        except Exception as exc:  # live public API -- degrade, don't crash
            weather_errors[site.id] = str(exc)

    missing = [s.id for s in (site_a, site_b) if s.id not in weather_by_site]
    if missing:
        raise RuntimeError(
            "Could not fetch live weather (Open-Meteo) for: "
            + ", ".join(f"{site_id} ({weather_errors.get(site_id, 'unknown error')})" for site_id in missing)
        )

    exposure = calculate_exposure(link=link, weather_by_site=weather_by_site)

    representativeness: Dict[str, WeatherRepresentativeness] = {}
    for site in (site_a, site_b):
        station_obs = distance_km = has_precip = None
        try:
            station_result = eccc.find_nearest_station(site.latitude, site.longitude)
            if station_result is not None:
                station_obs, distance_km, has_precip = station_result
        except Exception as exc:
            weather_errors[f"{site.id} (ECCC station)"] = str(exc)

        radar_obs = None
        try:
            radar_obs = eccc.get_radar_precipitation(site.latitude, site.longitude)
        except Exception as exc:
            weather_errors[f"{site.id} (ECCC radar)"] = str(exc)

        if station_obs is not None:
            rep = assess_representativeness(
                site=site, nearest_station=station_obs, station_distance_km=distance_km,
                station_reports_precipitation=has_precip,
                model_observation=weather_by_site.get(site.id), radar_observation=radar_obs,
            )
        else:
            rep = assess_representativeness(
                site=site, model_observation=weather_by_site.get(site.id), radar_observation=radar_obs,
            )
        representativeness[site.id] = rep

    return MicrowaveAnalysisResult(
        kind="microwave-exposure", exposure=exposure,
        representativeness=representativeness, weather_errors=weather_errors,
    )
