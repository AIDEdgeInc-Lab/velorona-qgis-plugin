"""'What changed': deterministic comparison of one entity's stored values now vs N hours ago (CONTRACT section 2). No model, no extrapolation,
no adjectives except the status words. Pure Python; the rules are written so they can be ported to JavaScript and checked with the shared
golden fixtures in tests/fixtures/history_changes_golden.json.

Rules (fixed, versioned with the schema):
1. Like with like: same entity, metric, kind AND source. Never observed against model, never one source against another.
2. 'then' = the stored row nearest to now - n_hours, accepted only within +-max(30 min, 25% of n_hours); otherwise ``insufficient_history``.
3. 'unchanged' = equal at the precision the value is displayed at (PRECISION below), not a physical threshold.
4. Status: changed iff the word differs; both words are reported.
5. A missing (NO DATA) value on either side is ``no_data`` and is never read as zero.
6. The sentence is built from fields only.
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Sequence

from .history_store import HistoryRecord, parse_utc

DEFAULT_WINDOWS_H = (1, 3, 6, 24)
MIN_TOLERANCE_S = 30 * 60
TOLERANCE_FRACTION = 0.25

# Decimal places a value is shown with; two values are 'unchanged' when equal after rounding to it. Rain, temperature and wind are 0.1 (CONTRACT);
# the others follow how the plugin displays them.
PRECISION = {"rain_rate": 1, "temperature": 1, "wind_speed": 1, "snowfall": 1, "rain_attenuation_estimate": 2, "exposure_ratio": 3,
             "clearance_ratio": 2, "weather_code": 0}
LABELS = {"rain_rate": "Rain rate", "temperature": "Temperature", "wind_speed": "Wind speed", "snowfall": "Snowfall", "weather_code": "Weather code",
          "rain_attenuation_estimate": "Estimated rain attenuation", "exposure_ratio": "Exposure ratio", "status": "Status",
          "clearance_ratio": "Clearance ratio"}
KIND_WORDS = {"model": "model-derived", "observed": "observed", "forecast": "forecast"}


def _hhmm(ts: str) -> str:
    return ts[11:16] + " UTC"


def _gap_text(change: dict) -> str:
    """How much earlier the compared value is, from the two stored times (not the requested window): the stored value nearest to the window is
    used, so the text states the real gap and never claims a window it did not use."""
    from .history_store import parse_utc as _p
    hours = (_p(change["now_ts_actual"]) - _p(change["then_ts_actual"])) / 3600
    return f"{hours:.1f} h earlier".replace(".0 h", " h")


def _fmt(metric: str, unit: str, value) -> str:
    if value is None:
        return "no data"
    if isinstance(value, str):
        return value
    places = PRECISION.get(metric, 1)
    return f"{value:.{places}f}" + ("" if unit in ("enum", "ratio", "wmo_code") else f" {unit}")


def compute_changes(records: Iterable[HistoryRecord], entity_id: str, now_epoch: float, n_hours: float, entity_label: Optional[str] = None) -> dict:
    """The ChangeSummary dict of the CONTRACT for ``entity_id`` over ``n_hours``."""
    if n_hours <= 0:
        raise ValueError("n_hours must be positive")
    groups: Dict[tuple, List[HistoryRecord]] = {}
    for r in records:
        if r.entity_id == entity_id and parse_utc(r.ts) <= now_epoch + 600:
            groups.setdefault((r.metric, r.kind, r.source), []).append(r)
    tolerance = max(MIN_TOLERANCE_S, TOLERANCE_FRACTION * n_hours * 3600)
    target = now_epoch - n_hours * 3600
    changes = []
    now_ts_all, then_ts_all = None, None
    for (metric, kind, source), rows in sorted(groups.items()):
        rows.sort(key=lambda r: parse_utc(r.ts))
        now_row = rows[-1]
        candidates = [r for r in rows if r is not now_row]
        then_row = min(candidates, key=lambda r: abs(parse_utc(r.ts) - target)) if candidates else None
        if then_row is not None and abs(parse_utc(then_row.ts) - target) > tolerance:
            then_row = None
        entry = {"metric": metric, "kind": kind, "source": source, "unit": now_row.unit, "then": None if then_row is None else then_row.value,
                 "now": now_row.value, "now_ts_actual": now_row.ts}
        if then_row is None:
            entry["result"] = "insufficient_history"
            entry["history_span_h"] = round((parse_utc(now_row.ts) - parse_utc(rows[0].ts)) / 3600, 1)
        else:
            entry["then_ts_actual"] = then_row.ts
            a, b = then_row.value, now_row.value
            if a is None or b is None:
                entry["result"] = "no_data"
            elif isinstance(a, str) or isinstance(b, str):
                entry["result"] = "unchanged" if a == b else "status_changed"
            else:
                places = PRECISION.get(metric, 1)
                delta = round(b, places) - round(a, places)
                entry["delta"] = round(delta, places)
                entry["result"] = "unchanged" if delta == 0 else "increased" if delta > 0 else "decreased"
        changes.append(entry)
        now_ts_all = max(now_ts_all or now_row.ts, now_row.ts)
        if then_row is not None:
            then_ts_all = min(then_ts_all or then_row.ts, then_row.ts)
    return {"schema": "velorona.change-summary/1", "entity_id": entity_id, "entity_label": entity_label or entity_id,
            "now_ts": now_ts_all, "then_ts": then_ts_all, "n_hours": n_hours, "changes": changes}


def sentence(change: dict, n_hours: float, label: str) -> str:
    """One line from fields only, e.g. 'Rain rate at Site A: 1.2 mm/h now, 0.0 mm/h 5 h ago (model-derived, open-meteo, 14:00 UTC → 19:00 UTC)'."""
    name = LABELS.get(change["metric"], change["metric"])
    kind = KIND_WORDS.get(change["kind"], change["kind"])
    head = f"{name} at {label}"
    if change["result"] == "insufficient_history":
        return (f"{head}: no stored value close enough to {n_hours:g} h ago to compare "
                f"(values stored over {change.get('history_span_h', 0):g} h; {kind}, {change['source']})")
    now_text, then_text = _fmt(change["metric"], change["unit"], change["now"]), _fmt(change["metric"], change["unit"], change["then"])
    tail = f"({kind}, {change['source']}, {_hhmm(change['then_ts_actual'])} → {_hhmm(change['now_ts_actual'])})"
    if change["result"] == "no_data":
        return f"{head}: {now_text} now, {then_text} {_gap_text(change)}; no comparison, a value is missing and is not read as zero {tail}"
    if change["result"] == "unchanged":
        return f"{head}: {now_text} now, unchanged from {_gap_text(change)} at the displayed precision {tail}"
    if change["result"] == "status_changed":
        return f"{head}: {now_text} now, {then_text} {_gap_text(change)} {tail}"
    return f"{head}: {now_text} now, {then_text} {_gap_text(change)} {tail}"


def sentences(summary: dict, label: Optional[str] = None) -> List[str]:
    return [sentence(c, summary["n_hours"], label or summary["entity_label"]) for c in summary["changes"]]


def age_text(now_epoch: float, ts: str) -> str:
    """'N hours ago' for the timeline."""
    seconds = max(0.0, now_epoch - parse_utc(ts))
    if seconds < 90:
        return "just now"
    if seconds < 3600:
        return f"{round(seconds / 60)} min ago"
    hours = seconds / 3600
    return f"{hours:.0f} h ago" if hours >= 10 else f"{hours:.1f} h ago"
