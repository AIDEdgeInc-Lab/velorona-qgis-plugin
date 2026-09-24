"""Third-party packages Velorona needs inside QGIS's Python, and the
message shown when they are missing.

Pure stdlib -- runs without QGIS. Keep REQUIREMENTS in step with
requirements.txt and the README's Requirements section."""

from __future__ import annotations

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


def missing_requirements() -> list[str]:
    """pip requirements whose package cannot be found."""
    return [pip for name, pip in REQUIREMENTS if not _is_installed(name)]


def install_message(missing: list[str], detail: str = "") -> str:
    """Plain-text instructions for the QGIS message bar and log."""
    tail = f" ({detail})" if detail else ""
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
