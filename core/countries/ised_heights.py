"""Antenna heights from ISED's raw Fixed Service extract (``TAFL_LTAF_Fixe.csv``), read BY COLUMN POSITION. Pure stdlib -- runs without QGIS.

CITATION (verified by the QGIS workstream, 2026-10-09; not only taken from the Map's note): ISED, "Spectrum Management System (SMS) Authorization Data Extract
- Field Descriptions", https://ised-isde.canada.ca/site/spectrum-management-system/sites/default/files/attachments/2022/tafl_description_ltaf.pdf
(21 pages, file sha256 8ee1ef262e44e512b8fb914a4b292575cdb442acc5a207a9422ad54f45c6ab5c; the same 61-column table covers all seven service files).
Its column table lists: 1 Station function (TX/RX) · 2 Frequency [MHz] · 29 **Height above ground level [m]** · 41 Latitude (WGS84) · 42 Longitude (WGS84) ·
43 Ground elevation above mean sea level [m] · 44 Antenna structure height above ground level [m] · 48 Authorization number. NOT stated by the
document: whether the
height is to the antenna centre or tip, and what several values at one endpoint mean (UNKNOWN).

The CSV has NO header row, so a column shift would be silent. Every row is therefore checked against the documented layout (61 columns; column 1 is TX or RX;
2, 41, 42 numeric; 29 empty or numeric); a violation raises ``PackCorruptError`` naming the row, never a shifted read.

The plugin ships NO heights by default. ``tools/build_ca_heights.py`` turns the raw file into a small sidecar (``velorona.ca-heights/1``) that
``CanadaProvider`` uses when it is present; with it, a Canadian link record carries ``site_a_height_m`` / ``site_b_height_m`` / ``height_source`` and
the existing
record-height channel (core/record_source.py) types them Observed while unchanged, Assumed once overridden.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
import zipfile
from typing import Dict, Optional, Tuple

from .base import PackCorruptError, PackMissingError, PackVersionError

COLUMNS = 61
COL_FUNCTION, COL_FREQ, COL_HEIGHT, COL_LAT, COL_LON, COL_AUTH = 1, 2, 29, 41, 42, 48     # 1-based, as in the ISED document
HEIGHT_RANGE_M = (0.1, 1000.0)    # CARRIED OVER: core/validation.py HEIGHT_M (terrain.PARAM_SPEC); outside it a height is NO DATA at the analysis boundary
SIDECAR_SCHEMA = "velorona.ca-heights/1"
FIELD_DOC_URL = "https://ised-isde.canada.ca/site/spectrum-management-system/sites/default/files/attachments/2022/tafl_description_ltaf.pdf"
FIELD_DOC_SHA256 = "8ee1ef262e44e512b8fb914a4b292575cdb442acc5a207a9422ad54f45c6ab5c"
RULE = ("per endpoint (authorization x coordinate at 5 decimals): the MINIMUM of the in-range values (0.1-1000 m) in file rows for that endpoint; if none is "
        "in range, the smallest raw value (the analysis then reports NO DATA, nothing is clamped). PROPOSED rule: ISED does not say what several "
        "values mean, and "
        "the lowest antenna is the conservative reading for clearance.")


def _num(text: str) -> Optional[float]:
    try:
        v = float(text)
    except ValueError:
        return None
    return v if math.isfinite(v) else None


def endpoint_key(auth: str, lat: float, lon: float) -> str:
    return f"{auth}|{lat:.5f}|{lon:.5f}"


def _open_rows(path: str):
    if not os.path.isfile(path):
        raise PackMissingError(f"The ISED extract '{path}' does not exist.")
    if path.lower().endswith(".zip"):
        zf = zipfile.ZipFile(path)
        names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
        if len(names) != 1:
            raise PackCorruptError(f"The zip '{path}' must contain exactly one .csv; it has {names}.")
        return io.TextIOWrapper(zf.open(names[0]), encoding="utf-8-sig", errors="replace", newline="")
    return open(path, encoding="utf-8-sig", errors="replace", newline="")


def sha256_of(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build_sidecar(path: str, source_file_updated: str) -> dict:
    """Parse the raw extract by column position into a sidecar dict. Raises PackCorruptError on any row that does not match the documented layout."""
    values: Dict[str, list] = {}
    rows = 0
    for n, row in enumerate(csv.reader(_open_rows(path)), start=1):
        rows = n
        if len(row) != COLUMNS:
            raise PackCorruptError(f"Row {n} of the ISED extract has {len(row)} columns; the documented layout has {COLUMNS}. "
                                   "Refusing to read heights by position.")
        if row[COL_FUNCTION - 1] not in ("TX", "RX"):
            raise PackCorruptError(f"Row {n}: column 1 (Station function) is {row[COL_FUNCTION - 1]!r}, expected TX or RX; the columns look shifted.")
        lat, lon, freq = _num(row[COL_LAT - 1]), _num(row[COL_LON - 1]), _num(row[COL_FREQ - 1])
        if lat is None or lon is None or freq is None or not -90 <= lat <= 90 or not -180 <= lon <= 180:
            raise PackCorruptError(f"Row {n}: columns 2/41/42 (frequency, latitude, longitude) are not valid numbers; the columns look shifted.")
        raw = row[COL_HEIGHT - 1]
        if raw == "":
            continue
        h = _num(raw)
        if h is None:
            raise PackCorruptError(f"Row {n}: column 29 (Height above ground level [m]) is {raw!r}, not a number; the columns look shifted.")
        values.setdefault(endpoint_key(row[COL_AUTH - 1], lat, lon), []).append(h)
    endpoints = {}
    for key, vals in values.items():
        in_range = [v for v in vals if HEIGHT_RANGE_M[0] <= v <= HEIGHT_RANGE_M[1]]
        chosen = min(in_range) if in_range else min(vals)
        endpoints[key] = [chosen, len(set(vals)), bool(in_range)]
    return {
        "schema": SIDECAR_SCHEMA, "rule": RULE,
        "source": {"agency": "ISED Canada", "dataset": "SMS Authorization Data Extract, Fixed Service (TAFL_LTAF_Fixe)", "file": os.path.basename(path),
                   "file_sha256": sha256_of(path), "source_file_updated": source_file_updated, "rows": rows, "columns": COLUMNS},
        "field": {"column": COL_HEIGHT, "name": "Height above ground level [m]", "document_url": FIELD_DOC_URL, "document_sha256": FIELD_DOC_SHA256,
                  "not_stated_by_document": "antenna centre vs tip; meaning of several values at one endpoint"},
        "counts": {"endpoints_with_height": len(endpoints), "endpoints_with_several_values": sum(1 for e in endpoints.values() if e[1] > 1),
                   "endpoints_out_of_range": sum(1 for e in endpoints.values() if not e[2])},
        "endpoints": endpoints,
    }


class HeightIndex:
    def __init__(self, data: dict):
        self.data = data
        self.endpoints = data["endpoints"]
        src = data["source"]
        self.source_text = (f"ISED SMS Authorization Data Extract (Fixed Service), column {data['field']['column']} '{data['field']['name']}', "
                            f"record-reported value, source file dated {src['source_file_updated']}")

    def lookup(self, auth: str, lat: float, lon: float) -> Tuple[Optional[float], str]:
        """(height_m or None, source text). None when the extract has no height for this endpoint.
        The text names the rule when the endpoint has several values."""
        e = self.endpoints.get(endpoint_key(auth, lat, lon))
        if e is None:
            return None, ""
        note = self.source_text + (f"; {e[1]} distinct values at this endpoint, the lowest in-range one is used" if e[1] > 1 else "")
        return float(e[0]), note


def load_sidecar(path: str) -> HeightIndex:
    if not os.path.isfile(path):
        raise PackMissingError(f"The Canadian heights file '{path}' does not exist.")
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        raise PackCorruptError(f"The Canadian heights file '{path}' is not valid JSON ({exc}).") from exc
    if not isinstance(data, dict) or data.get("schema") != SIDECAR_SCHEMA:
        raise PackVersionError(f"'{path}' is not a {SIDECAR_SCHEMA} file (schema {data.get('schema') if isinstance(data, dict) else None!r}).")
    for key in ("source", "field", "endpoints"):
        if not isinstance(data.get(key), dict):
            raise PackCorruptError(f"The Canadian heights file has no '{key}' block.")
    if data["field"].get("column") != COL_HEIGHT or data["source"].get("columns") != COLUMNS:
        raise PackVersionError("The Canadian heights file was built for a different column layout; rebuild it from the raw extract.")
    if not data["source"].get("source_file_updated"):
        raise PackCorruptError("The Canadian heights file does not say which ISED file date it came from; refusing it.")
    for k, e in data["endpoints"].items():
        if not (isinstance(e, list) and len(e) == 3 and isinstance(e[0], (int, float)) and math.isfinite(e[0])):
            raise PackCorruptError(f"The Canadian heights file has an invalid entry for {k!r}.")
    return HeightIndex(data)
