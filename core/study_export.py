"""Evidence export for ONE link study: every analysis of the same link in this session, in one CSV laid out like Velorona Map's evidence
file (web/workflow.js allSessionEvidenceCsv): a "# " preamble (title, analyses, product/convention lines, data sources, generated time, type
key), then the column "Analysis" followed by the six evidence columns. The rows are the plugin's own per-result evidence rows
(core/export.result_to_csv), so a study says exactly what each single export says.

Rules (same as the Map's file):
* sources, types, times and units come with every row; data limits are stated in the preamble (record nature, pack, pack verification);
* no stored history: "What changed" and the History store are never read here;
* the user's own site and link names are left out unless the user ticks "Include my site names": they become "Site A" / "Site B" / "Link".
  A name from a public register (any pack in packs.json, or another public dataset the plugin loads) is public data and stays, for terrain
  and weather alike (core/names.py, core/public_sources.py).
"""

from __future__ import annotations

import csv
import io
import re
from datetime import datetime, timezone
from typing import Iterable, List, Optional, Tuple

from . import attribution, csvsafe, names, packs
from .evidence_record import identity_lines, source_lines
from .export import EVIDENCE_HEADER, NotExportable, result_to_csv

TITLE = "Velorona QGIS -- link study evidence export"
STUDY_KINDS = ("terrestrial", "microwave-exposure", "link-investigation")
LABELS = {"terrestrial": "Path clearance", "microwave-exposure": "Weather exposure", "link-investigation": "Fixed Service link"}
# Velorona Map's EVIDENCE_TYPE_LEGEND (web/evidence.js), word for word, so the two files explain the types the same way.
TYPE_LEGEND = [
    ("Observed", "a sourced observation, reported by a named data source"),
    ("Model-derived", "a value produced by a weather or other model for this location and time (e.g. Open-Meteo), not a measurement"),
    ("Reference data (DEM)", "read from a fixed public dataset (the Copernicus 90 m surface model), not measured along this path and not a weather model"),
    ("Calculated", "derived by a stated formula from other values"),
    ("Assumed", "used as an assumption: an engine default, or a value you supplied (typed in or in your own CSV) -- not an observation Velorona made from a source"),
    ("Inferred", "a derived interpretation or assessment, never a measurement or an outage claim"),
]
# The user guide's "Data limits" section (Velorona Map web/guide.html#limits), word for word except the terrain line, which also names a local
# raster (QGIS can use one; its resolution is the user's).
DATA_LIMITS = [
    "Terrain. Online, the elevation data is a 90 m surface model (with a local raster: that raster's resolution). It cannot resolve individual "
    "buildings or trees, so a path can look clear or blocked when a single structure decides it. Near a threshold, a 10-15 m difference can change the status.",
    "Weather. The rain rate is a model value for the place and the moment, not a measurement at your site. It describes now, not the next hour.",
    "Records. Licence records show the licensee, which is not always the operator. Positions and heights are as filed.",
    "Your own links. Imported values are Assumed. Velorona has not verified them.",
    "A result is not a survey. It is a planning estimate. It does not replace a field survey or a regulatory filing.",
]
GUIDE_LIMITS_URL = "https://map.velorona.ai/guide#limits"


def _endpoints(result) -> Optional[Tuple[Tuple[float, float], Tuple[float, float]]]:
    kind = getattr(result, "kind", "")
    if kind == "terrestrial" and result.result.profile:
        a, b = result.result.profile[0], result.result.profile[-1]
        return (a.latitude, a.longitude), (b.latitude, b.longitude)
    if kind == "microwave-exposure":
        link = result.exposure.link
        return (link.site_a.latitude, link.site_a.longitude), (link.site_b.latitude, link.site_b.longitude)
    if kind == "link-investigation" and result.entry.site_a_point and result.entry.site_b_point:
        return tuple(result.entry.site_a_point), tuple(result.entry.site_b_point)
    return None


def study_key(result) -> Optional[tuple]:
    """The link a result is about: its two endpoints to 5 decimals (about 1 m), in either order. None for anything that is not a link study."""
    ends = _endpoints(result)
    if ends is None:
        return None
    return tuple(sorted((round(lat, 5), round(lon, 5)) for lat, lon in ends))


def same_study(results: Iterable, current) -> List:
    """The results in ``results`` that are about the same link as ``current``, oldest first, one per kind (the newest of each kind)."""
    key = study_key(current)
    if key is None:
        return []
    newest = {}
    for r in results:
        if getattr(r, "kind", "") in STUDY_KINDS and study_key(r) == key:
            newest[r.kind] = r
    return sorted(newest.values(), key=lambda r: STUDY_KINDS.index(r.kind))


def _subject(result) -> str:
    kind = result.kind
    if kind == "terrestrial":
        return f"{result.site_a_name} <-> {result.site_b_name}"
    if kind == "microwave-exposure":
        link = result.exposure.link
        return f"{link.site_a.name} <-> {link.site_b.name}"
    d = result.entry.data
    return str(d.get("authorization_number") or d.get("id") or "Fixed Service link")


def _rows_of(result) -> Tuple[List[str], List[list]]:
    """(preamble lines, evidence rows) of one result's own export, read back from result_to_csv."""
    with csvsafe.disabled():                     # plain strings here; the study writer applies the formula guard once, at the end
        text = result_to_csv(result)
    pre, body = [], []
    for line in text.splitlines():
        if line.startswith("#"):
            pre.append(line[1:].strip())
        else:
            body.append(line)
    rows = list(csv.reader(io.StringIO("\n".join(body))))
    if rows and rows[0] == EVIDENCE_HEADER:
        rows = rows[1:]
    return [p for p in pre if p], rows


def _data_lines(results) -> List[str]:
    out = []
    for r in results:
        attrs = r.entry.data if r.kind == "link-investigation" else getattr(r, "record", None)
        for line in source_lines(attrs):
            if line not in out:
                out.append(line)
    for pack_id, marker in (("ca-ised-fixed", "ISED"), ("us-fcc-uls-micro", "FCC")):
        if any(marker in line for line in out):
            out.append(f"Pack verification ({pack_id}): {packs.badge(pack_id, None).text.split(': ', 1)[1]}")
    return out


_PLAIN_NUMBER = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")
_NUMBER_WITH_UNIT = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?(?: [A-Za-z\u00b0\u00b5%/]+)+$")


def _formula_risk(piece: str) -> bool:
    t = piece.lstrip(" \t\r\n")
    return t[:1] in ("=", "+", "-", "@") and not _PLAIN_NUMBER.match(t) and not _NUMBER_WITH_UNIT.match(t)


def _comment(text: str) -> str:
    """A "# " preamble line, guarded like the Map's csvCommentLine (web/evidence.js): a line a spreadsheet would split into a formula cell, or
    one with a quote, is written as one quoted cell; line breaks become spaces."""
    line = "# " + re.sub(r"[\r\n]+", " ", text)
    risky = '"' in line or any(_formula_risk(p) for p in line.split(",")[1:])
    return ('"' + line.replace('"', '""') + '"') if risky else line


def study_to_csv(results: List, include_names: bool = False, generated: Optional[str] = None) -> str:
    """One CSV for the link study ``results`` (from same_study). ``include_names`` False (the default) replaces the user's own names."""
    results = [r for r in results if getattr(r, "kind", "") in STUDY_KINDS]
    if not results:
        raise NotExportable("Nothing to export for this link yet: run Terrain Clearance or Weather Exposure on it, or select a Fixed Service link.")
    replace = [] if include_names else sorted({p for r in results for p in names.private_names(r)}, key=lambda p: -len(p[0]))

    def clean(text):
        text = "" if text is None else str(text)
        for name, label in replace:
            text = text.replace(name, label)
        return text

    weather = any(r.kind != "terrestrial" for r in results)
    terrain = any(r.kind == "terrestrial" for r in results)
    lines = [TITLE,
             f"Analyses: {len(results)} (one link: {clean(_subject(results[0]))})",
             *identity_lines(decision=terrain, weather=weather),
             *_data_lines(results),
             *[f"Data credit: {line}" for line in [attribution.text(sorted({p for r in results for p in attribution.open_meteo_parts(r)}, reverse=True))] if line],
             f"Data limits ({GUIDE_LIMITS_URL}):", *[f"  {line}" for line in DATA_LIMITS],
             "Not included: stored history (What changed) and anything not computed in this session.",
             ("Names: your own site and link names are included (you ticked 'Include my site names')." if include_names
              else "Names: your own site and link names are replaced by Site A / Site B / Link. Names from public registers are kept."),
             f"Generated: {generated or datetime.now(timezone.utc).isoformat()}",
             "Type key:", *[f"  {t} = {d}" for t, d in TYPE_LEGEND]]
    buf = io.StringIO()
    for line in lines:
        buf.write(_comment(clean(line)) + "\n")
    buf.write("#\n")
    writer = csvsafe.writer(buf)
    writer.writerow(["Analysis", *EVIDENCE_HEADER])
    for r in results:
        _, rows = _rows_of(r)
        label = f"{LABELS[r.kind]}: {clean(_subject(r))}"
        for row in rows:
            writer.writerow([label, *[clean(c) for c in row]])
    return buf.getvalue()


def study_filename() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%MZ")
    return f"velorona_link_study_{stamp}.csv"
