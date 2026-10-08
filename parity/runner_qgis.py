#!/usr/bin/env python3
"""Parity runner for Velorona for QGIS. Calls the plugin's own engine and presentation code; only the network edge is replaced.

    python3 parity/runner_qgis.py <fixture.json> [...]   -> JSON array on stdout

Coupling (documented, not hidden):
* The plugin imports `qgis.core` at module level in core/features.py, which core/engines/microwave_exposure.py imports. A system
  Python has no QGIS, so this runner registers an EMPTY stand-in `qgis.core` (three placeholder names). Nothing in the decision path
  uses them; they exist only so the real `analyze_sites()` can be imported.
* aei-link-clearance is the released PyPI package (>=0.2.0,<0.3), as a shipped QGIS loads it; the other aei_* libraries are
  taken from the installed packages, falling back to sibling checkouts only when absent.
* Terrain: `requests.get` is replaced (elevation.py imports requests lazily), so the library's own get_elevations() (count check, float()) runs.
* Weather: TypedPrecipitationProvider(get=...) takes an injected HTTP getter; ECCC station/radar lookups are replaced by "none" and the
  hourly-history fetcher raises (history is context only, not a decision input -- microwave_exposure.py).
"""
import csv, io, json, os, sys, types
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPOS = os.path.dirname(ROOT)
sys.path.insert(0, ROOT)
import importlib.util
# Installed (PyPI) packages win; a sibling checkout is used only for a library that is not installed. aei-link-clearance has no
# sibling fallback: the plugin requires the released package (>=0.2.0,<0.3).
for mod, r in (("aei_mw_exposure", "aei-microwave-link-exposure"), ("aei_geo_features", "aei-geo-features")):
    if importlib.util.find_spec(mod) is None:
        sys.path.insert(0, os.path.join(REPOS, r, "src"))
if "qgis" not in sys.modules:
    q = types.ModuleType("qgis"); qc = types.ModuleType("qgis.core")
    class _Placeholder:
        def __init__(self, *args, **kwargs): pass
    for n in ("QgsCoordinateReferenceSystem", "QgsCoordinateTransform", "QgsProject"):
        setattr(qc, n, _Placeholder)
    q.core = qc; sys.modules["qgis"] = q; sys.modules["qgis.core"] = qc

import aei_link_clearance.terrain as terrain_mod
from aei_link_clearance import analyze_link, explain
from core import export
from core.engines import microwave_exposure as mw
from core.engines import terrestrial as tr
from core.validation import NoDataError
from core.presentation import terrain as pterrain, weather as pweather
from core.presentation.model import NO_DATA


def rows_from_csv(text):
    reader = csv.reader(io.StringIO(text)); out = []; seen = False
    for row in reader:
        if not seen:
            seen = row[:2] == ["Evidence", "Type"]; continue
        if row: out.append([row[0], row[1]])
    return out


def terrain_stage(fx):
    t, L = fx["terrain"], fx["link"]
    a, b = L["site_a"], L["site_b"]
    import requests as rq   # elevation.py imports requests lazily inside get_elevations(), so the module attribute is the seam
    class Resp:
        def __init__(self, body, err=None): self.body, self.err = body, err
        def raise_for_status(self):
            if self.err: raise rq.exceptions.HTTPError(self.err)
        def json(self): return self.body
    def fake_get(url, params=None, timeout=None):
        if t["mode"] == "error": return Resp(None, t["error"])
        return Resp({"elevation": [s[2] for s in t["samples"]]})   # nulls included, as a provider could return them
    orig = rq.get
    rq.get = fake_get          # the library's own get_elevations() runs; only the HTTP edge is replaced
    try:
        try:
            params = {"site_a_height_m": a["height_m"], "site_b_height_m": b["height_m"], "frequency_ghz": L["frequency_ghz"]}
            r = tr.analyze_endpoints(a["lat"], a["lon"], b["lat"], b["lon"], params, fx["id"])
        except NoDataError as exc:
            return {"noData": exc.reasons, "native_status": "NO DATA", "via": "core.engines.terrestrial.analyze_endpoints()"}
        except Exception as exc:                      # not NO DATA: reported as UNEXPECTED so it can never pass as a decision
            return {"error": "%s: %s" % (type(exc).__name__, exc), "unexpected": True, "via": "core.engines.terrestrial.analyze_endpoints()"}
    finally:
        rq.get = orig
    res = SimpleNamespace(kind="terrestrial", site_a_name="Site A", site_b_name="Site B", site_a_source="ISED Fixed Service record",
                          site_b_source="ISED Fixed Service record", site_a_height_m=a["height_m"], site_b_height_m=b["height_m"],
                          site_a_height_from_feature=False, site_b_height_from_feature=False, result=r, explanation=explain(r))
    brief = pterrain.terrain_brief(res)
    crit = pterrain.critical_point(r)
    return {
        "geometry": {"distance_km": r.distance_km, "bearing_deg": r.bearing_deg},
        "clearance": {"critical_index": next(i for i, p in enumerate(r.profile) if p is crit), "critical_distance_from_a_km": crit.distance_from_a_km,
                      "available_m": r.terrain_clearance_m, "required_m": r.required_clearance_m,
                      "margin_m": r.terrain_clearance_m - r.required_clearance_m, "ratio": r.clearance_ratio,
                      "percent_fresnel_clear": r.percent_fresnel_clear, "fresnel_radius_m": r.first_fresnel_radius_m},
        "los_status": r.los_status, "near_threshold": r.near_threshold, "native_status": brief.status,
        "explanation": pterrain.terrain_explanation(r), "status_reason": brief.reason,
        "provenance": rows_from_csv(export.result_to_csv(res)),
    }


def weather_stage(fx):
    w, L = fx["weather"], fx["link"]
    a, b = L["site_a"], L["site_b"]

    import requests.exceptions as rq_exc
    class Resp:
        def __init__(self, body): self.body = body
        def raise_for_status(self):
            if self.body is None: raise rq_exc.HTTPError(w["error"])
        def json(self): return {"current": self.body}

    def get(url, params=None, timeout=None):
        if "api.open-meteo.com/v1/forecast" not in url: raise RuntimeError("unexpected URL in parity run: " + url)
        if w["mode"] == "error": return Resp(None)
        site = "A" if abs(params["latitude"] - a["lat"]) < 1e-9 else "B"
        return Resp(w["sites"][site]["open_meteo_current"])

    src = "ISED Fixed Service record"
    params = {"frequency_ghz": L["frequency_ghz"], "polarization": L["polarization"], "fade_margin_db": L["fade_margin_db"]}
    origins = {"frequency_ghz": (L["frequency_origin"], "fixture"), "polarization": ("Assumed", "fixture"), "fade_margin_db": ("Assumed", "fixture")}

    def no_history(*args, **kw): raise RuntimeError("history is not part of the parity fixture")
    saved = (mw.eccc.find_nearest_station, mw.eccc.get_radar_precipitation)
    mw.eccc.find_nearest_station = lambda *x, **k: None
    mw.eccc.get_radar_precipitation = lambda *x, **k: None
    try:
        try:
            res = mw.analyze_link_record((a["lat"], a["lon"]), (b["lat"], b["lon"]), {"authorization_number": fx["id"], "source": src}, params,
                                         provider=mw.TypedPrecipitationProvider(get=get), history_fetcher=no_history)
        except NoDataError as exc:
            return {"noData": exc.reasons, "native_status": "NO DATA", "via": "core.engines.microwave_exposure.analyze_link_record()"}
        except Exception as exc:
            return {"error": "%s: %s" % (type(exc).__name__, exc), "unexpected": True, "via": "core.engines.microwave_exposure.analyze_link_record()"}
    finally:
        mw.eccc.find_nearest_station, mw.eccc.get_radar_precipitation = saved
    brief = pweather.exposure_brief(res, origins)
    e = res.exposure; att = e.attenuation
    p = res.precipitation.get(e.source_site_id)
    return {
        "precip": {"rate_mm_h": e.rain_rate_mm_h, "basis": p.basis if p else None, "class": p.precip_class if p else None, "flags": list(p.flags) if p else [],
                   "driver_site": e.source_site_id, "total_mm": p.total_mm if p else None, "rain_mm": p.rain_mm if p else None,
                   "showers_mm": p.showers_mm if p else None, "snowfall_cm": p.snowfall_cm if p else None, "frozen_mm": p.frozen_mm if p else None,
                   "has_frozen": p.has_frozen if p else None},
        "exposure": {"path_km": att.path_length_km, "specific_attenuation_db_km": att.specific_attenuation_db_km,
                     "effective_path_km": att.effective_path_length_km, "attenuation_db": att.predicted_attenuation_db,
                     "ratio": e.exposure_ratio, "severity": e.severity, "fade_margin_db": e.link.fade_margin_db,
                     "fade_remaining_db": e.link.fade_margin_db - att.predicted_attenuation_db},
        "native_status": brief.status, "status_reason": brief.reason, "caveats": brief.caveats,
        # The Fixed Service link flow (plugin.py: run_link_investigation) exports a LinkInvestigation, whose rows follow the parameter ORIGINS.
        "provenance": rows_from_csv(export.result_to_csv(SimpleNamespace(
            kind="link-investigation", exposure=res, param_origins=origins, weather_error=None,
            entry=SimpleNamespace(data={"authorization_number": fx["id"], "source": src, "frequencies_mhz": fx["selection"]["published_frequencies_mhz"]},
                                  site_a_point=(a["lat"], a["lon"]), site_b_point=(b["lat"], b["lon"]))))),
    }


if __name__ == "__main__":
    out = []
    for path in sys.argv[1:]:
        fx = json.load(open(path))
        t, w = terrain_stage(fx), weather_stage(fx)
        from core.presentation.model import worst    # the plugin's own worst-of (owner-approved P6)
        st = lambda d: d.get("native_status")
        out.append({"product": "qgis", "fixture": fx["id"], "terrain": t, "weather": w, "overall": worst(st(t), st(w)) if st(t) and st(w) else None})
    json.dump(out, sys.stdout, indent=1)
