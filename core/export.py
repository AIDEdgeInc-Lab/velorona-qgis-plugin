"""Evidence export -- canonical long-format table (one row per evidence
item): Evidence | Type | Source | Observation-Input | Calculated result |
Interpretation, Type in {Observed, Calculated, Inferred}. Every value
comes from the existing engine result objects (aei_link_clearance /
aei_mw_exposure), unmodified -- this module only serializes what's
already there. See docs/EVIDENCE_EXPORT_AUDIT.md for the gap analysis
this structure closes.

Single-feature (site/link) exports stay their own simpler shape --
raw records, not analysis results, so O/C/I framing doesn't apply the
same way; unchanged from the previous pass.

Satellite-earth-space results are excluded, same judgment call already
made in space.js (a computed geometry snapshot at one instant, not a raw
record or a link result with a stable identity to export)."""

from __future__ import annotations

import csv
import io
from datetime import datetime, timezone

EVIDENCE_HEADER = ["Evidence", "Type", "Source", "Observation-Input", "Calculated result", "Interpretation"]

NOT_DETERMINED = "Not determined"


class NotExportable(Exception):
    pass


def _preamble(lines: list[str]) -> str:
    return "".join(f"# {line}\n" for line in lines) + "#\n"


def _evidence_row(evidence: str, type_: str, source: str = "", observation_input="", calculated_result="", interpretation: str = "") -> list:
    return [evidence, type_, source or "", observation_input if observation_input not in (None, "") else "",
            calculated_result if calculated_result not in (None, "") else "", interpretation or ""]


# entriesToCsv()'s exact header (app.js) -- same column order for a
# single-feature drawer export as for the Map's own selection/results-panel
# export. Raw records, not analysis results -- kept in this simpler shape.
_FEATURE_CSV_HEADER = [
    "Name / Licensee", "Record ID / Authorization", "Call Sign", "Frequency (MHz)",
    "Site / Link", "Feature Type", "Latitude", "Longitude", "Province", "Source", "Retrieved / Generated",
]


def feature_to_csv(attrs: dict, latitude: float, longitude: float) -> str:
    """Single 'site' feature (tower/cellular/fixed-site/satellite/ground-station)
    -- same row shape as entriesToCsvRow()'s generic (non-link) branch."""
    preamble = _preamble([
        "Velorona QGIS export",
        f"Record: {attrs.get('name') or attrs.get('licensee') or 'site'}",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
    ])
    buf = io.StringIO()
    buf.write(preamble)
    writer = csv.writer(buf)
    writer.writerow(_FEATURE_CSV_HEADER)
    writer.writerow([
        attrs.get("name") or attrs.get("licensee"), attrs.get("record_id"),
        attrs.get("call_signs") or attrs.get("radio_call_sign"), attrs.get("frequencies_mhz"),
        "Site", attrs.get("feature_type"), latitude, longitude,
        attrs.get("province"), attrs.get("source"), attrs.get("retrieved_at") or attrs.get("coverage"),
    ])
    return buf.getvalue()


def link_feature_to_csv(attrs: dict, site_a_point, site_b_point) -> str:
    """Single 'link' feature (fixed-service link) -- same row shape as
    entriesToCsvRow()'s link branch."""
    preamble = _preamble([
        "Velorona QGIS export",
        f"Record: {attrs.get('authorization_number') or 'link'}",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
    ])
    buf = io.StringIO()
    buf.write(preamble)
    writer = csv.writer(buf)
    writer.writerow(_FEATURE_CSV_HEADER)
    writer.writerow([
        attrs.get("licensee"), attrs.get("authorization_number"), "", attrs.get("frequencies_mhz"),
        "Link", "Fixed Service link", site_a_point[0], site_a_point[1],
        "", attrs.get("source"), attrs.get("coverage"),
    ])
    return buf.getvalue()


def result_to_csv(result) -> str:
    if result.kind == "terrestrial":
        return _terrestrial_to_csv(result)
    if result.kind == "microwave-exposure":
        return _microwave_to_csv(result)
    if result.kind == "link":
        return link_feature_to_csv(result.data, result.site_a_point, result.site_b_point)
    if result.kind in ("site", "satellite", "ground-station"):
        return feature_to_csv(result.data, result.latitude, result.longitude)
    raise NotExportable(
        "Satellite / Earth-Space analysis results are a computed geometry snapshot at one "
        "instant, not a raw record -- excluded from export, same as Velorona Map's web app."
    )


def _terrestrial_to_csv(result) -> str:
    r = result.result
    site_a_pt = r.profile[0] if r.profile else None
    site_b_pt = r.profile[-1] if r.profile else None

    preamble = _preamble([
        "Velorona QGIS -- Terrestrial Path Clearance export",
        f"Link: {result.site_a_name} <-> {result.site_b_name}",
        "Calculated via aei_link_clearance (ITU-R P.530 Fresnel-zone / earth-curvature terrain clearance), unmodified.",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
    ])
    buf = io.StringIO()
    buf.write(preamble)
    writer = csv.writer(buf)
    writer.writerow(EVIDENCE_HEADER)

    rows = [
        _evidence_row(f"Site A location ({result.site_a_name})", "Observed", result.site_a_source,
                      observation_input=(f"{site_a_pt.latitude:.5f}, {site_a_pt.longitude:.5f}" if site_a_pt else NOT_DETERMINED)),
        _evidence_row(f"Site B location ({result.site_b_name})", "Observed", result.site_b_source,
                      observation_input=(f"{site_b_pt.latitude:.5f}, {site_b_pt.longitude:.5f}" if site_b_pt else NOT_DETERMINED)),
        _evidence_row("Site A antenna height", "Observed",
                      "Feature attribute" if result.site_a_height_from_feature else "User, via analysis dialog (default shown, user-confirmed)",
                      observation_input=f"{result.site_a_height_m:.0f} m"),
        _evidence_row("Site B antenna height", "Observed",
                      "Feature attribute" if result.site_b_height_from_feature else "User, via analysis dialog (default shown, user-confirmed)",
                      observation_input=f"{result.site_b_height_m:.0f} m"),
        _evidence_row("Frequency", "Observed", "User, via analysis dialog (not sourced from license data)",
                      observation_input=f"{r.frequency_ghz:.1f} GHz"),
        _evidence_row("Ground elevation profile", "Observed", "aei_link_clearance (Open-Meteo Elevation API, Copernicus DEM GLO-90, 90m surface model)",
                      observation_input=f"{len(r.profile)} samples along path"),
        _evidence_row("Path distance", "Calculated", "aei_link_clearance (haversine)",
                      calculated_result=f"{r.distance_km:.3f} km"),
        _evidence_row("Bearing", "Calculated", "aei_link_clearance",
                      calculated_result=f"{r.bearing_deg:.1f}°"),
        _evidence_row("First Fresnel radius (critical point)", "Calculated", "aei_link_clearance (ITU-R P.530 Fresnel-zone geometry)",
                      calculated_result=f"{r.first_fresnel_radius_m:.2f} m"),
        _evidence_row("Required clearance (critical point)", "Calculated", "aei_link_clearance (60% of first Fresnel zone)",
                      calculated_result=f"{r.required_clearance_m:.2f} m"),
        _evidence_row("Terrain clearance (critical point)", "Calculated", "aei_link_clearance (earth-curvature-adjusted)",
                      calculated_result=f"{r.terrain_clearance_m:.2f} m"),
        _evidence_row(
            "Obstruction distance from Site A", "Calculated", "aei_link_clearance",
            calculated_result=(f"{r.obstruction_distance_km:.3f} km" if r.obstruction_distance_km is not None else ""),
            interpretation=("" if r.obstruction_distance_km is not None else "Not applicable -- link is not obstructed"),
        ),
        _evidence_row("Clearance ratio", "Calculated", "aei_link_clearance (terrain clearance / required clearance)",
                      calculated_result=f"{r.clearance_ratio:.3f}"),
        _evidence_row("Line-of-sight status", "Inferred", "aei_link_clearance",
                      interpretation=("NEAR THRESHOLD" if r.near_threshold else r.los_status.upper())),
        _evidence_row("Explanation", "Inferred", "aei_link_clearance (explain())", interpretation=result.explanation),
    ]
    for row in rows:
        writer.writerow(row)
    return buf.getvalue()


def _microwave_to_csv(result) -> str:
    e = result.exposure
    link = e.link
    att = e.attenuation

    preamble = _preamble([
        "Velorona QGIS -- Microwave Weather Exposure export",
        f"Link: {link.site_a.name} <-> {link.site_b.name}",
        "Evidence of weather, not a hardware diagnosis or an outage prediction. Calculated via aei_mw_exposure (ITU-R P.530 / P.838-3), unmodified.",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
    ])
    buf = io.StringIO()
    buf.write(preamble)
    writer = csv.writer(buf)
    writer.writerow(EVIDENCE_HEADER)

    rows = [
        _evidence_row("Rain rate used", "Observed", f"Open-Meteo ({e.source_site_id})",
                      observation_input=f"{e.rain_rate_mm_h:.1f} mm/h", interpretation=e.rain_rate_assumption),
        _evidence_row("Fade margin (link spec)", "Observed", "User, via analysis dialog (not sourced from license data)",
                      observation_input=f"{link.fade_margin_db:.0f} dB"),
        _evidence_row("Frequency / polarization", "Observed", "User, via analysis dialog (not sourced from license data)",
                      observation_input=f"{link.frequency_ghz:.1f} GHz, {link.polarization}"),
        _evidence_row("Predicted rain attenuation", "Calculated", f"aei_mw_exposure ({att.method})",
                      observation_input=f"{e.rain_rate_mm_h:.1f} mm/h, {link.frequency_ghz:.1f} GHz, {link.polarization}, {link.length_km:.2f} km",
                      calculated_result=f"{att.predicted_attenuation_db:.2f} dB", interpretation=att.assumption),
        _evidence_row("Exposure ratio", "Calculated", "aei_mw_exposure (predicted attenuation / fade margin)",
                      calculated_result=f"{e.exposure_ratio * 100:.0f}%"),
        _evidence_row("Severity", "Inferred", "aei_mw_exposure", interpretation=f"{e.severity.upper()} -- {e.operational_note}"),
        _evidence_row("Hardware condition", "Inferred", "", interpretation=f"{NOT_DETERMINED} -- no hardware telemetry input to this analysis."),
    ]

    for rep in result.representativeness.values():
        site_label = rep.site.name
        station = rep.nearest_station
        if station is not None:
            precip = f"{station.rain_rate_mm_h:.1f} mm/h" if rep.station_reports_precipitation else NOT_DETERMINED
            rows.append(_evidence_row(f"Nearest ECCC station ({site_label})", "Observed", station.source,
                                       observation_input=station.timestamp))
            rows.append(_evidence_row(f"Station precipitation ({site_label})", "Observed", station.source,
                                       observation_input=precip,
                                       interpretation=("" if rep.station_reports_precipitation else "Station does not publish a precipitation reading")))
            rows.append(_evidence_row(f"Station distance ({site_label})", "Calculated", "aei_mw_exposure (haversine)",
                                       calculated_result=f"{rep.station_distance_km:.1f} km"))
        else:
            rows.append(_evidence_row(f"Nearest ECCC station ({site_label})", "Observed", "ECCC SWOB-Realtime",
                                       observation_input=NOT_DETERMINED,
                                       interpretation="No station reported within the last 90 minutes within the search radius used here."))

        if rep.model_observation is not None:
            rows.append(_evidence_row(f"Model precipitation ({site_label})", "Observed", rep.model_observation.source,
                                       observation_input=f"{rep.model_observation.rain_rate_mm_h:.1f} mm/h"))
        else:
            rows.append(_evidence_row(f"Model precipitation ({site_label})", "Observed", "Open-Meteo",
                                       observation_input=NOT_DETERMINED))

        if rep.radar_observation is not None:
            rows.append(_evidence_row(f"Radar precipitation ({site_label})", "Observed", rep.radar_observation.source,
                                       observation_input=f"{rep.radar_observation.rain_rate_mm_h:.1f} mm/h (estimated, {rep.radar_observation.timestamp})"))
        elif station is not None:
            rows.append(_evidence_row(f"Radar precipitation ({site_label})", "Observed", "ECCC Radar (RADAR_1KM_RRAI)",
                                       observation_input=NOT_DETERMINED,
                                       interpretation="Not available for this location/time."))

        if rep.precipitation_difference_mm_h is not None:
            rows.append(_evidence_row(f"Station vs. model difference ({site_label})", "Calculated", "aei_mw_exposure",
                                       calculated_result=f"{rep.precipitation_difference_mm_h:.1f} mm/h"))
        elif station is not None:
            rows.append(_evidence_row(f"Station vs. model difference ({site_label})", "Calculated", "aei_mw_exposure",
                                       calculated_result=NOT_DETERMINED, interpretation="Not calculable -- see representativeness note."))

        rows.append(_evidence_row(f"Weather representativeness ({site_label})", "Inferred", "aei_mw_exposure",
                                   interpretation=f"{rep.level.replace('_', ' ').upper()} -- {rep.note}"))

    for row in rows:
        writer.writerow(row)
    return buf.getvalue()
