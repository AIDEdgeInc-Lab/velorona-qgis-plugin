from __future__ import annotations

from qgis.core import QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsProject, QgsRasterLayer, QgsRectangle
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QAction, QMessageBox

from .core import layers as layer_helpers
from .core import overlays
from .core.colors import COLORS
from .core.engines import microwave_exposure, satellite_earth_space, terrestrial
from .core.inspector import feature_to_entry
from .core.layers import PUBLIC_RECORDS_DISCLOSURE
from .core.sources import space_public, terrestrial_public
from .ui.param_dialog import ParamDialog
from .ui.results_dock import VeloronaResultsDock

MENU_NAME = "&Velorona"
WGS84 = QgsCoordinateReferenceSystem("EPSG:4326")

# Basemap -- OSM tile source matches the fix already proven in
# aei-link-clearance/web/app.js (see its own header comment, lines ~9-36:
# CARTO Dark Matter is now key-gated, Esri's dark-gray canvas's ToS
# restricts it to non-commercial use). The web app additionally applies a
# CSS filter with a hue-rotate(180deg) term, which has no QGIS raster-filter
# equivalent (QgsHueSaturationFilter has invert/saturation but no
# hue-rotation-by-degrees control) -- so this couldn't be copied verbatim.
#
# The filter VALUES below were re-derived here by actually rendering the
# basemap headlessly (QgsMapRendererParallelJob -> QImage) and comparing
# real pixel statistics + visual output across several combinations, not
# guessed: invertColors=True alone preserved full color detail (as many
# distinct sampled colors as the unfiltered source, since invert is
# lossless) while being genuinely dark; the previous combination here
# (saturation -60, brightness -20, contrast -10) measurably destroyed MORE
# color detail (fewer distinct sampled pixel colors) while being LESS dark
# (higher mean luminance) than plain invert -- objectively worse on both
# axes it was meant to improve. Landed on invert + a mild saturation cut
# only (muted without crushing detail); brightness/contrast left at 0 since
# any contrast increase clipped most pixels toward black in testing.
#
# Known, disclosed limitation: water renders brown/orange, not dark blue --
# a direct consequence of invert-without-hue-rotate, structurally
# unavailable in QGIS's raster filter API. A genuinely correct fix would be
# a naturally-dark vector basemap instead of a filtered raster one (e.g.
# OpenFreeMap, tiles.openfreemap.org -- confirmed live/free/keyless via its
# TileJSON, HTTP 200, no key) rendered through QGIS's native vector tile
# support -- not implemented here; flagged as the real next step if the
# brown-water artifact needs to go away entirely rather than be tuned around.
BASEMAP_NAME = "OpenStreetMap (dark-filtered)"
BASEMAP_URI = "type=xyz&url=https://tile.openstreetmap.org/%7Bz%7D/%7Bx%7D/%7By%7D.png&zmax=19&zmin=0"
BASEMAP_SATURATION = -25
BASEMAP_BRIGHTNESS = 0
BASEMAP_CONTRAST = 0

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
        self._extents_connected = False

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
            self.iface.mapCanvas().extentsChanged.disconnect(self._refresh_viewport_layers)
            self._extents_connected = False
        if self.dock is not None:
            self.iface.removeDockWidget(self.dock)
            self.dock = None

    def _warn(self, message: str) -> None:
        QMessageBox.warning(self.iface.mainWindow(), "Velorona", message)

    def _error(self, message: str) -> None:
        QMessageBox.critical(self.iface.mainWindow(), "Velorona", message)

    # -- Explore: Load Public Data ----------------------------------------

    def _ensure_group(self, name: str, parent=None):
        parent = parent or QgsProject.instance().layerTreeRoot()
        existing = parent.findGroup(name)
        return existing if existing is not None else parent.insertGroup(0, name)

    def _ensure_basemap(self):
        """Adds QGIS's native dark-basemap XYZ tile layer beneath every
        other layer, once. Without this the canvas is just floating dots
        on white -- meaningless to a first-time user."""
        project = QgsProject.instance()
        for existing in project.mapLayers().values():
            if existing.name() == BASEMAP_NAME:
                return
        basemap = QgsRasterLayer(BASEMAP_URI, BASEMAP_NAME, "wms")
        if not basemap.isValid():
            self._warn(f"Could not load the {BASEMAP_NAME} basemap: {basemap.error().message()}")
            return
        # QGIS-native equivalent of the web Map's CSS tile-pane filter --
        # values re-derived from actual headless-rendered pixel output, see
        # the BASEMAP_* constants' comment above for the measurements.
        hue_sat = basemap.hueSaturationFilter()
        hue_sat.setInvertColors(True)
        hue_sat.setSaturation(BASEMAP_SATURATION)
        brightness_contrast = basemap.brightnessFilter()
        brightness_contrast.setBrightness(BASEMAP_BRIGHTNESS)
        brightness_contrast.setContrast(BASEMAP_CONTRAST)
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
        combined.scale(1.1)  # a little breathing room around the data
        canvas = self.iface.mapCanvas()
        canvas_crs = canvas.mapSettings().destinationCrs()
        if canvas_crs != WGS84:
            transform = QgsCoordinateTransform(WGS84, canvas_crs, QgsProject.instance())
            combined = transform.transformBoundingBox(combined)
        canvas.setExtent(combined)
        canvas.refresh()

    def load_public_data(self):
        project = QgsProject.instance()
        # See PROJECT_CRS's comment above -- measured ~2.4x full-redraw speedup
        # (real numbers) from avoiding on-the-fly raster reprojection of the
        # XYZ basemap tiles. Set explicitly on both project and canvas rather
        # than relying on QGIS's usual project-to-canvas CRS propagation.
        project.setCrs(PROJECT_CRS)
        self.iface.mapCanvas().setDestinationCrs(PROJECT_CRS)
        velorona_group = self._ensure_group("Velorona")
        infra_group = self._ensure_group("Infrastructure", velorona_group)
        space_group = self._ensure_group("Space", velorona_group)
        problems = []
        loaded_layers = []

        # Hero: on by default -- the primary Select Link -> Analyze -> Evidence workflow.
        try:
            sites, links = terrestrial_public.load_fixed_service_snapshot()
            sites_layer = layer_helpers.build_point_layer(
                f"Fixed Service sites -- {PUBLIC_RECORDS_DISCLOSURE}", sites,
                terrestrial_public.FIXED_SITE_FIELDS, COLORS["fixed-sites"],
                abstract=f"ISED Fixed Service, static snapshot. {PUBLIC_RECORDS_DISCLOSURE.capitalize()}.")
            links_layer = layer_helpers.build_link_layer(
                f"Fixed Service links -- {PUBLIC_RECORDS_DISCLOSURE}", links,
                terrestrial_public.FIXED_LINK_FIELDS, COLORS["fixed-links"],
                abstract=f"ISED Fixed Service, static snapshot. {PUBLIC_RECORDS_DISCLOSURE.capitalize()}.")
            layer_helpers.add_to_group(project, sites_layer, infra_group, visible=True)
            layer_helpers.add_to_group(project, links_layer, infra_group, visible=True)
            self._wire_inspector(sites_layer, "site")
            self._wire_inspector(links_layer, "link")
            loaded_layers += [sites_layer, links_layer]
        except Exception as exc:
            problems.append(f"Fixed Service (ISED): {exc}")

        # Context: present, off by default -- toggled on by the user, not removed.
        try:
            stations = space_public.load_ground_station_snapshot()
            gs_layer = layer_helpers.build_point_layer(
                "Ground/Earth Stations", stations, space_public.GROUND_STATION_FIELDS,
                COLORS["ground-stations"], kind="ground-station")
            layer_helpers.add_to_group(project, gs_layer, space_group, visible=False)
            self._wire_inspector(gs_layer, "ground-station")
            loaded_layers.append(gs_layer)
        except Exception as exc:
            problems.append(f"Ground/Earth Stations (SatNOGS): {exc}")

        try:
            elements = space_public.fetch_celestrak_satellites()
            records = space_public.build_satellite_records(elements)
            sat_layer = layer_helpers.build_point_layer(
                "Satellites", records, space_public.SATELLITE_FIELDS, COLORS["satellites"], kind="satellite")
            layer_helpers.add_to_group(project, sat_layer, space_group, visible=False)
            self._wire_inspector(sat_layer, "satellite")
            loaded_layers.append(sat_layer)
        except Exception as exc:
            problems.append(f"Satellites (CelesTrak): {exc}")

        self.towers_layer = layer_helpers.build_point_layer(
            f"Ontario Towers (GeoHub) -- {PUBLIC_RECORDS_DISCLOSURE}", [], terrestrial_public.TOWER_FIELDS,
            COLORS["towers"], abstract=f"Ontario GeoHub Tower dataset (MNRF), live query. {PUBLIC_RECORDS_DISCLOSURE.capitalize()}.")
        self.cellular_layer = layer_helpers.build_point_layer(
            f"Cellular Sites (ISED) -- {PUBLIC_RECORDS_DISCLOSURE}", [], terrestrial_public.CELLULAR_FIELDS,
            COLORS["cellular"], abstract=f"ISED Spectrum Licences Site Data, live query via Esri Canada mirror. {PUBLIC_RECORDS_DISCLOSURE.capitalize()}.")
        layer_helpers.add_to_group(project, self.towers_layer, infra_group, visible=False)
        layer_helpers.add_to_group(project, self.cellular_layer, infra_group, visible=False)
        self._wire_inspector(self.towers_layer, "site")
        self._wire_inspector(self.cellular_layer, "site")

        self._ensure_basemap()
        # Zoom before the viewport-scoped fetch below, so towers/cellular fetch
        # against the extent the user actually lands on, not whatever the
        # canvas happened to show before 'Load Public Data' was clicked.
        self._zoom_to_layers(loaded_layers)
        self._refresh_viewport_layers()
        if not self._extents_connected:
            self.iface.mapCanvas().extentsChanged.connect(self._refresh_viewport_layers)
            self._extents_connected = True

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
        layer_helpers.add_to_group(project, new_layer, group, visible=True)
        return new_layer

    def _update_weather_evidence_layers(self, microwave_result):
        evidence_group = self._ensure_group("Evidence", self._ensure_group("Velorona"))
        stations_layer, lines_layer = overlays.build_weather_evidence_layers(microwave_result)
        self.weather_stations_layer = self._replace_layer(self.weather_stations_layer, stations_layer, evidence_group)
        self.weather_lines_layer = self._replace_layer(self.weather_lines_layer, lines_layer, evidence_group)

    def _update_terrain_layer(self, terrestrial_result):
        evidence_group = self._ensure_group("Evidence", self._ensure_group("Velorona"))
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

    def _refresh_viewport_layers(self):
        if self.towers_layer is None or self.cellular_layer is None:
            return
        bbox = self._current_extent_bbox_wgs84()
        try:
            sites, _ = terrestrial_public.fetch_geohub_towers(bbox)
            layer_helpers.replace_point_features(self.towers_layer, sites, terrestrial_public.TOWER_FIELDS)
        except Exception:
            pass  # live public service -- degrade, don't crash the map interaction
        try:
            sites, _ = terrestrial_public.fetch_ised_cellular(bbox)
            layer_helpers.replace_point_features(self.cellular_layer, sites, terrestrial_public.CELLULAR_FIELDS)
        except Exception:
            pass

    # -- Inspector: single-feature selection on a Velorona-managed layer --
    # opens the same section-based drawer as a running analysis, never
    # QGIS's generic Attribute Table.

    def _wire_inspector(self, layer, kind: str):
        layer.selectionChanged.connect(lambda *_, lyr=layer, k=kind: self._on_feature_selected(lyr, k))

    def _on_feature_selected(self, layer, kind: str):
        if layer.selectedFeatureCount() != 1:
            return
        entry = feature_to_entry(layer.selectedFeatures()[0], kind)
        self._show_result(entry)

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
        if dialog.exec_() != dialog.Accepted:
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
        if dialog.exec_() != dialog.Accepted:
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

    def _show_result(self, result):
        if self.dock is None:
            self.dock = VeloronaResultsDock(self.iface.mainWindow())
            self.dock.elevation_profile_requested = self._open_elevation_profile
            self.iface.addDockWidget(Qt.RightDockWidgetArea, self.dock)
        self.dock.show_result(result)
        self.dock.show()
        self.dock.raise_()
