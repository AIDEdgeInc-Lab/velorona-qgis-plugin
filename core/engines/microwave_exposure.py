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


def frequency_ghz_from_record(frequencies_mhz) -> tuple:
    """(GHz, provenance note) from an ISED Fixed Service record's published
    frequency list, or (None, reason). The highest published frequency on the
    authorization is used: rain attenuation rises with frequency, so it is the
    conservative choice, and it is a value from the record -- never invented."""
    if not frequencies_mhz:
        return None, "No frequency published on this authorization."
    values = []
    for chunk in str(frequencies_mhz).split(","):
        try:
            values.append(float(chunk.strip()))
        except ValueError:
            continue
    if not values:
        return None, "Published frequency could not be parsed from this record."
    top = max(values)
    note = (f"Highest of {len(values)} published frequencies on this authorization "
            f"({top:.1f} MHz); rain attenuation rises with frequency.")
    return top / 1000.0, note


def endpoint_site(latitude, longitude, site_id, name, source) -> MicrowaveSite:
    """A MicrowaveSite at a Fixed Service link endpoint. The coordinates come
    from the ISED record the link itself carries, so the site is REAL, not
    user-entered and not inferred from proximity."""
    return MicrowaveSite(
        id=site_id, name=name, latitude=latitude, longitude=longitude,
        provenance=Provenance.REAL, source=source,
    )


def analyze_sites(site_a: MicrowaveSite, site_b: MicrowaveSite, params: dict,
                  link_provenance: Provenance = Provenance.USER_PROVIDED,
                  link_source: str = "Velorona QGIS plugin -- link parameters entered by user",
                  link_id: str = None) -> MicrowaveAnalysisResult:
    """The shared exposure + representativeness pass. Both the two-selected-
    sites path and the Fixed Service link path end up here, so there is one
    calculation, not two."""
    if site_a.id == site_b.id:
        site_a = MicrowaveSite(**{**site_a.__dict__, "id": f"{site_a.id}-a"})
        site_b = MicrowaveSite(**{**site_b.__dict__, "id": f"{site_b.id}-b"})

    link = MicrowaveLink(
        id=link_id or f"{site_a.id}__{site_b.id}", site_a=site_a, site_b=site_b,
        frequency_ghz=params["frequency_ghz"], polarization=params["polarization"],
        fade_margin_db=params["fade_margin_db"], provenance=link_provenance,
        source=link_source,
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


def analyze(entries, params: dict) -> MicrowaveAnalysisResult:
    """Two selected point features as the link's endpoints -- unchanged
    behaviour for the 'Analyze: Microwave Weather Exposure' action."""
    (layer_a, feat_a), (layer_b, feat_b) = entries
    return analyze_sites(
        _build_site(layer_a, feat_a, "Selected site A"),
        _build_site(layer_b, feat_b, "Selected site B"),
        params,
    )


def build_link_params(link_attrs: dict) -> tuple:
    """(params, origins) for a Fixed Service link record.

    Only the frequency exists in the public record. Polarization and fade
    margin are not published in ISED's Fixed Service extract, so they stay at
    the engine defaults and are reported as assumptions -- never presented as
    observations from the record."""
    frequency_ghz, frequency_note = frequency_ghz_from_record(link_attrs.get("frequencies_mhz"))
    defaults = {p["key"]: p["default"] for p in PARAM_SPEC}
    params = dict(defaults)
    origins = {
        "polarization": ("Assumed", f"Engine default ({defaults['polarization']}); not published in the "
                                    "ISED Fixed Service extract."),
        "fade_margin_db": ("Assumed", f"Engine default ({defaults['fade_margin_db']:.0f} dB); not published in "
                                      "the ISED Fixed Service extract."),
    }
    if frequency_ghz is not None:
        params["frequency_ghz"] = frequency_ghz
        origins["frequency_ghz"] = ("Observed", frequency_note)
    else:
        origins["frequency_ghz"] = ("Assumed", f"{frequency_note} Engine default "
                                               f"({defaults['frequency_ghz']:.1f} GHz) used instead.")
    return params, origins


def analyze_link_record(site_a_latlon, site_b_latlon, link_attrs: dict, params: dict) -> MicrowaveAnalysisResult:
    """Weather exposure for a Fixed Service link, using the endpoints the link
    record itself carries. The pairing comes from the shared authorization in
    ISED's extract -- it is never inferred from proximity."""
    lat_a, lon_a = site_a_latlon
    lat_b, lon_b = site_b_latlon
    authorization = link_attrs.get("authorization_number") or link_attrs.get("id") or "link"
    source = link_attrs.get("source") or "ISED Fixed Service extract"
    return analyze_sites(
        endpoint_site(lat_a, lon_a, f"{authorization}-A", "Site A", source),
        endpoint_site(lat_b, lon_b, f"{authorization}-B", "Site B", source),
        params,
        link_provenance=Provenance.DERIVED,
        link_source=(f"ISED Fixed Service authorization {authorization} -- endpoints and frequency from the "
                     "public record; polarization and fade margin are engine assumptions."),
        link_id=str(authorization),
    )
