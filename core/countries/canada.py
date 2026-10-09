"""Canada provider: the ISED Fixed Service snapshot bundled with the plugin. A thin, behaviour-preserving wrapper over
``terrestrial_public.load_fixed_service_snapshot``. Imports it lazily because that module imports QGIS.

The snapshot is the Velorona Map workstream's file, byte-identical (schema velorona.ca-ised-fixed/1.1, sha256 pinned in tests/test_bundled_snapshot.py):
24,859 sites / 16,956 links, loaded whole at start. From /1.1 each link may carry the endpoints' record antenna heights (ISED column 29, "Height above ground
level [m]"; contract: parity/contract/HEIGHTS_CONTRACT.md). The column-position check lives in the Map's builder (fail-closed on every build); QGIS reads the
finished snapshot and does not parse the raw CSV."""

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
        return LoadResult(sites=sites, links=links, attribution=None, tiles_requested=0,
                          heights_attached=sum(1 for lk in links if lk.get("site_a_height_m") is not None or lk.get("site_b_height_m") is not None))
