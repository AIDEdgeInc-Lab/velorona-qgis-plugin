"""Third-party packages Velorona needs inside QGIS's Python, and the
message shown when they are missing.

Pure stdlib -- runs without QGIS. Keep REQUIREMENTS in step with
requirements.txt and the README's Requirements section."""

from __future__ import annotations

from importlib import metadata as _metadata
from importlib.util import find_spec

# (import name, pip requirement)
REQUIREMENTS = [
    ("aei_link_clearance", "aei-link-clearance>=0.2.0,<0.3"),
    ("aei_mw_exposure", "aei-microwave-link-exposure>=0.1.4"),
    ("aei_geo_features", "aei-geo-features"),
    ("skyfield", "skyfield"),
]


def _is_installed(import_name: str) -> bool:
    try:
        return find_spec(import_name) is not None
    except (ImportError, ValueError):
        return False


def _shell_quote(requirement: str) -> str:
    """Quote a pip requirement that contains shell metacharacters ('>', '<'), so the copied command works."""
    return f"'{requirement}'" if any(c in requirement for c in "<>") else requirement


def missing_requirements() -> list[str]:
    """pip requirements whose package cannot be found."""
    return [pip for name, pip in REQUIREMENTS if not _is_installed(name)]


LC_DIST = "aei-link-clearance"
LC_MIN, LC_BELOW = (0, 2, 0), (0, 3)
LC_REQUIREMENT = "aei-link-clearance>=0.2.0,<0.3"


def console_install_command(requirements) -> str:
    """The same install, as one line for QGIS's own Python Console (Plugins > Python Console). It uses the pip that ships with QGIS's Python
    and installs into that interpreter, so there is no question which Python is meant (verified on macOS QGIS 4.2.2; other platforms UNKNOWN)."""
    quoted = ", ".join(repr(r) for r in requirements)
    return f"from pip._internal.cli.main import main; main(['install', '-U', {quoted}])"


def _version_tuple(text: str) -> tuple:
    parts = []
    for chunk in text.split("."):
        digits = ""
        for ch in chunk:
            if not ch.isdigit():
                break
            digits += ch
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


def library_range_warning() -> str:
    """A start-up WARNING (never a refusal) when the installed aei-link-clearance is outside the supported range; "" when it is inside, not
    installed (the missing-package path reports that), or its version cannot be read (editable / vendored installs): unknown is not a problem report."""
    try:
        version = _metadata.version(LC_DIST)
    except _metadata.PackageNotFoundError:
        return ""
    v = _version_tuple(version)
    if not v or (LC_MIN <= v[:3] and v[:2] < LC_BELOW):
        return ""
    return (f"Velorona: aei-link-clearance {version} is installed but Velorona needs {LC_REQUIREMENT}. Terrain clearance will be refused until it is "
            f"upgraded (older releases get the earth-curvature sign wrong). In QGIS: Plugins > Python Console, run:  "
            f"{console_install_command([LC_REQUIREMENT])}  then restart QGIS.")


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
        f"`python3 -m pip install {' '.join(_shell_quote(m) for m in missing)}` -- see the README's "
        "Requirements section for the exact interpreter path. Or, in QGIS: Plugins > Python Console, run:  "
        f"{console_install_command(missing)}  -- then restart QGIS."
    )
