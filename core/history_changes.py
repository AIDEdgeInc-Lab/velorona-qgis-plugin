"""'What changed': the comparison rules are the shared ``aei-history-contract`` (Python reference, ``summarize_changes`` / ``render_text``), not a copy.
This module only adapts the plugin's rows to the contract's plain dicts and adds the timeline's "N hours ago" text, which the contract does not
define. Nothing here decides what counts as a change.

The contract's rules, for reference: values are compared only with the same entity, metric, kind AND source; ``then`` is the stored row nearest to
now - n hours within max(30 min, 25 % of n); "unchanged" means equal at the displayed precision; a missing value is ``no_data``, never 0; the text is
built from fields only.
"""

from __future__ import annotations

from typing import Iterable, List, Optional

from .history_store import HistoryRecord, parse_utc, utc_text

DEFAULT_WINDOWS_H = (1, 3, 6, 24)


def contract():
    """The shared package; raises ``HistoryUnavailable`` (a plain-language ImportError) when it is not installed."""
    try:
        import aei_history_contract
    except ImportError as exc:                                       # pragma: no cover - exercised through history_store.HistoryUnavailable
        from .history_store import HistoryUnavailable
        raise HistoryUnavailable() from exc
    return aei_history_contract


def compute_changes(records: Iterable[HistoryRecord], entity_id: str, now_epoch: float, n_hours: float, entity_label: Optional[str] = None) -> dict:
    """The contract's ChangeSummary for ``entity_id`` over ``n_hours`` (plus ``entity_label`` for the sentences)."""
    if n_hours <= 0:
        raise ValueError("n_hours must be positive")
    c = contract()
    summary = c.summarize_changes([r.to_dict() for r in records if r.entity_id == entity_id], entity_id, utc_text(now_epoch), n_hours)
    summary["entity_label"] = entity_label or entity_id
    return summary


def sentences(summary: dict, label: Optional[str] = None) -> List[str]:
    c = contract()
    return [c.render_text(ch, summary["n_hours"], label or summary["entity_label"]) for ch in summary["changes"]]


def age_text(now_epoch: float, ts: str) -> str:
    """'N hours ago' for the timeline (display only; not part of the contract)."""
    seconds = max(0.0, now_epoch - parse_utc(ts))
    if seconds < 90:
        return "just now"
    if seconds < 3600:
        return f"{round(seconds / 60)} min ago"
    hours = seconds / 3600
    return f"{hours:.0f} h ago" if hours >= 10 else f"{hours:.1f} h ago"
