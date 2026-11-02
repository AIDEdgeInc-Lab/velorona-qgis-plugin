"""HTML for the History surfaces, built from stored records (pure Python, escaped, testable without Qt).

UI_AUDIT rhythm: values as ``Value | Unit | Source | As of`` with the freshness facts on every number; observed and model-derived (and forecast,
if ever stored) are shown in SEPARATE sections and never merged; 'History' means locally stored values only."""

from __future__ import annotations

import html
from typing import Dict, Iterable, List, Optional

from . import history_changes as C
from .history_store import HistoryRecord, parse_utc

KIND_TITLES = (("observed", "Observed"), ("model", "Model-derived (the provider's model value for the time shown, not a measurement)"),
               ("forecast", "Forecast"))
WINDOWS_SHOWN_H = (1, 6, 24)
LOCAL_ONLY = "Stored only on this computer. Nothing is uploaded."


def _esc(v) -> str:
    return html.escape(str(v))


def label_for(entity_id: str, known: Optional[Dict[str, str]] = None) -> str:
    """A readable name: the one stored on this computer, else 'Your site/link (h:ab12)' for a hashed entity, else the public id."""
    if known and entity_id in known:
        return known[entity_id]
    if entity_id.startswith("h:"):
        return f"Your link or site ({entity_id[:6]})"
    return entity_id


def _value_text(r: HistoryRecord) -> str:
    if r.value is None:
        return f"NO DATA" + (f" ({_esc(r.nodata_reason)})" if r.nodata_reason else "")
    if isinstance(r.value, str):
        return _esc(r.value)
    return _esc(f"{r.value:.{C.contract().PRECISION.get(r.metric, 1)}f}")


def timeline_html(records: Iterable[HistoryRecord], now: float, known: Optional[Dict[str, str]] = None) -> str:
    """The timeline: one section per kind, newest first, each row ``Value | Unit | Source | As of (UTC) | N hours ago``."""
    records = list(records)
    if not records:
        return empty_html()
    parts: List[str] = []
    for kind, title in KIND_TITLES:
        rows = sorted((r for r in records if r.kind == kind), key=lambda r: r.ts, reverse=True)
        if not rows:
            continue
        body = []
        for r in rows:
            derived = " <span class='note'>(calculated from the values above)</span>" if r.derived else ""
            body.append(
                f"<tr><td>{_esc(label_for(r.entity_id, known))}: {_esc(C.contract().LABELS.get(r.metric, r.metric))}{derived}</td><td><b>{_value_text(r)}</b></td>"
                f"<td>{_esc(r.unit)}</td><td>{_esc(r.source)}</td><td>{_esc(r.ts.replace('T', ' ').replace('Z', ' UTC'))}</td>"
                f"<td>{_esc(C.age_text(now, r.ts))}</td></tr>")
        parts.append(f"<div class='sec'>{_esc(title)}</div><table class='grid'><tr><th>Item</th><th>Value</th><th>Unit</th><th>Source</th><th>As of</th>"
                     f"<th>When</th></tr>{''.join(body)}</table>")
    parts.append(f"<p class='note'>{_esc(LOCAL_ONLY)}</p>")
    return "".join(parts)


def empty_html() -> str:
    return ("<p>No history is stored yet.</p><p class='note'>When you run a weather analysis, the values it fetches are kept here, on this computer, "
            f"for the retention period. {_esc(LOCAL_ONLY)}</p>")


def error_html(message: str) -> str:
    return (f"<p><b>History could not be read.</b></p><p>{_esc(message)}</p><p class='note'>Nothing was changed. Close and reopen this window to try again; "
            "your analyses are not affected.</p>")


def changes_html(records: Iterable[HistoryRecord], entity_labels: Dict[str, str], now: float, windows: Iterable[float] = WINDOWS_SHOWN_H) -> str:
    """The 'What changed' block: for each window, the sentences of every like-with-like pair that has enough history; if a window has none, one line
    saying how much history is stored. ``entity_labels``: {entity_id: name shown}."""
    records = list(records)
    if not records:
        return ""
    lines: List[str] = []
    for n in windows:
        found: List[str] = []
        spans = []
        for entity_id, name in entity_labels.items():
            summary = C.compute_changes(records, entity_id, now, n, entity_label=name)
            for change, text in zip(summary["changes"], C.sentences(summary)):
                if change["result"] == "insufficient_history":
                    spans.append(change.get("available_hours", 0))
                else:
                    found.append(text)
        if found:
            lines.append(f"<div class='sub'>Compared with {n:g} h ago</div>" + "".join(f"<p>{_esc(t)}</p>" for t in found))
        elif spans:
            lines.append(f"<div class='sub'>Compared with {n:g} h ago</div><p class='note'>No stored value is close enough to {n:g} h ago to compare (values are stored over {max(spans):g} h).</p>")
    if not lines:
        return ""
    return "<div class='sec'>What changed</div>" + "".join(lines) + f"<p class='note'>{_esc(LOCAL_ONLY)} Same source and kind compared with same; nothing is estimated between stored values.</p>"
