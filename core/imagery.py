"""USA base imagery and topographic map (USGS), off by default.

Both sources are the U.S. Geological Survey's The National Map tile services. They were chosen because they are the
only keyless US imagery/basemap services whose terms are clear: USGS-authored data is public domain and USGS asks for
credit (https://www.usgs.gov/information-policies-and-instructions/copyrights-and-credits). Each tile endpoint was
fetched live for Dallas, Anchorage and Toronto before this was written (HTTP 200 JPEG inside the United States, zoom
0-16; outside the US the service answers with a blank placeholder tile and above zoom 16 with HTTP 404), so the layer
is declared as US-only with a maximum zoom of 16 and QGIS over-zooms the last level.

Deliberately NOT included, pending an owner licensing decision: Esri World Imagery (the tile URL answers, but its
terms for a third-party product are not settled), and EOX Sentinel-2 cloudless (non-commercial licence).

The layers are plain XYZ raster layers: nothing is requested while a layer is switched off.
"""

from __future__ import annotations

USGS_TILE_BASE = "https://basemap.nationalmap.gov/arcgis/rest/services/{service}/MapServer/tile/{{z}}/{{y}}/{{x}}"
IMAGERY_MAX_ZOOM = 16
USGS_ATTRIBUTION = "Imagery: USDA, USGS The National Map (public domain; credit requested)."

# key, display name, ArcGIS service, abstract
IMAGERY_SOURCES = (
    ("imagery_usgs_aerial", "USA aerial imagery (USGS, US only)", "USGSImageryOnly",
     "USGS The National Map orthoimagery (aerial and satellite photography, mostly USDA NAIP). United States only: "
     "outside the US the service returns a blank tile. Zoom 0-16. Off by default: nothing is requested until you switch the layer on. " + USGS_ATTRIBUTION),
    ("imagery_usgs_topo", "USA topographic map (USGS, US only)", "USGSTopo",
     "USGS US Topo basemap (roads, contours, hydrography, place names). United States only: outside the US the "
     "service returns a blank tile. Zoom 0-16. Off by default: nothing is requested until you switch the layer on. " + USGS_ATTRIBUTION),
)


def tile_uri(service: str) -> str:
    url = USGS_TILE_BASE.format(service=service).replace("{z}", "%7Bz%7D").replace("{x}", "%7Bx%7D").replace("{y}", "%7By%7D")
    return f"type=xyz&url={url}&zmax={IMAGERY_MAX_ZOOM}&zmin=0"


def build_imagery_layer(name: str, service: str, abstract: str):
    from qgis.core import QgsRasterLayer
    layer = QgsRasterLayer(tile_uri(service), name, "wms")
    layer.setAttribution(USGS_ATTRIBUTION)
    metadata = layer.metadata()          # QgsMapLayer.setAbstract() is deprecated; metadata is what Layer Properties shows
    metadata.setTitle(name)
    metadata.setAbstract(abstract)
    layer.setMetadata(metadata)
    return layer
