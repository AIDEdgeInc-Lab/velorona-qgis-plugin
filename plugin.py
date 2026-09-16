from __future__ import annotations

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsMapBoxGlStyleConverter,
    QgsProject,
    QgsRectangle,
    QgsVectorTileLayer,
)
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
BASEMAP_NAME = "CARTO Dark Matter"
BASEMAP_STYLE_URL = "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json"
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
        """Adds the native QGIS vector tile basemap (CARTO Dark Matter)
        beneath every other layer, once. Without this the canvas is just
        floating dots on a black background -- meaningless to a
        first-time user."""
        project = QgsProject.instance()
        for existing in project.mapLayers().values():
            if existing.name() == BASEMAP_NAME:
                return

        import requests

        try:
            resp = requests.get(BASEMAP_STYLE_URL, timeout=10.0)
            resp.raise_for_status()
            style_json = resp.text
        except Exception as exc:
            self._warn(f"Could not fetch the {BASEMAP_NAME} style: {exc}")
            return

        tile_url_encoded = BASEMAP_TILE_URL.replace("{z}", "%7Bz%7D").replace("{x}", "%7Bx%7D").replace("{y}", "%7By%7D")
        uri = f"type=xyz&url={tile_url_encoded}&zmax={BASEMAP_TILE_MAXZOOM}&zmin=0"
        basemap = QgsVectorTileLayer(uri, BASEMAP_NAME)
        if not basemap.isValid():
            self._warn(f"Could not load the {BASEMAP_NAME} vector tile layer.")
            return

        converter = QgsMapBoxGlStyleConverter()
        result = converter.convert(style_json)
        if result != QgsMapBoxGlStyleConverter.Success:
            self._warn(f"Could not convert the {BASEMAP_NAME} style: {converter.errorMessage()}")
            return
        basemap.setRenderer(converter.renderer().clone())
        basemap.setLabelsEnabled(False)  # see module-level comment: label collision detection cost spikes at some zoom ranges

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
