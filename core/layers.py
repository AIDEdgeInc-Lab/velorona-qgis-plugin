"""Builds native QGIS vector layers from plain Python records. No new data
-- every record here was already produced by a `core/sources/*` adapter
that ports an existing Velorona Map fetch/parse function."""

from __future__ import annotations

from typing import Iterable, List, Sequence, Tuple

from qgis.core import (
    Qgis,
    QgsFeature,
    QgsField,
    QgsFontMarkerSymbolLayer,
    QgsGeometry,
    QgsLineSymbol,
    QgsMapLayer,
    QgsMarkerSymbol,
    QgsPointClusterRenderer,
    QgsPointXY,
    QgsProperty,
    QgsSimpleMarkerSymbolLayer,
    QgsSingleSymbolRenderer,
    QgsSymbolLayer,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QMetaType
from qgis.PyQt.QtGui import QColor

from .colors import COLORS_DARK, COLORS_LIGHT

# Marker/line visual weight, matched to the production web map's own
# values (aei-link-clearance/web/app.js: dotIcon()/addSiteMarker()/
# addLinkLine()) -- not re-picked from scratch. Sizes/widths are in
# screen pixels (not the QGIS default of millimetres), same reasoning as
# the web map: fixed visual weight regardless of zoom, so points read as
# distinct dots instead of overlapping into a solid mass at low zoom.
#
# MARKER_SIZE_PX raised from the web map's original 2.0: QGIS's own click/
# identify tolerance (QgsMapTool.searchRadiusMM(), a global, QgsSettings-
# backed value this plugin does not touch) is already generous --
# Qgis.DEFAULT_SEARCH_RADIUS_MM = 2.0mm, about a 7.6px radius at 96 DPI,
# independent of symbol size -- so a 2px dot wasn't hard to click because the
# hit area was too small; the hit area was never the bottleneck. It was hard
# to SEE where, inside that already-generous zone, to aim. 5.0px keeps the
# same "distinct dots, not a blob" character at density while being an
# actual target instead of a near-invisible speck.
MARKER_SIZE_PX = 5.0
MARKER_ALPHA = 170  # ~67%, out of 255 -- overlapping points show density, not a blob
LINE_WIDTH_PX = 0.8
LINE_ALPHA = 90  # ~35%, matches addLinkLine()'s opacity: 0.35 for fixed-links

# Selection halo -- drawn INSTEAD of the normal symbol only while a feature is
# selected (Qgis.SelectionRenderingMode.CustomSymbol, applied per layer in
# plugin.py, not QgsProject's project-wide setSelectionColor()). Because
# CustomSymbol replaces the whole symbol rather than tinting it, the halo
# symbol has to reproduce the layer's own coloured dot/line itself plus an
# added ring -- selection reads as "this one, and it is still a <type>"
# rather than the previous flat-colour swap, which could only ever show one
# or the other (measured: selecting a feature erased its type colour
# entirely, replacing it with a solid block of the selection colour).
#
# This is also the only mechanism that makes a selection visible at all for a
# feature still grouped inside a cluster bubble -- measured directly:
# QgsProject.setSelectionColor() (the previous mechanism) produced ZERO
# changed pixels for a feature inside an active cluster group, because the
# cluster bubble has no notion of "one of my members is selected" under that
# rendering mode. CustomSymbol mode makes QGIS break the selected feature out
# of its cluster and draw it individually with this halo -- confirmed by
# direct pixel diff, not assumed from documentation.
#
# Colour: the previous flat SELECTION_COLOR_DARK/LIGHT (#FFFF00 / #224B75, in
# plugin.py) were measured only against the two CARTO basemaps, never against
# the six PR #4 type colours -- CIEDE2000 measurement found the yellow falls
# to 4.6 against cellular (#FFBA7C) under deuteranopia/protanopia, and the
# navy to 9.3 against satellites (#508167) -- both well below the ~17 bar the
# six type colours hold against each other. A plain red or amber "fixes" that
# numerically but collides with this product's own severity colours
# (ui/theme.py: OBSTRUCTED #E2594F, MARGINAL #E0A73B) -- a selected feature
# could read as "this is obstructed" rather than "this is selected". These
# two hold >=10.8 CIEDE2000 against every type colour and every simulated
# vision type (deuteranopia/protanopia/tritanopia), and >=27/35 against the
# severity colours, so neither collision recurs.
SELECTION_HALO_COLOR_DARK = "#A48BDC"
SELECTION_HALO_COLOR_LIGHT = "#0A1620"
SELECTION_HALO_SIZE_PX = 11.0   # clearly exceeds the 5px marker without
SELECTION_HALO_WIDTH_PX = 2.0  # reading as a different, separate object

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


def fade_link_with_scale(symbol, color) -> None:
    """Fade and thin a link line as the view widens (see VIEW_SCALE_WIDE); full strength when zoomed in.
    The base colour stays the type hue; only the data-defined stroke colour/width vary,
    so the symbol's own colour (what tests and exports read) is unchanged."""
    layer = symbol.symbolLayer(0)
    a = color.alpha()
    layer.setDataDefinedProperty(QgsSymbolLayer.Property.StrokeColor, QgsProperty.fromExpression(
        f"color_rgba({color.red()},{color.green()},{color.blue()},"
        + scale_case(round(a * LINK_ALPHA_FACTOR_WIDE), round(a * LINK_ALPHA_FACTOR_MEDIUM), round(a * LINK_ALPHA_FACTOR_CLOSE))
        + ")"))
    layer.setDataDefinedProperty(QgsSymbolLayer.Property.StrokeWidth, QgsProperty.fromExpression(
        scale_case(round(LINE_WIDTH_PX * LINK_WIDTH_FACTOR_WIDE, 2), LINE_WIDTH_PX, LINE_WIDTH_PX)))


def link_symbol(dark: bool = True) -> QgsLineSymbol:
    ink = LINK_INK_DARK if dark else LINK_INK_LIGHT
    color = QColor(ink["color"])
    color.setAlpha(ink["alpha"])
    symbol = QgsLineSymbol.createSimple({"line_style": "solid"})
    symbol.setColor(color)
    symbol.setWidth(LINE_WIDTH_PX)
    symbol.setWidthUnit(Qgis.RenderUnit.Pixels)
    fade_link_with_scale(symbol, color)
    return symbol


def link_selection_symbol(dark: bool = True) -> QgsLineSymbol:
    """The selected-link symbol for Fixed Service links -- CustomSymbol mode's
    equivalent of selection_symbol() below, for a line instead of a point.
    Reproduces the link's own ink at full opacity (so it reads as the same
    link, not a different colour) plus a wider halo line beneath it."""
    ink = LINK_INK_DARK if dark else LINK_INK_LIGHT
    halo_color = SELECTION_HALO_COLOR_DARK if dark else SELECTION_HALO_COLOR_LIGHT

    halo = QgsLineSymbol.createSimple({"line_style": "solid"})
    halo_col = QColor(halo_color)
    halo_col.setAlpha(160)
    halo.setColor(halo_col)
    halo.setWidth(LINE_WIDTH_PX + SELECTION_HALO_WIDTH_PX * 2)
    halo.setWidthUnit(Qgis.RenderUnit.Pixels)

    core_line = QgsLineSymbol.createSimple({"line_style": "solid"})
    core_color = QColor(ink["color"])
    core_color.setAlpha(255)  # selected link is never the one left translucent
    core_line.setColor(core_color)
    core_line.setWidth(LINE_WIDTH_PX)
    core_line.setWidthUnit(Qgis.RenderUnit.Pixels)

    symbol = QgsLineSymbol()
    symbol.changeSymbolLayer(0, halo.symbolLayer(0).clone())
    symbol.appendSymbolLayer(core_line.symbolLayer(0).clone())
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
       stops as *data-defined* Property.FillColor/Property.StrokeColor
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
                layer.setDataDefinedProperty(QgsSymbolLayer.Property.FillColor,
                                             QgsProperty.fromValue(QColor(target)))
                layer.setDataDefinedProperty(QgsSymbolLayer.Property.StrokeColor,
                                             QgsProperty.fromValue(QColor(target)))
        style.setSymbol(symbol.clone())
        touched += 1
    renderer.setStyles(styles)
    return touched


# Light-basemap road legibility (field readability pass). CARTO Voyager draws minor, service and
# residential roads as a white fill with a white case on land #fbf8f3 (about 1.07:1), so the street
# network a technician navigates by is effectively invisible, and the pale-yellow/pale-orange arterials
# are only ~1.2:1. Only the colours of the existing road rules are replaced (filters, zoom ranges and
# the zoom-interpolated widths stay as CARTO defined them): a darker case gives every road an edge on
# the cream land, and arterials get progressively more saturated fills so the hierarchy
# (minor < secondary < primary < trunk/motorway) still reads. Dark Matter's roads were accepted as they
# are and are left untouched.
LIGHT_ROAD_CASE = {"service": "#A39D8F", "minor": "#A39D8F", "sec": "#BFA24F", "pri": "#CE9A2A",
                   "trunk": "#C4801A", "mot": "#C4801A"}
LIGHT_ROAD_FILL = {"service": "#FFFFFF", "minor": "#FFFFFF", "sec": "#FFF0A8", "pri": "#FFDC7A",
                   "trunk": "#FFC24A", "mot": "#FFC24A"}
LIGHT_ROAD_PATH = "#9C9588"
LIGHT_RAIL = "#8F8F8F"
LIGHT_BUILDING_FILL = "#D8CFC0"   # was #e4dcd0 (1.2:1 on land)
LIGHT_WATERWAY = "#8FBFCB"        # was #cce7ea (1.3:1 on land)


def _constant_color(layer, color: str) -> None:
    c = QColor(color)
    layer.setColor(c)                       # a line layer's stroke / a fill layer's fill
    if hasattr(layer, "setStrokeColor"):
        layer.setStrokeColor(c)
    if hasattr(layer, "setDataDefinedProperty"):
        layer.setDataDefinedProperty(QgsSymbolLayer.Property.StrokeColor, QgsProperty.fromValue(c))
        layer.setDataDefinedProperty(QgsSymbolLayer.Property.FillColor, QgsProperty.fromValue(c))


def _light_road_color(name: str):
    """The replacement colour for one CARTO Voyager style rule, or None to leave it alone."""
    if name.startswith("tunnel_"):
        return None            # tunnels stay faint on purpose
    if name.startswith(("road_", "bridge_")):
        if name.endswith("_path"):
            return LIGHT_ROAD_PATH
        parts = name.split("_")
        if len(parts) < 3 or parts[1] not in LIGHT_ROAD_CASE:
            return None
        if "_case" in name:
            return LIGHT_ROAD_CASE[parts[1]]
        if "_fill" in name:
            return LIGHT_ROAD_FILL[parts[1]]
        return None
    return {"rail": LIGHT_RAIL, "building": LIGHT_BUILDING_FILL, "waterway": LIGHT_WATERWAY}.get(name)


def retint_basemap_roads(renderer, dark: bool) -> int:
    """Raises road/rail/building/waterway contrast on the light basemap (see the constants above). A no-op
    for the dark basemap. Same write-back rules as retint_basemap_vegetation: styles() hands out copies and
    the converter's zoom-interpolated colours are data-defined, so both are replaced.
    Returns how many style rules were retinted."""
    if dark:
        return 0
    styles = renderer.styles()
    touched = 0
    for style in styles:
        color = _light_road_color(style.styleName())
        symbol = style.symbol()
        if color is None or symbol is None:
            continue
        for i in range(symbol.symbolLayerCount()):
            _constant_color(symbol.symbolLayer(i), color)
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

# Zoom-dependent calm (1.1.7 UI polish). A wide view shows many clusters and, for the US, tens of thousands of link lines; drawn at full strength they read as a
# dense mass. So the ink FADES and the discs SHRINK as the view widens, and return to the original strength when zoomed in,
# where there are few and each matters.
# Nothing about the data, the clustering (tolerance, counts) or the selection changes; only how loudly the same things are drawn. Thresholds are map scales
# (denominators), PROPOSED from rendering the US pack at ~1:1,000,000 (regional), ~1:200,000 (medium) and ~1:20,000 (close-up).
VIEW_SCALE_WIDE = 600000             # wider than 1:600,000
VIEW_SCALE_MEDIUM = 150000           # between 1:150,000 and 1:600,000
CLUSTER_FILL_ALPHA_WIDE = 46         # of 255; the full-strength value is CLUSTER_FILL_ALPHA below (used when zoomed in)
CLUSTER_FILL_ALPHA_MEDIUM = 70
CLUSTER_SIZE_FACTOR_WIDE = 0.8       # of the 32/40/48 px tiers
CLUSTER_SIZE_FACTOR_MEDIUM = 0.9
LINK_ALPHA_FACTOR_WIDE = 0.3         # of the link ink's alpha
LINK_ALPHA_FACTOR_MEDIUM = 0.55
LINK_ALPHA_FACTOR_CLOSE = 0.8
LINK_WIDTH_FACTOR_WIDE = 0.75


def scale_case(wide, medium, close) -> str:
    """A QGIS expression choosing a value by the current map scale."""
    return f"CASE WHEN @map_scale > {VIEW_SCALE_WIDE} THEN {wide} WHEN @map_scale > {VIEW_SCALE_MEDIUM} THEN {medium} ELSE {close} END"


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

    def f(t):
        return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116

    fx, fy, fz = f(x), f(y), f(z)
    return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))


def _lab_to_rgb(lab):
    L, a, b = lab
    fy = (L + 16) / 116
    fx, fz = fy + a / 500, fy - b / 200

    def finv(t):
        return t ** 3 if t ** 3 > 0.008856 else (t - 16 / 116) / 7.787

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
SOURCE_US_SITES = "us_fixed_sites"       # USA (FCC ULS) layers are separate from Canada's and loaded per extent from a pack
SOURCE_US_LINKS = "us_fixed_links"
SOURCE_US_OVERVIEW = "us_overview"       # presence counts for the zoomed-out United States (Velorona Map's "US overview"): not records, not selectable
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
    SOURCE_US_SITES: "fixed-sites",
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


VELORONA_SKIPPED_PROPERTY = "velorona_invalid_coordinates_skipped"


def valid_wgs84(latitude, longitude) -> bool:
    """True only for finite numbers inside the WGS84 range. A record that fails this is never drawn: a wrong or missing coordinate must not
    become a point on the map (it would look like a real location and Records/selection would navigate to it)."""
    try:
        lat, lon = float(latitude), float(longitude)
    except (TypeError, ValueError):
        return False
    return lat == lat and lon == lon and abs(lat) <= 90.0 and abs(lon) <= 180.0 and abs(lat) != float("inf") and abs(lon) != float("inf")


def _point_feature(layer, record, field_specs):
    """A feature for one point record, or None when its coordinates are missing or invalid."""
    if not valid_wgs84(record.get("latitude"), record.get("longitude")):
        return None
    feature = QgsFeature(layer.fields())
    feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(float(record["longitude"]), float(record["latitude"]))))
    feature.setAttributes([record.get(field_name) for field_name, _ in field_specs])
    return feature


def _link_feature(layer, link, field_specs):
    """A feature for one link record, or None when either endpoint is missing or has invalid coordinates."""
    site_a, site_b = link.get("site_a") or {}, link.get("site_b") or {}
    if not (valid_wgs84(site_a.get("latitude"), site_a.get("longitude")) and valid_wgs84(site_b.get("latitude"), site_b.get("longitude"))):
        return None
    feature = QgsFeature(layer.fields())
    feature.setGeometry(QgsGeometry.fromPolylineXY([
        QgsPointXY(float(site_a["longitude"]), float(site_a["latitude"])),
        QgsPointXY(float(site_b["longitude"]), float(site_b["latitude"])),
    ]))
    feature.setAttributes([link.get(field_name) for field_name, _ in field_specs])
    return feature


def _fill(layer, records, field_specs, make):
    features, skipped = [], 0
    for record in records:
        feature = make(layer, record, field_specs)
        if feature is None:
            skipped += 1
        else:
            features.append(feature)
    layer.dataProvider().addFeatures(features)
    layer.setCustomProperty(VELORONA_SKIPPED_PROPERTY, skipped)
    return skipped


def _build_fields(field_specs: Sequence[Tuple[str, QMetaType.Type]]) -> List[QgsField]:
    return [QgsField(name, qtype) for name, qtype in field_specs]


def set_abstract(layer: QgsVectorLayer, abstract: str) -> None:
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
    symbol.setSizeUnit(Qgis.RenderUnit.Pixels)
    return symbol


def selection_symbol(color_hex: str, dark: bool = True) -> QgsMarkerSymbol:
    """The selected-feature symbol for one of the five clustered point types
    -- CustomSymbol mode's replacement for _point_symbol(), verified by
    direct pixel diff (not assumed) to be the only mechanism that shows a
    selection at all once a feature is grouped into a cluster. See the
    module-level comment above SELECTION_HALO_COLOR_DARK for the colour
    measurement and why the previous flat-colour-swap mechanism could not
    keep the type colour visible while selected."""
    halo_color = SELECTION_HALO_COLOR_DARK if dark else SELECTION_HALO_COLOR_LIGHT
    fill = QColor(color_hex)
    fill.setAlpha(MARKER_ALPHA)
    symbol = QgsMarkerSymbol.createSimple({
        "name": "circle",
        "color": fill.name(QColor.NameFormat.HexArgb),
        "outline_color": halo_color,
        "outline_width": str(SELECTION_HALO_WIDTH_PX),
        "outline_width_unit": "Pixel",
        "size": str(SELECTION_HALO_SIZE_PX),
        "size_unit": "Pixel",
    })
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
        QgsSymbolLayer.Property.Size, QgsProperty.fromExpression(
            f"({CLUSTER_SIZE_EXPRESSION}) * " + scale_case(CLUSTER_SIZE_FACTOR_WIDE, CLUSTER_SIZE_FACTOR_MEDIUM, 1.0)))
    fr, fg, fb, _ = (int(v) for v in ink["fill"].split(","))
    disc.setDataDefinedProperty(
        QgsSymbolLayer.Property.FillColor, QgsProperty.fromExpression(
            f"color_rgba({fr},{fg},{fb}," + scale_case(CLUSTER_FILL_ALPHA_WIDE, CLUSTER_FILL_ALPHA_MEDIUM, CLUSTER_FILL_ALPHA) + ")"))

    count = QgsFontMarkerSymbolLayer.create({
        "font": "Helvetica",
        "chr": "0",
        "color": ink["text"],
        "size": str(CLUSTER_COUNT_SIZE_PX),
        "size_unit": "Pixel",
        "font_style": "Bold",
    })
    count.setDataDefinedProperty(
        QgsSymbolLayer.Property.Character, QgsProperty.fromExpression("@cluster_size"))

    symbol = QgsMarkerSymbol()
    symbol.changeSymbolLayer(0, disc)
    symbol.appendSymbolLayer(count)
    return symbol


def overview_symbol(color_hex: str, dark: bool = True) -> QgsMarkerSymbol:
    """The US-overview bubble: the cluster bubble (same restrained disc, same ink, same count text) with its size and its text taken from the bin's own count
    ('n' and 'label') instead of from how many features were grouped. Quieter than Canada's by construction: it reuses the cluster alpha."""
    symbol = cluster_symbol(color_hex, dark)
    disc, count = symbol.symbolLayer(0), symbol.symbolLayer(1)
    disc.setDataDefinedProperty(QgsSymbolLayer.Property.Size, QgsProperty.fromExpression(
        'CASE WHEN "n" < 500 THEN 26 WHEN "n" < 5000 THEN 32 ELSE 38 END'))
    count.setDataDefinedProperty(QgsSymbolLayer.Property.Character, QgsProperty.fromExpression('"label"'))
    return symbol


def build_overview_layer(name: str, color_hex: str, dark: bool = True, abstract: str = None) -> QgsVectorLayer:
    """An empty memory point layer for the US overview bubbles. Not a record layer: it is excluded from identify, never wired to the inspector and never
    listed in Records."""
    layer = QgsVectorLayer("Point?crs=EPSG:4326", name, "memory")
    layer.dataProvider().addAttributes([QgsField("n", QMetaType.Type.Int), QgsField("ns", QMetaType.Type.Int), QgsField("nl", QMetaType.Type.Int),
                                        QgsField("label", QMetaType.Type.QString)])
    layer.updateFields()
    layer.setRenderer(QgsSingleSymbolRenderer(overview_symbol(color_hex, dark)))
    flag = QgsMapLayer.LayerFlag
    layer.setFlags(flag(layer.flags().value & ~flag.Identifiable.value))      # not identifiable: the overview is presence, not records
    layer.setCustomProperty(VELORONA_KIND_PROPERTY, "us-overview")
    if abstract:
        set_abstract(layer, abstract)
    return layer


def fill_overview_layer(layer: QgsVectorLayer, bins) -> None:
    """Replaces the overview bubbles (a few dozen features; no selection exists on this layer)."""
    layer.dataProvider().truncate()
    features = []
    for b in bins:
        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(b["longitude"], b["latitude"])))
        feature.setAttributes([b["n"], b["ns"], b["nl"], b["label"]])
        features.append(feature)
    layer.dataProvider().addFeatures(features)
    layer.updateExtents()
    layer.triggerRepaint()


def _clustered_renderer(color_hex: str, dark: bool = True) -> QgsPointClusterRenderer:
    """Individual records at close zoom, grouped into counted clusters as the
    view widens -- QGIS's own point-cluster renderer, configured to the web
    map's parameters. The underlying data is untouched: every record stays
    reachable, and the cluster count is simply how many are represented."""
    embedded = QgsSingleSymbolRenderer(_point_symbol(color_hex))
    renderer = QgsPointClusterRenderer()
    renderer.setEmbeddedRenderer(embedded)
    renderer.setTolerance(CLUSTER_TOLERANCE_PX)
    renderer.setToleranceUnit(Qgis.RenderUnit.Pixels)
    renderer.setClusterSymbol(cluster_symbol(color_hex, dark))
    return renderer


def build_point_layer(
    name: str,
    records: Iterable[dict],
    field_specs: Sequence[Tuple[str, QMetaType.Type]],
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

    _fill(layer, records, field_specs, _point_feature)
    layer.updateExtents()

    layer.setRenderer(_clustered_renderer(color_hex) if cluster else QgsSingleSymbolRenderer(_point_symbol(color_hex)))
    layer.setCustomProperty(VELORONA_KIND_PROPERTY, kind)
    if abstract:
        set_abstract(layer, abstract)
    return layer


def build_link_layer(
    name: str,
    links: Iterable[dict],
    field_specs: Sequence[Tuple[str, QMetaType.Type]],
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

    _fill(layer, links, field_specs, _link_feature)
    layer.updateExtents()

    color = QColor(color_hex)
    color.setAlpha(LINE_ALPHA)
    symbol = QgsLineSymbol.createSimple({"line_style": line_style})
    symbol.setColor(color)
    symbol.setWidth(LINE_WIDTH_PX)
    symbol.setWidthUnit(Qgis.RenderUnit.Pixels)
    fade_link_with_scale(symbol, color)
    layer.setRenderer(QgsSingleSymbolRenderer(symbol))
    layer.setCustomProperty(VELORONA_KIND_PROPERTY, "link")
    if abstract:
        set_abstract(layer, abstract)
    return layer


SELECTION_KEY_FIELD = "id"     # the record's own identifier (every Velorona dataset carries it); QgsFeature ids are NOT stable across a reload


def _record_signature(feature) -> tuple:
    """What a record currently says: every attribute and its geometry. A record whose signature changed across a reload is a different
    observation (a satellite's position, a re-issued licence), so the details on screen would be stale."""
    geometry = feature.geometry()
    return (tuple(feature.attributes()), geometry.asWkt() if geometry is not None and not geometry.isNull() else "")


def _selected_records(layer) -> dict:
    """{record id: signature} for the layer's selected features (QgsFeature ids are reissued when a layer is repopulated)."""
    if not layer.selectedFeatureCount() or layer.fields().indexFromName(SELECTION_KEY_FIELD) < 0:
        return {}
    return {str(f[SELECTION_KEY_FIELD]): _record_signature(f) for f in layer.selectedFeatures() if f[SELECTION_KEY_FIELD] not in (None, "")}


def _restore_selection(layer, kept: dict) -> None:
    """After a layer's content was replaced, select the features that are still the SAME record (same record id and unchanged content), or
    nothing. The old feature ids are discarded: they may be absent or, worse, now identify a different record.

    An unchanged record is re-selected silently (the details on screen stay right and the map must not jump back to it while the user is
    panning). A selection that did not survive, or whose record changed, is announced as cleared so the details panel empties."""
    if not kept and not layer.selectedFeatureCount():
        return
    had = list(layer.selectedFeatureIds())
    layer.blockSignals(True)
    try:
        layer.removeSelection()
        fids = ([f.id() for f in layer.getFeatures() if kept.get(str(f[SELECTION_KEY_FIELD])) == _record_signature(f)]
                if kept and layer.fields().indexFromName(SELECTION_KEY_FIELD) >= 0 else [])
        if fids:
            layer.selectByIds(fids)
    finally:
        layer.blockSignals(False)
    if had and len(fids) != len(had):
        layer.selectionChanged.emit(list(fids), [i for i in had if i not in fids], True)


def replace_point_features(layer: QgsVectorLayer, records: Iterable[dict], field_specs: Sequence[Tuple[str, QMetaType.Type]]) -> None:
    """Clears and repopulates a memory point layer in place -- used for the
    viewport-scoped live layers (towers, cellular) on canvas extentsChanged,
    same refresh-in-place pattern as app.js's refreshLiveLayers()."""
    kept = _selected_records(layer)
    layer.dataProvider().truncate()
    skipped = _fill(layer, records, field_specs, _point_feature)
    layer.updateExtents()
    _restore_selection(layer, kept)
    layer.triggerRepaint()
    return skipped


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
    symbol.setWidthUnit(Qgis.RenderUnit.Pixels)
    layer.setRenderer(QgsSingleSymbolRenderer(symbol))
    layer.setCustomProperty(VELORONA_KIND_PROPERTY, "network-context")
    return layer


def replace_link_features(layer: QgsVectorLayer, links: Iterable[dict],
                          field_specs: Sequence[Tuple[str, QMetaType.Type]]) -> None:
    """Clears and repopulates a memory line layer in place, so a re-run of
    Load Public Data refreshes the existing layer instead of adding a second
    one (and keeps whatever visibility/styling the user set)."""
    kept = _selected_records(layer)
    layer.dataProvider().truncate()
    skipped = _fill(layer, links, field_specs, _link_feature)
    layer.updateExtents()
    _restore_selection(layer, kept)
    layer.triggerRepaint()
    return skipped


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
