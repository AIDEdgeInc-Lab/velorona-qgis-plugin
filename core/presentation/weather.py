"""Weather-exposure brief: aei_mw_exposure's result, with its provenance spelled out.

Nothing is recalculated. Fade remaining = fade margin - predicted attenuation,
both library values. Status mapping:

    severity low       -> CLEAR     (library: exposure ratio < 0.3)
    severity moderate  -> WATCH     (0.3 to < 0.7)
    severity high      -> AT RISK   (>= 0.7)
    predicted attenuation >= fade margin -> CRITICAL  (the margin is used up;
                          this is the definition of the margin, not a new threshold)
    no exposure result -> NO DATA

The library's 0.3 / 0.7 bands are its own stated conventions, "not a validated
risk model" (aei_mw_exposure.exposure); this layer only renames the buckets.
"""

from __future__ import annotations

from typing import Dict, Optional

from .. import evidence_record
from . import history as hist
from .model import (AT_RISK, CLEAR, CRITICAL, NO_DATA, NOT_DETERMINED, WATCH, Brief, Fact, SiteWeather,
                    exact, fmt, signed)

# Mirrors of aei_mw_exposure.providers.eccc.find_nearest_station's defaults and
# representativeness' conventions, checked against the library by
# tests/test_presentation_weather.py.
STATION_SEARCH_RADIUS_KM = 50.0
STATION_WINDOW_MINUTES = 90

MODEL_KIND = "Model-derived (weather model value at the site's coordinates, not a station measurement)"
STATION_KIND = "Observed (station measurement)"
RADAR_KIND = "Radar-estimated rain rate, not gauge-measured"   # classification (Observed vs Model-derived) is R6, not decided

SELECTION_MODEL = "Weather model value at the site's own coordinates; no station is selected for this value."
SELECTION_STATION = (f"Nearest ECCC station that reported within the last {STATION_WINDOW_MINUTES} minutes, "
                     f"searched within {STATION_SEARCH_RADIUS_KM:.0f} km (bounding box, then exact distance).")

LEVEL_TEXT = {
    "consistent": "Sources agree",
    "moderate_disagreement": "Sources partly disagree",
    "high_disagreement": "Sources disagree",
    "insufficient_evidence": "Not enough independent evidence",
}


def weather_status(exp) -> tuple:
    """(status, one-line reason, plain answer) from a library LinkExposure."""
    if exp is None:
        return (NO_DATA, "Live weather could not be retrieved for this link.",
                "No answer: there is no weather data for this link.")
    fade = exp.attenuation.predicted_attenuation_db
    margin = exp.link.fade_margin_db
    if fade >= margin:
        return (CRITICAL, f"Predicted rain fade ({fmt(fade)} dB) is larger than the fade margin ({fmt(margin, 0)} dB).",
                "The model predicts rain loss bigger than the link is designed to absorb.")
    if exp.severity == "high":
        return (AT_RISK, f"Predicted rain fade ({fmt(fade)} dB) uses most of the {fmt(margin, 0)} dB fade margin.",
                "Rain is likely to push this link close to its limit.")
    if exp.severity == "moderate":
        return (WATCH, f"Predicted rain fade ({fmt(fade)} dB) is a noticeable part of the {fmt(margin, 0)} dB fade margin.",
                "Rain is starting to matter for this link, but it is not yet a likely capacity problem.")
    return (CLEAR, f"Predicted rain fade ({fmt(fade)} dB) is small compared with the {fmt(margin, 0)} dB fade margin.",
            "Weather is not a meaningful concern for this link right now.")


def _site_weather(rep, label: str, point, p=None) -> SiteWeather:
    model, station, radar = rep.model_observation, rep.nearest_station, rep.radar_observation
    return SiteWeather(
        site_label=label, site_point=point,
        source=model.source if model else NOT_DETERMINED,
        kind=MODEL_KIND if model else NOT_DETERMINED,
        timestamp=model.timestamp if model else NOT_DETERMINED,
        selection=SELECTION_MODEL,
        temperature_c=model.temperature_c if model else None,
        wind_kmh=model.wind_speed_kmh if model else None,
        rain_mm_h=model.rain_rate_mm_h if model else None,
        station_name=(station.site_id or station.source) if station else None,
        station_point=(station.latitude, station.longitude) if station else None,
        station_distance_km=rep.station_distance_km if station else None,
        station_time=station.timestamp if station else None,
        station_rain_mm_h=station.rain_rate_mm_h if station and rep.station_reports_precipitation else None,
        station_reports_rain=rep.station_reports_precipitation if station else None,
        radar_rain_mm_h=radar.rain_rate_mm_h if radar else None,
        representativeness=LEVEL_TEXT.get(rep.level, rep.level),
        representativeness_note=rep.note,
        precip_total_mm_h=(p.total_mm * 3600.0 / p.interval_s) if (p and p.total_mm is not None) else None,
        precip_basis=p.basis if p else "",
    )


def _trend_sentence(label: str, change) -> str:
    if change is None:
        return ""
    # Hourly model values, said as such: the rain rate used above is the current
    # reading, a different product, and the two can differ.
    if change.direction == "flat":
        return f"Hourly model rain at {label} is unchanged {change.baseline[3:]} ({fmt(change.current)} mm/h)."
    word = "higher" if change.direction == "up" else "lower"
    return (f"Hourly model rain at {label} is {word} than {change.baseline[3:]} "
            f"({fmt(change.current)} vs {fmt(change.previous)} mm/h).")


def exposure_brief(mw, param_origins: Optional[dict] = None, weather_error: Optional[str] = None) -> Brief:
    """`mw` is a MicrowaveAnalysisResult (duck-typed), or None with `weather_error`."""
    if mw is None or mw.exposure is None:
        reason = weather_error or "Live weather services were unavailable."
        return Brief(kind="weather", title="Weather exposure", location="", status=NO_DATA,
                     reason=reason, answer="No answer: there is no weather data for this link.",
                     caveats=["Nothing was substituted for the missing weather."])

    exp = mw.exposure
    link = exp.link
    att = exp.attenuation
    origins = param_origins or {}
    status, reason, answer = weather_status(exp)
    location = f"{link.site_a.name} ↔ {link.site_b.name}"

    sites = []
    labels = {}
    for site in (link.site_a, link.site_b):
        rep = mw.representativeness.get(site.id)
        labels[site.id] = site.name
        if rep is not None:
            sites.append(_site_weather(rep, site.name, (site.latitude, site.longitude),
                                       (getattr(mw, "precipitation", None) or {}).get(site.id)))

    driver_id = exp.source_site_id
    driver_name = labels.get(driver_id, driver_id)
    other = next((s for s in sites if s.site_label != driver_name), None)

    histories: Dict[str, hist.WeatherHistory] = dict(getattr(mw, "history", None) or {})
    driver_hist = histories.get(driver_id)
    changes = []
    trend = ""
    if driver_hist is not None:
        for hours in (1, 3):
            changes.extend(hist.changes(driver_hist, hours))
        rain_1h = hist.compare(driver_hist, "rain", 1)
        trend = _trend_sentence(driver_name, rain_1h)

    fade_left = link.fade_margin_db - att.predicted_attenuation_db
    key_facts = [
        Fact("Rain rate used", f"{fmt(exp.rain_rate_mm_h)} mm/h",
             f"the higher of the two sites: {driver_name}"
             + (f" ({fmt(other.rain_mm_h)} mm/h at {other.site_label})" if other and other.rain_mm_h is not None else ""),
             "Model-derived liquid rain; used as a stand-in for rain along the path"),
        Fact("Predicted rain fade", f"{fmt(att.predicted_attenuation_db)} dB",
             f"link fade margin {fmt(link.fade_margin_db, 0)} dB", "Signal the rain is expected to remove"),
        Fact("Fade margin remaining", f"{signed(fade_left)} dB", "fade margin minus predicted rain fade",
             "Positive means the link can absorb it"),
        Fact("Path", f"{fmt(att.path_length_km, 2)} km", f"{exact(link.frequency_ghz)} GHz, {link.polarization} polarization"),
    ]
    technical = [
        Fact("Exposure ratio", f"{exp.exposure_ratio * 100:.1f}% of fade margin used",
             "predicted rain fade / fade margin", "Library bands: WATCH from 30%, AT RISK from 70%"),
        Fact("Specific attenuation", f"{att.specific_attenuation_db_km:.4f} dB/km", f"k={att.k:g}, α={att.alpha:g}",
             "Rain loss per kilometre (ITU-R P.838-3)"),
        Fact("Effective path length", f"{fmt(att.effective_path_length_km, 2)} km",
             f"of {fmt(att.path_length_km, 2)} km geometric", "Rain cells are smaller than long hops (ITU-R P.530)"),
        Fact("Method", att.method),
        Fact("Frequency", f"{exact(link.frequency_ghz)} GHz", _origin(origins, "frequency_ghz")),
        Fact("Polarization", link.polarization, _origin(origins, "polarization")),
        Fact("Fade margin", f"{exact(link.fade_margin_db)} dB", _origin(origins, "fade_margin_db")),
    ]
    evidence = [Fact("Calculation", f"aei_mw_exposure ({att.method})"),
                Fact("Rain assumption", exp.rain_rate_assumption)]
    for s in sites:
        evidence.append(Fact(f"{s.site_label} weather source", s.source, s.kind, f"observation time {s.timestamp}"))

    caveats = ["Model estimate of rain loss, not an outage prediction and not a hardware diagnosis."]
    if evidence_record.rain_table_notice():
        caveats.append(evidence_record.rain_table_notice())
    for site in (link.site_a, link.site_b):
        p = (getattr(mw, "precipitation", None) or {}).get(site.id)
        if p is None:
            continue
        if p.has_frozen:
            caveats.append(f"{site.name}: frozen precipitation (about {fmt(p.frozen_mm, 2)} mm water equivalent) is present and is not counted "
                           f"as rain. It is a separate signal and does not change the status. Rain used: {fmt(p.rate_mm_h, 2)} mm/h.")
        if p.has_freezing:
            caveats.append(f"{site.name}: freezing precipitation is reported (WMO code {p.weather_code}); the rain model does not quantify it "
                           f"and it is not counted as rain.")
    assumed = [k.replace("_", " ") for k, (kind, _) in origins.items() if kind == "Assumed"]
    if assumed:
        caveats.append("Assumed rather than published: " + ", ".join(assumed)
                       + ". The result is only as good as these inputs.")
    for key, message in (getattr(mw, "weather_errors", None) or {}).items():
        caveats.append(f"{key}: {message}")

    inspect = ""
    if status != CLEAR:
        inspect = f"Check rain at {driver_name}"
        d = next((s for s in sites if s.site_label == driver_name), None)
        if d and d.site_point:
            inspect += f" (lat {d.site_point[0]:.5f}, lon {d.site_point[1]:.5f})"
        if d and d.station_name:
            inspect += f" and compare with station {d.station_name}, {fmt(d.station_distance_km)} km away"
        inspect += "."

    return Brief(
        kind="weather", title="Weather exposure", location=location, status=status, reason=reason,
        answer=(answer + (" " + trend if trend else "")), key_facts=key_facts, technical=technical,
        evidence=evidence, changes=changes, sites=sites, caveats=caveats, inspect=inspect,
        data={
            "rain_rate_mm_h": exp.rain_rate_mm_h, "driver_site_id": driver_id, "driver_site": driver_name,
            "predicted_attenuation_db": att.predicted_attenuation_db, "fade_margin_db": link.fade_margin_db,
            "fade_remaining_db": fade_left, "exposure_ratio": exp.exposure_ratio, "severity": exp.severity,
            "path_length_km": att.path_length_km, "frequency_ghz": link.frequency_ghz,
            "polarization": link.polarization, "specific_attenuation_db_km": att.specific_attenuation_db_km,
            "effective_path_length_km": att.effective_path_length_km, "k": att.k, "alpha": att.alpha,
            "history": histories, "site_names": labels,
        },
    )


def _origin(origins: dict, key: str) -> str:
    found = origins.get(key)
    if not found:
        return "entered by the user in the analysis dialog"
    kind, note = found
    return f"{kind.lower()}: {note}"
