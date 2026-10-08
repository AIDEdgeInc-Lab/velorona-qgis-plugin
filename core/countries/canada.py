"""Canada provider: the ISED Fixed Service snapshot bundled with the plugin. A thin, behaviour-preserving wrapper over
``terrestrial_public.load_fixed_service_snapshot`` -- no Canadian logic moved or changed (Canada parity stays byte-for-byte as before).

Unlike the USA pack, the Canadian snapshot IS bundled (13.7 MB, 24,859 sites / 16,956 links) and is loaded whole at start, as it always was.
Imports ``terrestrial_public`` lazily because that module imports QGIS."""

from __future__ import annotations

from .base import LoadResult


class CanadaProvider:
    country = "CA"

    def __init__(self, path=None):
        self.path = path

    def load_all(self) -> LoadResult:
        from ..sources import terrestrial_public
        sites, links = (terrestrial_public.load_fixed_service_snapshot(self.path) if self.path
                        else terrestrial_public.load_fixed_service_snapshot())
        return LoadResult(sites=sites, links=links, attribution=None, tiles_requested=0)
