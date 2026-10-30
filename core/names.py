"""The user's own site and link names in exports: left out unless the user ticks "Include my site names"; public register names stay.

A name is public when its site comes from a public register (core/public_sources.py: a layer Velorona created from a pack or another public
dataset, or a Fixed Service record). Everything else (a site from the user's own layer) is the user's own and becomes "Site A" / "Site B" /
"Link". Weather exposure on two public sites keeps their names, like terrain clearance does."""

from __future__ import annotations

import csv
import dataclasses
import io
from typing import List, Tuple

from . import csvsafe, public_sources


def private_names(result) -> List[Tuple[str, str]]:
    """[(name, replacement)], longest first, for the names the user supplied in ``result``."""
    kind = getattr(result, "kind", "")
    out = []
    if kind == "terrestrial":
        for name, public, label in ((result.site_a_name, getattr(result, "site_a_public", False), "Site A"),
                                    (result.site_b_name, getattr(result, "site_b_public", False), "Site B")):
            if name and not public:
                out.append((str(name), label))
    elif kind == "microwave-exposure":
        link = result.exposure.link
        private_any = False
        for site, label in ((link.site_a, "Site A"), (link.site_b, "Site B")):
            if public_sources.is_public(getattr(site, "source", "")):
                continue
            private_any = True
            out += [(str(v), label) for v in (site.name, site.id) if v]
            out += [(str(sid), label) for sid in (result.representativeness or {}) if str(sid).startswith(str(site.id))]
        if private_any:
            out += [(str(v), "Link") for v in (getattr(link, "name", None), getattr(link, "id", None)) if v]
    # one-character values are never replaced (too likely to hit other text)
    return sorted({(n, r) for n, r in out if len(n) > 1}, key=lambda p: -len(p[0]))


def has_private_names(result) -> bool:
    return bool(private_names(result))


def replace_in(text, pairs) -> str:
    text = "" if text is None else str(text)
    for name, label in pairs:
        text = text.replace(name, label)
    return text


def rewrite_csv(raw: str, pairs) -> str:
    """``raw``: a plugin export written WITHOUT the formula guard (csvsafe.disabled). Returns it with the names replaced in the preamble and in
    every cell, the table written again WITH the guard, so the guard sees the final text."""
    pre, body = [], []
    for line in raw.splitlines():
        (pre if line.startswith("#") and not body else body).append(line)
    out = io.StringIO()
    for line in pre:
        out.write(replace_in(line, pairs) + "\n")
    writer = csvsafe.writer(out)
    for row in csv.reader(io.StringIO("\n".join(body))):
        writer.writerow([replace_in(c, pairs) for c in row])
    return out.getvalue()


def redact_sheets(sheets, pairs) -> None:
    """Replaces the names in every text cell of workbook sheets (core/presentation/xlsx.py Sheet/Cell), in place."""
    for sheet in sheets:
        for row in sheet.rows:
            for i, cell in enumerate(row):
                if isinstance(cell, str):
                    row[i] = replace_in(cell, pairs)
                elif isinstance(getattr(cell, "value", None), str):
                    row[i] = dataclasses.replace(cell, value=replace_in(cell.value, pairs))     # Cell is frozen
