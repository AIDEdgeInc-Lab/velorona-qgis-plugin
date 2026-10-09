"""Canada provider: the ISED Fixed Service snapshot bundled with the plugin. A thin, behaviour-preserving wrapper over
``terrestrial_public.load_fixed_service_snapshot`` -- no Canadian logic moved or changed (Canada parity stays byte-for-byte as before).

Unlike the USA pack, the Canadian snapshot IS bundled (13.7 MB, 24,859 sites / 16,956 links) and is loaded whole at start, as it always was.
Imports ``terrestrial_public`` lazily because that module imports QGIS.

OPTIONAL record antenna heights (ISED column 29, see ised_heights.py): only when a heights sidecar is found -- ``data/ca_endpoint_heights.json`` in the plugin
or the file named by VELORONA_CA_HEIGHTS. None ships by default, so by default nothing changes: 30 m, Assumed."""

from __future__ import annotations

import os

from . import ised_heights
from .base import LoadResult, PackError

HEIGHTS_ENV = "VELORONA_CA_HEIGHTS"
BUNDLED_HEIGHTS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data", "ca_endpoint_heights.json")


def find_heights_file():
    for candidate in (os.environ.get(HEIGHTS_ENV, "").strip(), BUNDLED_HEIGHTS):
        if candidate and os.path.isfile(candidate):
            return candidate
    return None


class CanadaProvider:
    country = "CA"

    def __init__(self, path=None, heights=None):
        """``heights``: None = look for a sidecar (env / bundled); False = never; a path = that sidecar.
        A sidecar that exists but is invalid raises PackError."""
        self.path = path
        self.heights = heights

    def _height_index(self):
        if self.heights is False:
            return None
        found = self.heights if self.heights else find_heights_file()
        return ised_heights.load_sidecar(found) if found else None

    def load_all(self) -> LoadResult:
        from ..sources import terrestrial_public
        sites, links = (terrestrial_public.load_fixed_service_snapshot(self.path) if self.path
                        else terrestrial_public.load_fixed_service_snapshot())
        result = LoadResult(sites=sites, links=links, attribution=None, tiles_requested=0)
        try:
            index = self._height_index()
        except PackError as exc:           # an OPTIONAL file: say why it was not used, still load the records with the default heights
            result.heights_error = f"Canadian antenna-height file not used: {exc}"
            index = None
        if index is not None:
            result.heights_attached = attach_heights(links, index)
        return result


def attach_heights(links, index) -> int:
    """Adds site_a_height_m / site_b_height_m / height_source to each link whose BOTH endpoints have a record height; returns how many. A link with only
    one known end gets neither (a half-known pair would mix an Observed and a default height under one source line)."""
    n = 0
    for link in links:
        auth = link["authorization_number"]
        ha, na = index.lookup(auth, link["site_a"]["latitude"], link["site_a"]["longitude"])
        hb, nb = index.lookup(auth, link["site_b"]["latitude"], link["site_b"]["longitude"])
        if ha is None or hb is None:
            continue
        link["site_a_height_m"], link["site_b_height_m"] = ha, hb
        link["height_source"] = na if na == nb else f"{na} (end A); {nb} (end B)"
        n += 1
    return n
