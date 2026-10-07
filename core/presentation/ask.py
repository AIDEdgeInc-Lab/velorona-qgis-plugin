"""Ask a question about the current result.

Rule-based, not a language model: a question is matched to one of a fixed set
of intents and answered from the Brief the dock is already showing. Every
answer quotes values that exist in that Brief and names the evidence behind
them; a question outside that set gets an explicit "I can't answer that" and the
list of what can be asked. Nothing is generated, so nothing can be invented.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

from . import history as hist
from .model import CLEAR, NO_DATA, Brief, fmt, signed
from .terrain import CRITICAL_POINT_DEFINITION, margin_phrase
from .weather import SELECTION_STATION, STATION_SEARCH_RADIUS_KM, STATION_WINDOW_MINUTES

_RANK_ORDER = ["CLEAR", "NO DATA", "WATCH", "AT RISK", "CRITICAL"]  # same order as model._RANK

SUGGESTED = [
    "Is this link clear?",
    "What is the main risk?",
    "Why is this marked " + "{status}" + "?",
    "How much clearance do we have?",
    "Where is the critical point?",
    "What changed in the last 2 hours?",
    "Which weather station was used?",
    "Show me the weather history.",
    "What evidence supports this result?",
]


@dataclass
class Answer:
    text: str
    evidence: List[str] = field(default_factory=list)
    matched: str = ""

    def as_text(self) -> str:
        out = self.text
        if self.evidence:
            out += "\n\nEvidence:\n" + "\n".join(f"- {e}" for e in self.evidence)
        return out


@dataclass
class AskContext:
    terrain: Optional[Brief] = None
    weather: Optional[Brief] = None

    def briefs(self) -> List[Brief]:
        return [b for b in (self.terrain, self.weather) if b is not None]


def suggested_questions(ctx: AskContext) -> List[str]:
    status = (ctx.briefs()[0].status if ctx.briefs() else "WATCH")
    questions = []
    for q in SUGGESTED:
        q = q.replace("{status}", status)
        if ctx.terrain is None and any(w in q for w in ("clearance", "critical point")):
            continue
        if ctx.weather is None and any(w in q for w in ("weather", "changed")):
            continue
        questions.append(q)
    return questions


_INTENTS = [
    ("history", r"\b(weather|rain|temperature|wind)\b.*\bhistory\b|\bhistory\b|\btrend"),
    ("changed", r"\bchang|\bworse|\bbetter|\bgetting\b|\bincreas|\bdecreas|\blast \d+ hours?|\bago\b"),
    ("station", r"\bstation|\bwhere .*weather|\bweather (source|data|come)|\bwhich weather|\bsource of (the )?weather"),
    ("why", r"\bwhy\b"),
    ("critical", r"\bcritical\b|\bwhere\b|\btightest|\bworst point|\bobstruct"),
    ("clearance", r"\bhow much\b.*(clearance|margin|room)|\bclearance\b|\bmargin\b"),
    ("risk", r"\brisk\b|\bconcern|\bproblem|\bissue|\bbiggest"),
    ("evidence", r"\bevidence|\bsupport|\bproof|\bbased on|\bsources?\b|\bhow do you know"),
    ("status", r"\bclear\b|\bok\b|\bokay\b|\bfine\b|\bstatus\b|\bworking\b|\bgood\b|\bsafe\b|\bblocked\b"),
]


def ask(question: str, ctx: AskContext) -> Answer:
    q = (question or "").strip().lower()
    if not ctx.briefs():
        return Answer("There is no analysis result to ask about yet. Run an analysis first.")
    if not q:
        return _help(ctx)
    for name, pattern in _INTENTS:
        if re.search(pattern, q):
            handler = _HANDLERS[name]
            answer = handler(q, ctx)
            answer.matched = name
            return answer
    return _help(ctx, "I can only answer from this analysis's own data, and I could not match that question.")


def _help(ctx: AskContext, lead: str = "Ask about this result.") -> Answer:
    return Answer(lead + " For example:\n" + "\n".join(f"- {q}" for q in suggested_questions(ctx)), matched="help")


# ---- handlers ------------------------------------------------------------

def _status(q, ctx) -> Answer:
    lines, evidence = [], []
    briefs = ctx.briefs()
    first = briefs[0]
    if first.status == NO_DATA:
        lead = "UNKNOWN \u2014 NO DATA."
    elif first.status == CLEAR:
        lead = "YES \u2014 CLEAR."
    else:
        lead = f"NOT CLEAR \u2014 {first.status}."
    for b in briefs:
        if len(briefs) > 1 or b.status != first.status:
            lines.append(f"{b.title}: {b.status}. {b.reason}")
        if b.kind == "terrain" and b.status != NO_DATA:
            lines.append(_clearance_sentences(b))
        else:
            lines.append(b.reason if len(briefs) == 1 else "")
            lines += [f"{f.label}: {f.value}" for f in b.key_facts if f.label != "Path"]
        evidence += _short_evidence(b)
    return Answer("\n".join([lead] + [l for l in lines if l]), evidence)


def _clearance_sentences(t: Brief) -> str:
    d = t.data
    return (f"Available terrain clearance is {fmt(d['terrain_clearance_m'])} m"
            + (f" (negative: the terrain is {fmt(-d['terrain_clearance_m'])} m above the line of sight)"
               if d["terrain_clearance_m"] < 0 else "") + ".\n"
            f"Required clearance is {fmt(d['required_clearance_m'])} m.\n"
            f"The margin is {signed(d['margin_m'])} m. "
            f"{margin_phrase(d['terrain_clearance_m'], d['required_clearance_m'])}.")


def _why(q, ctx) -> Answer:
    brief = _pick(q, ctx)
    ev = [f.value for f in brief.evidence[:1]] + [f"{f.label}: {f.value}" for f in brief.key_facts[:3]]
    return Answer(f"{brief.title} is {brief.status}.\n{brief.reason}", ev)


def _clearance(q, ctx) -> Answer:
    t = ctx.terrain
    if t is None:
        return Answer("Terrain clearance is not part of this analysis. Run Terrestrial Path Clearance on two sites.")
    if t.status == NO_DATA:
        return Answer(t.reason)
    return Answer(_clearance_sentences(t), _short_evidence(t))


def _critical(q, ctx) -> Answer:
    t = ctx.terrain
    if t is None:
        return Answer("The critical terrain point is not part of this analysis. Run Terrestrial Path Clearance.")
    d = t.data
    if d.get("critical_distance_from_a_km") is None:
        return Answer(t.reason)
    return Answer(
        f"The tightest point on the path is {fmt(d['critical_distance_from_a_km'])} km from {d['site_a_name']} "
        f"(lat {d['critical_latitude']:.5f}, lon {d['critical_longitude']:.5f}).\n"
        f"Clearance there is {fmt(d['terrain_clearance_m'])} m against {fmt(d['required_clearance_m'])} m required "
        f"({signed(d['margin_m'])} m).",
        [CRITICAL_POINT_DEFINITION] + _short_evidence(t))


def _risk(q, ctx) -> Answer:
    briefs = ctx.briefs()
    top = max(briefs, key=lambda b: _RANK_ORDER.index(b.status))
    if top.status == CLEAR:
        return Answer("No risk is flagged: " + top.reason, _short_evidence(top))
    lead = f"Main concern: {top.title.lower()} is {top.status}. {top.reason}"
    if top.inspect:
        lead += "\n" + top.inspect
    others = [f"{b.title}: {b.status}" for b in briefs if b is not top]
    if others:
        lead += "\nAlso: " + "; ".join(others) + "."
    return Answer(lead, _short_evidence(top))


def _station(q, ctx) -> Answer:
    w = ctx.weather
    if w is None or not w.sites:
        return Answer("Weather is not part of this analysis. Run Microwave Weather Exposure, or select a Fixed Service link.")
    lines, evidence = [], []
    for s in w.sites:
        if s.station_name:
            rain = (f"{fmt(s.station_rain_mm_h)} mm/h" if s.station_reports_rain else "no precipitation reading published")
            lines.append(f"{s.site_label}: station {s.station_name}, {fmt(s.station_distance_km)} km away, "
                         f"observed {s.station_time}, rain {rain}.")
        else:
            lines.append(f"{s.site_label}: no station reported within {STATION_SEARCH_RADIUS_KM:.0f} km "
                         f"in the last {STATION_WINDOW_MINUTES} minutes.")
        lines.append(f"  Rain rate used comes from: {s.source}, {s.timestamp} — {s.kind}.")
        lines.append(f"  Why: {s.selection}" + (f" Station: {_station_selection()}" if s.station_name else ""))
        evidence.append(f"{s.site_label}: {s.representativeness}. {s.representativeness_note}")
    return Answer("\n".join(lines), evidence)


def _station_selection() -> str:
    return SELECTION_STATION


def _hours_in(q: str, default: int) -> int:
    m = re.search(r"(\d+)\s*(?:h|hr|hrs|hour|hours)\b", q)
    if m:
        return max(int(m.group(1)), 1)
    if re.search(r"\bhour\b", q) and not re.search(r"\bhours\b", q):
        return 1
    return default


def _changed(q, ctx) -> Answer:
    w = ctx.weather
    driver_hist = _driver_history(w)
    if w is None or driver_hist is None:
        return Answer("No weather history is available for this result, so I can't say what changed.")
    reach = hist.available_hours(driver_hist)
    hours = _hours_in(q, 2)
    note = ""
    if hours > reach:
        note = f"Only {reach} hours of history were retrieved, so the comparison is limited to that.\n"
        hours = reach
    if hours < 1:
        return Answer("Not enough hourly history was retrieved to compare.")
    cs = hist.changes(driver_hist, hours)
    if not cs:
        return Answer("The history has gaps for these hours, so no comparison is possible.")
    site = w.data["driver_site"]
    lines = [f"{note}At {site} (the site driving the rain rate used), latest hour vs {hours} hour{'s' if hours != 1 else ''} earlier:"]
    lines += [f"- {c.label}: {c.text}" for c in cs]
    rain = next((c for c in cs if c.variable == "rain"), None)
    if rain is not None:
        if rain.direction == "up":
            lines.append("Hourly rain, the only weather driver in this analysis, has increased.")
        elif rain.direction == "down":
            lines.append("Hourly rain, the only weather driver in this analysis, has decreased.")
        else:
            lines.append("Hourly rain, the only weather driver in this analysis, has not changed.")
    cur = driver_hist.latest
    return Answer("\n".join(lines),
                  [f"Model-derived hourly weather (not station observations), {cur.time} vs {cs[0].previous_time}", f"Source: {driver_hist.source}"])


def _history(q, ctx) -> Answer:
    w = ctx.weather
    h = _driver_history(w)
    if w is None or h is None:
        return Answer("No weather history is available for this result.")
    rows = [f"{p.time}  rain {_v(p.rain_mm_h)} mm/h  temp {_v(p.temperature_c)} °C  wind {_v(p.wind_kmh)} km/h"
            for p in h.points]
    return Answer(f"Model-derived hourly weather at {w.data['driver_site']} (Open-Meteo, not station observations; last {len(h.points)} hours):\n" + "\n".join(rows),
                  [f"Source: {h.source}", f"Time zone: {h.timezone}"])


def _evidence(q, ctx) -> Answer:
    lines = []
    for b in ctx.briefs():
        lines.append(f"{b.title} ({b.status}):")
        lines += [f"- {f.label}: {f.value}" + (f" ({f.comparison})" if f.comparison else "") for f in b.evidence]
    return Answer("\n".join(lines))


_HANDLERS = {
    "history": _history, "changed": _changed, "station": _station, "why": _why, "critical": _critical,
    "clearance": _clearance, "risk": _risk, "evidence": _evidence, "status": _status,
}


# ---- helpers -------------------------------------------------------------

def _v(x) -> str:
    return "n/a" if x is None else fmt(x)


def _driver_history(w: Optional[Brief]):
    if w is None:
        return None
    return (w.data.get("history") or {}).get(w.data.get("driver_site_id"))


def _pick(q: str, ctx: AskContext) -> Brief:
    if ctx.weather is not None and re.search(r"weather|rain|watch|exposure|fade", q) and ctx.terrain is None:
        return ctx.weather
    if ctx.terrain is not None and ctx.weather is not None and re.search(r"weather|rain|fade|exposure", q):
        return ctx.weather
    return ctx.briefs()[0]


def _short_evidence(b: Brief) -> List[str]:
    return [f"{f.label}: {f.value}" for f in b.evidence[:2]]
