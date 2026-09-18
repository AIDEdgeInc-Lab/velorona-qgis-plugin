"""Builds native QGIS vector layers from plain Python records. No new data
-- every record here was already produced by a `core/sources/*` adapter
that ports an existing Velorona Map fetch/parse function."""

from __future__ import annotations

from typing import Iterable, List, Sequence, Tuple

from qgis.core import (
    QgsFeature,
    QgsField,
    QgsFontMarkerSymbolLayer,
    QgsGeometry,
    QgsLineSymbol,
    QgsMarkerSymbol,
    QgsPointClusterRenderer,
    QgsPointXY,
    QgsProperty,
    QgsSimpleMarkerSymbolLayer,
    QgsSingleSymbolRenderer,
    QgsSymbolLayer,
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

# Normal Fixed Service links need a different ink per basemap. Measured against
# Voyager's cream land, the dark-mode pale blue #99C6F3 reaches only 1.18:1 even
# at high alpha -- the hue, not the opacity, is the problem. The brand accent at
# half opacity reaches 1.60:1 while staying far below the selected link's
# 8.15:1, so the hierarchy selected > connected > normal still holds.
LINK_INK_DARK = {"color": "#99C6F3", "alpha": 90}
LINK_INK_LIGHT = {"color": "#5F98D1", "alpha": 128}


def link_symbol(dark: bool = True) -> QgsLineSymbol:
    ink = LINK_INK_DARK if dark else LINK_INK_LIGHT
    color = QColor(ink["color"])
    color.setAlpha(ink["alpha"])
    symbol = QgsLineSymbol.createSimple({"line_style": "solid"})
    symbol.setColor(color)
    symbol.setWidth(LINE_WIDTH_PX)
    symbol.setWidthUnit(QgsUnitTypes.RenderPixels)
    return symbol


# CARTO's converted style renders vegetation (wood/grass/scrub/nature_reserve/
# national_park, MapBox classes "landcover" and "park") at a colour that is, by
# measurement, *identical* to the bare-land background in Dark Matter --
# rgb(14,14,14) on rgb(14,14,14), zero distance -- so every landcover polygon
# is invisible and the dark map reads as flat black. Voyager's version is not
# invisible but is washed out: rgba(197,225,178,51), a pale green at 20%
# opacity over near-white land, distance ~18 from the land colour. Retinting
# only these two MapBox layers -- not touching water, boundary, waterway,
# transportation or landuse-residential, which already measure 40-140 RGB
# units of separation from their surroundings -- is the isolated, measured fix:
# same filters, same zoom ranges, same CARTO data, only the fill made visible.
BASEMAP_VEGETATION_LAYERS = ("landcover", "park")
BASEMAP_VEGETATION_FILL_DARK = QColor(24, 30, 24, 255)   # was (14,14,14) == land, 0 contrast
BASEMAP_VEGETATION_FILL_LIGHT = QColor(197, 225, 178, 132)  # was alpha 51 (20%); now ~52%


def retint_basemap_vegetation(renderer, dark: bool) -> int:
    """Recolours the landcover/park fill rules of an already-converted CARTO
    vector-tile renderer. Every filter expression, zoom range and other style
    rule is left exactly as CARTO defined it; only the fill (and its outline,
    kept equal to the fill so no new border appears) changes.

    Two independent things had to be fixed here, each verified in isolation
    before this was written:

    1. QgsVectorTileBasicRenderer.styles() returns value copies in PyQGIS -- a
       style fetched, mutated and dropped has no effect on the renderer
       (confirmed: a mutated copy, re-read from the renderer, came back
       unchanged). The full style list has to be rebuilt and written back with
       setStyles().

    2. Setting the symbol layer's static color was not enough on its own.
       QgsMapBoxGlStyleConverter preserves CARTO's zoom-interpolated colour
       stops as *data-defined* PropertyFillColor/PropertyStrokeColor
       expressions, which QGIS evaluates instead of the static colour at paint
       time. Confirmed directly: landcover, park, landuse and building all
       carry active data-defined fill/stroke properties, while the one
       polygon layer that visibly rendered without this fix -- water's base
       rule -- is the one layer with no active data-defined colour. An
       isolated render test (extreme colour, real tiles with confirmed
       source data, two different regions) produced zero drawn pixels for
       landcover until the data-defined property itself was replaced with a
       constant; after that, the same test produced thousands.

    Returns how many style rules were retinted, for verification."""
    target = BASEMAP_VEGETATION_FILL_DARK if dark else BASEMAP_VEGETATION_FILL_LIGHT
    styles = renderer.styles()
    touched = 0
    for style in styles:
        if style.layerName() not in BASEMAP_VEGETATION_LAYERS:
            continue
        symbol = style.symbol()
        if symbol is None:
            continue
        for i in range(symbol.symbolLayerCount()):
            layer = symbol.symbolLayer(i)
            if hasattr(layer, "setFillColor"):
                layer.setFillColor(QColor(target))
            if hasattr(layer, "setStrokeColor"):
                layer.setStrokeColor(QColor(target))
            if hasattr(layer, "setDataDefinedProperty"):
                layer.setDataDefinedProperty(QgsSymbolLayer.PropertyFillColor,
                                             QgsProperty.fromValue(QColor(target)))
                layer.setDataDefinedProperty(QgsSymbolLayer.PropertyStrokeColor,
                                             QgsProperty.fromValue(QColor(target)))
        style.setSymbol(symbol.clone())
        touched += 1
    renderer.setStyles(styles)
    return touched


# Clustering parameters ported from the Velorona Web Map's clusterGroup()
# (aei-link-clearance/web/app.js): same 50px grouping radius and the same
# 32/40/48px size tiers by represented-record count, so the two products
# behave and read alike. The count is a count of source records -- nothing
# about health, risk, coverage or performance is implied by it.
CLUSTER_TOLERANCE_PX = 50            # web map: maxClusterRadius: 50
CLUSTER_SIZE_SMALL_PX = 32           # web map: count < 25
CLUSTER_SIZE_MEDIUM_PX = 40          # web map: count < 100
CLUSTER_SIZE_LARGE_PX = 48           # web map: otherwise (also the cap)
CLUSTER_SIZE_EXPRESSION = (
    f"CASE WHEN @cluster_size < 25 THEN {CLUSTER_SIZE_SMALL_PX} "
    f"WHEN @cluster_size < 100 THEN {CLUSTER_SIZE_MEDIUM_PX} "
    f"ELSE {CLUSTER_SIZE_LARGE_PX} END"
)

# Cluster ink for each map appearance, as "r,g,b,a" (alpha out of 255).
#
# Dark is the web map's .marker-cluster-velorona measured rather than eyeballed
# (aei-link-clearance/web/style.css): the bubble stacks --accent-soft
# rgba(95,152,209,0.12) under an inner rgba(95,152,209,0.28), which over an
# opaque backdrop composites to a single 1-(1-0.12)*(1-0.28) = 0.366 alpha of
# the #5F98D1 accent -- 93/255. Keeping it *translucent* rather than flattening
# it to a solid hex is the point: the basemap reads through the bubble there,
# and a cluster is a rendering aid, not an object that occludes the map.
#
# The border is the web map's --accent-line rgba(153,198,243,0.24) = 61/255.
# The ring is soft because of that alpha, not because it is thin -- the web map
# draws a full 2px border and still reads as a halo.
#
# Light has no web map counterpart (it exists for CARTO Voyager). It gets the
# same treatment -- same translucent accent fill -- with the navy ring at 0.30
# rather than 0.24, because a dark ring on Voyager's cream land needs slightly
# more weight than a pale ring on Dark Matter to hold its edge.
CLUSTER_INK_DARK = {"fill": "95,152,209,93", "stroke": "153,198,243,61", "text": "#F5F7FA"}
CLUSTER_INK_LIGHT = {"fill": "95,152,209,93", "stroke": "34,75,117,77", "text": "#12242F"}

# Border and count geometry, both in screen pixels so they keep the web map's
# fixed ratio (a 12px count inside a 32/40/48px disc) instead of drifting apart
# under DPI scaling the way a Point-sized font inside a Pixel-sized disc does.
CLUSTER_STROKE_WIDTH_PX = 2          # web map: border: 2px solid var(--accent-line)
CLUSTER_COUNT_SIZE_PX = 12           # web map: .marker-cluster-velorona div font-size

VELORONA_KIND_PROPERTY = "velorona_kind"

# Ownership is tracked on the layer itself so the plugin can identify what it
# created without depending on instance attributes staying in sync (they do
# not survive a plugin reload). LIFECYCLE separates the two classes of owned
# layer: PERSISTENT layers are loaded public data the user works with and are
# left alone on unload; EVIDENCE layers are per-analysis overlays the plugin
# regenerates on the next run.
VELORONA_OWNER_PROPERTY = "velorona_owned"
VELORONA_LIFECYCLE_PROPERTY = "velorona_lifecycle"
VELORONA_SOURCE_KEY_PROPERTY = "velorona_source_key"
LIFECYCLE_PERSISTENT = "persistent"
LIFECYCLE_EVIDENCE = "evidence"

# Stable logical identity per public source, independent of display name, so a
# re-run of Load Public Data (or a plugin reload) can find the layer it already
# created instead of adding a second copy.
SOURCE_FIXED_SITES = "fixed_sites"
SOURCE_FIXED_LINKS = "fixed_links"
SOURCE_TOWERS = "towers"
SOURCE_CELLULAR = "cellular"
SOURCE_SATELLITES = "satellites"
SOURCE_GROUND_STATIONS = "ground_stations"
SOURCE_BASEMAP = "basemap"


def mark_velorona_owned(layer, lifecycle: str = LIFECYCLE_PERSISTENT,
                        source_key: str = None) -> None:
    layer.setCustomProperty(VELORONA_OWNER_PROPERTY, True)
    layer.setCustomProperty(VELORONA_LIFECYCLE_PROPERTY, lifecycle)
    if source_key:
        layer.setCustomProperty(VELORONA_SOURCE_KEY_PROPERTY, source_key)


def layer_source_key(layer) -> str:
    return layer.customProperty(VELORONA_SOURCE_KEY_PROPERTY) or ""


def find_owned_layer(project, source_key: str):
    """The Velorona-owned layer for this logical source, or None. Matching is
    by stored key, never by display name, so a renamed layer is still found and
    an unrelated user layer with a similar name never is."""
    for layer in project.mapLayers().values():
        if is_velorona_owned(layer) and layer_source_key(layer) == source_key:
            return layer
    return None


def is_velorona_owned(layer) -> bool:
    return bool(layer.customProperty(VELORONA_OWNER_PROPERTY))


def layer_lifecycle(layer) -> str:
    return layer.customProperty(VELORONA_LIFECYCLE_PROPERTY) or LIFECYCLE_PERSISTENT


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


def cluster_symbol(dark: bool = True) -> QgsMarkerSymbol:
    """The Velorona cluster bubble: a restrained accent disc sized by how many
    records it represents, with the count drawn on top.

    Same visual language as the web map's .marker-cluster-velorona -- accent
    fill, accent border, bold count -- rather than QGIS's default cluster
    style, and size-capped so a dense region cannot produce a disc that covers
    the map."""
    ink = CLUSTER_INK_DARK if dark else CLUSTER_INK_LIGHT

    disc = QgsSimpleMarkerSymbolLayer.create({
        "name": "circle",
        "color": ink["fill"],
        "outline_color": ink["stroke"],
        "outline_width": str(CLUSTER_STROKE_WIDTH_PX),
        "outline_width_unit": "Pixel",
        "size_unit": "Pixel",
    })
    disc.setDataDefinedProperty(
        QgsSymbolLayer.PropertySize, QgsProperty.fromExpression(CLUSTER_SIZE_EXPRESSION))

    count = QgsFontMarkerSymbolLayer.create({
        "font": "Helvetica",
        "chr": "0",
        "color": ink["text"],
        "size": str(CLUSTER_COUNT_SIZE_PX),
        "size_unit": "Pixel",
        "font_style": "Bold",
    })
    count.setDataDefinedProperty(
        QgsSymbolLayer.PropertyCharacter, QgsProperty.fromExpression("@cluster_size"))

    symbol = QgsMarkerSymbol()
    symbol.changeSymbolLayer(0, disc)
    symbol.appendSymbolLayer(count)
    return symbol


def _clustered_renderer(color_hex: str, dark: bool = True) -> QgsPointClusterRenderer:
    """Individual records at close zoom, grouped into counted clusters as the
    view widens -- QGIS's own point-cluster renderer, configured to the web
    map's parameters. The underlying data is untouched: every record stays
    reachable, and the cluster count is simply how many are represented."""
    embedded = QgsSingleSymbolRenderer(_point_symbol(color_hex))
    renderer = QgsPointClusterRenderer()
    renderer.setEmbeddedRenderer(embedded)
    renderer.setTolerance(CLUSTER_TOLERANCE_PX)
    renderer.setToleranceUnit(QgsUnitTypes.RenderPixels)
    renderer.setClusterSymbol(cluster_symbol(dark))
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


def build_context_link_layer(name: str, features, color_hex: str) -> QgsVectorLayer:
    """A soft secondary highlight for links that share an endpoint with the
    selected one. Geometry is copied from the features already in the project;
    no attributes are carried, because this layer is map context, not a record."""
    layer = QgsVectorLayer("LineString?crs=EPSG:4326", name, "memory")
    provider = layer.dataProvider()
    copies = []
    for source in features:
        feature = QgsFeature()
        feature.setGeometry(source.geometry())
        copies.append(feature)
    provider.addFeatures(copies)
    layer.updateExtents()

    color = QColor(color_hex)
    color.setAlpha(150)
    symbol = QgsLineSymbol.createSimple({"line_style": "dash"})
    symbol.setColor(color)
    symbol.setWidth(1.6)
    symbol.setWidthUnit(QgsUnitTypes.RenderPixels)
    layer.setRenderer(QgsSingleSymbolRenderer(symbol))
    layer.setCustomProperty(VELORONA_KIND_PROPERTY, "network-context")
    return layer


def replace_link_features(layer: QgsVectorLayer, links: Iterable[dict],
                          field_specs: Sequence[Tuple[str, QVariant.Type]]) -> None:
    """Clears and repopulates a memory line layer in place, so a re-run of
    Load Public Data refreshes the existing layer instead of adding a second
    one (and keeps whatever visibility/styling the user set)."""
    provider = layer.dataProvider()
    provider.truncate()
    features = []
    for link in links:
        site_a, site_b = link["site_a"], link["site_b"]
        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromPolylineXY([
            QgsPointXY(site_a["longitude"], site_a["latitude"]),
            QgsPointXY(site_b["longitude"], site_b["latitude"]),
        ]))
        feature.setAttributes([link.get(field_name) for field_name, _ in field_specs])
        features.append(feature)
    provider.addFeatures(features)
    layer.updateExtents()
    layer.triggerRepaint()


def add_to_group(project, layer: QgsVectorLayer, group, visible: bool,
                 lifecycle: str = LIFECYCLE_PERSISTENT, source_key: str = None) -> None:
    """Adds a layer to the project and a layer-tree group, then sets the
    real Layers-panel checkbox state via QGIS's own native
    QgsLayerTreeLayer.setItemVisibilityChecked() -- the hero/context
    default-visibility split, not a custom on/off control."""
    mark_velorona_owned(layer, lifecycle, source_key)
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
