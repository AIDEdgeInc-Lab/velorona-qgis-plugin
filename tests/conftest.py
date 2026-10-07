"""Makes the aei_* libraries importable for the unit tests.

QGIS's Python has them pip-installed; a plain system Python usually does not, so
fall back to the sibling checkouts next to this repo (velorona-repos/aei-*/src)."""
import importlib.util
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

_SIBLINGS = {
    "aei_link_clearance": "aei-link-clearance",
    "aei_mw_exposure": "aei-microwave-link-exposure",
    "aei_geo_features": "aei-geo-features",
}
for module, repo in _SIBLINGS.items():
    if importlib.util.find_spec(module) is None:
        candidate = os.path.join(os.path.dirname(_ROOT), repo, "src")
        if os.path.isdir(candidate):
            sys.path.append(candidate)
