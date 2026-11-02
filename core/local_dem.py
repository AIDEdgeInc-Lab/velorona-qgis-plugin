"""Reads a raster layer the user holds as an elevation provider for the library seam. Needs QGIS (QgsRasterLayer), nothing else.

The sampler runs in a worker thread (analyses run in a QgsTask), so it never touches the live layer: it uses a CLONE of the layer's data
provider and a coordinate transform built on the main thread. Cells without a value (outside the extent, nodata) are returned as None, which
the library turns into an explicit "no elevation" failure; a raster with no usable CRS is refused before a value is read.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from qgis.core import QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsPointXY, QgsProject, QgsRasterLayer

WGS84 = QgsCoordinateReferenceSystem("EPSG:4326")


def candidate_layers(project=None) -> List[Tuple[str, "QgsRasterLayer"]]:
    """[(label, layer)] for every valid single-band raster layer in the project, labelled so two layers with one name stay distinguishable."""
    project = project or QgsProject.instance()
    layers = [layer for layer in project.mapLayers().values()
              if isinstance(layer, QgsRasterLayer) and layer.isValid() and layer.bandCount() == 1]
    layers.sort(key=lambda layer: layer.name().lower())
    seen = {}
    for layer in layers:
        seen[layer.name()] = seen.get(layer.name(), 0) + 1
    out = []
    for layer in layers:
        label = layer.name() if seen[layer.name()] == 1 else f"{layer.name()}  [{layer.id()[-8:]}]"
        out.append((label, layer))
    return out


def not_usable_reason(layer) -> Optional[str]:
    """Why this raster cannot be used as an elevation source, or None."""
    if layer is None or not layer.isValid():
        return "the raster layer is not valid"
    if layer.bandCount() != 1:
        return f"the raster has {layer.bandCount()} bands; an elevation raster has exactly one"
    if not layer.crs().isValid():
        return "the raster has no coordinate reference system, so its cells cannot be placed on the map"
    return None


def make_provider(layer):
    """A ``LocalDEMProvider`` reading ``layer`` (band 1, values taken as metres). Raises ``DEMCrsMismatchError`` / ``ValueError`` with a reason."""
    from aei_link_clearance import DEMCrsMismatchError, LocalDEMProvider

    reason = not_usable_reason(layer)
    if reason:
        raise DEMCrsMismatchError(f"{layer.name() if layer is not None else 'The raster'}: {reason}.")
    data_provider = layer.dataProvider().clone()          # thread-safe copy: the worker never touches the live layer
    transform = QgsCoordinateTransform(WGS84, layer.crs(), QgsProject.instance().transformContext())
    extent = layer.extent()

    def sampler(lat: float, lon: float) -> Optional[float]:
        try:
            point = transform.transform(QgsPointXY(lon, lat))
        except Exception:                                  # a point the transform cannot handle has no cell
            return None
        if not extent.contains(point):
            return None
        value, ok = data_provider.sample(point, 1)
        return float(value) if ok else None

    return LocalDEMProvider(sampler, layer.source() and _basename(layer.source()) or layer.name(), dem_crs=layer.crs().authid() or "unknown", sampler_reprojects=True)


def _basename(source: str) -> str:
    # layer.source() can be a path, a URI with options ("file.tif|layername=..") or a URL; keep the readable tail only
    tail = source.replace("\\", "/").split("|", 1)[0].rstrip("/").rsplit("/", 1)[-1]
    return tail or source
