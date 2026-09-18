"""Shared-endpoint context for a selected Fixed Service link.

Two links are treated as connected only when they terminate at the *same*
endpoint coordinate -- the same site record in ISED's Fixed Service extract,
which is why both links carry an identical vertex. Nothing here infers a
relationship from proximity, distance, azimuth, frequency similarity or
visual crossing, and nothing here claims anything about fault behaviour: it is
spatial context for the map, not analysis.
"""

from __future__ import annotations

# Endpoint coordinates come from the same source record, so an exact match at
# 6 decimal places (~0.1 m) is an identity test, not a distance threshold.
_PRECISION = 6

# A hub site can carry many links; the context overlay is capped so a dense hub
# cannot turn one selection into thousands of drawn features.
MAX_CONNECTED = 60


def endpoint_key(latitude, longitude):
    return (round(float(latitude), _PRECISION), round(float(longitude), _PRECISION))


def _feature_endpoints(feature):
    geom = feature.geometry()
    if geom is None or geom.isEmpty():
        return None
    line = geom.asMultiPolyline()[0] if geom.isMultipart() else geom.asPolyline()
    if not line:
        return None
    return endpoint_key(line[0].y(), line[0].x()), endpoint_key(line[-1].y(), line[-1].x())


def build_endpoint_index(layer) -> dict:
    """endpoint key -> list of feature ids terminating there."""
    index = {}
    for feature in layer.getFeatures():
        ends = _feature_endpoints(feature)
        if ends is None:
            continue
        for key in ends:
            index.setdefault(key, []).append(feature.id())
    return index


def connected_links(index: dict, feature) -> dict:
    """Feature ids of other links sharing this link's Site A or Site B.

    Returns {"site_a": [...], "site_b": [...]} with the selected feature itself
    excluded. Empty lists mean the record shares no endpoint with any other
    link -- reported as such, never padded with nearby links."""
    ends = _feature_endpoints(feature)
    if ends is None:
        return {"site_a": [], "site_b": []}
    key_a, key_b = ends
    own = feature.id()
    return {
        "site_a": [fid for fid in index.get(key_a, []) if fid != own],
        "site_b": [fid for fid in index.get(key_b, []) if fid != own],
    }
