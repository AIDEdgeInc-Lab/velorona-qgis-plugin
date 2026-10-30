"""Evidence export for ONE link study: every analysis of the same link in this session, in one CSV laid out like Velorona Map's evidence
file (web/workflow.js allSessionEvidenceCsv): a "# " preamble (title, analyses, product/convention lines, data sources, generated time, type
key), then the column "Analysis" followed by the six evidence columns. The rows are the plugin's own per-result evidence rows
(core/export.result_to_csv), so a study says exactly what each single export says.

Rules (same as the Map's file):
* sources, types, times and units come with every row; data limits are stated in the preamble (record nature, pack, pack verification);
* no stored history: "What changed" and the History store are never read here;
* the user's own site and link names are left out unless the user ticks "Include my site names": they become "Site A" / "Site B" / "Link".
  A name from a public register (an ISED/FCC record) is public data and stays. Weather exposure run on two selected sites is treated as the
  user's own (the same rule the History store applies), because the result does not carry where its sites came from.
"""

from __future__ import annotations

import csv
import io
import re
from datetime import datetime, timezone
from typing import Iterable, List, Optional, Tuple

from . import csvsafe, packs
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
PUBLIC_SOURCE_MARKERS = ("ISED", "FCC")       # site sources that are public registers (core/sources, core/countries)


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


def _private_names(result) -> List[Tuple[str, str]]:
    """[(name, replacement)] for names the user supplied in this result."""
    kind = result.kind
    out = []
    if kind == "terrestrial":
        for name, source, label in ((result.site_a_name, result.site_a_source, "Site A"), (result.site_b_name, result.site_b_source, "Site B")):
            if name and not any(m in str(source or "") for m in PUBLIC_SOURCE_MARKERS):
                out.append((str(name), label))
    elif kind == "microwave-exposure":
        link = result.exposure.link
        for site, label in ((link.site_a, "Site A"), (link.site_b, "Site B")):
            for value in (site.name, site.id):
                if value:
                    out.append((str(value), label))
        for sid in (result.representativeness or {}):
            out.append((str(sid), "Site A" if sid.startswith(str(link.site_a.id)) else "Site B"))
        for value in (getattr(link, "name", None), getattr(link, "id", None)):
            if value:
                out.append((str(value), "Link"))
    # longest first, so "Tower 12" is replaced before "Tower 1"; one-character values are never replaced (too likely to hit other text)
    return sorted({(n, r) for n, r in out if len(n) > 1}, key=lambda p: -len(p[0]))


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
    replace = [] if include_names else [p for r in results for p in _private_names(r)]

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
