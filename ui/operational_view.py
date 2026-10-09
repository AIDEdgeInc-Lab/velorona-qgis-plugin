"""Summary and Details views for the results dock, rendered from a Brief.

Three levels of disclosure, one object behind all of them:

    Summary   what a technician reads in seconds: status, why, the few numbers
              that matter each next to what they are compared with, what to check
    Details   what a planner needs: every contextualised value, where the weather
              came from and why, what changed, the evidence and its caveats
    Evidence  the original Observed / Calculated / Inferred report (results_dock)

Pure HTML strings; no Qt here, so it is testable without QGIS. Charts are
referenced by name and supplied separately (ui/charts.py).
"""

from __future__ import annotations

import html
from typing import List, Tuple

from ..core.presentation.terrain import CRITICAL_POINT_DEFINITION
from ..core.presentation.weather import SELECTION_STATION
from ..core.presentation.model import AT_RISK, CLEAR, CRITICAL, NO_DATA, NOT_DETERMINED, WATCH, Brief, fmt
from . import theme

STATUS_COLORS = {
    CLEAR: theme.CLEAR, WATCH: theme.MARGINAL, AT_RISK: "#E2803B", CRITICAL: theme.OBSTRUCTED, NO_DATA: theme.TEXT_FAINT,
}

CHART_PREFIX = "velorona-chart://"


def _e(value) -> str:
    return html.escape(str(value)) if value is not None else ""


def status_badge(status: str) -> str:
    return f"<span class='pill' style='color:{STATUS_COLORS.get(status, theme.TEXT)}; font-size:15px'>{_e(status)}</span>"


def _facts_table(facts) -> str:
    rows = []
    for f in facts:
        extra = ""
        if f.comparison:
            extra += f"<div class='note'>{_e(f.comparison)}</div>"
        if f.meaning:
            extra += f"<div class='note'>{_e(f.meaning)}</div>"
        rows.append(f"<tr><td class='fk'>{_e(f.label)}</td><td><b>{_e(f.value)}</b>{extra}</td></tr>")
    return f"<table cellpadding='3'>{''.join(rows)}</table>" if rows else ""


def _section(label: str, body: str) -> str:
    return f"<div class='sec'>{_e(label)}</div>{body}" if body else ""


def _group_changes(changes):
    """[(baseline, rows_html)] in first-seen order. Each baseline ("vs 1 hour ago") gets its own table so
    comparisons against different baselines are never interleaved; a change with no baseline is kept
    under an explicit "not determined" group rather than attached to another baseline."""
    groups: dict = {}
    for c in changes:
        label = (c.baseline or "").strip()
        period = f"{_e(c.previous_time)} \u2192 {_e(c.current_time)}"
        groups.setdefault(label, []).append(
            f"<tr><td class='fk'>{_e(c.label)}</td><td><b>{_e(fmt(c.current, c.decimals))} {_e(c.unit)}</b> "
            f"&nbsp;{_e(c.delta_text)} <span class='note'>({period})</span></td></tr>")
    return [(label, "".join(rows)) for label, rows in groups.items()]


def _changes_block(brief: Brief) -> str:
    if not brief.changes:
        return ""
    site = brief.data.get("driver_site", "")
    tables = "".join(
        f"<div class='sub'>{_e(baseline or NOT_DETERMINED)}</div>"
        f"<table cellpadding='3'>{rows}</table>"
        for baseline, rows in _group_changes(brief.changes))
    return (f"{tables}<p class='caveat'>Model-derived hourly values (Open-Meteo weather model) at {_e(site)}, not station observations. "
            f"Hourly values are compared with hourly values, so they can differ from the current reading above.</p>")


def _header(brief: Brief) -> str:
    # The reason line already says why the status is NO DATA; the badge is the status itself.
    return (f"<div class='kicker'>{_e(brief.title)}</div>"
            f"<h3>{_e(brief.heading or brief.location)}</h3>"
            f"<p>{status_badge(brief.status)} &nbsp;{_e(brief.reason)}</p>")


def _answer_line(brief: Brief) -> str:
    """The plain-language answer. For NO DATA it only restated the reason ("No answer: there is no ... data"),
    so the reason stays and the answer is dropped; every other status keeps its answer."""
    if brief.status == NO_DATA:
        return ""
    return f"<p><b>{_e(brief.answer)}</b></p>"


def render_summary(brief: Brief) -> Tuple[str, List[str]]:
    """(html, chart names needed)."""
    charts: List[str] = []
    parts = [_header(brief), _answer_line(brief), _section("The numbers", _facts_table(brief.key_facts))]
    if brief.changes:
        parts.append(_section("What changed", _changes_block(brief)))
        if brief.data.get("history"):
            charts.append("rain")
            parts.append(f"<p class='note'>Is rain getting worse?</p><img src='{CHART_PREFIX}rain'>")
    elif brief.kind == "terrain" and brief.data.get("samples"):
        charts.append("clearance")
        parts.append("<div class='sec'>Where is the tightest point?</div>"
                     f"<img src='{CHART_PREFIX}clearance'>"
                     f"<p class='caveat'>{_e(CRITICAL_POINT_DEFINITION)}</p>")
    if brief.inspect:
        parts.append(_section("What to inspect", f"<p>{_e(brief.inspect)}</p>"))
    if brief.evidence:
        first = brief.evidence[:2]
        parts.append(_section("Evidence", "".join(f"<p class='src'>{_e(f.label)}: {_e(f.value)}</p>" for f in first)))
    if brief.caveats:
        parts.append("".join(f"<p class='caveat'>{_e(c)}</p>" for c in brief.caveats[:2]))
    parts.append("<p class='caveat'>Switch to Details for the engineering values, or Evidence for the full "
                 "Observed / Calculated / Inferred record.</p>")
    return "".join(parts), charts


def _site_block(s) -> str:
    rows = [
        ("Weather source", s.source, s.kind),
        ("Model value time", s.timestamp, ""),
        ("Why this record", s.selection, ""),
    ]
    if s.temperature_c is not None:
        rows.append(("Temperature", f"{fmt(s.temperature_c)} °C", ""))
    if s.wind_kmh is not None:
        rows.append(("Wind", f"{fmt(s.wind_kmh)} km/h", ""))
    if s.rain_mm_h is not None:
        rows.append(("Rain rate (model-derived)", f"{fmt(s.rain_mm_h)} mm/h", s.precip_basis))
    if s.precip_total_mm_h is not None and abs(s.precip_total_mm_h - (s.rain_mm_h or 0.0)) > 0.005:
        rows.append(("Total precipitation (model)", f"{fmt(s.precip_total_mm_h, 2)} mm/h", "not all of it is liquid rain; only the rain part is used"))
    if s.station_name:
        rows.append(("Nearest station", s.station_name,
                     f"{fmt(s.station_distance_km)} km from {s.site_label}"
                     + (f", at {s.station_point[0]:.4f}, {s.station_point[1]:.4f}" if s.station_point else "")))
        rows.append(("Why this station", SELECTION_STATION, ""))
        rows.append(("Station observation", s.station_time or NOT_DETERMINED, ""))
        rows.append(("Station rain", f"{fmt(s.station_rain_mm_h)} mm/h" if s.station_reports_rain else NOT_DETERMINED,
                     "" if s.station_reports_rain else "this station does not publish precipitation"))
    else:
        rows.append(("Nearest station", NOT_DETERMINED, "no station reported in range"))
    if s.radar_rain_mm_h is not None:
        rows.append(("Radar rain (estimated)", f"{fmt(s.radar_rain_mm_h)} mm/h", "radar-estimated, not gauge-measured"))
    rows.append(("Do the sources agree?", s.representativeness, s.representativeness_note))
    from ..core.presentation.model import Fact
    coords = (f"{s.site_point[0]:.5f}, {s.site_point[1]:.5f}" if s.site_point else "")
    where = f"<span class='coord'> &nbsp;&middot;&nbsp; {_e(coords)}</span>" if coords else ""
    return (f"<div class='site'>{_e(s.site_label)}{where}</div>"
            + _facts_table([Fact(a, b, c) for a, b, c in rows]))


def render_details(brief: Brief) -> Tuple[str, List[str]]:
    charts: List[str] = []
    parts = [_header(brief), _section("Values and what they mean", _facts_table(brief.key_facts))]
    if brief.kind == "terrain":
        charts.append("clearance")
        parts.append("<div class='sec'>Clearance along the path</div>"
                     "<p class='note'>Solid: clearance available. Dashed: clearance required. "
                     "The ring marks the critical point.</p>"
                     f"<img src='{CHART_PREFIX}clearance'>"
                     f"<p class='caveat'>{_e(CRITICAL_POINT_DEFINITION)}</p>")
    if brief.sites:
        parts.append("<div class='sec'>Where the weather came from</div>")
        parts.extend(_site_block(s) for s in brief.sites)
    if brief.changes:
        parts.append(_section("What changed", _changes_block(brief)))
        charts += ["rain", "temperature", "wind"]
        parts.append("<div class='sec'>Last hours at the driving site (model-derived)</div>"
                     + "".join(f"<p class='note'>{label}</p><img src='{CHART_PREFIX}{name}'>"
                               for name, label in (("rain", "Rain (mm/h) — is it getting worse?"),
                                                   ("temperature", "Temperature (°C)"),
                                                   ("wind", "Wind (km/h)"))))
    parts.append(_section("Engineering detail", _facts_table(brief.technical)))
    parts.append(_section("Evidence and sources", _facts_table(brief.evidence)))
    if brief.caveats:
        parts.append(_section("Limits of this result", "".join(f"<p class='caveat'>{_e(c)}</p>" for c in brief.caveats)))
    return "".join(parts), charts


def render_answer(text: str) -> str:
    """An Ask answer: plain text, line breaks kept, bullet lines indented."""
    return "<br>".join(_e(line) for line in text.splitlines())

