"""Terrestrial Path Clearance engine -- calls aei_link_clearance.analyze_link
and explain() unmodified. This module only adapts QGIS features into that
function's arguments; no Fresnel/terrain math lives here."""

from __future__ import annotations

from dataclasses import dataclass

from aei_link_clearance import LinkClearanceResult, analyze_link, explain

from ..features import feature_attr, feature_id_name, feature_to_latlon

PARAM_SPEC = [
    {"key": "site_a_height_m", "label": "Site A antenna height", "type": "float", "default": 30.0, "suffix": " m"},
    {"key": "site_b_height_m", "label": "Site B antenna height", "type": "float", "default": 30.0, "suffix": " m"},
    {"key": "frequency_ghz", "label": "Frequency", "type": "float", "default": 7.0, "suffix": " GHz"},
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


def analyze(entries, params: dict) -> TerrestrialAnalysisResult:
    (layer_a, feat_a), (layer_b, feat_b) = entries
    lat_a, lon_a = feature_to_latlon(layer_a, feat_a)
    lat_b, lon_b = feature_to_latlon(layer_b, feat_b)
    id_a, name_a = feature_id_name(feat_a, "Selected site A")
    id_b, name_b = feature_id_name(feat_b, "Selected site B")
    source_a = feature_attr(feat_a, "source", "Selected QGIS feature")
    source_b = feature_attr(feat_b, "source", "Selected QGIS feature")

    result = analyze_link(
        link_id=f"{id_a}__{id_b}",
        site_a_lat=lat_a, site_a_lon=lon_a, site_a_height_m=params["site_a_height_m"],
        site_b_lat=lat_b, site_b_lon=lon_b, site_b_height_m=params["site_b_height_m"],
        frequency_ghz=params["frequency_ghz"],
    )
    return TerrestrialAnalysisResult(
        kind="terrestrial", site_a_name=name_a, site_b_name=name_b,
        site_a_source=source_a, site_b_source=source_b,
        site_a_height_m=params["site_a_height_m"], site_b_height_m=params["site_b_height_m"],
        site_a_height_from_feature=feature_attr(feat_a, "height_above_ground_m") is not None,
        site_b_height_from_feature=feature_attr(feat_b, "height_above_ground_m") is not None,
        result=result, explanation=explain(result),
    )
