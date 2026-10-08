"""Terrestrial Path Clearance engine -- calls aei_link_clearance.analyze_link
and explain() unmodified. This module only adapts QGIS features into that
function's arguments; no Fresnel/terrain math lives here."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

from aei_link_clearance import LinkClearanceResult, analyze_link, explain
from aei_link_clearance import terrain as _library_terrain

from ..record_source import frequency_ghz_from_record, frequency_origin, record_labels
from ..validation import NoDataError, require_corrected_clearance, terrain_input_reasons

from ..features import feature_attr, feature_id_name, feature_to_latlon

# Bounds carry their own basis, because an out-of-range value is accepted,
# computed and exported typed "Calculated" -- a physically meaningless number
# wearing the same authority as a real one. Each "basis" below says where the
# limit comes from; where no citable source exists it says so explicitly
# rather than presenting an engineering judgment as derived.
PARAM_SPEC = [
    {"key": "site_a_height_m", "label": "Site A antenna height", "type": "float",
     "default": 30.0, "suffix": " m", "min": 0.1, "max": 1000.0,
     "basis": "Conservative engineering limit, not a derived bound: no library or "
              "standard constrains antenna height. 1000 m clears the CN Tower (553 m) "
              "and the tallest guyed mast (~628 m) with margin."},
    {"key": "site_b_height_m", "label": "Site B antenna height", "type": "float",
     "default": 30.0, "suffix": " m", "min": 0.1, "max": 1000.0,
     "basis": "Conservative engineering limit, not a derived bound: no library or "
              "standard constrains antenna height. 1000 m clears the CN Tower (553 m) "
              "and the tallest guyed mast (~628 m) with margin."},
    {"key": "frequency_ghz", "label": "Frequency", "type": "float", "decimals": 5,
     "default": 7.0, "suffix": " GHz", "min": 0.1, "max": 100.0,
     "basis": "Lower bound derived: aei_link_clearance.fresnel.fresnel_radius_m and "
              "terrain.py both raise ValueError for a non-positive frequency. The "
              "0.1-100 GHz envelope is a conservative engineering limit, not a model "
              "range -- Fresnel geometry has no frequency ceiling. It brackets the "
              "loaded ISED Fixed Service data (915.1 MHz to 85.75 GHz) so it cannot "
              "exclude a real record."},
]


@dataclass
class TerrestrialAnalysisResult:
    kind: str
    site_a_name: str
    site_b_name: str
    site_a_source: str
    site_b_source: str
    site_a_height_m: float
    site_b_height_m: float
    site_a_height_from_feature: bool
    site_b_height_from_feature: bool
    result: LinkClearanceResult
    explanation: str
    # Where the frequency came from, as (type, source note) with type in the evidence vocabulary. None = the two-site flow, where the value
    # is entered by the user and is Assumed. Set by the link-record flow (frequency-origin channel, see core/record_source.py).
    frequency_origin: Optional[Tuple[str, str]] = None
    # The selected link record (id, source, attribution) when the analysis was started from one; None for two free sites.
    record: Optional[dict] = None


def build_params(entries) -> dict:
    """Pre-fills defaults from feature attributes when the layer already
    carries them (e.g. towers' height_above_ground_m), same convention as
    M1's extract_link_defaults()."""
    (layer_a, feat_a), (layer_b, feat_b) = entries
    defaults = {p["key"]: p["default"] for p in PARAM_SPEC}
    height_a = feature_attr(feat_a, "height_above_ground_m")
    height_b = feature_attr(feat_b, "height_above_ground_m")
    if height_a is not None:
        defaults["site_a_height_m"] = float(height_a)
    if height_b is not None:
        defaults["site_b_height_m"] = float(height_b)
    return defaults


def analyze_endpoints(lat_a, lon_a, lat_b, lon_b, params: dict, link_id: str) -> LinkClearanceResult:
    """QGIS-free boundary of the terrain decision: library guard, explicit NO DATA validation, then the unmodified library call."""
    require_corrected_clearance(_library_terrain)
    reasons = terrain_input_reasons(lat_a, lon_a, lat_b, lon_b, params["site_a_height_m"], params["site_b_height_m"], params["frequency_ghz"])
    if reasons:
        raise NoDataError("terrain", reasons)

    # Imported here, after the library-convention guard above, so an old library fails with the clear message rather than an ImportError.
    import requests
    from aei_link_clearance.elevation import ElevationDataError
    try:
        return analyze_link(
            link_id=link_id,
            site_a_lat=lat_a, site_a_lon=lon_a, site_a_height_m=params["site_a_height_m"],
            site_b_lat=lat_b, site_b_lon=lon_b, site_b_height_m=params["site_b_height_m"],
            frequency_ghz=params["frequency_ghz"],
        )
    except (ElevationDataError, requests.exceptions.RequestException) as exc:   # the two explicit elevation-data failures only (T1, R5)
        raise NoDataError("terrain", [f"elevation data unavailable (T1/R5): {exc}"]) from exc


def analyze(entries, params: dict) -> TerrestrialAnalysisResult:
    (layer_a, feat_a), (layer_b, feat_b) = entries
    lat_a, lon_a = feature_to_latlon(layer_a, feat_a)
    lat_b, lon_b = feature_to_latlon(layer_b, feat_b)
    id_a, name_a = feature_id_name(feat_a, "Selected site A")
    id_b, name_b = feature_id_name(feat_b, "Selected site B")
    source_a = feature_attr(feat_a, "source", "Selected QGIS feature")
    source_b = feature_attr(feat_b, "source", "Selected QGIS feature")

    result = analyze_endpoints(lat_a, lon_a, lat_b, lon_b, params, f"{id_a}__{id_b}")
    return TerrestrialAnalysisResult(
        kind="terrestrial", site_a_name=name_a, site_b_name=name_b,
        site_a_source=source_a, site_b_source=source_b,
        site_a_height_m=params["site_a_height_m"], site_b_height_m=params["site_b_height_m"],
        site_a_height_from_feature=feature_attr(feat_a, "height_above_ground_m") is not None,
        site_b_height_from_feature=feature_attr(feat_b, "height_above_ground_m") is not None,
        result=result, explanation=explain(result),
    )


def build_link_params(link_attrs: dict) -> Tuple[dict, Optional[float], str]:
    """Dialog defaults for a terrain analysis started from ONE selected link record: (defaults, record_ghz, record_note).

    The frequency is the highest published on the record (the same rule as the Velorona Map). Antenna heights are not published by either
    register's pack, so they keep the 30 m default and are typed Assumed."""
    defaults = {p["key"]: p["default"] for p in PARAM_SPEC}
    record_ghz, note = frequency_ghz_from_record(link_attrs.get("frequencies_mhz"))
    if record_ghz is not None:
        defaults["frequency_ghz"] = record_ghz
    return defaults, record_ghz, note


def analyze_link_record(link_attrs: dict, site_a_point, site_b_point, params: dict) -> TerrestrialAnalysisResult:
    """Terrain clearance for a Fixed Service link record, using the endpoints and the frequency the record carries.

    ``params`` are the values the user confirmed in the dialog. The frequency is typed Observed only if it still equals the record's own
    value; an overridden value is Assumed (spec F.1). Pairing comes from the record, never from proximity."""
    labels = record_labels(link_attrs)
    authorization = str(link_attrs.get("authorization_number") or link_attrs.get("id") or "link")
    source = str(link_attrs.get("source") or labels.extract)
    record_ghz, note = frequency_ghz_from_record(link_attrs.get("frequencies_mhz"))
    origin = frequency_origin(record_ghz, note, params["frequency_ghz"], labels)

    result = analyze_endpoints(site_a_point[0], site_a_point[1], site_b_point[0], site_b_point[1], params, authorization)
    return TerrestrialAnalysisResult(
        kind="terrestrial", site_a_name=f"Site A of {authorization}", site_b_name=f"Site B of {authorization}",
        site_a_source=source, site_b_source=source,
        site_a_height_m=params["site_a_height_m"], site_b_height_m=params["site_b_height_m"],
        site_a_height_from_feature=False, site_b_height_from_feature=False,
        result=result, explanation=explain(result), frequency_origin=origin,
        record={"id": link_attrs.get("id"), "authorization_number": authorization, "source": source,
                "coverage": link_attrs.get("coverage"), "country": link_attrs.get("country"),
                "attribution": link_attrs.get("attribution"), "pack_generated": link_attrs.get("pack_generated"),
                "source_file_updated": link_attrs.get("source_file_updated"),
                "pack_input_sha256": link_attrs.get("pack_input_sha256")},
    )
