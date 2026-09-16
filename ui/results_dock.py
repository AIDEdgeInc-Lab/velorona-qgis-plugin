"""Results/Evidence dock: single-feature drawers (site/link/satellite/
ground-station) and analysis-result drawers (terrestrial/microwave/
satellite-earth-space), all through one shared section-based layout --
same information architecture as aei-link-clearance/web/app.js's
renderDrawerRecord()/openDrawer(), reused verbatim (labels, section
names, provenance sentences), not reinvented. QGIS's generic Attribute
Table is never shown for these kinds.

Every section is labeled Observed / Calculated / Inferred consistently
across analysis kinds (terrestrial and microwave both, not just
microwave -- see docs/EVIDENCE_EXPORT_AUDIT.md item 2). Fields a source
genuinely tracks but doesn't have a value for on this record render
"Not determined", never a silent gap (item 4); fields a source doesn't
track at all for that record's kind stay omitted (that's not a gap, it's
irrelevant for that kind)."""

from __future__ import annotations

import html

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QDockWidget, QFileDialog, QHBoxLayout, QMessageBox, QPushButton, QTextBrowser, QVBoxLayout, QWidget

from ..core.export import NotExportable, result_to_csv

NOT_DETERMINED = "Not determined"


class VeloronaResultsDock(QDockWidget):
    def __init__(self, parent=None):
        super().__init__("Velorona -- Results / Evidence", parent)
        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self._result = None
        self.elevation_profile_requested = None  # callable, set by plugin.py

        container = QWidget(self)
        layout = QVBoxLayout(container)
        self.browser = QTextBrowser(container)
        button_row = QHBoxLayout()
        self.export_button = QPushButton("Export as CSV...", container)
        self.export_button.clicked.connect(self._on_export_clicked)
        self.elevation_button = QPushButton("Open Elevation Profile", container)
        self.elevation_button.clicked.connect(self._on_elevation_clicked)
        self.elevation_button.hide()
        button_row.addWidget(self.export_button)
        button_row.addWidget(self.elevation_button)
        layout.addWidget(self.browser)
        layout.addLayout(button_row)
        self.setWidget(container)

    def show_result(self, result) -> None:
        self._result = result
        self.browser.setHtml(_render_html(result))
        self.elevation_button.setVisible(result.kind == "terrestrial")
        self.export_button.setVisible(result.kind != "satellite-earth-space")

    def _on_export_clicked(self):
        if self._result is None:
            return
        try:
            csv_text = result_to_csv(self._result)
        except NotExportable as exc:
            QMessageBox.information(self, "Velorona", str(exc))
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export CSV", "velorona_export.csv", "CSV files (*.csv)")
        if not path:
            return
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(csv_text)
        QMessageBox.information(self, "Velorona", f"Exported to {path}")

    def _on_elevation_clicked(self):
        if self.elevation_profile_requested:
            self.elevation_profile_requested()


def _esc(value) -> str:
    return html.escape(str(value)) if value is not None else ""


def _field_row(label: str, value) -> str:
    if value is None or value == "":
        return ""
    return f"<tr><td class='fk'>{_esc(label)}</td><td>{_esc(value)}</td></tr>"


def _field_row_checked(d: dict, key: str, label: str, formatter=None) -> str:
    """Distinguishes 'this source doesn't track this concept for this kind
    of record' (the key is absent from this record's own attribute schema
    -- correctly omitted, not a gap) from 'this source tracks it but has
    no value for this specific record' (key present, value empty --
    rendered as Not determined, never silently dropped)."""
    if key not in d:
        return ""
    value = d.get(key)
    if value is None or value == "":
        return f"<tr><td class='fk'>{_esc(label)}</td><td class='nd'>{NOT_DETERMINED}</td></tr>"
    return _field_row(label, formatter(value) if formatter else value)


def _section_html(label: str, rows: str) -> str:
    if not rows.strip():
        return ""
    return f"<div class='sec'>{_esc(label)}</div><table cellpadding='3'>{rows}</table>"


_STYLE = """
<style>
body { font-family: sans-serif; font-size: 12.5px; }
.kicker { font-size: 10px; letter-spacing: 0.06em; color: #888; margin-bottom: 2px; }
h3 { margin: 0 0 10px; font-size: 14px; }
.sec { font-size: 10.5px; letter-spacing: 0.04em; color: #888; text-transform: uppercase;
       margin: 12px 0 3px; border-top: 1px solid #444; padding-top: 6px; }
table { border-collapse: collapse; width: 100%; margin-bottom: 2px; }
td { padding: 1px 6px 1px 0; vertical-align: top; }
td.fk { color: #999; white-space: nowrap; }
td.nd { color: #777; font-style: italic; }
.caveat { color: #888; font-size: 11px; margin: 4px 0; }
.src { color: #999; font-size: 11px; margin: 2px 0 8px; }
.assumption { font-size: 11px; background: rgba(128,128,128,0.12); padding: 4px 6px;
              white-space: pre-wrap; margin: 2px 0; }
p { margin: 3px 0; }
</style>
"""


def _render_html(result) -> str:
    renderers = {
        "site": _render_site_feature,
        "link": _render_link_feature,
        "satellite": _render_satellite_feature,
        "ground-station": _render_ground_station_feature,
        "terrestrial": _render_terrestrial,
        "microwave-exposure": _render_microwave,
        "satellite-earth-space": _render_satellite_analysis,
    }
    renderer = renderers.get(result.kind)
    if renderer is None:
        return _STYLE + f"<p>Unknown result kind: {_esc(result.kind)}</p>"
    return _STYLE + renderer(result)


# ---------------------------------------------------------------------
# Single-feature drawers -- mirrors app.js's openDrawer() site/link
# branches and space.js's satellite/ground-station DrawerRenderers.
# ---------------------------------------------------------------------

def _render_site_feature(entry) -> str:
    d = entry.data
    kicker = (d.get("feature_type") or "Site").upper()
    title = d.get("name") or d.get("licensee") or "Site"
    identity = (
        _field_row_checked(d, "record_id", "Record ID") + _field_row_checked(d, "licensee", "Licensee")
        + _field_row_checked(d, "authorizations", "Authorizations")
        + (_field_row_checked(d, "call_signs", "Call sign(s)") or _field_row_checked(d, "radio_call_sign", "Call sign(s)"))
    )
    technical = (
        _field_row_checked(d, "frequencies_mhz", "Frequencies (MHz)") + _field_row_checked(d, "purpose", "Purpose")
        + _field_row_checked(d, "service_bands", "Service band(s)")
        + _field_row_checked(d, "channel_count", "Channel count at this site")
        + _field_row_checked(d, "height_above_ground_m", "Height above ground (m)")
    )
    location = (
        _field_row_checked(d, "province", "Province")
        + _field_row("Latitude", f"{entry.latitude:.5f}°" if entry.latitude is not None else None)
        + _field_row("Longitude", f"{entry.longitude:.5f}°" if entry.longitude is not None else None)
    )
    provenance = (
        _field_row("Source", d.get("source"))
        + _field_row("Effective/updated", d.get("effective_datetime") or d.get("geometry_update_datetime") or d.get("business_effective_date") or d.get("source_file_updated"))
        + _field_row("Retrieved", d.get("retrieved_at"))
        + _field_row("Coverage", d.get("coverage"))
    )
    return (
        f"<div class='kicker'>{_esc(kicker)}</div><h3>{_esc(title)}</h3>"
        + _section_html("Identity", identity) + _section_html("Technical", technical)
        + _section_html("Location", location) + _section_html("Provenance", provenance)
    )


def _render_link_feature(entry) -> str:
    d = entry.data
    kicker = "FIXED SERVICE LINK"
    title = d.get("authorization_number") or d.get("licensee") or "Fixed Service link"
    identity = _field_row_checked(d, "authorization_number", "Authorization number") + _field_row_checked(d, "licensee", "Licensee")
    technical = _field_row_checked(d, "frequencies_mhz", "Frequencies (MHz)") + _field_row_checked(d, "in_service_date", "In-service date")
    a_lat, a_lon = entry.site_a_point or (None, None)
    b_lat, b_lon = entry.site_b_point or (None, None)
    endpoints = (
        _field_row("Site A location", f"{a_lat:.5f}°, {a_lon:.5f}°" if a_lat is not None else None)
        + _field_row("Site B location", f"{b_lat:.5f}°, {b_lon:.5f}°" if b_lat is not None else None)
    )
    provenance = (
        _field_row("Source", d.get("source"))
        + _field_row("Pairing", "Both sites share this authorization number in ISED's Fixed Service extract and "
                     "resolve to exactly two distinct coordinates -- not inferred from proximity or frequency.")
        + _field_row("Coverage", d.get("coverage"))
    )
    return (
        f"<div class='kicker'>{_esc(kicker)}</div><h3>{_esc(title)}</h3>"
        + _section_html("Identity", identity) + _section_html("Technical", technical)
        + _section_html("Endpoints", endpoints) + _section_html("Provenance", provenance)
    )


def _render_satellite_feature(entry) -> str:
    d = entry.data
    kicker = (d.get("feature_type") or "Satellite").upper()
    title = d.get("name") or "Satellite"
    identity = _field_row_checked(d, "norad_cat_id", "NORAD catalog number") + _field_row_checked(d, "object_id", "Object ID (COSPAR)")
    technical = _field_row_checked(d, "orbit_category", "Orbit category") + _field_row(
        "Orbital period", f"{d['period_minutes']:.1f} min" if d.get("period_minutes") is not None else None)
    position = (
        _field_row("Latitude", f"{entry.latitude:.4f}°" if entry.latitude is not None else None)
        + _field_row("Longitude", f"{entry.longitude:.4f}°" if entry.longitude is not None else None)
        + _field_row("Altitude", f"{d['altitude_km']:.1f} km" if d.get("altitude_km") is not None else None)
    )
    provenance = (
        _field_row("Source", d.get("source"))
        + _field_row("TLE epoch", f"{d.get('tle_epoch')} -- position accuracy degrades with time since this epoch")
        + _field_row("Coverage", d.get("coverage"))
    )
    return (
        f"<div class='kicker'>{_esc(kicker)}</div><h3>{_esc(title)}</h3>"
        + _section_html("Identity", identity) + _section_html("Technical", technical)
        + _section_html("Position (now)", position) + _section_html("Provenance", provenance)
    )


def _render_ground_station_feature(entry) -> str:
    d = entry.data
    kicker = (d.get("feature_type") or "Ground/Earth Station").upper()
    title = d.get("name") or "Ground/Earth Station"
    identity = (
        _field_row_checked(d, "record_id", "Record ID") + _field_row_checked(d, "licensee", "Operator/owner")
        + _field_row_checked(d, "status", "Status")
    )
    success_rate_row = ""
    if "success_rate" in d:
        sr = d.get("success_rate")
        success_rate_row = _field_row("Success rate (SatNOGS)", f"{sr}%") if isinstance(sr, (int, float)) else \
            f"<tr><td class='fk'>Success rate (SatNOGS)</td><td class='nd'>{NOT_DETERMINED}</td></tr>"
    technical = (
        _field_row_checked(d, "frequencies_mhz", "Antenna frequencies") + _field_row("Antenna count", d.get("antenna_count"))
        + _field_row_checked(d, "observations", "Observations (SatNOGS)")
        + success_rate_row
        + _field_row_checked(d, "min_horizon_deg", "Station's declared min. horizon", formatter=lambda v: f"{v}°")
    )
    location = (
        _field_row_checked(d, "qthlocator", "Grid locator") + _field_row_checked(d, "altitude_m", "Altitude (m)")
        + _field_row("Latitude", f"{entry.latitude:.4f}°" if entry.latitude is not None else None)
        + _field_row("Longitude", f"{entry.longitude:.4f}°" if entry.longitude is not None else None)
    )
    provenance = (
        _field_row("Source", d.get("source")) + _field_row("Snapshot retrieved", "not a live feed")
        + _field_row("Coverage", d.get("coverage"))
    )
    return (
        f"<div class='kicker'>{_esc(kicker)}</div><h3>{_esc(title)}</h3>"
        + _section_html("Identity", identity) + _section_html("Technical", technical)
        + _section_html("Location", location) + _section_html("Provenance", provenance)
    )


# ---------------------------------------------------------------------
# Terrestrial Path Clearance result -- Observed/Calculated/Inferred
# sections, same vocabulary as the microwave renderer below (previously
# labeled "Path"/"Result"/"Terrain-Elevation" with no O/C/I type at all --
# see docs/EVIDENCE_EXPORT_AUDIT.md item 2).
# ---------------------------------------------------------------------

def _render_terrestrial(result) -> str:
    r = result.result
    status_color = {"clear": "#2ca25f", "marginal": "#e6b800", "obstructed": "#d7191c"}[r.los_status]
    badge = f"<b style='color:{status_color}'>{_esc((r.near_threshold and 'NEAR THRESHOLD') or r.los_status.upper())}</b>"

    height_a_note = "from feature attribute" if result.site_a_height_from_feature else "default shown in dialog, user-confirmed"
    height_b_note = "from feature attribute" if result.site_b_height_from_feature else "default shown in dialog, user-confirmed"
    source_note = (
        f"<p class='src'>Site A: {_esc(result.site_a_source)}. Site B: {_esc(result.site_b_source)}. "
        f"Height A: {result.site_a_height_m:.0f} m ({height_a_note}). "
        f"Height B: {result.site_b_height_m:.0f} m ({height_b_note}). "
        f"Frequency: {r.frequency_ghz:.1f} GHz (entered by user via analysis dialog, not sourced from license data).</p>"
    )

    observed = (
        _field_row("Distance (km)", f"{r.distance_km:.2f}") + _field_row("Bearing", f"{r.bearing_deg:.1f}°")
        + _field_row("Frequency (GHz)", f"{r.frequency_ghz:.1f}")
        + _field_row("Elevation samples", f"{len(r.profile)} points along path (Open-Meteo Elevation API, Copernicus DEM GLO-90)")
    )
    calculated = (
        _field_row("First Fresnel radius (critical point)", f"{r.first_fresnel_radius_m:.1f} m")
        + _field_row("Required clearance", f"{r.required_clearance_m:.1f} m")
        + _field_row("Terrain clearance", f"{r.terrain_clearance_m:.1f} m")
        + _field_row("Obstruction distance", f"{r.obstruction_distance_km:.1f} km" if r.obstruction_distance_km is not None else None)
        + _field_row("Clearance ratio", f"{r.clearance_ratio:.2f}")
    )
    inferred = _field_row("Status", (r.near_threshold and "NEAR THRESHOLD") or r.los_status.upper()) + _field_row("Explanation", result.explanation)

    return (
        f"<div class='kicker'>{'SELECTED-FEATURE ANALYSIS'}</div>"
        f"<h3>{_esc(r.link_id)} {badge}</h3>"
        + source_note
        + _section_html("Observed", observed)
        + _section_html("Calculated", calculated)
        + _section_html("Inferred", inferred)
        + "<p class='caveat'>Calculated via aei_link_clearance (ITU-R P.530 Fresnel-zone / earth-curvature terrain "
          "clearance), unmodified.</p>"
        + "<p class='caveat'>Open the Elevation Profile button below for the full sampled-path chart "
          "(distance vs. ground elevation, Fresnel zone, line of sight).</p>"
    )


# ---------------------------------------------------------------------
# Microwave Weather Exposure result -- Observed/Calculated/Inferred +
# full per-site Weather Evidence, reusing aei-microwave-link-exposure's
# own app.py inspector-panel structure verbatim (field-for-field), with
# the DEMO/SYNTHETIC caveat corrected to this plugin's actual provenance
# (USER_PROVIDED link params, not a demo network).
# ---------------------------------------------------------------------

def _render_weather_evidence_site(rep) -> str:
    station = rep.nearest_station
    observed = ""
    calculated = ""
    if station is not None:
        precip = f"{station.rain_rate_mm_h:.1f} mm/h" if rep.station_reports_precipitation else "not published by this station"
        observed += _field_row("Nearest ECCC weather station", f"{station.source} (see Weather Evidence layer)")
        observed += _field_row("Station time", station.timestamp)
        observed += _field_row("Station precipitation", precip)
        calculated += _field_row("Station distance", f"{rep.station_distance_km:.1f} km")
    if rep.model_observation is not None:
        observed += _field_row("Model precipitation", f"{rep.model_observation.rain_rate_mm_h:.1f} mm/h ({rep.model_observation.source})")
    else:
        observed += _field_row("Model precipitation", "unavailable")
    if rep.radar_observation is not None:
        observed += _field_row("Radar rate", f"{rep.radar_observation.rain_rate_mm_h:.1f} mm/h (estimated, {rep.radar_observation.timestamp})")
    elif station is not None:
        observed += _field_row("Radar", "not available for this location/time")
    if rep.precipitation_difference_mm_h is not None:
        calculated += _field_row("Station vs. model difference", f"{rep.precipitation_difference_mm_h:.1f} mm/h")
    elif station is not None:
        calculated += _field_row("Difference", "not calculable (see note)")

    level_color = {
        "consistent": "#2ca25f", "moderate_disagreement": "#e6b800",
        "high_disagreement": "#d7191c", "insufficient_evidence": "#888888",
    }[rep.level]
    level_label = rep.level.replace("_", " ").title()
    interpreted = f"<p><b style='color:{level_color}'>{_esc(level_label)}</b></p><p>{_esc(rep.note)}</p>"
    if rep.level == "insufficient_evidence":
        interpreted += "<p class='caveat'>This is an honest, expected result when nearby evidence is thin -- not an error and not a low-risk result.</p>"

    if station is None:
        body = (
            "<p class='caveat'>No nearby ECCC observing station was available for this location -- no station "
            "reported in the last 90 minutes within the search radius used here, so there is no independent "
            "evidence to compare. The site itself remains available above.</p>"
        )
    else:
        body = (
            _section_html("OBSERVED", observed) + _section_html("CALCULATED", calculated)
            + f"<div class='sec'>INTERPRETED</div>{interpreted}"
        )
    return f"<p><b>{_esc(rep.site.name)}</b></p>{body}"


def _render_microwave(result) -> str:
    exp = result.exposure
    link = exp.link
    severity_color = {"low": "#2ca25f", "moderate": "#e6b800", "high": "#d7191c"}[exp.severity]
    severity_label = exp.severity.title()

    observed = f"<p>{_esc(exp.rain_rate_assumption)}</p>" + f"<p>Rain rate used: <b>{exp.rain_rate_mm_h:.1f} mm/h</b></p>"
    calculated = (
        f"<p>Method: {_esc(exp.attenuation.method)}</p>"
        f"<pre class='assumption'>{_esc(exp.attenuation.assumption)}</pre>"
        f"<p>Predicted attenuation: <b>{exp.attenuation.predicted_attenuation_db:.2f} dB</b></p>"
        f"<p>Fade margin (link spec): {link.fade_margin_db:.0f} dB</p>"
        f"<p>Exposure ratio: {exp.exposure_ratio * 100:.0f}%</p>"
    )
    inferred = (
        f"<p><b style='color:{severity_color}'>{_esc(severity_label)}</b></p>"
        f"<p>{_esc(exp.operational_note)}</p>"
        f"<p class='caveat'>This link's geometry/frequency/fade margin were entered by the user via the analysis "
        f"dialog ({_esc(link.provenance.value)}), not sourced from license data. The weather driving this "
        f"calculation is real and live.</p>"
    )
    # Rendered as a real Evidence row, not a prose disclaimer -- the engine
    # never determines this for any input, so it stays "Not determined"
    # rather than being upgraded to an inferred value (item 5).
    evidence_status = _field_row("Hardware condition", NOT_DETERMINED + " -- no hardware telemetry input to this analysis")

    parts = [
        "<div class='kicker'>MICROWAVE WEATHER EXPOSURE</div>",
        f"<h3>{_esc(link.site_a.name)} &harr; {_esc(link.site_b.name)}</h3>",
        "<div class='sec'>Observed weather (LIVE)</div>", observed,
        "<div class='sec'>Calculated exposure (DERIVED)</div>", calculated,
        "<div class='sec'>Inferred implication</div>", inferred,
        "<div class='sec'>Evidence status</div>", f"<table cellpadding='3'>{evidence_status}</table>",
        "<div class='sec'>Weather Evidence</div>",
    ]
    for rep in result.representativeness.values():
        parts.append(_render_weather_evidence_site(rep))

    if result.weather_errors:
        parts.append("<div class='sec'>Notices</div><ul>")
        for key, message in result.weather_errors.items():
            parts.append(f"<li>{_esc(key)}: {_esc(message)}</li>")
        parts.append("</ul>")

    parts.append(
        "<p class='caveat'>Weather evidence supports or weakens weather as a plausible contributor. "
        "It is not an outage prediction.</p>"
    )
    return "".join(parts)


# ---------------------------------------------------------------------
# Satellite / Earth-Space Analysis result
# ---------------------------------------------------------------------

def _render_satellite_analysis(result) -> str:
    badge_color = "#2ca25f" if result.visible else "#d7191c"
    geometry = (
        _field_row("Elevation angle", f"{result.elevation_deg:.2f}°")
        + _field_row("Azimuth", f"{result.azimuth_deg:.2f}°")
        + _field_row("Slant range", f"{result.slant_range_km:.1f} km")
    )
    return (
        "<div class='kicker'>SATELLITE / EARTH-SPACE ANALYSIS</div>"
        f"<h3>{_esc(result.station_name)} &harr; {_esc(result.satellite_name)} "
        f"<b style='color:{badge_color}'>{'VISIBLE' if result.visible else 'NOT VISIBLE'}</b></h3>"
        + _section_html("Geometry", geometry)
        + f"<p class='caveat'>Method: Geometry only (elevation, slant range, azimuth, visibility) -- SGP4 "
          f"propagation + observer-relative look angles (skyfield). No propagation loss, no link budget, "
          f"no weather exposure -- out of scope for this phase.</p>"
        + f"<p class='caveat'>Minimum elevation mask: {result.min_elevation_mask_deg}° (standard practice "
          f"range is 5-10°; the more conservative end was used since Phase 1 has no per-site "
          f"horizon-obstruction survey).</p>"
        + f"<p class='caveat'>Satellite TLE epoch: {_esc(result.tle_epoch)} -- position accuracy degrades with "
          f"time since this epoch.</p>"
        + "<p class='caveat'>Not exportable: a computed geometry snapshot at this instant, not a raw record.</p>"
    )
