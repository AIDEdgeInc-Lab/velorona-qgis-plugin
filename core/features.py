"""Shared QGIS-feature helpers used by every analysis engine."""

from __future__ import annotations

from qgis.core import QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsProject

WGS84 = QgsCoordinateReferenceSystem("EPSG:4326")


def feature_to_latlon(layer, feature) -> tuple[float, float]:
    """(latitude, longitude) in EPSG:4326, reprojecting from the layer's
    own CRS if needed. Uses the geometry centroid -- the feature's own
    point for a point layer, a reasonable stand-in for anything else."""
    geom = feature.geometry()
    if geom is None or geom.isEmpty():
        raise ValueError(f"feature {feature.id()} has no geometry")
    point = geom.centroid().asPoint()
    layer_crs = layer.crs()
    if layer_crs != WGS84:
        transform = QgsCoordinateTransform(layer_crs, WGS84, QgsProject.instance())
        point = transform.transform(point)
    return point.y(), point.x()


def feature_id_name(feature, fallback_label: str) -> tuple[str, str]:
    fields = feature.fields().names()
    raw_id = feature["id"] if "id" in fields else None
    raw_name = feature["name"] if "name" in fields else None
    feature_id = str(raw_id) if raw_id not in (None, "") else f"qgis-feature-{feature.id()}"
    name = str(raw_name) if raw_name not in (None, "") else fallback_label
    return feature_id, name


def feature_attr(feature, key, default=None):
    fields = feature.fields().names()
    if key in fields and feature[key] not in (None, ""):
        return feature[key]
    return default
