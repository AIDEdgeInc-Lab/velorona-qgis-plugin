"""Velorona QGIS plugin -- load / render / navigation benchmark.

Runs the REAL plugin against a real QgsProject + QgsMapCanvas offscreen,
triggering the real QAction. Counts the work that matters (network calls,
canvas refreshes, viewport-refresh invocations, style conversions) and
times load, first render, and a pan/zoom sequence.

Usage: python3.12 bench.py <label>
"""

import json
import os
import sys
import time

# Repo-local: tests/ lives directly under the plugin package.
PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(PLUGIN_DIR))

LABEL = sys.argv[1] if len(sys.argv) > 1 else "run"

import requests  # noqa: E402

from qgis.core import (  # noqa: E402
    QgsApplication,
    QgsMapRendererParallelJob,
    QgsProject,
    QgsRectangle,
)
from qgis.gui import QgsLayerTreeMapCanvasBridge, QgsMapCanvas  # noqa: E402
from qgis.PyQt.QtCore import QSize  # noqa: E402
from qgis.PyQt.QtWidgets import QMainWindow  # noqa: E402

qgs = QgsApplication([], False)
qgs.initQgis()

stats = {
    "label": LABEL,
    "http_requests": 0,
    "http_seconds": 0.0,
    "http_by_host": {},
    "canvas_refresh_calls": 0,
    "viewport_refresh_calls": 0,
    "style_conversions": 0,
    "basemap_constructions": 0,
    "layer_repaints": 0,
}

_real_get = requests.get


def counting_get(url, *a, **kw):
    host = url.split("/")[2] if "//" in url else url
    t = time.monotonic()
    try:
        return _real_get(url, *a, **kw)
    finally:
        dt = time.monotonic() - t
        stats["http_requests"] += 1
        stats["http_seconds"] += dt
        h = stats["http_by_host"].setdefault(host, {"n": 0, "s": 0.0})
        h["n"] += 1
        h["s"] += dt


requests.get = counting_get


class CountingCanvas(QgsMapCanvas):
    def refresh(self):
        stats["canvas_refresh_calls"] += 1
        super().refresh()


class FakeIface:
    def __init__(self):
        self.window = QMainWindow()
        self.canvas = CountingCanvas()
        self.canvas.resize(1280, 800)
        self._docks = []

    def mapCanvas(self):
        return self.canvas

    def mainWindow(self):
        return self.window

    def addToolBarIcon(self, a):
        pass

    def addPluginToMenu(self, m, a):
        pass

    def removePluginMenu(self, m, a):
        pass

    def removeToolBarIcon(self, a):
        pass

    def addDockWidget(self, area, dock):
        self._docks.append(dock)

    def removeDockWidget(self, dock):
        pass


iface = FakeIface()
canvas = iface.canvas
project = QgsProject.instance()

# QGIS Desktop syncs the project layer tree onto the canvas through this
# bridge; without it a bare canvas holds no layers and renders nothing.
bridge = QgsLayerTreeMapCanvasBridge(project.layerTreeRoot(), canvas)
bridge.setAutoSetupOnFirstLayer(False)

import velorona.plugin as plugin_mod  # noqa: E402
from velorona.core import layers as layer_helpers  # noqa: E402

# Count style conversions (basemap style parse/convert).
_RealConverter = plugin_mod.QgsMapBoxGlStyleConverter


class CountingConverter(_RealConverter):
    def convert(self, *a, **kw):
        stats["style_conversions"] += 1
        return super().convert(*a, **kw)


plugin_mod.QgsMapBoxGlStyleConverter = CountingConverter

_RealTileLayer = plugin_mod.QgsVectorTileLayer


def counting_tile_layer(*a, **kw):
    stats["basemap_constructions"] += 1
    return _RealTileLayer(*a, **kw)


plugin_mod.QgsVectorTileLayer = counting_tile_layer

_real_replace = layer_helpers.replace_point_features


def counting_replace(*a, **kw):
    stats["layer_repaints"] += 1
    return _real_replace(*a, **kw)


layer_helpers.replace_point_features = counting_replace
plugin_mod.layer_helpers.replace_point_features = counting_replace

plugin = plugin_mod.VeloronaPlugin(iface)
plugin._warn = lambda m: timings.setdefault("warnings", []).append(m.replace("\n", " | "))
plugin._error = lambda m: timings.setdefault("errors", []).append(m.replace("\n", " | "))

timings = {}

# Sub-phase timing: wrap the internal steps without altering behaviour.
_phase = {}


def timed(obj, name, key):
    real = getattr(obj, name)

    def wrapper(*a, **kw):
        t = time.monotonic()
        try:
            return real(*a, **kw)
        finally:
            _phase[key] = _phase.get(key, 0.0) + (time.monotonic() - t)
            _phase[key + "_n"] = _phase.get(key + "_n", 0) + 1

    setattr(obj, name, wrapper)
    return real


timed(plugin, "_ensure_basemap", "basemap")
timed(plugin, "_zoom_to_layers", "zoom_to_layers")


_real_viewport = plugin._refresh_viewport_layers


def counted_viewport(*a, **kw):
    stats["viewport_refresh_calls"] += 1
    t = time.monotonic()
    try:
        return _real_viewport(*a, **kw)
    finally:
        _phase["viewport"] = _phase.get("viewport", 0.0) + (time.monotonic() - t)


plugin._refresh_viewport_layers = counted_viewport

timed(plugin_mod.terrestrial_public, "load_fixed_service_snapshot", "fixed_service")
timed(plugin_mod.space_public, "load_ground_station_snapshot", "ground_stations")
timed(plugin_mod.space_public, "fetch_celestrak_satellites", "celestrak_fetch")
timed(plugin_mod.space_public, "build_satellite_records", "satellite_propagate")
timed(plugin_mod.layer_helpers, "build_point_layer", "build_point_layers")
timed(plugin_mod.layer_helpers, "build_link_layer", "build_link_layer")


def render(tag):
    """Pure render cost at the canvas's current extent/CRS/layers."""
    qgs.processEvents()
    ms = canvas.mapSettings()
    ms.setOutputSize(QSize(1280, 800))
    timings.setdefault("render_layer_counts", []).append(len(ms.layers()))
    job = QgsMapRendererParallelJob(ms)
    t = time.monotonic()
    job.start()
    job.waitForFinished()
    dt = time.monotonic() - t
    timings.setdefault("renders", []).append({"tag": tag, "seconds": round(dt, 3)})
    return dt


plugin.initGui()

timings["crs_before"] = project.crs().authid()

# --- A: blank project -> Load Public Data --------------------------------
t0 = time.monotonic()
plugin.action_load_public.trigger()
for _ in range(30):
    qgs.processEvents()   # workspace CRS + initial extent settle on the event loop
timings["A_load_public_data"] = round(time.monotonic() - t0, 3)

timings["crs_after_project"] = project.crs().authid()
timings["crs_after_canvas"] = canvas.mapSettings().destinationCrs().authid()
ext = canvas.extent()
timings["extent_after_load"] = [round(v, 1) for v in (ext.xMinimum(), ext.yMinimum(), ext.xMaximum(), ext.yMaximum())]
timings["extent_width_m"] = round(ext.width(), 1)
timings["layer_count"] = len(project.mapLayers())

# --- B: first stable render ----------------------------------------------
timings["B_first_render_cold"] = round(render("first_cold"), 3)
timings["B_first_render_warm"] = round(render("first_warm"), 3)

# --- C/D/E/F: navigation --------------------------------------------------
load_stats = dict(stats)


def nav(tag, new_extent):
    before_http = stats["http_requests"]
    before_vp = stats["viewport_refresh_calls"]
    before_refresh = stats["canvas_refresh_calls"]
    t = time.monotonic()
    canvas.setExtent(new_extent)
    qgs.processEvents()
    handler = time.monotonic() - t
    r = render(tag)
    timings.setdefault("nav", []).append({
        "step": tag,
        "handler_seconds": round(handler, 3),
        "render_seconds": round(r, 3),
        "total_seconds": round(handler + r, 3),
        "http_requests": stats["http_requests"] - before_http,
        "viewport_refreshes": stats["viewport_refresh_calls"] - before_vp,
        "canvas_refreshes": stats["canvas_refresh_calls"] - before_refresh,
    })


base = canvas.extent()


def shifted(e, fx, fy):
    dx, dy = e.width() * fx, e.height() * fy
    return QgsRectangle(e.xMinimum() + dx, e.yMinimum() + dy, e.xMaximum() + dx, e.yMaximum() + dy)


def scaled(e, f):
    r = QgsRectangle(e)
    r.scale(f)
    return r


nav("C_pan_1", shifted(base, 0.25, 0.0))
nav("D_zoom_in", scaled(shifted(base, 0.25, 0.0), 0.5))
nav("E_zoom_out", scaled(shifted(base, 0.25, 0.0), 2.0))
nav("F_pan_2", shifted(base, -0.25, 0.1))
nav("F_pan_3", shifted(base, 0.1, -0.2))
nav("F_zoom_in_2", scaled(base, 0.4))


# --- G: debounce + visibility behaviour (post-fix paths) ------------------
def spin(ms):
    end = time.monotonic() + ms / 1000.0
    while time.monotonic() < end:
        qgs.processEvents()
        time.sleep(0.01)


def node_for(layer):
    return project.layerTreeRoot().findLayer(layer.id())


g = {}

# G1: a burst of extent changes (what one real pan/zoom gesture emits)
before_http, before_vp = stats["http_requests"], stats["viewport_refresh_calls"]
t = time.monotonic()
for i in range(5):
    canvas.setExtent(shifted(base, 0.05 * (i + 1), 0.02 * (i + 1)))
    qgs.processEvents()
spin(1200)
g["G1_burst_of_5_extent_changes"] = {
    "seconds": round(time.monotonic() - t, 3),
    "http_requests": stats["http_requests"] - before_http,
    "viewport_refreshes": stats["viewport_refresh_calls"] - before_vp,
}

# G2: switch both viewport layers ON -> they must fetch on demand
for lyr in (plugin.towers_layer, plugin.cellular_layer):
    n = node_for(lyr)
    if n is not None:
        n.setItemVisibilityChecked(True)
before_http, before_vp = stats["http_requests"], stats["viewport_refresh_calls"]
t = time.monotonic()
spin(2500)
g["G2_layers_switched_on"] = {
    "seconds": round(time.monotonic() - t, 3),
    "http_requests": stats["http_requests"] - before_http,
    "viewport_refreshes": stats["viewport_refresh_calls"] - before_vp,
    "towers_features": plugin.towers_layer.featureCount(),
    "cellular_features": plugin.cellular_layer.featureCount(),
}

# G3: same extent again -> must not refetch
before_http = stats["http_requests"]
t = time.monotonic()
canvas.setExtent(canvas.extent())
qgs.processEvents()
spin(1200)
g["G3_same_extent_again"] = {
    "seconds": round(time.monotonic() - t, 3),
    "http_requests": stats["http_requests"] - before_http,
}

# G4: a real pan with the layers visible
before_http = stats["http_requests"]
t = time.monotonic()
canvas.setExtent(shifted(canvas.extent(), 0.3, 0.0))
qgs.processEvents()
spin(3000)
g["G4_pan_with_layers_visible"] = {
    "seconds": round(time.monotonic() - t, 3),
    "http_requests": stats["http_requests"] - before_http,
}
# G5: pan back to an extent already fetched -> must be served from cache
visible_extent = QgsRectangle(canvas.extent())
before_http = stats["http_requests"]
t = time.monotonic()
canvas.setExtent(shifted(visible_extent, 0.6, 0.0))  # away, to a fresh extent
qgs.processEvents()
spin(3000)
g["G5_pan_away_fresh_extent"] = {
    "seconds": round(time.monotonic() - t, 3),
    "http_requests": stats["http_requests"] - before_http,
}

before_http = stats["http_requests"]
t = time.monotonic()
canvas.setExtent(visible_extent)  # back to the previously fetched extent
qgs.processEvents()
spin(3000)
g["G6_pan_back_cached_extent"] = {
    "seconds": round(time.monotonic() - t, 3),
    "http_requests": stats["http_requests"] - before_http,
    "cache_entries": len(plugin._viewport_cache),
}
timings["G_behaviour"] = g

timings["phases"] = {k: (round(v, 3) if isinstance(v, float) else v) for k, v in _phase.items()}
timings["stats_total"] = stats
timings["stats_during_load"] = load_stats

print(json.dumps(timings, indent=2))
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), f"bench_{LABEL}.json"), "w") as f:
    json.dump(timings, f, indent=2)

qgs.exitQgis()
