"""What a weather analysis writes to the local history: the values it fetched (each time an analysis fetched them; no polling) and the three
numbers it derived from them. Pure Python: reads a MicrowaveAnalysisResult / LinkInvestigation, returns HistoryRecords.

* Open-Meteo `current` -> kind ``model`` (it is neither a measurement nor a forecast: the provider's model value for now).
* ECCC station and radar -> kind ``observed`` (the radar value is radar-ESTIMATED; the source string says so).
* kind ``forecast`` is never written: the plugin does not use a forecast.
* Derived rows (estimated rain attenuation, exposure ratio, status) are marked ``derived`` and take the kind of their input (``model``).
* A value the provider did not report is stored as NO DATA (NULL) with the reason, never as 0.
* Open-Meteo reports the SITE's local time; it is converted to UTC with the offset the provider returned. If the provider gave no offset the
  value cannot be given a true UTC time, so it is not stored (counted as invalid), rather than stored with a wrong one.
* Entities the user supplied (their own sites and links) are stored under a salted hash, not their id (CONTRACT). Public Fixed Service
  records keep their authorization number.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional, Tuple

from . import eccc_coverage
from .history_store import HistoryRecord, HistoryStore, to_utc_text, utc_text
from .presentation.weather import weather_status

MODEL_SOURCE_MAX = 120


def _iso_to_utc_text(text: str) -> Optional[str]:
    """ECCC style '2026-10-06T19:55:00Z' (or with an offset) -> UTC text; None when it cannot be read."""
    try:
        t = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _lib_version() -> str:
    try:
        from importlib.metadata import version
        return f"aei-microwave-link-exposure {version('aei-microwave-link-exposure')}"
    except Exception:
        return "aei-microwave-link-exposure (version unknown)"


def exposure_of(result):
    """The MicrowaveAnalysisResult inside a result (a link investigation wraps one; it may hold none)."""
    return getattr(result, "exposure", None) if getattr(result, "kind", "") == "link-investigation" else result


def is_public(result) -> bool:
    return getattr(result, "kind", "") == "link-investigation"


def entity_ids(result, store: HistoryStore) -> Tuple[str, dict]:
    """(link entity id, {site id: entity id}) as stored: raw for public records, salted hash for the user's own."""
    mw = exposure_of(result)
    link = mw.exposure.link
    keep = (lambda raw: raw) if is_public(result) else store.entity_hash
    return keep(link.id), {s: keep(s) for s in mw.representativeness}


def records_from_result(result, store: HistoryStore, now: float) -> Tuple[List[HistoryRecord], int]:
    """([records], n_not_storable). ``result`` with no weather (link investigation without exposure) gives ([], 0)."""
    mw = exposure_of(result)
    if mw is None or not getattr(mw, "exposure", None):
        return [], 0
    version = _lib_version()
    fetched_now = utc_text(now)
    link_id, site_ids = entity_ids(result, store)
    out: List[HistoryRecord] = []
    skipped = 0
    offsets = getattr(mw, "utc_offsets", {}) or {}
    precipitation = getattr(mw, "precipitation", {}) or {}

    def add(**kw):
        out.append(HistoryRecord(data_version=version, **kw))

    model_ts_for_link = None
    for sid, rep in mw.representativeness.items():
        ent = site_ids[sid]
        obs = rep.model_observation
        if obs is not None:
            offset = offsets.get(sid)
            ts = to_utc_text(obs.timestamp, offset) if offset is not None else None
            if ts is None:
                skipped += 1
            else:
                if sid == mw.exposure.source_site_id:
                    model_ts_for_link = (ts, obs.source)
                fetched = utc_text(obs.fetched_at) if obs.fetched_at else fetched_now
                common = dict(ts=ts, fetched_ts=fetched, source=str(obs.source)[:MODEL_SOURCE_MAX], entity_id=ent, entity_type="site", kind="model")
                p = precipitation.get(sid)
                add(metric="rain_rate", value=obs.rain_rate_mm_h, unit="mm/h", **common)
                add(metric="temperature", value=obs.temperature_c, unit="degC",
                    nodata_reason=None if obs.temperature_c is not None else "the provider did not report it", **common)
                add(metric="wind_speed", value=obs.wind_speed_kmh, unit="km/h",
                    nodata_reason=None if obs.wind_speed_kmh is not None else "the provider did not report it", **common)
                if p is not None:
                    add(metric="snowfall", value=p.snowfall_cm, unit="cm",
                        nodata_reason=None if p.snowfall_cm is not None else "the provider did not report it", **common)
                    add(metric="weather_code", value=None if p.weather_code is None else float(p.weather_code), unit="wmo_code",
                        nodata_reason=None if p.weather_code is not None else "the provider did not report it", **common)
        st = rep.nearest_station
        if st is not None:
            ts = _iso_to_utc_text(st.timestamp)
            if ts is None:
                skipped += 1
            else:
                reports = bool(rep.station_reports_precipitation)
                add(ts=ts, fetched_ts=fetched_now, source=str(st.source)[:MODEL_SOURCE_MAX], entity_id=ent, entity_type="site", kind="observed",
                    metric="rain_rate", value=st.rain_rate_mm_h if reports else None, unit="mm/h",
                    nodata_reason=None if reports else "the station does not publish a precipitation reading")
        rd = rep.radar_observation if eccc_coverage.covers(rep.site.latitude, rep.site.longitude) else None   # never store a radar value from outside Canada
        if rd is not None:
            ts = _iso_to_utc_text(rd.timestamp)
            if ts is None:
                skipped += 1
            else:
                add(ts=ts, fetched_ts=fetched_now, source=str(rd.source)[:MODEL_SOURCE_MAX], entity_id=ent, entity_type="site", kind="observed",
                    metric="rain_rate", value=rd.rain_rate_mm_h, unit="mm/h")

    if model_ts_for_link is None:
        skipped += 3                                    # the three derived numbers cannot be dated without the model observation time
    else:
        ts, _src = model_ts_for_link
        e = mw.exposure
        base = dict(ts=ts, fetched_ts=fetched_now, source="aei-mw-exposure", entity_id=link_id, entity_type="link", kind="model", derived=True)
        add(metric="rain_attenuation_estimate", value=e.attenuation.predicted_attenuation_db, unit="dB", **base)
        add(metric="exposure_ratio", value=e.exposure_ratio, unit="ratio", **base)
        add(metric="status", value=weather_status(e)[0], unit="enum", **base)
    return out, skipped


def capture(result, store: HistoryStore, now: float):
    """Records the result into the store. Never raises: returns the WriteReport (history must not make an analysis fail)."""
    from .history_store import WriteReport
    try:
        records, skipped = records_from_result(result, store, now)
    except Exception as exc:                            # a shape this code did not expect: say so, store nothing
        r = WriteReport()
        r.error, r.message = "other", f"the result could not be turned into history rows ({type(exc).__name__}: {exc})"
        return r
    report = store.add_many(records)
    report.invalid += skipped
    return report
