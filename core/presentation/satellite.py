"""Satellite / Earth-Space evidence rows -- pure (no QGIS). The same rows, labels and typing as Velorona Map's satelliteEvidenceRows() (web/space.js), so an
exported result means the same thing in both products.

Typing: Observed = reported by a named source (station listing, element set); Calculated = derived by a stated method from stated inputs; Assumed = chosen,
typed or defaulted (the analysis time, the minimum elevation unless the user picks the station's own declared horizon); Inferred = a hedged reading. A
calculated position is never typed as a live observation, and a listing status is never presented as verification that a station operates."""

from __future__ import annotations

import re

MIN_ELEVATION_DEFAULT_TEXT = "10 degrees -- the conservative end of the 5-10 degree standard-practice range; no per-site horizon survey"
MAX_WINDOW_ROWS = 12   # individual window rows; the summary row always carries the full count


def fmt_utc(iso) -> str:
    if not iso:
        return "(not within the window)"
    return re.sub(r"\.\d+Z$", "Z", iso.replace("T", " "))


def window_text(w: dict) -> str:
    rise = "already above at the start" if w.get("open_at_start") else fmt_utc(w.get("rise_utc"))
    set_ = "still above at the end" if w.get("open_at_end") else fmt_utc(w.get("set_utc"))
    length = f", {w['duration_sec'] / 60:.1f} min" if w.get("duration_sec") is not None else ""
    return (f"{rise} to {set_}{length}; highest {w['max_elevation_deg']:.1f}° at {fmt_utc(w.get('max_utc'))}, azimuth {w['max_azimuth_deg']:.0f}°, "
            f"closest {w['min_range_km']:.0f} km")


def _row(evidence, type_, source="", observation_input="", calculated_result="", interpretation=""):
    return [evidence, type_, source or "", observation_input if observation_input not in (None, "") else "",
            calculated_result if calculated_result not in (None, "") else "", interpretation or ""]


def evidence_rows(r) -> list:
    alt = getattr(r, "station_altitude_m", None)
    if r.mask_origin == "station":
        mask_source = f"The station's own published horizon ({r.station_source}); its owner's declared tracking limit, used because you asked for it"
    elif r.mask_origin == "user":
        mask_source = "Entered by the user"
    else:
        mask_source = MIN_ELEVATION_DEFAULT_TEXT
    rows = [
        _row(f"Ground station ({r.station_name})", "Observed", f"{r.station_source}; snapshot {r.station_retrieved}",
             f"{r.station_latitude:.4f}, {r.station_longitude:.4f}"),
        (_row("Station altitude", "Observed", r.station_source, f"{alt:g} m") if alt is not None
         else _row("Station altitude", "Assumed", "Not published for this station -- 0 m used", "0 m")),
        (_row("Station listing status", "Observed", f"{r.station_source}; snapshot {r.station_retrieved}", r.station_status, "",
              "A listing status, not verification that the station is operating, authorised, or able to communicate with this satellite.")
         if r.station_status else _row("Station listing status", "Observed", r.station_source, "not published", "", "No status is published for this station.")),
    ]
    if r.station_min_horizon_deg is not None:
        rows.append(_row("Station declared minimum horizon", "Observed", r.station_source, f"{r.station_min_horizon_deg:g} degrees", "",
                         "The station owner's own tracking limit. Shown for context; it is the mask only if you choose it."))
    age = "unknown" if r.epoch_age_days is None else f"{r.epoch_age_days:.2f} days"
    fresh = {"stale": "The element set is old relative to the analysis time: treat positions and window times as unreliable.",
             "aging": "The element set is several days from the analysis time: window times may be off by more than the stated precision.",
             "fresh": "Element set is close to the analysis time. This does not make the prediction exact."}.get(r.epoch_level, "Age could not be determined.")
    rows += [
        _row(f"Satellite ({r.satellite_name})", "Observed", r.satellite_source, f"NORAD {r.norad_cat_id}, element-set epoch {r.tle_epoch}", "",
             "Position accuracy degrades with time from the element-set epoch."),
        _row("Analysis time (UTC)", "Assumed", "Entered by the user" if r.time_origin == "user" else "The clock at the moment of analysis", r.analysis_time_utc, "",
             "All look angles and windows are for this instant and the window after it. They are predictions from an element set, not observations."),
        _row("Orbital data age at the analysis time", "Calculated", "Analysis time minus element-set epoch", f"epoch {r.tle_epoch}", age, r.epoch_note),
        _row("Orbital data freshness", "Inferred", "Age thresholds are an assumed convention (fresh <= 3 d, stale > 14 d)", "", r.epoch_level, fresh),
        _row("Satellite position (at analysis time)", "Calculated", "SGP4 propagation (Skyfield), at the analysis time", "",
             f"{r.sat_latitude:.4f}, {r.sat_longitude:.4f}, {r.sat_altitude_km:.1f} km", "A calculated position, not a live observation."),
        _row("Minimum elevation mask", r.mask_type, mask_source, "", f"{r.min_elevation_mask_deg:g} degrees"),
        _row("Elevation angle", "Calculated", "Observer-relative look angles (Skyfield topocentric altaz)", "", f"{r.elevation_deg:.2f} degrees"),
        _row("Azimuth", "Calculated", "Observer-relative look angles (Skyfield topocentric altaz); from true north, clockwise", "", f"{r.azimuth_deg:.2f} degrees"),
        _row("Slant range", "Calculated", "Observer-relative look angles (Skyfield topocentric altaz)", "", f"{r.slant_range_km:.1f} km"),
        _row("Visibility at the analysis time", "Inferred", "Elevation vs. the minimum-elevation mask", "", "",
             "VISIBLE -- above the mask." if r.visible else "NOT VISIBLE -- below the mask."),
    ]
    mask_s = f"{r.min_elevation_mask_deg:g}"
    if r.windows_error:
        rows.append(_row("Visibility windows", "Calculated", "Window search (Skyfield SGP4, scanned and refined)", "", "not computed", r.windows_error))
    else:
        n = len(r.windows)
        hours = f"{r.window_hours:g}"
        summary = (f"above {mask_s}° for the whole {hours} h" if r.window_state == "always-above"
                   else f"never above {mask_s}° in {hours} h" if r.window_state == "never-above" else f"{n} window{'' if n == 1 else 's'} in {hours} h")
        rows.append(_row("Visibility windows", "Calculated",
                         f"SGP4 elevation scanned every {r.window_step_sec} s from {fmt_utc(r.window_start_utc)} to {fmt_utc(r.window_end_utc)}; "
                         f"each crossing refined by bisection to {r.window_refine_sec} s",
                         f"minimum elevation {mask_s}°", summary,
                         "Geometry only. A window shorter than the scan step could be missed. Not a statement that a link is usable."))
        for i, w in enumerate(r.windows[:MAX_WINDOW_ROWS]):
            rows.append(_row(f"Window {i + 1}", "Calculated", "Same method as above", "", window_text(w)))
        if n > MAX_WINDOW_ROWS:
            rows.append(_row("Further windows", "Calculated", "Same method as above", "", f"{n - MAX_WINDOW_ROWS} more not listed",
                             "Re-run with a shorter interval to see them individually."))
    rows.append(_row("Scope", "Inferred", "", "", "",
                     "Geometry only: no propagation loss, link budget, signal strength, weather exposure, or confirmation that a station may communicate with this satellite."))
    return rows
