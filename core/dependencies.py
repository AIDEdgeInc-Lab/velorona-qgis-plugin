"""Third-party packages Velorona needs inside QGIS's Python, and the
message shown when they are missing.

Pure stdlib -- runs without QGIS. Keep REQUIREMENTS in step with
requirements.txt and the README's Requirements section."""

from __future__ import annotations

import os
from importlib.util import find_spec

# (import name, pip requirement)
REQUIREMENTS = [
    ("aei_link_clearance", "aei-link-clearance"),
    ("aei_mw_exposure", "aei-microwave-link-exposure>=0.1.4"),
    ("aei_geo_features", "aei-geo-features"),
    ("skyfield", "skyfield"),
]


def _is_installed(import_name: str) -> bool:
    try:
        return find_spec(import_name) is not None
    except (ImportError, ValueError):
        return False


# The shared workflow/run core. Release zips bundle it (tools/package.sh -> _vendor/), so it is not a pip requirement of a release;
# a source checkout needs it installed from the aei-workflow-runner repository. It is not on PyPI, so it is never suggested to pip.
SHARED_CORE = "aei-workflow-runner"


def _shared_core_present() -> bool:
    vendor = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_vendor", "aei_workflow")
    return os.path.isdir(vendor) or _is_installed("aei_workflow")


def missing_requirements() -> list[str]:
    """pip requirements whose package cannot be found. The shared core is reported as SHARED_CORE when absent."""
    missing = [pip for name, pip in REQUIREMENTS if not _is_installed(name)]
    if not _shared_core_present():
        missing.append(SHARED_CORE)
    return missing


def install_message(missing: list[str], detail: str = "") -> str:
    """Plain-text instructions for the QGIS message bar and log."""
    tail = f" ({detail})" if detail else ""
    if SHARED_CORE in missing:
        pip_missing = [m for m in missing if m != SHARED_CORE]
        extra = (f" Also install with QGIS's Python: `python3 -m pip install {' '.join(pip_missing)}`." if pip_missing else "")
        return ("Velorona could not start: the shared workflow core (aei-workflow-runner) was not found. It is bundled inside "
                "release builds of the plugin, so this looks like a source checkout or a damaged install: reinstall the plugin "
                "from a release zip, or install the package from the aei-workflow-runner repository into QGIS's own Python "
                f"(`python3 -m pip install -e path/to/aei-workflow-runner`).{extra}{tail}")
    if not missing:
        # Every package is importable, so the failure is something else.
        return f"Velorona could not start: an import failed{tail}. It needs " + ", ".join(
            pip for _, pip in REQUIREMENTS
        ) + " in QGIS's own Python environment; check their versions."
    return (
        "Velorona could not start: required Python packages are missing from QGIS's "
        f"own Python environment{tail}. Install them with QGIS's Python, e.g. "
        f"`python3 -m pip install {' '.join(missing)}` -- see the README's "
        "Requirements section for the exact interpreter path -- then restart QGIS."
    )
