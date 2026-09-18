from __future__ import annotations

import time

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsLayerTreeLayer,
    QgsMapBoxGlStyleConverter,
    QgsPointClusterRenderer,
    QgsSingleSymbolRenderer,
    QgsProject,
    QgsRectangle,
    QgsVectorTileLayer,
)
from qgis.PyQt.QtCore import Qt, QTimer
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import QAction, QApplication, QMessageBox, QWIDGETSIZE_MAX

from .core import basemap_labels
from .core import layers as layer_helpers
from .core import network_context
from .core import overlays
from .core.colors import COLORS
from .core.engines import microwave_exposure, satellite_earth_space, terrestrial
from .core import inspector
from .core.inspector import feature_to_entry
from .core.layers import LIFECYCLE_EVIDENCE, PUBLIC_RECORDS_DISCLOSURE
from .core.sources import space_public, terrestrial_public
from .core.viewport_cache import FAILED, MISS, ViewportCache
from .ui import records_table
from .ui import theme
from .ui.param_dialog import ParamDialog
from .ui.results_dock import VeloronaResultsDock

MENU_NAME = "&Velorona"
WGS84 = QgsCoordinateReferenceSystem("EPSG:4326")

# Basemap -- native QGIS vector tile layer, CARTO Dark Matter, styled from
# CARTO's own current MapLibre GL JSON (not a filtered raster). The
# previous approach (invert-filtering bright OSM raster tiles) is gone
# entirely: RGB inversion cannot preserve hue (there is no hue-rotation
# control in QGIS's raster filter API, confirmed), so it always rendered
# water brown/orange -- not a tuning problem, a structural one.
#
# URL verified live against CARTO's current basemap service, not
# remembered: style.json fetched and inspected directly (background
# #0e0e0e, water fill present, real MapLibre style, HTTP 200); the vector
# tile source it references (tiles.basemaps.cartocdn.com/vectortiles/...)
# fetched as an actual tile -- 114KB of real gzip-compressed protobuf, not
# an error/placeholder -- confirming the vector endpoint is currently
# keyless, unlike the raster one that broke. Converted via QGIS's own
# QgsMapBoxGlStyleConverter (66/66 style rules converted, only
# sprite/font warnings, which don't block fills/lines).
#
# Labels are deliberately OFF on this layer, not an oversight: headless
# render timing (QgsMapRendererParallelJob) found the labeling engine's
# collision detection is the actual cost, and it is extent/zoom dependent,
# not simply size dependent -- the exact Canada-wide extent/canvas used in
# the original 582ms raster benchmark rendered in 657ms cold / 164ms warm
# WITH labels (comparable), but a Great Lakes regional extent (a smaller
# area that resolves to a higher, more label-dense tile zoom) took 8.9
# SECONDS with labels on, vs 611/269 ms with labels off at that same
# extent -- confirmed by isolating the renderer from the labeling engine
# directly, not guessed. Since that spike is real and its trigger (which
# zoom ranges get label-dense) isn't something this pass tuned or fully
# characterized, labels are off for predictable performance across
# whatever extent a user actually pans to. Velorona's own site/tower/link
# labels are unaffected -- those come from feature attributes and the
# dock, not this basemap layer.
BASEMAP_NAME = "Velorona Basemap (CARTO)"
# Two CARTO styles over the *same* vector tiles, so switching presentation
# costs no extra data and adds no dependency.
#
# Light is Voyager rather than Positron: Positron renders land almost pure
# white with pale grey water and no vegetation, which reads as a blank page
# under the telecom layers. Voyager keeps the same restraint but has warm land,
# genuinely blue water, visible green areas and legible roads -- 1353 distinct
# sampled colours against Positron's 686 at the same extent, and it renders
# slightly faster.
#
# Which one is active is Velorona's own setting, not QGIS's UI theme: this
# QGIS build reports only {'default': ''} from uiThemes(), so a host-theme
# signal would be unavailable on the very installation this ships to.
BASEMAP_STYLE_URL_DARK = "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json"
BASEMAP_STYLE_URL_LIGHT = "https://basemaps.cartocdn.com/gl/voyager-gl-style/style.json"
BASEMAP_STYLE_URL = BASEMAP_STYLE_URL_DARK

# Velorona's own map appearance. Dark is the default: it is the presentation
# the product was designed around and keeps the telecom layers dominant.
MAP_APPEARANCE_DARK = "dark"
MAP_APPEARANCE_LIGHT = "light"
DEFAULT_MAP_APPEARANCE = MAP_APPEARANCE_DARK

# Selection highlight, measured against the two basemaps rather than chosen by
# eye. QGIS's default pure yellow scores 17.5:1 on the dark map but only
# 1.03:1 against Voyager's cream land -- a selected link effectively vanishes
# on the light map. Velorona's deep brand blue scores 8.15:1 there, so the
# highlight follows the appearance. Both values are existing brand/QGIS
# colours; nothing new was invented, and only this project is touched.
SELECTION_COLOR_DARK = "#FFFF00"
SELECTION_COLOR_LIGHT = "#224B75"
BASEMAP_TILE_URL = "https://tiles-a.basemaps.cartocdn.com/vectortiles/carto.streets/v1/{z}/{x}/{y}.mvt"
BASEMAP_TILE_MAXZOOM = 14

# Project CRS -- set to EPSG:3857 (Web Mercator, the XYZ tiles' native CRS)
# in load_public_data() below. Measured headlessly: rendering the filtered
# basemap with the project in EPSG:4326 (forcing QGIS to warp/reproject
# every tile on the fly) took ~580-600ms per redraw (warm/cached tiles);
# the exact same filtered layer at its native EPSG:3857 CRS (no reprojection)
# took ~165ms -- a ~3.5x difference from reprojection alone interacting with
# the filter pipeline, not from tile-fetch latency (cold-cache fetch added
# a separate, smaller ~600ms one-time penalty; the point/link vector layers
# reprojected to EPSG:3857 on the fly for negligible added cost, ~225ms/95ms
# for 24,859 points / 16,956 links respectively, confirmed not to just move
# the bottleneck onto them). Full combined render (basemap + both vector
# layers): ~600ms at EPSG:4326 vs ~250ms at EPSG:3857, warm, real numbers
# from QgsMapRendererParallelJob.
PROJECT_CRS = QgsCoordinateReferenceSystem("EPSG:3857")

# Web Mercator is undefined at the poles. The SatNOGS snapshot contains a
# station at exactly 90 deg N, so an un-clamped combined extent projects to
# a y value roughly twice the height of the world and the canvas lands on a
# stretched whole-globe view instead of the data.
WEB_MERCATOR_MAX_LAT = 85.05112878

# A single pan or zoom emits extentsChanged several times. The viewport
# layers are backed by live ArcGIS queries (measured at ~10s for the ISED
# cellular service), so each burst is coalesced into one fetch.
VIEWPORT_REFRESH_DEBOUNCE_MS = 400

# The map stays the primary workspace: the investigation dock opens at roughly
# a third of the window, never below a readable width, and never wide enough to
# dominate the map. The user can still resize it by dragging the splitter.
DOCK_WIDTH_FRACTION = 0.32
DOCK_MIN_WIDTH_PX = 340
DOCK_MAX_WIDTH_PX = 760

# Satellite sub-points are time-dependent; re-propagate if the layer is shown
# again after this long.
SATELLITE_REFRESH_SECONDS = 600

# Selection behaviour. Exactly one feature gets the full investigation --
# endpoint weather is fetched only in that case, so a whole-layer selection can
# never fan out into thousands of live requests.
#
# Three separate budgets, because they cost wildly different amounts. Measured
# against the full 16,956-link / 24,859-site ISED dataset:
#
#   what                                    1,455      16,956      24,859
#   ------------------------------------  --------  ----------  ----------
#   attribute scan for the aggregates       0.011s      0.145s      0.265s
#   scan + capturing every row              0.025s      0.309s      0.637s
#   populating the Records table widget     0.136s     25.542s         n/a
#
# Rendering is what costs; reading does not. A single shared cap used to tie
# the export to the widget's budget, which is why a regional selection could be
# summarised but not exported.
#
# SELECTION_TABLE_LIMIT bounds what is drawn on screen -- the Records table
# widget and the evidence dock's HTML listing, which builds one table row per
# record. 200 keeps both instant.
SELECTION_TABLE_LIMIT = 200
# SELECTION_LISTING_LIMIT bounds what is captured for export. Nothing is
# rendered, so this is the cheap axis: it clears the entire national dataset at
# 0.637s worst case. Past it the export says the listing was omitted and names
# this number, rather than shipping a header with no rows under it.
SELECTION_LISTING_LIMIT = 25000
# SELECTION_SCAN_LIMIT caps how many features are read for the aggregate
# figures. It has to be at least SELECTION_LISTING_LIMIT: the capture happens
# inside the scan loop, so a lower scan cap would silently truncate the listing.
SELECTION_SCAN_LIMIT = 25000


class VeloronaPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.dock = None
        self.actions = []
        self.layer_group = None
        self.towers_layer = None
        self.cellular_layer = None
        self.weather_stations_layer = None
        self.weather_lines_layer = None
        self.terrain_layer = None
        self.network_context_layer = None
        self._extents_connected = False
        self._project_read_connected = False
        self._viewport_timer = None
        self._last_viewport_bbox = {}
        self._basemap_renderers = {}
        self._map_appearance = DEFAULT_MAP_APPEARANCE
        self._licensee_filter = ""
        self._basemap_is_dark = None
        self._viewport_cache = ViewportCache()
        self._viewport_refreshing = False
        # Same bounded/TTL/negative-cache mechanism as the viewport layers,
        # keyed by authorization + endpoint coordinates: re-selecting a link
        # must not re-hit the live weather services.
        self._link_weather_cache = ViewportCache()
        self._selecting_from_table = False
        self.satellites_layer = None
        self._satellites_fetched_at = None
        self._endpoint_index = {}
        self.network_context_layer = None

    # -- QGIS plugin lifecycle -------------------------------------------

    def initGui(self):
        self.action_load_public = self._make_action(
            "Explore: Load Public Data",
            "Adds every public source Velorona Map ships (Ontario GeoHub towers, ISED cellular, "
            "ISED Fixed Service, CelesTrak satellites, SatNOGS ground stations) as QGIS layers, "
            "each at its own real geographic coverage.",
            self.load_public_data,
        )
        self.action_terrestrial = self._make_action(
            "Analyze: Terrestrial Path Clearance",
            "Select exactly two point features (any layer, public or imported) as a link's endpoints.",
            self.run_terrestrial,
        )
        self.action_microwave = self._make_action(
            "Analyze: Microwave Weather Exposure",
            "Select exactly two point features (any layer, public or imported) as a link's endpoints.",
            self.run_microwave,
        )
        self.action_satellite = self._make_action(
            "Analyze: Satellite / Earth-Space",
            "Select exactly one Ground/Earth Station feature and one Satellite feature.",
            self.run_satellite,
        )
        self.action_show_dock = self._make_action(
            "Show Velorona Panel",
            "Reopens the Velorona Records / Results panel if it was closed.",
            self.show_panel,
        )

        # Guard against a stale/pre-existing project: one saved before
        # PROJECT_CRS was forced to EPSG:3857, or one whose CRS was later
        # changed independently via QGIS's own Project Properties dialog.
        # load_public_data()'s own setCrs() call only fires when that
        # action is (re-)run -- it doesn't help a project that's already
        # open (at plugin activation, or right after the user opens a
        # .qgz file) and already contains Velorona's basemap layer.
        QgsProject.instance().readProject.connect(self._check_stale_project_crs)
        self._project_read_connected = True
        self._check_stale_project_crs()

    def show_panel(self):
        """Reopens the one Velorona dock. QGIS also lists it under View >
        Panels because it carries a stable object name; this action is the
        in-plugin route to the same single instance -- it never creates a
        second dock."""
        dock = self._ensure_dock()
        dock.show()
        dock.raise_()

    def _check_stale_project_crs(self, *args):
        """If the currently open project already contains Velorona's
        basemap layer but its CRS isn't PROJECT_CRS, correct it. Scoped to
        Velorona projects specifically (presence of BASEMAP_NAME) so this
        never forces a CRS change on an unrelated project that happens to
        be open."""
        project = QgsProject.instance()
        has_velorona_basemap = any(
            layer.name() == BASEMAP_NAME for layer in project.mapLayers().values()
        )
        if has_velorona_basemap and project.crs() != PROJECT_CRS:
            project.setCrs(PROJECT_CRS)
            self.iface.mapCanvas().setDestinationCrs(PROJECT_CRS)

    def _make_action(self, label, tooltip, slot) -> QAction:
        action = QAction(label, self.iface.mainWindow())
        action.setToolTip(tooltip)
        action.triggered.connect(slot)
        self.iface.addToolBarIcon(action)
        self.iface.addPluginToMenu(MENU_NAME, action)
        self.actions.append(action)
        return action

    def unload(self):
        for action in self.actions:
            self.iface.removePluginMenu(MENU_NAME, action)
            self.iface.removeToolBarIcon(action)
        self.actions = []
        if self._extents_connected:
            self._safe_disconnect(self.iface.mapCanvas().extentsChanged, self._schedule_viewport_refresh)
            self._safe_disconnect(QgsProject.instance().layerTreeRoot().visibilityChanged,
                                  self._on_layer_visibility_changed)
            self._extents_connected = False
        if self._viewport_timer is not None:
            self._viewport_timer.stop()
            self._viewport_timer = None
        if self._project_read_connected:
            self._safe_disconnect(QgsProject.instance().readProject, self._check_stale_project_crs)
            self._project_read_connected = False
        self._viewport_cache.clear()
        self._link_weather_cache.clear()
        self._remove_evidence_layers()
        if self.dock is not None:
            self.iface.removeDockWidget(self.dock)
            self.dock = None

    @staticmethod
    def _safe_disconnect(signal, slot) -> None:
        """Teardown must not abort half-way: Qt raises TypeError when the slot
        was never connected and RuntimeError once the C++ object behind the
        signal is gone, both of which are reachable on a plugin reload."""
        try:
            signal.disconnect(slot)
        except (TypeError, RuntimeError):
            pass

    def _remove_evidence_layers(self) -> None:
        """Drops the per-analysis overlays this plugin generated, identified by
        their ownership marker rather than by instance state, which does not
        survive a reload. Loaded public data is deliberately left in place --
        it is the user's working data, not a plugin artifact."""
        project = QgsProject.instance()
        stale = [
            layer_id for layer_id, layer in project.mapLayers().items()
            if layer_helpers.is_velorona_owned(layer)
            and layer_helpers.layer_lifecycle(layer) == LIFECYCLE_EVIDENCE
        ]
        for layer_id in stale:
            project.removeMapLayer(layer_id)
        self.weather_stations_layer = None
        self.weather_lines_layer = None
        self.terrain_layer = None
        self.network_context_layer = None

    def _warn(self, message: str) -> None:
        QMessageBox.warning(self.iface.mainWindow(), "Velorona", message)

    def _error(self, message: str) -> None:
        QMessageBox.critical(self.iface.mainWindow(), "Velorona", message)

    # -- Explore: Load Public Data ----------------------------------------

    def _ensure_group(self, name: str, parent=None, index: int = 0):
        """The group for `name`, created at `index` if missing. The index is
        explicit because the layer tree is ordered top-to-bottom and Velorona's
        hierarchy puts terrestrial infrastructure first; relying on creation
        order alone put Space above Infrastructure."""
        parent = parent or QgsProject.instance().layerTreeRoot()
        existing = parent.findGroup(name)
        if existing is not None:
            return existing
        return parent.insertGroup(index, name)

    def _ensure_velorona_groups(self):
        """Velorona's four groups, in their intended top-to-bottom order.
        Created up front so the hierarchy reads the same before and after an
        analysis, and so 'My Data' exists as a home for the user's own layers."""
        velorona = self._ensure_group("Velorona")
        groups = {}
        for index, name in enumerate(("Infrastructure", "Space", "My Data", "Evidence")):
            groups[name] = self._ensure_group(name, velorona, index)
        return velorona, groups

    def _finalize_workspace(self, zoom_targets):
        """Runs after QGIS's own queued layer-tree handling, so the workspace
        CRS is the last word and the initial extent is computed in it."""
        self._establish_workspace_crs()
        self._zoom_to_layers(zoom_targets)

    def _establish_workspace_crs(self):
        """Velorona's workspace is EPSG:3857 (see PROJECT_CRS). Set on both the
        project and the canvas so the user never has to change it by hand; only
        this project is touched, never a QGIS global preference."""
        project = QgsProject.instance()
        if project.crs() != PROJECT_CRS:
            project.setCrs(PROJECT_CRS)
        canvas = self.iface.mapCanvas()
        if canvas.mapSettings().destinationCrs() != PROJECT_CRS:
            canvas.setDestinationCrs(PROJECT_CRS)

    def _ensure_public_layer(self, source_key, group, visible, kind, build, refresh=None):
        """Returns the one Velorona layer for this logical source, creating it
        only if it isn't already in the project.

        Re-running Load Public Data (or reloading the plugin) used to add a
        second copy of every layer, because creation was unconditional. The
        layer is now found by its stored source key, refreshed in place, and
        its current visibility left alone -- a layer the user switched off is
        an existing layer, not a missing one. Only a freshly created layer gets
        the default visibility and a selection connection, so reuse cannot
        double-wire the inspector."""
        project = QgsProject.instance()
        existing = layer_helpers.find_owned_layer(project, source_key)
        if existing is not None:
            if refresh is not None:
                refresh(existing)
            node = project.layerTreeRoot().findLayer(existing.id())
            if node is None:  # removed from the tree but still registered
                group.addLayer(existing).setItemVisibilityChecked(visible)
            return existing

        layer = build()
        layer_helpers.add_to_group(project, layer, group, visible=visible, source_key=source_key)
        self._wire_inspector(layer, kind)
        return layer

    def _basemap_renderer(self, dark: bool):
        """The converted CARTO renderer for this presentation, fetched and
        converted once per session per style. Both steps are blocking (a network
        round trip and a 66-rule conversion) and neither depends on the project,
        so each is cached and cloned for any later project."""
        cached = self._basemap_renderers.get(dark)
        if cached is not None:
            return cached

        import requests

        url = BASEMAP_STYLE_URL_DARK if dark else BASEMAP_STYLE_URL_LIGHT
        try:
            resp = requests.get(url, timeout=10.0)
            resp.raise_for_status()
        except Exception as exc:
            self._warn(f"Could not fetch the {BASEMAP_NAME} style: {exc}")
            return None

        converter = QgsMapBoxGlStyleConverter()
        if converter.convert(resp.text) != QgsMapBoxGlStyleConverter.Success:
            self._warn(f"Could not convert the {BASEMAP_NAME} style: {converter.errorMessage()}")
            return None
        renderer = converter.renderer()
        # CARTO's own converted fill is measured identical to bare land in Dark
        # Matter (0 RGB distance) and washed out in Voyager -- see
        # core/layers.py:retint_basemap_vegetation for the measurements. This
        # only recolours the existing landcover/park rules; every filter, zoom
        # range and other layer in the 66-rule CARTO style is untouched.
        layer_helpers.retint_basemap_vegetation(renderer, dark)
        self._basemap_renderers[dark] = renderer
        return self._basemap_renderers[dark]

    def _restyle_clusters(self, dark: bool) -> None:
        """Cluster bubbles have to stay legible over both basemaps, so their
        ink follows the appearance. Only the cluster symbol changes -- the
        renderer, its tolerance and the underlying records are untouched."""
        project = QgsProject.instance()
        for key in (layer_helpers.SOURCE_FIXED_SITES, layer_helpers.SOURCE_TOWERS,
                    layer_helpers.SOURCE_CELLULAR, layer_helpers.SOURCE_SATELLITES,
                    layer_helpers.SOURCE_GROUND_STATIONS):
            layer = layer_helpers.find_owned_layer(project, key)
            if layer is None:
                continue
            renderer = layer.renderer()
            if isinstance(renderer, QgsPointClusterRenderer):
                renderer.setClusterSymbol(layer_helpers.cluster_symbol(dark))
                layer.triggerRepaint()

    def _restyle_links(self, dark: bool) -> None:
        """Normal Fixed Service links keep comfortable visibility on both
        basemaps without ever competing with the selected link."""
        layer = layer_helpers.find_owned_layer(QgsProject.instance(), layer_helpers.SOURCE_FIXED_LINKS)
        if layer is None:
            return
        renderer = layer.renderer()
        if isinstance(renderer, QgsSingleSymbolRenderer):
            renderer.setSymbol(layer_helpers.link_symbol(dark))
            layer.triggerRepaint()

    def _apply_selection_color(self, dark: bool) -> None:
        """Keeps the selected feature visible on whichever basemap is active.
        This is a project property, not a QGIS preference."""
        QgsProject.instance().setSelectionColor(
            QColor(SELECTION_COLOR_DARK if dark else SELECTION_COLOR_LIGHT))

    def map_is_dark(self) -> bool:
        """Velorona's own map appearance -- deliberately independent of the QGIS
        UI theme, which this QGIS build does not let the user change."""
        return self._map_appearance == MAP_APPEARANCE_DARK

    def set_map_appearance(self, appearance: str) -> None:
        """Switches the basemap presentation. Only the style and label ink
        change: the same tiles, layers, records, CRS and analyses stay in
        place, and a style already used this session is reused without a
        further request."""
        if appearance == self._map_appearance:
            return
        self._map_appearance = appearance
        self.apply_basemap_theme(self.map_is_dark())
        # Panel and map are one appearance. dock.set_map_appearance blocks the
        # combo's signal, so this cannot bounce back here.
        if self.dock is not None:
            self.dock.set_map_appearance(appearance)

    def apply_basemap_theme(self, dark: bool = None) -> None:
        """Restyles the existing basemap for the active QGIS palette. The layer
        and its tiles are reused -- only the style and label ink change, so no
        tile is refetched and nothing else in the project is touched."""
        if dark is None:
            dark = self.map_is_dark()
        basemap = layer_helpers.find_owned_layer(QgsProject.instance(), layer_helpers.SOURCE_BASEMAP)
        if basemap is None:
            self._basemap_is_dark = dark
            return
        renderer = self._basemap_renderer(dark)
        if renderer is None:
            return
        basemap.setRenderer(renderer.clone())
        basemap.setLabeling(basemap_labels.place_labeling(dark))
        basemap.setLabelsEnabled(True)
        basemap.triggerRepaint()
        self._apply_selection_color(dark)
        self._restyle_clusters(dark)
        self._restyle_links(dark)
        self._basemap_is_dark = dark

    def _ensure_basemap(self):
        """Adds the native QGIS vector tile basemap (CARTO Dark Matter)
        beneath every other layer, once. Without this the canvas is just
        floating dots on a black background -- meaningless to a
        first-time user."""
        project = QgsProject.instance()
        for existing in project.mapLayers().values():
            if existing.name() == BASEMAP_NAME:
                return

        dark = self.map_is_dark()
        renderer = self._basemap_renderer(dark)
        if renderer is None:
            return

        tile_url_encoded = BASEMAP_TILE_URL.replace("{z}", "%7Bz%7D").replace("{x}", "%7Bx%7D").replace("{y}", "%7By%7D")
        uri = f"type=xyz&url={tile_url_encoded}&zmax={BASEMAP_TILE_MAXZOOM}&zmin=0"
        basemap = QgsVectorTileLayer(uri, BASEMAP_NAME)
        if not basemap.isValid():
            self._warn(f"Could not load the {BASEMAP_NAME} vector tile layer.")
            return

        basemap.setRenderer(renderer.clone())
        # Geographic orientation: country / province / lake / city / town labels
        # from the `place` and `water_name` layers already inside these tiles.
        # CARTO's own converted style contributes no label sub-layers, and
        # enabling its full label set measured 8.9s at a regional extent, so
        # only those two are labelled -- see core/basemap_labels.py.
        basemap.setLabeling(basemap_labels.place_labeling(dark))
        basemap.setLabelsEnabled(True)
        self._apply_selection_color(dark)
        self._basemap_is_dark = dark

        layer_helpers.mark_velorona_owned(basemap, source_key=layer_helpers.SOURCE_BASEMAP)
        project.addMapLayer(basemap, False)
        project.layerTreeRoot().addLayer(basemap)  # appended last = bottom of the render stack

    def _zoom_to_layers(self, layers):
        """Equivalent to QGIS's own 'Zoom to Layer(s)' for whichever
        layers were just (re)loaded, so the user lands on the data instead
        of a random default view."""
        combined = QgsRectangle()
        for layer in layers:
            if layer is None:
                continue
            extent = layer.extent()
            if extent is None or extent.isNull() or extent.isEmpty():
                continue
            if combined.isNull():
                combined = QgsRectangle(extent)
            else:
                combined.combineExtentWith(extent)
        if combined.isNull():
            return
        canvas = self.iface.mapCanvas()
        canvas_crs = canvas.mapSettings().destinationCrs()
        if canvas_crs != WGS84:
            combined = QgsRectangle(
                max(combined.xMinimum(), -180.0),
                max(combined.yMinimum(), -WEB_MERCATOR_MAX_LAT),
                min(combined.xMaximum(), 180.0),
                min(combined.yMaximum(), WEB_MERCATOR_MAX_LAT),
            )
            transform = QgsCoordinateTransform(WGS84, canvas_crs, QgsProject.instance())
            combined = transform.transformBoundingBox(combined)
        # Padded after projecting: scaling degrees first pushed the corners
        # past +/-180 lon and +/-90 lat, which Web Mercator blows up.
        combined.scale(1.1)
        canvas.setExtent(combined)
        canvas.refresh()

    def load_public_data(self):
        project = QgsProject.instance()
        # See PROJECT_CRS's comment above -- measured ~2.4x full-redraw speedup
        # (real numbers) from avoiding on-the-fly raster reprojection of the
        # XYZ basemap tiles. Set explicitly on both project and canvas rather
        # than relying on QGIS's usual project-to-canvas CRS propagation.
        self._establish_workspace_crs()
        # Add the basemap before any Velorona vector layer: QGIS adopts the
        # first added layer's CRS for an empty project, and the basemap is
        # already EPSG:3857, so the adoption agrees with the workspace instead
        # of flipping it to the 4326 of the memory layers. Groups are inserted
        # at index 0, so the basemap still ends up at the bottom of the stack.
        self._ensure_basemap()
        velorona_group, groups = self._ensure_velorona_groups()
        infra_group = groups["Infrastructure"]
        space_group = groups["Space"]
        problems = []
        # The initial view comes from Velorona's terrestrial infrastructure,
        # never from the space layers: satellite subpoints and SatNOGS
        # stations span the globe, so including them lands the canvas on a
        # whole-world view instead of the data. They are only the fallback
        # when no terrestrial layer loaded at all.
        home_layers = []
        context_layers = []

        # Hero: on by default -- the primary Select Link -> Analyze -> Evidence workflow.
        try:
            sites, links = terrestrial_public.load_fixed_service_snapshot()
            sites_layer = self._ensure_public_layer(
                layer_helpers.SOURCE_FIXED_SITES, infra_group, visible=True, kind="site",
                build=lambda: layer_helpers.build_point_layer(
                    f"Fixed Service sites -- {PUBLIC_RECORDS_DISCLOSURE}", sites,
                    terrestrial_public.FIXED_SITE_FIELDS, COLORS["fixed-sites"],
                    abstract=f"ISED Fixed Service, static snapshot. {PUBLIC_RECORDS_DISCLOSURE.capitalize()}."),
                refresh=lambda lyr: layer_helpers.replace_point_features(
                    lyr, sites, terrestrial_public.FIXED_SITE_FIELDS))
            links_layer = self._ensure_public_layer(
                layer_helpers.SOURCE_FIXED_LINKS, infra_group, visible=True, kind="link",
                build=lambda: layer_helpers.build_link_layer(
                    f"Fixed Service links -- {PUBLIC_RECORDS_DISCLOSURE}", links,
                    terrestrial_public.FIXED_LINK_FIELDS, COLORS["fixed-links"],
                    abstract=f"ISED Fixed Service, static snapshot. {PUBLIC_RECORDS_DISCLOSURE.capitalize()}."),
                refresh=lambda lyr: layer_helpers.replace_link_features(
                    lyr, links, terrestrial_public.FIXED_LINK_FIELDS))
            home_layers += [sites_layer, links_layer]
        except Exception as exc:
            problems.append(f"Fixed Service (ISED): {exc}")

        # Context: present, off by default -- toggled on by the user, not removed.
        try:
            stations = space_public.load_ground_station_snapshot()
            context_layers.append(self._ensure_public_layer(
                layer_helpers.SOURCE_GROUND_STATIONS, space_group, visible=False, kind="ground-station",
                build=lambda: layer_helpers.build_point_layer(
                    "Ground/Earth Stations", stations, space_public.GROUND_STATION_FIELDS,
                    COLORS["ground-stations"], kind="ground-station"),
                refresh=lambda lyr: layer_helpers.replace_point_features(
                    lyr, stations, space_public.GROUND_STATION_FIELDS)))
        except Exception as exc:
            problems.append(f"Ground/Earth Stations (SatNOGS): {exc}")

        # Satellites are off by default and CelesTrak is a live service that
        # measured 75.0s of a 76.8s load when it throttles (5 groups x 15s
        # timeout). Same treatment as the other off-by-default live layers:
        # the layer is created empty and populated when it is switched on.
        self.satellites_layer = self._ensure_public_layer(
            layer_helpers.SOURCE_SATELLITES, space_group, visible=False, kind="satellite",
            build=lambda: layer_helpers.build_point_layer(
                "Satellites", [], space_public.SATELLITE_FIELDS,
                COLORS["satellites"], kind="satellite"))

        # Viewport-scoped: created empty, filled by _refresh_viewport_layers
        # once the user switches them on.
        self.towers_layer = self._ensure_public_layer(
            layer_helpers.SOURCE_TOWERS, infra_group, visible=False, kind="site",
            build=lambda: layer_helpers.build_point_layer(
                f"Ontario Towers (GeoHub) -- {PUBLIC_RECORDS_DISCLOSURE}", [], terrestrial_public.TOWER_FIELDS,
                COLORS["towers"],
                abstract=f"Ontario GeoHub Tower dataset (MNRF), live query. {PUBLIC_RECORDS_DISCLOSURE.capitalize()}."))
        self.cellular_layer = self._ensure_public_layer(
            layer_helpers.SOURCE_CELLULAR, infra_group, visible=False, kind="site",
            build=lambda: layer_helpers.build_point_layer(
                f"Cellular Sites (ISED) -- {PUBLIC_RECORDS_DISCLOSURE}", [], terrestrial_public.CELLULAR_FIELDS,
                COLORS["cellular"],
                abstract=f"ISED Spectrum Licences Site Data, live query via Esri Canada mirror. {PUBLIC_RECORDS_DISCLOSURE.capitalize()}."))

        # Zoom before the viewport-scoped fetch below, so towers/cellular fetch
        # against the extent the user actually lands on, not whatever the
        # canvas happened to show before 'Load Public Data' was clicked.
        # QGIS adopts the first added layer's CRS for an otherwise-empty
        # project, and does it from a queued handler -- so it lands *after*
        # this function returns and silently replaces the workspace CRS with
        # the 4326 of Velorona's own memory layers. Re-assert the CRS and
        # compute the extent once that handler has run, otherwise the extent
        # is built against whichever CRS happened to be current.
        zoom_targets = home_layers or context_layers
        QTimer.singleShot(0, lambda: self._finalize_workspace(zoom_targets))
        self._refresh_viewport_layers()
        if not self._extents_connected:
            self.iface.mapCanvas().extentsChanged.connect(self._schedule_viewport_refresh)
            project.layerTreeRoot().visibilityChanged.connect(self._on_layer_visibility_changed)
            self._extents_connected = True

        self._populate_records()

        if problems:
            self._warn(
                "Loaded, with some sources unavailable right now (live public services -- try "
                "'Load Public Data' again later):\n\n" + "\n".join(problems)
            )

    def _replace_layer(self, old_layer, new_layer, group):
        """Removes a previous run's overlay layer (if any) and adds the
        freshly built one in its place, hero-visible. Overlay layers are
        small (one link/site at a time) -- rebuilding is simpler and just
        as cheap as an in-place field-preserving refresh."""
        project = QgsProject.instance()
        if old_layer is not None and old_layer.id() in project.mapLayers():
            project.removeMapLayer(old_layer.id())
        layer_helpers.add_to_group(project, new_layer, group, visible=True,
                                   lifecycle=LIFECYCLE_EVIDENCE)
        return new_layer

    def _update_weather_evidence_layers(self, microwave_result):
        evidence_group = self._ensure_velorona_groups()[1]["Evidence"]
        stations_layer, lines_layer = overlays.build_weather_evidence_layers(microwave_result)
        self.weather_stations_layer = self._replace_layer(self.weather_stations_layer, stations_layer, evidence_group)
        self.weather_lines_layer = self._replace_layer(self.weather_lines_layer, lines_layer, evidence_group)

    def _update_terrain_layer(self, terrestrial_result):
        evidence_group = self._ensure_velorona_groups()[1]["Evidence"]
        terrain_layer = overlays.build_terrain_layer(terrestrial_result)
        self.terrain_layer = self._replace_layer(self.terrain_layer, terrain_layer, evidence_group)

    def _current_extent_bbox_wgs84(self):
        canvas = self.iface.mapCanvas()
        extent = canvas.extent()
        canvas_crs = canvas.mapSettings().destinationCrs()
        if canvas_crs != WGS84:
            transform = QgsCoordinateTransform(canvas_crs, WGS84, QgsProject.instance())
            extent = transform.transformBoundingBox(extent)
        return (extent.xMinimum(), extent.yMinimum(), extent.xMaximum(), extent.yMaximum())

    def _schedule_viewport_refresh(self):
        """Coalesces a burst of extentsChanged into a single fetch once the
        viewport settles."""
        if self._viewport_timer is None:
            self._viewport_timer = QTimer(self.iface.mainWindow())
            self._viewport_timer.setSingleShot(True)
            self._viewport_timer.timeout.connect(self._refresh_viewport_layers)
        self._viewport_timer.start(VIEWPORT_REFRESH_DEBOUNCE_MS)

    def _on_layer_visibility_changed(self, node):
        """A layer switched on holds no data yet, since nothing was fetched
        while it was hidden."""
        if not isinstance(node, QgsLayerTreeLayer) or not node.isVisible():
            return
        if self.satellites_layer is not None and node.layerId() == self.satellites_layer.id():
            self._populate_satellites()
            return
        if self.towers_layer is None or self.cellular_layer is None:
            return
        if node.layerId() in (self.towers_layer.id(), self.cellular_layer.id()):
            self._schedule_viewport_refresh()

    def _populate_satellites(self):
        """Fetches CelesTrak element sets and propagates sub-points, once the
        Satellites layer is actually visible. Sub-points are time-dependent, so
        a refresh is re-run if the layer is switched off and on again after the
        positions have gone stale."""
        if self.satellites_layer is None:
            return
        now = time.monotonic()
        if self._satellites_fetched_at is not None and now - self._satellites_fetched_at < SATELLITE_REFRESH_SECONDS:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        QApplication.processEvents()
        try:
            records = space_public.build_satellite_records(space_public.fetch_celestrak_satellites())
        except Exception as exc:
            self._warn(f"Satellites (CelesTrak) unavailable right now: {exc}")
            return
        finally:
            QApplication.restoreOverrideCursor()
        layer_helpers.replace_point_features(self.satellites_layer, records, space_public.SATELLITE_FIELDS)
        self._satellites_fetched_at = now
        if not records:
            # fetch_celestrak_satellites degrades per group rather than raising,
            # so an empty result is silent otherwise -- say so instead of
            # leaving an empty layer with no explanation.
            self._warn("CelesTrak returned no element sets just now (the service rate-limits "
                       "repeated requests). The Satellites layer is empty; switch it off and on "
                       "again later to retry.")
        if self.dock is not None:
            self.dock.records.refresh_current()

    def _refresh_viewport_layers(self):
        if self.towers_layer is None or self.cellular_layer is None:
            return
        # A fetch can block for several seconds and pumps the event loop once
        # to paint the busy cursor, so a queued timeout could otherwise
        # re-enter this method mid-fetch.
        if self._viewport_refreshing:
            return
        root = QgsProject.instance().layerTreeRoot()
        bbox = self._current_extent_bbox_wgs84()
        self._viewport_refreshing = True
        busy = False
        refreshed = False
        try:
            for layer, fetch, fields, source in (
                (self.towers_layer, terrestrial_public.fetch_geohub_towers,
                 terrestrial_public.TOWER_FIELDS, terrestrial_public.TOWER_SOURCE_KEY),
                (self.cellular_layer, terrestrial_public.fetch_ised_cellular,
                 terrestrial_public.CELLULAR_FIELDS, terrestrial_public.CELLULAR_SOURCE_KEY),
            ):
                # Both layers are off by default. Querying a live service for a
                # layer nobody can see cost ~10s of blocked GUI time per map
                # movement (measured, ISED cellular), so the fetch waits until
                # the layer is actually switched on.
                node = root.findLayer(layer.id())
                if node is None or not node.isVisible():
                    continue
                if self._last_viewport_bbox.get(layer.id()) == bbox:
                    continue

                cached = self._viewport_cache.get(source, bbox)
                if cached is FAILED:
                    continue  # recent failure -- don't hammer a service that is down
                if cached is MISS:
                    if not busy:
                        # The ISED query alone measures ~8s. Paint the busy
                        # state once, before the first blocking call.
                        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
                        QApplication.processEvents()
                        busy = True
                    try:
                        sites, _ = fetch(bbox)
                    except Exception:
                        # live public service -- degrade, don't crash the map interaction
                        self._viewport_cache.put_failure(source, bbox)
                        continue
                    self._viewport_cache.put(source, bbox, sites)
                else:
                    sites = cached

                layer_helpers.replace_point_features(layer, sites, fields)
                self._last_viewport_bbox[layer.id()] = bbox
                refreshed = True
        finally:
            if busy:
                QApplication.restoreOverrideCursor()
            self._viewport_refreshing = False
        if refreshed and self.dock is not None:
            self.dock.records.refresh_current()

    # -- Inspector: single-feature selection on a Velorona-managed layer --
    # opens the same section-based drawer as a running analysis, never
    # QGIS's generic Attribute Table.

    def _wire_inspector(self, layer, kind: str):
        layer.selectionChanged.connect(lambda *_, lyr=layer, k=kind: self._on_feature_selected(lyr, k))

    def _on_feature_selected(self, layer, kind: str):
        """One selected feature is a detailed investigation; several are a
        selection summary. Endpoint-level weather is only ever fetched for a
        single link, so selecting the whole layer cannot trigger thousands of
        live requests."""
        count = layer.selectedFeatureCount()
        if count == 0:
            if self.dock is not None:
                self.dock.show_empty_state()
            return
        if count > 1:
            self._show_result(self._summarize_selection(layer, kind, count))
            if self.dock is not None and not self._selecting_from_table and count <= SELECTION_TABLE_LIMIT:
                self.dock.records.show_features(layer, layer.selectedFeatureIds())
            return

        feature = layer.selectedFeatures()[0]
        entry = feature_to_entry(feature, kind)
        if kind == "link":
            result = self._investigate_link(entry)
            self._update_network_context(layer, feature, result)
        else:
            result = entry
        self._show_result(result)
        # Map -> table: keep Records on the same record the map is showing.
        if self.dock is not None and not self._selecting_from_table:
            self.dock.records.show_feature(layer, feature.id())

    def _update_network_context(self, layer, feature, investigation):
        """Draws the other Fixed Service links that terminate at this link's own
        endpoints. Purely spatial context from confirmed shared endpoints in the
        record -- no weather is fetched for them and nothing is inferred about
        how one link behaves when another does."""
        index = self._endpoint_index.get(layer.id())
        if index is None:
            index = network_context.build_endpoint_index(layer)
            self._endpoint_index[layer.id()] = index
        connected = network_context.connected_links(index, feature)
        investigation.connected_site_a = len(connected["site_a"])
        investigation.connected_site_b = len(connected["site_b"])

        fids = (connected["site_a"] + connected["site_b"])[:network_context.MAX_CONNECTED]
        project = QgsProject.instance()
        if self.network_context_layer is not None and self.network_context_layer.id() in project.mapLayers():
            project.removeMapLayer(self.network_context_layer.id())
            self.network_context_layer = None
        if not fids:
            return
        context_layer = layer_helpers.build_context_link_layer(
            "Network Context -- shared endpoints",
            [layer.getFeature(fid) for fid in fids],
            COLORS["fixed-links"])
        evidence_group = self._ensure_velorona_groups()[1]["Evidence"]
        self.network_context_layer = self._replace_layer(None, context_layer, evidence_group)

    def _summarize_selection(self, layer, kind: str, count: int):
        """Aggregates for a multi-feature selection.

        Attributes are read from the already-loaded layer only -- no network,
        no per-feature analysis -- and the scan itself is capped so selecting
        every record stays responsive. Above SELECTION_TABLE_LIMIT the listing
        is dropped and the user is asked to narrow the selection instead."""
        source_key = layer_helpers.layer_source_key(layer)
        columns = records_table.COLUMNS.get(source_key, [])
        scanned = min(count, SELECTION_SCAN_LIMIT)
        # Capture for export, not for display: the dock and the Records widget
        # apply their own, much smaller SELECTION_TABLE_LIMIT before drawing.
        want_rows = count <= SELECTION_LISTING_LIMIT

        rows, licensees, frequencies = [], set(), []
        extent = QgsRectangle()
        for index, feature in enumerate(layer.selectedFeatures()):
            if index >= scanned:
                break
            geom = feature.geometry()
            if geom is not None and not geom.isEmpty():
                box = geom.boundingBox()
                extent = QgsRectangle(box) if extent.isNull() else (extent.combineExtentWith(box) or extent)
            names = feature.fields().names()
            if "licensee" in names and feature["licensee"]:
                licensees.add(str(feature["licensee"]))
            if "frequencies_mhz" in names and feature["frequencies_mhz"]:
                for chunk in str(feature["frequencies_mhz"]).split(","):
                    try:
                        frequencies.append(float(chunk.strip()))
                    except ValueError:
                        continue
            if want_rows:
                rows.append(records_table.display_row(feature, columns))

        return inspector.SelectionSummary(
            kind_label=records_table.DATASET_LABELS.get(source_key, "features"),
            feature_kind=kind,
            count=count,
            scanned=scanned,
            licensees=sorted(licensees),
            frequency_range=((min(frequencies), max(frequencies)) if frequencies else None),
            extent_wgs84=(None if extent.isNull() else
                          (extent.xMinimum(), extent.yMinimum(), extent.xMaximum(), extent.yMaximum())),
            columns=[label for label, _ in columns],
            rows=rows,
            table_limit=SELECTION_TABLE_LIMIT,
            listing_limit=SELECTION_LISTING_LIMIT,
            licensee_filter=self._licensee_filter,
        )

    def _on_record_chosen(self, layer, fid, kind):
        """Table -> map: make the layer current, select the feature, and let the
        existing selection path open the evidence drawer."""
        self._selecting_from_table = True
        try:
            self.iface.setActiveLayer(layer)
            layer.selectByIds([fid])
        finally:
            self._selecting_from_table = False

    def _on_records_chosen(self, layer, fids, kind):
        """Several table rows -> the same multi-selection on the map, which
        flows back through the normal selection path as a summary."""
        self._selecting_from_table = True
        try:
            self.iface.setActiveLayer(layer)
            layer.selectByIds(list(fids))
        finally:
            self._selecting_from_table = False

    def _investigate_link(self, entry):
        """Selecting a Fixed Service link runs the existing microwave weather
        engine against the two endpoints the link record itself carries, so the
        investigation the user needs arrives with the selection instead of
        requiring a separate action. Pairing still comes from the shared
        authorization in ISED's extract -- never from proximity."""
        if entry.site_a_point is None or entry.site_b_point is None:
            return inspector.LinkInvestigation(
                entry=entry, weather_error="This link record has no usable endpoint geometry.")

        params, origins = microwave_exposure.build_link_params(entry.data)
        cache_key = ("link-weather", str(entry.data.get("authorization_number") or entry.data.get("id")))
        bbox = (entry.site_a_point[0], entry.site_a_point[1],
                entry.site_b_point[0], entry.site_b_point[1])

        cached = self._link_weather_cache.get(cache_key, bbox)
        if cached is not MISS and cached is not FAILED:
            return inspector.LinkInvestigation(entry=entry, exposure=cached, param_origins=origins)
        if cached is FAILED:
            return inspector.LinkInvestigation(
                entry=entry, param_origins=origins,
                weather_error="Live weather was unavailable for this link a moment ago; not retried yet.")

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        QApplication.processEvents()  # paint the busy state before the blocking fetch
        try:
            exposure = microwave_exposure.analyze_link_record(
                entry.site_a_point, entry.site_b_point, entry.data, params)
        except Exception as exc:  # live public weather services -- degrade, don't crash
            self._link_weather_cache.put_failure(cache_key, bbox)
            return inspector.LinkInvestigation(entry=entry, param_origins=origins, weather_error=str(exc))
        finally:
            QApplication.restoreOverrideCursor()

        self._link_weather_cache.put(cache_key, bbox, exposure)
        return inspector.LinkInvestigation(entry=entry, exposure=exposure, param_origins=origins)

    def _open_elevation_profile(self):
        for action in self.iface.mainWindow().findChildren(QAction):
            if "elevation profile" in action.text().lower():
                action.trigger()
                return
        self._warn("Could not find QGIS's Elevation Profile action automatically -- open it via the View menu.")

    # -- Select: gather selected features across every layer --------------

    def _gather_selected_entries(self):
        entries = []
        for layer in QgsProject.instance().mapLayers().values():
            if not hasattr(layer, "selectedFeatures"):
                continue
            kind = layer_helpers.layer_kind(layer)
            for feature in layer.selectedFeatures():
                entries.append((kind, layer, feature))
        return entries

    def _selected_by_kind(self, kind: str):
        return [(layer, feature) for k, layer, feature in self._gather_selected_entries() if k == kind]

    # -- Analyze ------------------------------------------------------------

    def run_terrestrial(self):
        entries = self._selected_by_kind("site")
        if len(entries) != 2:
            self._warn(
                f"Select exactly two 'site' features (any layer -- public or your own import) as "
                f"the link's endpoints. Currently {len(entries)} selected."
            )
            return
        defaults = terrestrial.build_params(entries)
        dialog = ParamDialog(self.iface.mainWindow(), "Velorona -- Terrestrial Path Clearance", terrestrial.PARAM_SPEC, defaults)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        try:
            result = terrestrial.analyze(entries, dialog.values())
        except Exception as exc:
            self._error(f"Analysis failed:\n{exc}")
            return
        self._update_terrain_layer(result)
        self._show_result(result)

    def run_microwave(self):
        entries = self._selected_by_kind("site")
        if len(entries) != 2:
            self._warn(
                f"Select exactly two 'site' features (any layer -- public or your own import) as "
                f"the link's endpoints. Currently {len(entries)} selected."
            )
            return
        defaults = microwave_exposure.build_params(entries)
        dialog = ParamDialog(self.iface.mainWindow(), "Velorona -- Microwave Weather Exposure", microwave_exposure.PARAM_SPEC, defaults)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        try:
            result = microwave_exposure.analyze(entries, dialog.values())
        except Exception as exc:
            self._error(f"Analysis failed:\n{exc}")
            return
        self._update_weather_evidence_layers(result)
        self._show_result(result)

    def run_satellite(self):
        ground_stations = self._selected_by_kind("ground-station")
        satellites = self._selected_by_kind("satellite")
        if len(ground_stations) != 1 or len(satellites) != 1:
            self._warn(
                f"Select exactly 1 Ground/Earth Station feature and 1 Satellite feature. Currently "
                f"{len(ground_stations)} ground station(s), {len(satellites)} satellite(s) selected."
            )
            return
        try:
            result = satellite_earth_space.analyze(ground_stations[0], satellites[0])
        except Exception as exc:
            self._error(f"Analysis failed:\n{exc}")
            return
        self._show_result(result)

    def _ensure_dock(self):
        if self.dock is None:
            self.dock = VeloronaResultsDock(self.iface.mainWindow())
            self.dock.elevation_profile_requested = self._open_elevation_profile
            self.dock.map_appearance_changed = self.set_map_appearance
            self.dock.set_map_appearance(self._map_appearance)
            self.dock.records.featureChosen.connect(self._on_record_chosen)
            self.dock.records.featuresChosen.connect(self._on_records_chosen)
            self.dock.records.licenseeChanged.connect(self.set_licensee_filter)
            self.iface.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock)
            self._size_dock()
        return self.dock

    def _size_dock(self):
        """The map is the primary workspace, so the investigation panel takes
        about a third of the window and the map keeps the rest. Derived from the
        window's current width rather than a fixed pixel size, and applied only
        when the dock is first created -- the user can still drag the splitter
        afterwards."""
        main_window = self.iface.mainWindow()
        if main_window is None or not hasattr(main_window, "resizeDocks"):
            return
        self.dock.setMinimumWidth(DOCK_MIN_WIDTH_PX)
        target = max(DOCK_MIN_WIDTH_PX, min(DOCK_MAX_WIDTH_PX,
                                            int(main_window.width() * DOCK_WIDTH_FRACTION)))
        # Constrain only for this one resize, then release it so the splitter
        # stays free afterwards.
        self.dock.setMaximumWidth(target)
        main_window.resizeDocks([self.dock], [target], Qt.Orientation.Horizontal)
        QTimer.singleShot(0, lambda: self.dock.setMaximumWidth(QWIDGETSIZE_MAX))

    def set_licensee_filter(self, licensee: str) -> None:
        """Shows only this licensee's Fixed Service site records.

        Applied as a provider filter on the layer that is already loaded, so
        the map clusters, the Records table and any selection all see the same
        subset. Nothing is refetched, no second dataset is created, and the
        cluster counts become counts of the filtered records. This is spatial
        record distribution only -- it implies nothing about coverage,
        performance or operator standing."""
        project = QgsProject.instance()
        sites = layer_helpers.find_owned_layer(project, layer_helpers.SOURCE_FIXED_SITES)
        if sites is None:
            return
        if licensee:
            escaped = licensee.replace("'", "''")
            sites.setSubsetString(f"\"licensee\" = '{escaped}'")
        else:
            sites.setSubsetString("")
        self._licensee_filter = licensee
        sites.triggerRepaint()
        # Only rebuild the table when it is actually showing the filtered
        # dataset; rebuilding the links table here cost ~1.1s per switch.
        if self.dock is not None and self.dock.records.current_source_key() == layer_helpers.SOURCE_FIXED_SITES:
            self.dock.records.refresh_current()

    def _licensee_counts(self, sites_layer) -> dict:
        """Record count per licensee, read from the loaded layer itself."""
        counts = {}
        if sites_layer is None:
            return counts
        previous = sites_layer.subsetString()
        sites_layer.setSubsetString("")
        try:
            for feature in sites_layer.getFeatures():
                name = (feature["licensee"] or "").strip()
                if name:
                    counts[name] = counts.get(name, 0) + 1
        finally:
            sites_layer.setSubsetString(previous)
        return counts

    def _populate_records(self):
        """Point the Records table at the Velorona layers now in the project."""
        project = QgsProject.instance()
        dock = self._ensure_dock()
        dock.records.set_layers({
            key: layer_helpers.find_owned_layer(project, key)
            for key in (layer_helpers.SOURCE_FIXED_LINKS, layer_helpers.SOURCE_FIXED_SITES,
                        layer_helpers.SOURCE_TOWERS, layer_helpers.SOURCE_CELLULAR,
                        layer_helpers.SOURCE_SATELLITES, layer_helpers.SOURCE_GROUND_STATIONS)
        })
        dock.records.populate_licensees(
            self._licensee_counts(layer_helpers.find_owned_layer(project, layer_helpers.SOURCE_FIXED_SITES)))

    def _show_result(self, result):
        self._ensure_dock()
        self.dock.show_result(result)
        self.dock.show()
        self.dock.raise_()
