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

from .colors import COLORS_DARK, COLORS_LIGHT

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

# Normal Fixed Service links need a different ink per basemap, at a lower
# opacity than the type colour itself, so they never compete with a selected
# link. The hue is the same one core/colors.py assigns "fixed-links" for that
# appearance -- previously this borrowed the *fixed-sites* brand-blue hue on
# light mode specifically because the old fixed-links hex (#99C6F3) measured
# only 1.18:1 against Voyager even at high alpha; the new fixed-links hue
# (chosen for the six-type distinctness system, see colors.py) measures
# 3.52:1 solid, so no borrowing is needed any more. Alpha is unchanged from
# the original measurement: composited, both stay far below the selected
# link's 8.15:1 (light) / 15.80:1 (dark), so selected > connected > normal
# still holds.
LINK_INK_DARK = {"color": COLORS_DARK["fixed-links"], "alpha": 90}
LINK_INK_LIGHT = {"color": COLORS_LIGHT["fixed-links"], "alpha": 128}


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

# Cluster ink, as "r,g,b,a" (alpha out of 255), derived from each layer's own
# type colour rather than one shared accent. The web map's own
# .marker-cluster-velorona is one shared blue for every clustered layer
# (aei-link-clearance/web/style.css) -- the six-type distinctness system this
# module now supports is a Velorona-QGIS-specific requirement (reported
# directly by an operator running the demo, not a Web Map parity item), so it
# intentionally diverges from the web map here.
#
# The *treatment* is still the one measured against the web map's CSS:
# fill = the type colour, blended to a 0.366 composite alpha (93/255) --
# stacking --accent-soft 0.12 under an inner 0.28 the web map applies to its
# single shared accent composites to 1-(1-0.12)*(1-0.28) = 0.366 of the base
# hue; translucent rather than flattened to a solid hex, so the basemap reads
# through and a cluster stays a rendering aid, not an object that occludes
# the map. Stroke = the same hue lightened (dark mode, a glow ring) or
# darkened (light mode, to hold its edge against Voyager's cream) by a fixed
# amount in CIELab lightness, at the same alphas the earlier single-accent
# calibration measured: 61/255 (0.24) dark, 77/255 (0.30) light.
CLUSTER_FILL_ALPHA = 93          # 0.366 -- the web map's stacked composite
CLUSTER_STROKE_ALPHA_DARK = 61   # 0.24  -- the web map's own --accent-line
CLUSTER_STROKE_ALPHA_LIGHT = 77  # 0.30  -- held slightly heavier for Voyager
CLUSTER_STROKE_LIGHTNESS_SHIFT = 30  # CIELab L units, lighten dark / darken light
CLUSTER_TEXT_DARK = "#F5F7FA"    # basemap-dependent only, not type-dependent --
CLUSTER_TEXT_LIGHT = "#12242F"   # verified to hold >= 4.5:1 against every type's
                                  # composited fill in tests/qgis_e2e.py


def _hex_to_rgb(hex_color: str):
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i:i + 2], 16) for i in (0, 2, 4))


def _srgb_to_linear(c: float) -> float:
    c /= 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _linear_to_srgb(c: float) -> float:
    c = max(0.0, min(1.0, c))
    return 255 * (12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055)


def _rgb_to_lab(rgb):
    r, g, b = (_srgb_to_linear(v) for v in rgb)
    x = (r * 0.4124 + g * 0.3576 + b * 0.1805) / 0.95047
    y = r * 0.2126 + g * 0.7152 + b * 0.0722
    z = (r * 0.0193 + g * 0.1192 + b * 0.9505) / 1.08883
    f = lambda t: t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116
    fx, fy, fz = f(x), f(y), f(z)
    return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))


def _lab_to_rgb(lab):
    L, a, b = lab
    fy = (L + 16) / 116
    fx, fz = fy + a / 500, fy - b / 200
    finv = lambda t: t ** 3 if t ** 3 > 0.008856 else (t - 16 / 116) / 7.787
    x, y, z = finv(fx) * 0.95047, finv(fy), finv(fz) * 1.08883
    r = x * 3.2406 + y * -1.5372 + z * -0.4986
    g = x * -0.9689 + y * 1.8758 + z * 0.0415
    bl = x * 0.0557 + y * -0.2040 + z * 1.0570
    return tuple(round(_linear_to_srgb(v)) for v in (r, g, bl))


def _shift_lightness(hex_color: str, delta_l: float) -> tuple:
    """hex_color's own hue, lightened (positive delta_l) or darkened
    (negative), by shifting CIELab L -- a perceptual lightness move, not a
    naive per-channel blend toward white/black."""
    L, a, b = _rgb_to_lab(_hex_to_rgb(hex_color))
    return _lab_to_rgb((max(0.0, min(100.0, L + delta_l)), a, b))


def cluster_ink(color_hex: str, dark: bool = True) -> dict:
    """The fill/stroke/text ink for one layer type's cluster bubble in one
    map appearance -- see the module-level comment above for the alpha and
    lightness-shift rationale."""
    r, g, b = _hex_to_rgb(color_hex)
    stroke_alpha = CLUSTER_STROKE_ALPHA_DARK if dark else CLUSTER_STROKE_ALPHA_LIGHT
    shift = CLUSTER_STROKE_LIGHTNESS_SHIFT if dark else -CLUSTER_STROKE_LIGHTNESS_SHIFT
    sr, sg, sb = _shift_lightness(color_hex, shift)
    return {
        "fill": f"{r},{g},{b},{CLUSTER_FILL_ALPHA}",
        "stroke": f"{sr},{sg},{sb},{stroke_alpha}",
        "text": CLUSTER_TEXT_DARK if dark else CLUSTER_TEXT_LIGHT,
    }


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

# Every clustered point layer's source key -> the colour-lookup key
# core/colors.py uses for it (mostly the same string with a hyphen instead of
# an underscore; kept explicit rather than derived so a renamed SOURCE_* or
# COLORS_* key fails loudly instead of silently mismatching).
CLUSTERED_LAYER_COLOR_KEY = {
    SOURCE_FIXED_SITES: "fixed-sites",
    SOURCE_TOWERS: "towers",
    SOURCE_CELLULAR: "cellular",
    SOURCE_SATELLITES: "satellites",
    SOURCE_GROUND_STATIONS: "ground-stations",
}

# The three layers that carry a 'licensee' field and therefore participate in
# the Operator filter -- Fixed Service sites and links (ISED) and Cellular
# sites (ISED via the Esri Canada mirror). Towers, Satellites and Ground
# Stations do not carry a licensee/operator field at all.
OPERATOR_SOURCE_KEYS = (SOURCE_FIXED_SITES, SOURCE_FIXED_LINKS, SOURCE_CELLULAR)


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


def cluster_symbol(color_hex: str, dark: bool = True) -> QgsMarkerSymbol:
    """The Velorona cluster bubble for one layer type: a restrained disc in
    that layer's own colour, sized by how many records it represents, with
    the count drawn on top.

    Same visual language as the web map's .marker-cluster-velorona -- accent
    fill, accent border, bold count -- rather than QGIS's default cluster
    style, and size-capped so a dense region cannot produce a disc that covers
    the map. Unlike the web map (one shared accent for every cluster), the
    fill/stroke hue is per layer type -- see cluster_ink()'s docstring."""
    ink = cluster_ink(color_hex, dark)

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
    renderer.setClusterSymbol(cluster_symbol(color_hex, dark))
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
