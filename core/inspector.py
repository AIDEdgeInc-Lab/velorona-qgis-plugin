"""Builds a plain-data entry from a selected QGIS feature, for the
single-feature drawer (site/link/satellite/ground-station) -- the QGIS
equivalent of app.js's openDrawer(entry) where entry = {kind, data}.

Only used for layers this plugin itself builds (all EPSG:4326 already),
so no CRS reprojection is needed here unlike core/features.py's
feature_to_latlon() (which must handle arbitrary imported layers)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple


@dataclass
class FeatureEntry:
    kind: str  # "site" | "link" | "satellite" | "ground-station"
    data: Dict[str, Any] = field(default_factory=dict)
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    site_a_point: Optional[Tuple[float, float]] = None  # (lat, lon)
    site_b_point: Optional[Tuple[float, float]] = None


def feature_to_entry(feature, kind: str) -> FeatureEntry:
    attrs = {f.name(): feature[f.name()] for f in feature.fields()}
    geom = feature.geometry()

    if kind == "link":
        polyline = geom.asMultiPolyline()[0] if geom.isMultipart() else geom.asPolyline()
        a, b = polyline[0], polyline[-1]
        return FeatureEntry(kind=kind, data=attrs, site_a_point=(a.y(), a.x()), site_b_point=(b.y(), b.x()))

    point = geom.centroid().asPoint()
    return FeatureEntry(kind=kind, data=attrs, latitude=point.y(), longitude=point.x())
