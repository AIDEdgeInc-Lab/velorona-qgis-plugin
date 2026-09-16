"""Builds native QGIS vector layers from plain Python records. No new data
-- every record here was already produced by a `core/sources/*` adapter
that ports an existing Velorona Map fetch/parse function."""

from __future__ import annotations

from typing import Iterable, List, Sequence, Tuple

from qgis.core import (
    QgsFeature,
    QgsField,
    QgsGeometry,
    QgsLineSymbol,
    QgsMarkerSymbol,
    QgsPointClusterRenderer,
    QgsPointXY,
    QgsSingleSymbolRenderer,
    QgsUnitTypes,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QVariant
from qgis.PyQt.QtGui import QColor

# Marker/line visual weight, matched to the production web map's own
# values (aei-link-clearance/web/app.js: dotIcon()/addSiteMarker()/
# addLinkLine()) -- not re-picked from scratch. Sizes/widths are in
# screen pixels (not the QGIS default of millimetres), same reasoning as
# the web map: fixed visual weight regardless of zoom, so points read as
# distinct dots instead of overlapping into a solid mass at low zoom.
MARKER_SIZE_PX = 2.0
MARKER_ALPHA = 170  # ~67%, out of 255 -- overlapping points show density, not a blob
LINE_WIDTH_PX = 0.8
LINE_ALPHA = 90  # ~35%, matches addLinkLine()'s opacity: 0.35 for fixed-links
CLUSTER_TOLERANCE_PX = 40  # declustering distance -- QGIS's native point-cluster renderer,
# same idea as the web map's Leaflet.markercluster, no new dependency

VELORONA_KIND_PROPERTY = "velorona_kind"

# Required UI-honesty label for any layer showing raw public infrastructure
# records (towers, cellular, fixed-sites, fixed-links): sparse records in a
# region mean sparse public records, not proven absence of network
# coverage. Must be visible in the UI itself, not just documented --
# appended to the layer's display name (always visible in the Layers
# panel, no hover needed) and set as the layer's abstract (QGIS's native
# Layer Properties / metadata panel).
PUBLIC_RECORDS_DISCLOSURE = "public infrastructure records, not a coverage guarantee"


def _build_fields(field_specs: Sequence[Tuple[str, QVariant.Type]]) -> List[QgsField]:
    return [QgsField(name, qtype) for name, qtype in field_specs]


def _set_abstract(layer: QgsVectorLayer, abstract: str) -> None:
    """QgsMapLayer.setAbstract() is deprecated (3.38+, QGIS-Server-only);
    QgsLayerMetadata.abstract is the non-deprecated, Desktop-visible one
    (Layer Properties -> Metadata)."""
    metadata = layer.metadata()
    metadata.setAbstract(abstract)
    layer.setMetadata(metadata)


def _point_symbol(color_hex: str) -> QgsMarkerSymbol:
    color = QColor(color_hex)
    color.setAlpha(MARKER_ALPHA)
    symbol = QgsMarkerSymbol.createSimple({"outline_style": "no"})
    symbol.setColor(color)
    symbol.setSize(MARKER_SIZE_PX)
    symbol.setSizeUnit(QgsUnitTypes.RenderPixels)
    return symbol


def _clustered_renderer(color_hex: str) -> QgsPointClusterRenderer:
    """Small, semi-transparent dots by default, decluttered into count
    bubbles at low zoom -- QGIS's own built-in point-cluster renderer,
    same mechanism the production web map uses (Leaflet.markercluster),
    not a custom implementation."""
    embedded = QgsSingleSymbolRenderer(_point_symbol(color_hex))
    renderer = QgsPointClusterRenderer()
    renderer.setEmbeddedRenderer(embedded)
    renderer.setTolerance(CLUSTER_TOLERANCE_PX)
    renderer.setToleranceUnit(QgsUnitTypes.RenderPixels)
    cluster_color = QColor(color_hex)
    cluster_symbol = QgsMarkerSymbol.createSimple({
        "color": cluster_color.name(),
        "outline_color": "#05090C",  # legible against the dark basemap
        "outline_width": "0.5",
    })
    renderer.setClusterSymbol(cluster_symbol)
    return renderer


def build_point_layer(
    name: str,
    records: Iterable[dict],
    field_specs: Sequence[Tuple[str, QVariant.Type]],
    color_hex: str,
    kind: str = "site",
    abstract: str = None,
    cluster: bool = True,
) -> QgsVectorLayer:
    """Builds a memory point layer at EPSG:4326 from records carrying
    'latitude'/'longitude' plus whatever attributes field_specs names."""
    layer = QgsVectorLayer("Point?crs=EPSG:4326", name, "memory")
    provider = layer.dataProvider()
    provider.addAttributes(_build_fields(field_specs))
    layer.updateFields()

    features = []
    for record in records:
        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(record["longitude"], record["latitude"])))
        feature.setAttributes([record.get(field_name) for field_name, _ in field_specs])
        features.append(feature)
    provider.addFeatures(features)
    layer.updateExtents()

    layer.setRenderer(_clustered_renderer(color_hex) if cluster else QgsSingleSymbolRenderer(_point_symbol(color_hex)))
    layer.setCustomProperty(VELORONA_KIND_PROPERTY, kind)
    if abstract:
        _set_abstract(layer, abstract)
    return layer


def build_link_layer(
    name: str,
    links: Iterable[dict],
    field_specs: Sequence[Tuple[str, QVariant.Type]],
    color_hex: str,
    line_style: str = "solid",
    abstract: str = None,
) -> QgsVectorLayer:
    """Builds a memory line layer from link records, each carrying
    'site_a' and 'site_b' dicts with their own 'latitude'/'longitude'."""
    layer = QgsVectorLayer("LineString?crs=EPSG:4326", name, "memory")
    provider = layer.dataProvider()
    provider.addAttributes(_build_fields(field_specs))
    layer.updateFields()

    features = []
    for link in links:
        site_a, site_b = link["site_a"], link["site_b"]
        geom = QgsGeometry.fromPolylineXY([
            QgsPointXY(site_a["longitude"], site_a["latitude"]),
            QgsPointXY(site_b["longitude"], site_b["latitude"]),
        ])
        feature = QgsFeature(layer.fields())
        feature.setGeometry(geom)
        feature.setAttributes([link.get(field_name) for field_name, _ in field_specs])
        features.append(feature)
    provider.addFeatures(features)
    layer.updateExtents()

    color = QColor(color_hex)
    color.setAlpha(LINE_ALPHA)
    symbol = QgsLineSymbol.createSimple({"line_style": line_style})
    symbol.setColor(color)
    symbol.setWidth(LINE_WIDTH_PX)
    symbol.setWidthUnit(QgsUnitTypes.RenderPixels)
    layer.setRenderer(QgsSingleSymbolRenderer(symbol))
    layer.setCustomProperty(VELORONA_KIND_PROPERTY, "link")
    if abstract:
        _set_abstract(layer, abstract)
    return layer


def replace_point_features(layer: QgsVectorLayer, records: Iterable[dict], field_specs: Sequence[Tuple[str, QVariant.Type]]) -> None:
    """Clears and repopulates a memory point layer in place -- used for the
    viewport-scoped live layers (towers, cellular) on canvas extentsChanged,
    same refresh-in-place pattern as app.js's refreshLiveLayers()."""
    provider = layer.dataProvider()
    provider.truncate()
    features = []
    for record in records:
        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(record["longitude"], record["latitude"])))
        feature.setAttributes([record.get(field_name) for field_name, _ in field_specs])
        features.append(feature)
    provider.addFeatures(features)
    layer.updateExtents()
    layer.triggerRepaint()


def add_to_group(project, layer: QgsVectorLayer, group, visible: bool) -> None:
    """Adds a layer to the project and a layer-tree group, then sets the
    real Layers-panel checkbox state via QGIS's own native
    QgsLayerTreeLayer.setItemVisibilityChecked() -- the hero/context
    default-visibility split, not a custom on/off control."""
    project.addMapLayer(layer, False)
    node = group.addLayer(layer)
    node.setItemVisibilityChecked(visible)


def layer_kind(layer) -> str:
    """'satellite' / 'ground-station' for the two space layers this plugin
    creates; 'site' for every other point layer, including the user's own
    imported data -- matching the same kind-tagging convention app.js uses
    in wireFeature()."""
    value = layer.customProperty(VELORONA_KIND_PROPERTY)
    return value if value else "site"
