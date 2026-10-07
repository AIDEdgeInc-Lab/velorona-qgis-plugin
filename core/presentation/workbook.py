"""The Excel workbook: one analysis, eight sheets, every number traceable.

    SUMMARY            answer first -- Field | Result | Interpretation
    LINK ANALYSIS      terrain clearance, each value with what it is compared to
    WEATHER            where each site's weather came from and why
    WEATHER HISTORY    hourly series and change vs earlier hours
    ELEVATION-TERRAIN  every sampled point of the path profile
    EVIDENCE           the canonical Observed/Calculated/Inferred table (same
                       rows as the CSV export, read back from it)
    RAW DATA           un-rounded numeric values, with unit, source, calculation id
    DATA DICTIONARY    every field, calculation and status defined

A sheet that does not apply to this analysis says so in one line instead of
being silently empty. Numbers are numeric cells at full precision; the format
only shortens what is displayed.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from typing import List, Optional

from . import registry
from .ask import AskContext
from .model import NOT_DETERMINED, fmt
from .terrain import CRITICAL_POINT_DEFINITION, profile_rows
from .weather import SELECTION_STATION
from .xlsx import FILLS, Cell, Sheet, header, write_workbook

NOT_APPLICABLE = "Not part of this analysis"


def context_for(result) -> Optional[AskContext]:
    """The Briefs for a result object, or None when the kind has none."""
    from .terrain import terrain_brief
    from .weather import exposure_brief
    kind = getattr(result, "kind", None)
    if kind == "terrestrial":
        return AskContext(terrain=terrain_brief(result))
    if kind == "microwave-exposure":
        return AskContext(weather=exposure_brief(result))
    if kind == "link-investigation":
        return AskContext(weather=exposure_brief(result.exposure, result.param_origins, result.weather_error))
    return None


def build_workbook(result, evidence_csv: str, generated_at: Optional[datetime] = None) -> bytes:
    ctx = context_for(result)
    if ctx is None:
        raise ValueError(f"No operational workbook for result kind {getattr(result, 'kind', None)!r}")
    # Readable to the second, with the zone spelled out (not a microsecond ISO string).
    generated = (generated_at or datetime.now(timezone.utc)).strftime("%Y-%m-%d %H:%M:%S UTC")
    sheets = [
        _summary(result, ctx, generated),
        _link_analysis(ctx),
        _weather(ctx),
        _weather_history(ctx),
        _elevation(result, ctx),
        _evidence(evidence_csv),
        _raw(ctx),
        _dictionary(),
    ]
    return write_workbook(sheets)


def _n(value, numfmt: str = "0.0"):
    """A number cell, or an explicit marker when the value is missing."""
    return NOT_DETERMINED if value is None else Cell(value, fmt=numfmt)


def _status_cell(status: str) -> Cell:
    return Cell(status, bold=True, fill=FILLS.get(status))


def _note(name: str, text: str) -> Sheet:
    return Sheet(name, [header("Note"), [f"{NOT_APPLICABLE}. {text}"]], widths=[90])


# ---- SUMMARY -------------------------------------------------------------

def _summary(result, ctx: AskContext, generated: str) -> Sheet:
    rows: List[List] = [
        [Cell("Velorona operational summary", bold=True)],
        ["Generated (UTC)", generated],
        [],
        header("Field", "Result", "Interpretation"),
    ]
    t, w = ctx.terrain, ctx.weather
    if t is not None:
        rows += [
            ["Link", t.location, "Direction of analysis: Site A to Site B"],
            ["Link status", _status_cell(t.status), t.reason],
            ["Plain-language answer", t.answer, ""],
            ["Distance", t.key_facts[0].value, "Link distance"],
            ["Frequency", f"{_g(t.data['frequency_ghz'])} GHz", "Analysis frequency (entered by the user)"],
            ["Required clearance", t.key_facts[2].value, "Minimum required at the tightest point"],
            ["Available clearance", t.key_facts[1].value, "Terrain clearance at the tightest point"],
            ["Clearance margin", t.key_facts[3].value, t.key_facts[3].comparison],
            ["Plain comparison", t.data["explanation"], "Available vs required clearance at the critical point"],
            ["Critical point", f"{fmt(t.data['critical_distance_from_a_km'])} km from {t.data['site_a_name']}"
             if t.data.get("critical_distance_from_a_km") is not None else NOT_DETERMINED,
             "Lowest Fresnel-zone clearance fraction; not necessarily the fewest metres of clearance"],
            ["Terrain evidence", t.evidence[0].value, t.evidence[1].value],
        ]
        if t.inspect:
            rows.append(["What to inspect", t.inspect, ""])
    if w is not None:
        if t is None:
            rows.append(["Link", w.location or NOT_DETERMINED, ""])
        rows += [
            ["Weather status", _status_cell(w.status), w.reason],
            ["Plain-language answer", w.answer, ""],
        ]
        if w.key_facts:
            rows += [
                ["Rain rate used", w.key_facts[0].value, w.key_facts[0].comparison],
                ["Predicted rain fade", w.key_facts[1].value, w.key_facts[1].comparison],
                ["Fade margin remaining", w.key_facts[2].value, w.key_facts[2].meaning],
            ]
        for s in w.sites:
            station = (f"{s.station_name}, {fmt(s.station_distance_km)} km away" if s.station_name
                       else "No station within range")
            rows.append([f"Weather source ({s.site_label})", f"{s.source}, {s.timestamp}",
                         f"{s.kind}. Independent check: {station}. {s.representativeness}."])
        for c in w.changes:
            rows.append([f"{c.label} change", c.text,
                         f"Model-derived hourly values (not station observations), {c.current_time} vs {c.previous_time} (can differ from the current reading)"])
        if w.inspect:
            rows.append(["What to inspect", w.inspect, ""])
    for b in ctx.briefs():
        for cav in b.caveats:
            rows.append(["Caveat", cav, ""])
    rows.append(["Note", "Status wording is Velorona's mapping of the engineering result; see DATA DICTIONARY.", ""])
    return Sheet("SUMMARY", rows, widths=[26, 56, 70], freeze=4)


def _g(value: float) -> str:
    from .model import exact
    return exact(value)


# ---- LINK ANALYSIS -------------------------------------------------------

_TERRAIN_ROWS = [
    ("Path distance", "distance_km", "km", "0.0", "Link length", ""),
    ("Bearing", "bearing_deg", "degrees", "0.0", "Site A to Site B", ""),
    ("Frequency", "frequency_ghz", "GHz", None, "Analysis frequency", "Entered by the user"),
    ("Clearance available", "terrain_clearance_m", "m", "0.0", "Compared with the required clearance", "Terrain clearance at the tightest point"),
    ("Clearance required", "required_clearance_m", "m", "0.0", "60% of the first Fresnel radius", "Minimum required"),
    ("Clearance margin", "margin_m", "m", "+0.0;-0.0;0.0", "Available minus required", "Positive means room to spare"),
    ("First Fresnel radius", "first_fresnel_radius_m", "m", "0.0", "At the tightest point", "Zone that should stay mostly obstacle-free"),
    ("Clearance ratio", "clearance_ratio", "x", "0.00", "Available / required (1 = exactly the minimum)", "Technical detail. Negative means the terrain is above the line of sight."),
    ("Fresnel zone clear at critical point", "percent_fresnel_clear", "fraction", "0.00", "Clear >= 0.60, marginal >= 0.30", "Technical detail"),
    ("Critical point, distance from Site A", "critical_distance_from_a_km", "km", "0.0", "Where the Fresnel-zone clearance fraction is lowest", CRITICAL_POINT_DEFINITION),
    ("Elevation samples", "samples", "count", "0", "Points along the path", "Open-Meteo Elevation API, Copernicus DEM GLO-90"),
]


def _link_analysis(ctx: AskContext) -> Sheet:
    t = ctx.terrain
    if t is None:
        return _note("LINK ANALYSIS", "Terrain clearance was not run. Use Terrestrial Path Clearance on two sites.")
    rows = [header("Item", "Value", "Unit", "Compared with", "Meaning"),
            ["Status", _status_cell(t.status), "", "", t.reason]]
    for label, key, unit, numfmt, compared, meaning in _TERRAIN_ROWS:
        value = t.data.get(key)
        rows.append([label, Cell(value, fmt=numfmt) if value is not None else NOT_DETERMINED, unit, compared, meaning])
    return Sheet("LINK ANALYSIS", rows, widths=[28, 16, 11, 46, 52], freeze=1)


# ---- WEATHER -------------------------------------------------------------

def _weather(ctx: AskContext) -> Sheet:
    w = ctx.weather
    if w is None:
        return _note("WEATHER", "Weather exposure was not run. Use Microwave Weather Exposure, or select a Fixed Service link.")
    if not w.sites:
        return Sheet("WEATHER", [header("Status", "Reason"), [_status_cell(w.status), w.reason]], widths=[14, 90])
    labels = [s.site_label for s in w.sites]
    rows = [header("Item", *labels)]

    def line(label, getter, numfmt=None):
        cells = []
        for s in w.sites:
            v = getter(s)
            cells.append(Cell(v, fmt=numfmt) if isinstance(v, (int, float)) and not isinstance(v, bool)
                         else (NOT_DETERMINED if v in (None, "") else v))
        rows.append([label, *cells])

    line("Site coordinates (lat, lon)", lambda s: f"{s.site_point[0]:.5f}, {s.site_point[1]:.5f}" if s.site_point else None)
    line("Rain-rate source", lambda s: s.source)
    line("Kind of value", lambda s: s.kind)
    line("Model value time", lambda s: s.timestamp)
    line("Why this record", lambda s: s.selection)
    line("Temperature (°C)", lambda s: s.temperature_c, "0.0")
    line("Wind (km/h)", lambda s: s.wind_kmh, "0.0")
    line("Rain rate, model-derived (mm/h)", lambda s: s.rain_mm_h, "0.0")
    line("Precipitation basis", lambda s: s.precip_basis)
    line("Total precipitation, model (mm/h)", lambda s: s.precip_total_mm_h, "0.00")
    line("Nearest station", lambda s: s.station_name)
    line("Why this station", lambda s: SELECTION_STATION if s.station_name else None)
    line("Station coordinates (lat, lon)",
         lambda s: f"{s.station_point[0]:.5f}, {s.station_point[1]:.5f}" if s.station_point else None)
    line("Distance, site to station (km)", lambda s: s.station_distance_km, "0.0")
    line("Station observation time", lambda s: s.station_time)
    line("Station rain (mm/h)", lambda s: s.station_rain_mm_h, "0.0")
    line("Station publishes rain?", lambda s: None if s.station_reports_rain is None else ("Yes" if s.station_reports_rain else "No"))
    line("Radar rain, estimated (mm/h)", lambda s: s.radar_rain_mm_h, "0.0")
    line("Do the sources agree?", lambda s: s.representativeness)
    line("Note", lambda s: s.representativeness_note)
    return Sheet("WEATHER", rows, widths=[32] + [58] * len(labels), freeze=1)


# ---- WEATHER HISTORY -----------------------------------------------------

def _weather_history(ctx: AskContext) -> Sheet:
    w = ctx.weather
    histories = (w.data.get("history") if w is not None else None) or {}
    if w is None:
        return _note("WEATHER HISTORY", "Weather exposure was not run.")
    if not histories:
        return Sheet("WEATHER HISTORY", [header("Note"), ["No weather history could be retrieved for this analysis. "
                                                          "Nothing was substituted."]], widths=[90])
    from . import history as hist
    names = w.data.get("site_names", {})
    rows = [[Cell("All values on this sheet are model-derived (Open-Meteo), not station observations.", bold=True)], [],
            header("Site", "Hours back", "Quantity", "Latest", "Earlier", "Change", "Direction", "Baseline", "Latest time", "Earlier time")]
    for site_id, h in histories.items():
        for hours in (1, 2, 3):
            for c in hist.changes(h, hours):
                rows.append([names.get(site_id, site_id), hours, f"{c.label} ({c.unit})",
                             Cell(c.current, fmt="0.0"), Cell(c.previous, fmt="0.0"), Cell(c.delta, fmt="+0.0;-0.0;0.0"),
                             {"up": "↑ increase", "down": "↓ decrease", "flat": "→ no change"}[c.direction],
                             c.baseline, c.current_time, c.previous_time])
    rows += [[], header("Site", "Time", "Rain (mm/h)", "Temperature (°C)", "Wind (km/h)", "Source", "Time zone")]
    for site_id, h in histories.items():
        for p in h.points:
            rows.append([names.get(site_id, site_id), p.time,
                         _n(p.rain_mm_h), _n(p.temperature_c), _n(p.wind_kmh),
                         h.source, h.timezone])
    return Sheet("WEATHER HISTORY", rows, widths=[20, 20, 16, 18, 14, 50, 20], freeze=3)


# ---- ELEVATION / TERRAIN -------------------------------------------------

_ELEV_COLS = [
    ("sample", "Sample", "0"), ("distance_from_a_km", "Distance from Site A (km)", "0.000"),
    ("latitude", "Latitude", "0.00000"), ("longitude", "Longitude", "0.00000"),
    ("ground_elevation_m", "Ground elevation (m)", "0.0"), ("earth_bulge_m", "Earth bulge (m)", "0.00"),
    ("terrain_adjusted_m", "Terrain, curvature-adjusted (m)", "0.00"), ("los_height_m", "Line of sight height (m)", "0.00"),
    ("fresnel_radius_m", "First Fresnel radius (m)", "0.00"), ("clearance_m", "Clearance (m)", "0.00"),
    ("percent_fresnel_clear", "Fresnel zone clear (fraction)", "0.00"), ("critical", "Critical point (lowest Fresnel-zone fraction)", None),
]


def _elevation(result, ctx: AskContext) -> Sheet:
    if ctx.terrain is None:
        return _note("ELEVATION-TERRAIN", "Terrain clearance was not run.")
    rows = [header(*[c[1] for c in _ELEV_COLS])]
    for p in profile_rows(result.result):
        row = []
        for key, _, numfmt in _ELEV_COLS:
            v = p[key]
            row.append(("YES" if v else "") if key == "critical" else (NOT_DETERMINED if v is None else Cell(v, fmt=numfmt)))
        rows.append(row)
    return Sheet("ELEVATION-TERRAIN", rows, widths=[8, 16, 12, 12, 14, 12, 18, 16, 16, 12, 16, 10], freeze=1)


# ---- EVIDENCE ------------------------------------------------------------

def _evidence(evidence_csv: str) -> Sheet:
    """The CSV export's own table, so the two cannot disagree. Preamble lines
    (starting with '#') are provenance and are kept above the table."""
    lines = list(io.StringIO(evidence_csv))
    pre = [[line[1:].strip()] for line in lines if line.startswith("#") and line[1:].strip()]
    # A quoted field can span lines, so the table part is parsed as a whole.
    table = [r for r in csv.reader(io.StringIO("".join(line for line in lines if not line.startswith("#")))) if r]
    rows = pre + [[]] + ([header(*table[0])] + table[1:] if table else [])
    return Sheet("EVIDENCE", rows, widths=[40, 12, 44, 30, 22, 80])


# ---- RAW DATA ------------------------------------------------------------

def raw_rows(ctx: AskContext) -> List[list]:
    """(key, value, unit, kind, source, calculation id) for every numeric or
    categorical value behind the briefs, un-rounded."""
    out = []
    for b in ctx.briefs():
        for key, value in b.data.items():
            f = registry.FIELDS.get(key)
            if f is None or isinstance(value, dict):
                continue
            out.append([f"{b.kind}.{key}", value, f.unit, f.kind, f.source, f.calc])
        if b.kind == "weather":
            for s in b.sites:
                tag = s.site_label
                for key, value, unit, kind, source in (
                    ("model_rain_mm_h", s.rain_mm_h, "mm/h", registry.MODEL, s.source),
                    ("model_temperature_c", s.temperature_c, "°C", registry.MODEL, s.source),
                    ("model_wind_kmh", s.wind_kmh, "km/h", registry.MODEL, s.source),
                    ("station_rain_mm_h", s.station_rain_mm_h, "mm/h", registry.OBSERVED, s.station_name or ""),
                    ("station_distance_km", s.station_distance_km, "km", registry.CALCULATED, "aei_mw_exposure"),
                    ("radar_rain_mm_h", s.radar_rain_mm_h, "mm/h", registry.OBSERVED, "ECCC radar"),
                ):
                    if value is not None:
                        out.append([f"weather.{tag}.{key}", value, unit, kind, source,
                                    "weather.station_distance" if key == "station_distance_km" else ""])
                if s.site_point:
                    out.append([f"weather.{tag}.latitude", s.site_point[0], "degrees", registry.INPUT, "Site record", ""])
                    out.append([f"weather.{tag}.longitude", s.site_point[1], "degrees", registry.INPUT, "Site record", ""])
    return out


def _raw(ctx: AskContext) -> Sheet:
    rows = [header("Key", "Value", "Unit", "Kind", "Source", "Calculation id")]
    for key, value, unit, kind, source, calc in raw_rows(ctx):
        rows.append([key, Cell(value) if not isinstance(value, str) and value is not None else (value if value is not None else NOT_DETERMINED),
                     unit, kind, source, calc])
    return Sheet("RAW DATA", rows, widths=[46, 22, 12, 12, 52, 28], freeze=1)


# ---- DATA DICTIONARY -----------------------------------------------------

def _dictionary() -> Sheet:
    rows = [[Cell("Statuses", bold=True)], header("Status", "Meaning")]
    rows += [[Cell(s, bold=True, fill=FILLS[s]), m] for s, m in registry.STATUS_DEFINITIONS]
    rows += [[], [Cell("Fields", bold=True)], header("Key", "Label", "Unit", "Kind", "Source", "Calculation id", "Definition")]
    rows += [[f.key, f.label, f.unit, f.kind, f.source, f.calc, f.definition] for f in registry.FIELDS.values()]
    rows += [[], [Cell("Calculations", bold=True)],
             header("Id", "Name", "Formula", "Inputs", "Unit", "Source", "Threshold", "Interpretation")]
    rows += [[c.id, c.name, c.formula, c.inputs, c.unit, c.source, c.threshold, c.interpretation]
             for c in registry.CALCULATIONS]
    return Sheet("DATA DICTIONARY", rows, widths=[30, 28, 44, 36, 12, 48, 46, 56])

