"""Geographic orientation labels for the Velorona basemap.

Everything here comes from layers already inside the vector tiles Velorona
fetches for the basemap -- `place` (country / state / city / town points with a
`rank`) and `water_name` (lake and sea names). No extra dataset, no extra
request, and QGIS's own vector-tile labelling engine rather than a second one.

CARTO's converted style contributes no label sub-layers of its own (the
sprite/font resources it references do not convert), so without this the map is
an anonymous background. Enabling the style's whole label set was measured at
8.9 s for a regional extent because it labels every road, waterway and POI;
restricting to `place` and `water_name` keeps orientation at a few tens of ms.

The zoom ranges and rank ceilings below were set by rendering real tiles and
counting drawn text, not by assumption: `state` features only exist in these
tiles at low zoom, and a rank ceiling of 3 drew almost nothing.
"""

from __future__ import annotations

from qgis.core import (
    Qgis,
    QgsPalLayerSettings,
    QgsTextBufferSettings,
    QgsTextFormat,
    QgsVectorTileBasicLabeling,
    QgsVectorTileBasicLabelingStyle,
)
from qgis.PyQt.QtGui import QColor

# Far enough to collapse the same name repeated across adjacent tiles,
# short enough that two genuinely different places keep their labels.
DUPLICATE_DISTANCE_MM = 55.0

# Orientation needs a handful of names, not every place in view. Without a cap,
# a continental zoom-out feeds thousands of candidates to the labelling engine
# and the collision pass was measured at 8.2 s for a single frame. Capping each
# tier keeps the worst frame in the low hundreds of milliseconds.
#
# The single flat cap of 40 was a performance ceiling, not a cartographic
# choice: at a continental extent it let the province and city tiers each draw
# up to 40 names at once, which is the "wall of province/state names" this pass
# removes. Each tier now carries its own cap (last field of TIERS) so density
# follows the scale that tier serves. 40 remains the fallback.
MAX_LABELS_PER_TIER = 40

# The tiles carry names in many scripts; resolving fonts for those is slow and
# they are unreadable to most users of this plugin anyway. Prefer the Latin
# transliteration, then English, then whatever the record has.
NAME_EXPRESSION = 'coalesce("name:latin", "name_en", "name")' 

PLACE_LAYER = "place"
WATER_LAYER = "water_name"

# Label ink for each basemap presentation: light text over the dark basemap,
# dark text over the light one, each with the opposite-tone halo.
#
# Calibrated against the Velorona Web Map rather than chosen by eye. The Web Map
# renders OpenStreetMap raster tiles under a CSS invert/contrast filter; putting
# a real tile through that same filter chain numerically shows its brightest
# label text lands at rgb(174,174,174) -- about 5.1:1 against its own land
# colour -- not at white. Velorona's previous city ink measured rgb(228,237,245)
# at 16.3:1, which is why geographic names read as primary content here and as
# quiet context there. The values below bring the brightest tier to 10.6:1 --
# muted toward the Web Map's character while staying comfortably legible on a
# desktop canvas, which is viewed further back than a 256 px web tile. Every
# light-theme value is held at or above 4.5:1 so nothing becomes hard to read.
DARK_INK = {"place": "#B4C2D0", "place_muted": "#8A9AAA", "water": "#6F8FA8", "halo": "#05090C"}
LIGHT_INK = {"place": "#46535E", "place_muted": "#647380", "water": "#527287", "halo": "#FFFFFF"}

# name, source layer, ink key, point size, zoom range, filter, rank ceiling,
# max labels. Sizes step down from the previous 9.0-10.5 pt: at this render's
# 96 dpi, 10 pt drew a 13.3 px glyph against the ~7 px city glyph measured in
# the Web Map's own tiles. 8-9 pt (10.7-12 px) closes most of that gap without
# going to a web tile's literal size.
TIERS = [
    ("country", PLACE_LAYER, "place_muted", 9.0, 0, 4, "\"class\" = 'country'", None, 4),
    ("province", PLACE_LAYER, "place_muted", 8.0, 0, 5, "\"class\" = 'state'", None, 8),
    ("water", WATER_LAYER, "water", 8.5, 3, 12, "", None, 12),
    ("city-wide", PLACE_LAYER, "place", 9.0, 0, 5, "\"class\" = 'city'", 8, 10),
    ("city", PLACE_LAYER, "place", 9.0, 6, 14, "\"class\" = 'city'", 20, 24),
    ("town", PLACE_LAYER, "place_muted", 8.0, 10, 14, "\"class\" IN ('town', 'village')", None, 20),
]


def _text_format(size: float, color: str, halo: str) -> QgsTextFormat:
    fmt = QgsTextFormat()
    fmt.setSize(size)
    fmt.setSizeUnit(Qgis.RenderUnit.Points)
    fmt.setColor(QColor(color))
    buffer_settings = QgsTextBufferSettings()
    buffer_settings.setEnabled(True)
    # 0.9 mm is 3.4 px either side of every glyph at 96 dpi -- a visible collar
    # that made each name read as a solid object rather than as text on a map.
    # The halo still has a job (names cross water edges and roads), so it is
    # thinned rather than removed.
    buffer_settings.setSize(0.6)
    buffer_settings.setSizeUnit(Qgis.RenderUnit.Millimeters)
    buffer_settings.setColor(QColor(halo))
    buffer_settings.setOpacity(0.75)
    fmt.setBuffer(buffer_settings)
    return fmt


def _style(tier, ink) -> QgsVectorTileBasicLabelingStyle:
    name, source_layer, ink_key, size, zmin, zmax, expression, rank_max, max_labels = tier
    settings = QgsPalLayerSettings()
    settings.fieldName = NAME_EXPRESSION
    settings.isExpression = True
    settings.placement = (Qgis.LabelPlacement.Horizontal if source_layer == WATER_LAYER
                          else Qgis.LabelPlacement.OverPoint)
    settings.setFormat(_text_format(size, ink[ink_key], ink["halo"]))
    # Label priority is deliberately left at its default. Setting it low was
    # measured to suppress every label on a vector tile layer (473 drawn text
    # pixels -> 0), and there is nothing to lose a collision against: Velorona's
    # own layers carry no labels of their own.

    # Vector tiles carry the same feature once per tile, so a lake or a city
    # near a tile seam is labelled several times. QGIS's own duplicate removal
    # collapses those repeats.
    thinning = settings.thinningSettings()
    thinning.setAllowDuplicateRemoval(True)
    thinning.setMinimumDistanceToDuplicate(DUPLICATE_DISTANCE_MM)
    thinning.setMinimumDistanceToDuplicateUnit(Qgis.RenderUnit.Millimeters)
    thinning.setLimitNumberLabelsEnabled(True)
    thinning.setMaximumNumberLabels(max_labels or MAX_LABELS_PER_TIER)
    settings.setThinningSettings(thinning)

    style = QgsVectorTileBasicLabelingStyle()
    style.setStyleName(name)
    style.setLayerName(source_layer)
    style.setGeometryType(Qgis.GeometryType.Line if source_layer == WATER_LAYER
                          else Qgis.GeometryType.Point)
    style.setMinZoomLevel(zmin)
    style.setMaxZoomLevel(zmax)
    if rank_max is not None:
        expression = f'{expression} AND "rank" <= {rank_max}' if expression else f'"rank" <= {rank_max}'
    style.setFilterExpression(expression)
    style.setLabelSettings(settings)
    style.setEnabled(True)
    return style


def place_labeling(dark: bool = True) -> QgsVectorTileBasicLabeling:
    """Country / province / lake / city / town labels, tiered by zoom and rank
    and inked for the active basemap presentation."""
    ink = DARK_INK if dark else LIGHT_INK
    labeling = QgsVectorTileBasicLabeling()
    labeling.setStyles([_style(tier, ink) for tier in TIERS])
    return labeling
