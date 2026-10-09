"""Identity, version and data-source lines every exported decision carries (canonical decision spec 0.3, section G: "a second reviewer must
be able to recompute the status from the export alone"). Pure stdlib -- runs without QGIS.

These are written as ``# `` preamble lines, which the CSV table readers, the parity harness and the .xlsx EVIDENCE sheet already treat as
provenance above the table, so no table column or row changes.
"""

from __future__ import annotations

import hashlib
import os
from importlib import metadata as importlib_metadata

from . import rain_check
from .record_source import is_fcc

SPEC_VERSION = "0.3"
CURVATURE_CONVENTION = ("bulge-added-to-terrain: the effective-earth bulge (k = 4/3, R = 6371 km) is added to the terrain, i.e. subtracted "
                        "from the geometric clearance")
# Open issue (Velorona Map CCR-2; re-run against the released libraries by the QGIS workstream 2026-10-08, see docs/RAIN_COEFFICIENTS_CAVEAT.md).
# It is a notice on weather results, not a claim that the table is wrong in any specific band; remove it only with the library release that
# resolves owner decision D-4.
RAIN_TABLE_CAVEAT = ("Open issue: the rain-attenuation coefficient table in aei-microwave-link-exposure has NOT been verified against "
                     "ITU-R P.838-3; an independent check (2026-10-08) found rows that differ, which can understate predicted attenuation, "
                     "mostly at 6-10 GHz. 'P.838-3' in this export names the method, not a verified table.")
RAIN_MODEL_CHECKED = ("Rain model: the installed rain-coefficient model reproduced Recommendation ITU-R P.838-3 Table 5 at 6, 10 and 38 GHz (both polarizations, "
                      "within 0.5 %) when this result was made; a spot check, not a validation of the model.")
LIBRARIES = ("aei-link-clearance", "aei-microwave-link-exposure", "aei-geo-features")

_PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Same file as core/sources/terrestrial_public.py FIXED_SERVICE_SNAPSHOT_PATH (that module imports QGIS, this one must not).
FIXED_SERVICE_SNAPSHOT_PATH = os.path.join(_PLUGIN_ROOT, "data", "fixed_service_snapshot.json")
_SNAPSHOT_SHA = {}


def rain_table_notice() -> str:
    """The open-issue notice, only while the installed rain model fails the P.838-3 spot check (core/rain_check.py). "" when it passes or cannot be tested."""
    return RAIN_TABLE_CAVEAT if rain_check.rain_model_matches_p838_3() is False else ""


def product_version() -> str:
    try:
        with open(os.path.join(_PLUGIN_ROOT, "metadata.txt"), encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("version="):
                    return line.split("=", 1)[1].strip()
    except OSError:
        pass
    return "unknown"


def library_versions() -> str:
    out = []
    for name in LIBRARIES:
        try:
            out.append(f"{name} {importlib_metadata.version(name)}")
        except importlib_metadata.PackageNotFoundError:
            out.append(f"{name} (version not found)")
    return "; ".join(out)


def _snapshot_sha256(path: str) -> str:
    if path not in _SNAPSHOT_SHA:
        h = hashlib.sha256()
        try:
            with open(path, "rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(chunk)
            _SNAPSHOT_SHA[path] = h.hexdigest()
        except OSError:
            _SNAPSHOT_SHA[path] = "unavailable"
    return _SNAPSHOT_SHA[path]


def identity_lines(decision: bool = True, weather: bool = False) -> list:
    """Product, spec, library and convention lines. ``decision`` adds the curvature convention (terrain); ``weather`` adds the open rain-table caveat."""
    lines = [f"Product: Velorona for QGIS {product_version()}; decision spec {SPEC_VERSION}",
             f"Libraries: {library_versions()}"]
    if decision:
        lines.append(f"Earth-curvature convention: {CURVATURE_CONVENTION}")
    if weather:
        lines.append(rain_table_notice() or RAIN_MODEL_CHECKED)
    return lines


def source_lines(attrs) -> list:
    """Where the record came from. A US record carries the pack's own attribution text, the source and pack dates, the pack id and
    the statement of what kind of data it is; a Canadian record names its register and the hash of the bundled snapshot."""
    attrs = attrs or {}
    if is_fcc(attrs):
        text = attrs.get("attribution")
        if not text:
            return ["Data source: FCC ULS public access database (microwave); attribution text not available on this record."]
        out = [f"Data source: {text}",
               f"Pack: us-fcc-uls-micro; source file dated {attrs.get('source_file_updated') or 'unknown'}; pack built "
               f"{attrs.get('pack_generated') or 'unknown'}"]
        if attrs.get("pack_input_sha256"):
            out[-1] += f"; input file sha256 {attrs['pack_input_sha256']}"
        out.append("Nature of the data: licensee-reported record data from a public register, not a field measurement; "
                   "antenna heights are not in the record (30 m default, Assumed).")
        return out
    if attrs.get("source"):
        out = [f"Data source: {attrs['source']}"]
        if "ISED" in str(attrs["source"]) and "Fixed Service" in str(attrs["source"]):
            out.append(f"Pack: bundled fixed_service_snapshot.json, sha256 {_snapshot_sha256(FIXED_SERVICE_SNAPSHOT_PATH)}")
        return out
    return []
