"""Satellite geometry -- pure calculation, no QGIS, no network. The Python counterpart of Velorona Map's web/satgeo.js.

What it computes: SGP4 position, observer-relative look angles (elevation, azimuth, slant range) at an EXPLICIT UTC instant, and the windows in which
the elevation is at or above a minimum elevation over a given interval. What it does not compute: propagation loss, link budget, signal strength,
service availability. Geometric visibility is not a working link.

Same semantics as the Map (so a result means the same thing in both products): same validation and refusals, same mask rule, same element-set age
convention, same window search (20 s scan, crossings refined by bisection to 1 s, a window open at either end reported as such, a GEO-type satellite
above the minimum throughout reported as "always-above" with no invented pass). The two products use different SGP4 front ends -- satellite.js in the
Map, Skyfield here -- and tests/test_satellite_geometry.py measures their agreement against the Map's golden output rather than assuming it.

Limits (also stated in every export): element sets are mean-element fits whose error grows from the epoch; no refraction; Skyfield applies its own
Earth-orientation model (the Map applies a GMST rotation) -- the difference is far below element-set error; a pass shorter than one scan step above
the minimum can be missed.
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timedelta, timezone

import numpy as np
from skyfield.api import EarthSatellite, load, wgs84

DEFAULT_MIN_ELEVATION_DEG = 10.0
MAX_WINDOW_HOURS = 72
DEFAULT_STEP_SEC = 20
DEFAULT_REFINE_SEC = 1
# Element-set age thresholds in days either side of the analysis instant: an ASSUMED engineering convention (mean-element sets are refreshed every few
# days and position error grows with age), not a property of any one satellite. Same values as the Map.
EPOCH_FRESH_DAYS = 3
EPOCH_STALE_DAYS = 14

_TS = load.timescale()
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d+))?)?\s*(Z|[+-]\d{2}:?\d{2})?$", re.IGNORECASE)


def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def parse_utc(value) -> datetime | None:
    """A timezone-aware UTC datetime, or None. A string with no zone designator is UTC (CelesTrak EPOCH), never local time."""
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str) or not value.strip():
        return None
    m = _ISO.match(value.strip())
    if not m:
        return None
    y, mo, d, h, mi, s, frac, zone = m.groups()
    micro = int((frac or "0").ljust(6, "0")[:6])
    try:
        dt = datetime(int(y), int(mo), int(d), int(h), int(mi), int(s or 0), micro, tzinfo=timezone.utc)
    except ValueError:
        return None
    if zone and zone.upper() != "Z":
        sign = 1 if zone[0] == "+" else -1
        digits = zone[1:].replace(":", "")
        dt -= sign * timedelta(hours=int(digits[:2]), minutes=int(digits[2:]))
    return dt


def iso_ms(dt: datetime) -> str:
    """ISO-8601 UTC with millisecond precision and a trailing Z -- the same shape as JavaScript's toISOString()."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _ms(dt: datetime) -> int:
    return int(round((dt - _EPOCH).total_seconds() * 1000))


def _from_ms(ms: int) -> datetime:
    return _EPOCH + timedelta(milliseconds=ms)


def resolve_mask(station: dict | None, user_deg=None, use_station_horizon: bool = False) -> dict:
    """The minimum elevation. Default 10 degrees (Assumed); a typed value is Assumed; the station's own published min_horizon_deg is used ONLY on request
    and then typed Observed (it is its owner's declared tracking limit, which Velorona does not silently adopt as the link-geometry mask)."""
    if user_deg is not None:
        if not _is_num(user_deg) or user_deg < 0 or user_deg > 60:
            return {"ok": False, "reason": "The minimum elevation must be a number from 0 to 60 degrees."}
        return {"ok": True, "deg": float(user_deg), "origin": "user", "type": "Assumed"}
    h = (station or {}).get("min_horizon_deg")
    if use_station_horizon:
        if _is_num(h) and 0 <= h <= 60:
            return {"ok": True, "deg": float(h), "origin": "station", "type": "Observed"}
        return {"ok": False, "reason": "This station publishes no usable horizon (0-60 degrees); enter a minimum elevation instead."}
    return {"ok": True, "deg": DEFAULT_MIN_ELEVATION_DEG, "origin": "default", "type": "Assumed"}


def epoch_status(epoch_iso, at) -> dict:
    epoch, when = parse_utc(epoch_iso), parse_utc(at)
    if epoch is None or when is None:
        return {"level": "unknown", "age_days": None, "epoch_utc": None, "note": "The element-set epoch could not be read."}
    age = (when - epoch).total_seconds() / 86400.0
    a = abs(age)
    level = "fresh" if a <= EPOCH_FRESH_DAYS else "aging" if a <= EPOCH_STALE_DAYS else "stale"
    direction = "after" if age >= 0 else "before"
    return {"level": level, "age_days": age, "epoch_utc": iso_ms(epoch),
            "note": (f"Analysis instant is {a:.2f} days {direction} the element-set epoch ({level}; fresh <= {EPOCH_FRESH_DAYS} d, "
                     f"stale > {EPOCH_STALE_DAYS} d -- an assumed convention).")}


def valid_station(station) -> bool:
    if not isinstance(station, dict):
        return False
    lat, lon, alt = station.get("latitude"), station.get("longitude"), station.get("altitude_m")
    return (_is_num(lat) and _is_num(lon) and -90 <= lat <= 90 and -180 <= lon <= 180 and (alt is None or _is_num(alt)))


def _observer(station: dict):
    alt = station.get("altitude_m")
    return wgs84.latlon(station["latitude"], station["longitude"], elevation_m=float(alt) if _is_num(alt) else 0.0)


def satellite_from_omm(record: dict) -> EarthSatellite | None:
    """From a CelesTrak GP/OMM record (used by the tests); None when it cannot be used."""
    try:
        return EarthSatellite.from_omm(_TS, record)
    except Exception:
        return None


def _tle_line_ok(line: str, number: str) -> bool:
    """A TLE line is 69 characters, starts "<number> ", and its last digit is the mod-10 checksum of the first 68 (digits count their value, '-' counts 1)."""
    if not isinstance(line, str) or len(line) != 69 or line[:2] != f"{number} ":
        return False
    total = sum(int(c) if c.isdigit() else 1 if c == "-" else 0 for c in line[:68])
    return line[68].isdigit() and total % 10 == int(line[68])


def satellite_from_tle(line1: str, line2: str, name: str = "") -> EarthSatellite | None:
    """From two TLE lines; None unless both pass the format and checksum test. Skyfield/sgp4 will parse arbitrary text into a numerically valid satellite,
    so a malformed or corrupted element set must be refused here, not computed."""
    if not (_tle_line_ok(line1, "1") and _tle_line_ok(line2, "2")) or line1[2:7] != line2[2:7]:
        return None
    try:
        return EarthSatellite(line1, line2, name, _TS)
    except Exception:
        return None


def look_angles_at(sat: EarthSatellite, station: dict, when) -> dict:
    """Look angles of one satellite from one station at one instant: {ok: True, ...} or {ok: False, reason}."""
    t = parse_utc(when)
    if t is None:
        return {"ok": False, "reason": "The analysis time is not a valid UTC instant."}
    if not valid_station(station):
        return {"ok": False, "reason": "The ground station has no valid latitude/longitude."}
    if sat is None:
        return {"ok": False, "reason": "The orbital elements are invalid."}
    try:
        ts = _TS.from_datetime(t)
        geocentric = sat.at(ts)
        alt, az, dist = (sat - _observer(station)).at(ts).altaz()
        sub = wgs84.subpoint_of(geocentric)
        out = {"ok": True, "time": iso_ms(t), "elevation_deg": float(alt.degrees), "azimuth_deg": float(az.degrees) % 360.0,
               "range_km": float(dist.km), "sub_lat_deg": float(sub.latitude.degrees), "sub_lon_deg": float(sub.longitude.degrees),
               "altitude_km": float(sub.elevation.km)}
    except Exception as exc:
        return {"ok": False, "reason": f"Propagation failed: {exc}"}
    if not all(math.isfinite(out[k]) for k in ("elevation_deg", "azimuth_deg", "range_km")):
        return {"ok": False, "reason": "Propagation produced a non-finite look angle."}
    return out


def _batch(sat, station, ms_list):
    """Elevation, azimuth and range for many instants in ONE Skyfield evaluation (a scalar evaluation costs ~5 ms, mostly the nutation series, so
    refining crossings and maxima point by point made a 24 h search take about a second on the GUI thread). Returns three float arrays; NaN where
    propagation failed."""
    grid = _TS.from_datetimes([_from_ms(int(ms)) for ms in ms_list])
    alt, az, dist = (sat - _observer(station)).at(grid).altaz()
    return (np.asarray(alt.degrees, dtype=float), np.asarray(az.degrees, dtype=float) % 360.0, np.asarray(dist.km, dtype=float))


def _bisect(sat, station, lo, hi, mask, rising, refine_ms):
    """The crossing inside [lo, hi] (below the mask at one end, at/above at the other), to refine_ms. Evaluated on a refine_ms grid in one call:
    the first grid instant at/above the mask (rising) or the last one (falling) -- the same bracket the Map's bisection ends in."""
    ms = list(range(int(lo), int(hi), int(refine_ms))) + [int(hi)]
    el, _az, _rng = _batch(sat, station, ms)
    ok = np.where(np.isfinite(el) & (el >= mask))[0]
    if ok.size == 0:
        return hi if rising else lo
    return ms[int(ok[0])] if rising else ms[int(ok[-1])]


def _peak(sat, station, lo, hi):
    """The instant of maximum elevation in [lo, hi] to 1 s: one grid call when the window is short, otherwise a coarse grid then a 1 s grid around the best."""
    lo, hi = int(lo), int(hi)
    width = hi - lo
    step = 1000 if width <= 1_800_000 else int(math.ceil(width / 1800 / 1000) * 1000)
    ms = list(range(lo, hi, step)) + [hi]
    el, _az, _rng = _batch(sat, station, ms)
    if not np.isfinite(el).any():
        return None
    best = ms[int(np.nanargmax(el))]
    if step > 1000:
        fine = list(range(max(lo, best - step), min(hi, best + step) + 1, 1000))
        el2, _a, _r = _batch(sat, station, fine)
        if not np.isfinite(el2).any():
            return None
        best = fine[int(np.nanargmax(el2))]
    return best


def _finish(sat, station, rise_ms, set_ms, start_ms, end_ms):
    lo = start_ms if rise_ms is None else rise_ms
    hi = end_ms if set_ms is None else set_ms
    peak_ms = _peak(sat, station, lo, hi)
    want = [m for m in (rise_ms, peak_ms, set_ms) if m is not None]
    el, az, rng = _batch(sat, station, want) if want else (np.array([]),) * 3
    at = {m: (float(el[i]), float(az[i]), float(rng[i])) for i, m in enumerate(want)}
    peak = at.get(peak_ms)
    return {
        "rise_utc": None if rise_ms is None else iso_ms(_from_ms(rise_ms)),
        "rise_azimuth_deg": at[rise_ms][1] if rise_ms is not None else None,
        "max_utc": iso_ms(_from_ms(peak_ms)) if peak else None,
        "max_elevation_deg": peak[0] if peak else None,
        "max_azimuth_deg": peak[1] if peak else None,
        "min_range_km": peak[2] if peak else None,
        "set_utc": None if set_ms is None else iso_ms(_from_ms(set_ms)),
        "set_azimuth_deg": at[set_ms][1] if set_ms is not None else None,
        "duration_sec": int(math.floor((set_ms - rise_ms) / 1000 + 0.5)) if rise_ms is not None and set_ms is not None else None,
        "open_at_start": rise_ms is None, "open_at_end": set_ms is None,
    }


def find_windows(sat: EarthSatellite, station: dict, start, end, min_elev_deg, step_sec: int = DEFAULT_STEP_SEC, refine_sec: int = DEFAULT_REFINE_SEC) -> dict:
    """Windows with elevation >= min_elev_deg between start and end (UTC). {ok: True, state, windows, ...} or {ok: False, reason}.

    state: "windows" | "always-above" (above the minimum at every sample, e.g. GEO; windows is then empty) | "never-above"."""
    t0, t1 = parse_utc(start), parse_utc(end)
    if t0 is None or t1 is None:
        return {"ok": False, "reason": "The window start or end is not a valid UTC instant."}
    if t1 <= t0:
        return {"ok": False, "reason": "The window end must be after its start."}
    if (t1 - t0).total_seconds() / 3600.0 > MAX_WINDOW_HOURS:
        return {"ok": False, "reason": f"The window may not exceed {MAX_WINDOW_HOURS} hours."}
    if not _is_num(min_elev_deg) or min_elev_deg < 0 or min_elev_deg > 60:
        return {"ok": False, "reason": "The minimum elevation must be a number from 0 to 60 degrees."}
    if not valid_station(station):
        return {"ok": False, "reason": "The ground station has no valid latitude/longitude."}
    if sat is None:
        return {"ok": False, "reason": "The orbital elements are invalid."}
    step_ms, refine_ms = int(step_sec * 1000), int(refine_sec * 1000)
    s0, s1 = _ms(t0), _ms(t1)
    times = list(range(s0, s1, step_ms)) + [s1]

    # Vectorised scan: one Skyfield evaluation for the whole grid.
    try:
        grid = _TS.from_datetimes([_from_ms(ms) for ms in times])
        alt, _az, _dist = (sat - _observer(station)).at(grid).altaz()
        els = np.asarray(alt.degrees, dtype=float)
    except Exception as exc:
        return {"ok": False, "reason": f"Propagation failed over the window ({exc}); no windows reported."}
    bad = np.where(~np.isfinite(els))[0]
    if bad.size:
        return {"ok": False, "reason": f"Propagation failed at {iso_ms(_from_ms(times[int(bad[0])]))} (the element set may be invalid or decayed at that time); no windows reported."}

    windows = []
    open_rise = None
    is_open = bool(els[0] >= min_elev_deg)
    for i in range(1, len(times)):
        a_above, b_above = bool(els[i - 1] >= min_elev_deg), bool(els[i] >= min_elev_deg)
        if not a_above and b_above:
            open_rise = _bisect(sat, station, times[i - 1], times[i], min_elev_deg, True, refine_ms)
            is_open = True
        if a_above and not b_above and is_open:
            set_ms = _bisect(sat, station, times[i - 1], times[i], min_elev_deg, False, refine_ms)
            windows.append(_finish(sat, station, open_rise, set_ms, s0, times[-1]))
            is_open, open_rise = False, None
    if is_open:
        windows.append(_finish(sat, station, open_rise, None, s0, times[-1]))

    above = els >= min_elev_deg
    state = "always-above" if above.all() else "never-above" if not above.any() else "windows"
    return {"ok": True, "state": state, "windows": [] if state == "always-above" else windows, "min_elevation_deg": float(min_elev_deg),
            "start_utc": iso_ms(t0), "end_utc": iso_ms(t1), "step_sec": step_sec, "refine_sec": refine_sec}


# ---------------------------------------------------------------------
# Plain-language readings of ONE result for three audiences. Same facts, different words, same wording as the Map's plainReadings(): nothing here
# adds a claim the result does not carry, and every reading ends with what geometry cannot establish.
# ---------------------------------------------------------------------

def _fmt_t(iso) -> str:
    if not iso:
        return "?"
    s = iso.replace("T", " ")
    s = re.sub(r"\.\d+Z$", "Z", s)
    return re.sub(r":00Z$", "Z", s)


def _fmt_min(sec) -> str:
    return "unknown length" if sec is None else f"{sec / 60:.1f} min"


def _js_round0(x: float) -> str:
    return str(int(math.floor(x + 0.5)))


def plain_readings(r: dict) -> dict:
    """r: the result fields (analysis_time_utc, elevation_deg, azimuth_deg, visible, min_elevation_mask_deg, mask_origin, mask_type, window_hours,
    windows, window_state, window_start_utc, window_end_utc, window_step_sec, window_refine_sec, tle_epoch, epoch_level, epoch_note, station_status)."""
    w = r.get("windows") or []
    known = [x for x in w if x.get("duration_sec") is not None]
    longest = max((x["duration_sec"] for x in known), default=0)
    total = sum(x["duration_sec"] for x in known)
    at = parse_utc(r["analysis_time_utc"])
    next_win = next((x for x in w if x.get("rise_utc") and parse_utc(x["rise_utc"]) > at), None)
    mask = r["min_elevation_mask_deg"]
    mask_s = f"{mask:g}"
    station_note = (f'The station is listed as "{r["station_status"]}" in the {r.get("station_source_short") or "public listing"}; that is a listing, not verification '
                    "that it is operating or authorised.") if r.get("station_status") else "No status is published for this station."
    cannot = "This is geometry only: it does not show that a link works, that a signal is received, or that the station may communicate with this satellite."
    hours = f"{r['window_hours']:g}"

    if r["visible"]:
        f1 = (f"At {_fmt_t(r['analysis_time_utc'])} the satellite is ABOVE your {mask_s}° minimum: point at azimuth {_js_round0(r['azimuth_deg'])}° "
              f"(from true north, not magnetic) and {_js_round0(r['elevation_deg'])}° up.")
    else:
        el = r["elevation_deg"]
        f1 = (f"At {_fmt_t(r['analysis_time_utc'])} the satellite is NOT above your {mask_s}° minimum "
              f"(it is {_js_round0(abs(el))}° {'below the horizon' if el < 0 else 'up'}).")
    if r.get("window_state") == "always-above":
        f2 = f"It stays above the minimum for the whole {hours} h checked (a geostationary-type orbit)."
    elif r.get("window_state") == "never-above":
        f2 = f"It does not rise above the minimum in the next {hours} h."
    elif next_win:
        f2 = (f"Next window: {_fmt_t(next_win['rise_utc'])} to {_fmt_t(next_win['set_utc']) if next_win.get('set_utc') else 'after the checked period'}, "
              f"highest {_js_round0(next_win['max_elevation_deg'])}° at azimuth {_js_round0(next_win['max_azimuth_deg'])}° (from true north, not magnetic).")
    else:
        f2 = "No new window starts in the checked period."
    f3 = ("WARNING: the orbit data is old; the pointing may be wrong." if r.get("epoch_level") == "stale"
          else "The orbit data is a few days old; re-check before relying on it." if r.get("epoch_level") == "aging" else "")
    field = " ".join(x for x in (f1, f2, f3, cannot) if x)

    if r.get("window_state") == "always-above":
        p1 = f"Continuously above {mask_s}° for the whole {hours} h window."
    elif r.get("window_state") == "never-above":
        p1 = f"No time above {mask_s}° in the {hours} h window."
    else:
        p1 = f"{len(w)} window{'' if len(w) == 1 else 's'} above {mask_s}° in {hours} h" + (f"; longest {_fmt_min(longest)}, total {_js_round0(total / 60)} min." if known else ".")
    basis = {"station": "the station's published horizon", "user": "entered by you"}.get(r.get("mask_origin"), "default")
    planner = " ".join([p1, f"Minimum elevation: {mask_s}° ({basis}); no site horizon survey was applied.",
                        f"Orbit data: {r.get('epoch_note') or 'epoch unknown'}", station_note, cannot])

    analyst = " ".join([
        f"SGP4 (Skyfield) from the element set with epoch {r['tle_epoch']}; look angles at {r['analysis_time_utc']} (UTC).",
        f"Mask {mask_s}° ({r.get('mask_type')}, origin: {r.get('mask_origin')}). Window scan {r.get('window_step_sec')} s step, bisection to {r.get('window_refine_sec')} s, "
        f"interval {_fmt_t(r.get('window_start_utc'))} to {_fmt_t(r.get('window_end_utc'))}.",
        f"Not modelled: refraction, element-set error growth beyond the stated age; a pass shorter than the step above the mask can be missed. {cannot}",
    ])
    return {"field": field, "planner": planner, "analyst": analyst}
