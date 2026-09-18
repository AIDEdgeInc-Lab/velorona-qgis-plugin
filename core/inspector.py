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


@dataclass
class LinkInvestigation:
    """A selected Fixed Service link plus the weather evidence for its two
    endpoints. `exposure` is the unmodified MicrowaveAnalysisResult from the
    existing engine, or None when the live weather services could not be
    reached -- `weather_error` then carries the reason so the UI reports the
    limitation rather than substituting a value."""
    entry: FeatureEntry
    exposure: Any = None
    param_origins: Dict[str, Any] = field(default_factory=dict)
    weather_error: Optional[str] = None
    connected_site_a: int = 0
    connected_site_b: int = 0
    kind: str = "link-investigation"


@dataclass
class SelectionSummary:
    """Several features selected at once. Carries only what can be aggregated
    honestly from the loaded records -- counts, distinct licensees, the
    published frequency range and the geographic extent. No weather is fetched
    and no per-link analysis is run, so nothing here is an inference."""
    kind_label: str
    feature_kind: str
    count: int
    scanned: int
    licensees: list = field(default_factory=list)
    frequency_range: Optional[Tuple[float, float]] = None
    extent_wgs84: Optional[Tuple[float, float, float, float]] = None
    columns: list = field(default_factory=list)
    rows: list = field(default_factory=list)
    table_limit: int = 200
    # The layer-level filter the selection was made through, so the export can
    # state which subset the records were drawn from. Empty means unfiltered.
    licensee_filter: str = ""
    kind: str = "selection-summary"


def feature_to_entry(feature, kind: str) -> FeatureEntry:
    attrs = {f.name(): feature[f.name()] for f in feature.fields()}
    geom = feature.geometry()

    if kind == "link":
        polyline = geom.asMultiPolyline()[0] if geom.isMultipart() else geom.asPolyline()
        a, b = polyline[0], polyline[-1]
        return FeatureEntry(kind=kind, data=attrs, site_a_point=(a.y(), a.x()), site_b_point=(b.y(), b.x()))

    point = geom.centroid().asPoint()
    return FeatureEntry(kind=kind, data=attrs, latitude=point.y(), longitude=point.x())
