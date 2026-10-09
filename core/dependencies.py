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
    ("aei_mw_exposure", "aei-microwave-link-exposure>=0.2.0,<0.3"),
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
MW_DIST = "aei-microwave-link-exposure"
MW_REQUIREMENT = "aei-microwave-link-exposure>=0.2.0,<0.3"   # 0.2.0 evaluates ITU-R P.838-3; <= 0.1.5 used a table that was wrong in 21 of 24 rows
# (distribution, minimum, exclusive upper bound, pip requirement, why it matters)
RANGES = [
    (LC_DIST, LC_MIN, LC_BELOW, LC_REQUIREMENT, "Terrain clearance will be refused until it is upgraded (older releases get the earth-curvature sign wrong)."),
    (MW_DIST, (0, 2, 0), (0, 3), MW_REQUIREMENT, "Older releases use a rain-coefficient table that differs from ITU-R P.838-3 and understate rain loss, most at 6-10 GHz."),
]


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
    """A start-up WARNING (never a refusal) naming every installed library that is outside its supported range; "" when all are inside, not installed (the
    missing-package path reports that), or their version cannot be read (editable / vendored installs): unknown is not a problem report."""
    parts, fix = [], []
    for dist, low, below, requirement, why in RANGES:
        try:
            version = _metadata.version(dist)
        except _metadata.PackageNotFoundError:
            continue
        v = _version_tuple(version)
        if not v or (low <= v[:3] and v[:2] < below):
            continue
        parts.append(f"{dist} {version} is installed but Velorona needs {requirement}. {why}")
        fix.append(requirement)
    if not parts:
        return ""
    return ("Velorona: " + " ".join(parts) + " In QGIS: Plugins > Python Console, run:  " + console_install_command(fix) + "  then restart QGIS.")


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
