"""Makes the aei_* libraries importable for the unit tests.

QGIS's Python has them pip-installed; a plain system Python usually does not, so
fall back to the sibling checkouts next to this repo (velorona-repos/aei-*/src).

aei_link_clearance is deliberately NOT in that fallback: the plugin requires the released PyPI package (>=0.2.0,<0.3), and a sibling
directory of that name is the Map repo, not the library. Install it with pip."""
import importlib.util
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

_SIBLINGS = {
    "aei_mw_exposure": "aei-microwave-link-exposure",
    "aei_geo_features": "aei-geo-features",
}
for module, repo in _SIBLINGS.items():
    if importlib.util.find_spec(module) is None:
        candidate = os.path.join(os.path.dirname(_ROOT), repo, "src")
        if os.path.isdir(candidate):
            sys.path.append(candidate)


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def no_real_backoff_sleep(monkeypatch):
    """Provider backoff (core/provider_retry.py) must not make the suite wait; the waits it WOULD have made are recorded for the tests that check them."""
    from core import provider_retry
    waits = []
    monkeypatch.setattr(provider_retry, "_sleep", waits.append)
    return waits
