"""Terrain-clearance brief: aei_link_clearance's result, said plainly.

Nothing is recalculated. `available` and `required` are the library's own
`terrain_clearance_m` and `required_clearance_m` at its critical point; the
margin is their difference. The library's `clearance_ratio` and
`percent_fresnel_clear` stay available under `technical`.

Status mapping (a presentation of the library's own classification, no new
threshold):

    obstructed (< 30 % of first Fresnel zone cleared)       -> CRITICAL
    marginal   (30-60 %)                                    -> AT RISK
    clear but ratio < COMFORTABLE (1.3, strictly below)     -> WATCH
    clear                                                   -> CLEAR
    no profile                                              -> NO DATA

COMFORTABLE (1.3) is aei_link_clearance.explain.COMFORTABLE_MARGIN_RATIO. It is a PROVISIONAL operational threshold carried over from
QGIS 1.1.4 (owner decision P2): not physics-validated and not operator-validated. near_threshold (the library's elevation-uncertainty
check) is a verification FLAG shown beside the status; it never changes the status (owner decision P3).
"""

from __future__ import annotations

import math
from .model import link_title, AT_RISK, CLEAR, CRITICAL, NO_DATA, NOT_DETERMINED, WATCH, Brief, Fact, exact, fmt, signed

# Mirrors of library constants, kept in sync by tests/test_presentation_terrain.py
# so this module stays importable without the aei_* packages (QGIS-free tests).
COMFORTABLE_MARGIN_RATIO = 1.3   # provisional carried-over operational threshold (P2); the single definition in the plugin
ELEVATION_UNCERTAINTY_M = 15.0
CLEAR_THRESHOLD = 0.60
OBSTRUCTED_THRESHOLD = 0.30
# The library's definition (aei_link_clearance.terrain.analyze_link), stated wherever
# the critical / "tightest" point appears. Do not shorten it to "lowest clearance".
CRITICAL_POINT_DEFINITION = (
    "The critical (tightest) point is where the Fresnel-zone clearance fraction (clearance divided by the "
    "first Fresnel radius) is lowest. It is not necessarily where the absolute terrain clearance in metres is lowest.")
ELEVATION_SOURCE = "Open-Meteo Elevation API (Copernicus DEM GLO-90, 90 m surface model)"


def critical_point(r):
    """The profile point the library chose as critical: the interior sample
    with the lowest fraction-of-Fresnel-zone clearance (terrain.analyze_link)."""
    interior = [p for p in r.profile if p.percent_fresnel_clear is not None]
    if interior:
        return min(interior, key=lambda p: p.percent_fresnel_clear)
    return r.profile[len(r.profile) // 2] if r.profile else None


def terrain_status(r) -> tuple:
    """(status, one-line reason, plain answer) from the library's own result."""
    if not r.profile:
        return (NO_DATA, "Elevation data could not be retrieved for this path.",
                "No answer: there is no elevation data for this path.")

    available, required = r.terrain_clearance_m, r.required_clearance_m
    margin = available - required

    if r.los_status == "obstructed":
        if available < 0:
            reason = (f"Terrain rises {fmt(-available)} m above the line of sight at the tightest point, "
                      f"{fmt(required)} m of clearance is required.")
        else:
            reason = (f"Clearance is {fmt(available)} m at the tightest point, less than half of the "
                      f"{fmt(required)} m required.")
        return (CRITICAL, reason, "The terrain blocks or nearly blocks the path.")
    if r.los_status == "marginal":
        return (AT_RISK, f"Clearance is {fmt(-margin)} m below the required minimum at the tightest point.",
                "Terrain is closer to the path than recommended.")
    if r.clearance_ratio < COMFORTABLE_MARGIN_RATIO:
        return (WATCH, "Clearance is above the minimum, but the margin is small.",
                "Terrain clears the path, with little room to spare.")
    return (CLEAR, "Available terrain clearance is well above the required minimum.",
            "Terrain is well above the required clearance.")


def ratio_value(r) -> str:
    return "unbounded" if math.isinf(r.clearance_ratio) else f"{r.clearance_ratio:.2f}×"


def ratio_meaning(r) -> str:
    """What the ratio means at this value. Negative is valid, not an error: the
    library divides clearance by the requirement without clamping, so it is below
    zero exactly when the terrain is above the line of sight."""
    if r.terrain_clearance_m < 0:
        return ("Negative: the terrain is above the line of sight, so there is no clearance at all "
                "(1× would be exactly the minimum)")
    if r.clearance_ratio < 1:
        return "Below 1×: less clearance than the required minimum (1× is exactly the minimum)"
    return "1× is exactly the minimum"


def margin_phrase(available: float, required: float) -> str:
    """Margin in words. A negative margin means the terrain intrudes into the
    clearance the link needs; when clearance itself is negative it is above the line of sight."""
    margin = available - required
    if margin >= 0:
        return f"{fmt(margin)} m above the minimum"
    text = f"Terrain is inside the required clearance envelope by {fmt(-margin)} m"
    if available < 0:
        text += f" and {fmt(-available)} m above the line of sight"
    return text


def terrain_explanation(r) -> str:
    """The sentence shown wherever the library's explain() used to be shown: a
    direct physical comparison, with the ratio as a multiple and no percentages.
    The library's own explain() text is still produced and kept in the data."""
    if not r.profile:
        return "Elevation data could not be retrieved for this path."
    avail, req = r.terrain_clearance_m, r.required_clearance_m
    ratio = ratio_value(r)
    if avail < 0:
        text = (f"Terrain is {fmt(-avail)} m above the line of sight at the critical point; {fmt(req)} m of "
                f"clearance is required, so the path is short by {fmt(req - avail)} m.")
    elif avail < req:
        text = (f"{fmt(avail)} m available vs {fmt(req)} m required at the critical point: short by "
                f"{fmt(req - avail)} m (available is {ratio} the required minimum).")
    else:
        text = (f"{fmt(avail)} m available vs {fmt(req)} m required at the critical point: {fmt(avail - req)} m "
                f"of margin ({ratio} the required minimum).")
    if r.near_threshold:
        text += (f" A difference of about {fmt(ELEVATION_UNCERTAINTY_M, 0)} m in elevation could change the "
                 f"result; verify with a survey before relying on it.")
    return text


def terrain_brief(result) -> Brief:
    """`result` is a TerrestrialAnalysisResult (duck-typed)."""
    r = result.result
    status, reason, answer = terrain_status(r)
    crit = critical_point(r)
    available, required = r.terrain_clearance_m, r.required_clearance_m
    margin = available - required
    location = f"{result.site_a_name} → {result.site_b_name}"
    heading = link_title((getattr(result, "record", None) or {}).get("authorization_number"))

    where = ""
    if crit is not None:
        where = f"{fmt(crit.distance_from_a_km)} km from {result.site_a_name}"

    key_facts = [
        Fact("Path", f"{fmt(r.distance_km)} km", f"Analysis frequency {exact(r.frequency_ghz)} GHz", "Link distance"),
        Fact("Clearance available", f"{fmt(available)} m",
             f"at the critical point{', ' + where if where else ''}"
             + (f"; negative means the terrain is {fmt(-available)} m above the line of sight" if available < 0 else ""),
             "Terrain clearance at the point with the lowest Fresnel-zone clearance fraction"),
        Fact("Clearance required", f"{fmt(required)} m", "60% of the first Fresnel zone at that point", "Minimum required"),
        Fact("Margin", f"{signed(margin)} m", margin_phrase(available, required),
             "Positive means there is room to spare"),
    ]
    technical = [
        Fact("Critical point", where or NOT_DETERMINED, "lowest Fresnel-zone clearance fraction", CRITICAL_POINT_DEFINITION),
        Fact("Clearance ratio", ratio_value(r), "available / required clearance", ratio_meaning(r)),
        Fact("First Fresnel radius", f"{fmt(r.first_fresnel_radius_m)} m", "at the tightest point",
             "Radius of the zone that should stay mostly free of obstacles"),
        Fact("Fresnel zone clear", f"{r.percent_fresnel_clear * 100:.0f}% of the first Fresnel radius",
             f"clear ≥{CLEAR_THRESHOLD * 100:.0f}%, marginal ≥{OBSTRUCTED_THRESHOLD * 100:.0f}%",
             "Negative means the terrain is above the line of sight" if r.percent_fresnel_clear < 0
             else "Share of the first Fresnel radius that is clear at the critical point"),
        Fact("Bearing", f"{fmt(r.bearing_deg)}°", "from Site A to Site B"),
        Fact("Effective earth radius factor k", exact(r.k_factor), "standard atmosphere (ITU-R P.530 median)"),
        Fact("Antenna height A", f"{exact(result.site_a_height_m)} m", _origin(result.site_a_height_from_feature)),
        Fact("Antenna height B", f"{exact(result.site_b_height_m)} m", _origin(result.site_b_height_from_feature)),
    ]
    evidence = [
        Fact("Evidence", f"{len(r.profile)} elevation samples along the path"),
        Fact("Elevation source", ELEVATION_SOURCE),
        Fact("Calculation", "aei_link_clearance.analyze_link (ITU-R P.530 Fresnel zone, earth-curvature adjusted)"),
        Fact("Site A source", result.site_a_source),
        Fact("Site B source", result.site_b_source),
        Fact("Frequency source", "Entered by the user in the analysis dialog (not taken from licence data)"),
    ]
    caveats = [
        CRITICAL_POINT_DEFINITION,
        f"Elevation comes from a 90 m surface model; a different but equally valid source can differ by about "
        f"{fmt(ELEVATION_UNCERTAINTY_M, 0)} m at one point."
    ]
    if r.near_threshold:
        caveats.append("Result is near a classification boundary: a survey could move it to the next status.")

    inspect = ""
    if crit is not None and status != CLEAR:
        inspect = (f"Inspect the terrain about {fmt(crit.distance_from_a_km)} km from {result.site_a_name} "
                   f"(lat {crit.latitude:.5f}, lon {crit.longitude:.5f}).")

    return Brief(
        kind="terrain", title="Terrain clearance", location=location, heading=heading, status=status, reason=reason, answer=answer,
        key_facts=key_facts, technical=technical, evidence=evidence, caveats=caveats, inspect=inspect,
        data={
            "link_id": r.link_id, "distance_km": r.distance_km, "bearing_deg": r.bearing_deg,
            "frequency_ghz": r.frequency_ghz, "k_factor": r.k_factor,
            "first_fresnel_radius_m": r.first_fresnel_radius_m, "required_clearance_m": required,
            "terrain_clearance_m": available, "margin_m": margin, "clearance_ratio": r.clearance_ratio,
            "percent_fresnel_clear": r.percent_fresnel_clear, "los_status": r.los_status,
            "near_threshold": r.near_threshold, "samples": len(r.profile),
            "critical_distance_from_a_km": crit.distance_from_a_km if crit else None,
            "critical_latitude": crit.latitude if crit else None,
            "critical_longitude": crit.longitude if crit else None,
            "site_a_name": result.site_a_name, "site_b_name": result.site_b_name,
            "profile": profile_rows(r),
            "explanation": terrain_explanation(r),
            "library_explanation": getattr(result, "explanation", ""),
        },
    )


def _origin(from_feature: bool) -> str:
    return "from the feature's own attribute" if from_feature else "entered by the user (default shown, user-confirmed)"


def profile_rows(r) -> list:
    """The full sampled profile, one dict per sample, for the workbook."""
    crit = critical_point(r)
    rows = []
    for i, p in enumerate(r.profile):
        rows.append({
            "sample": i + 1, "distance_from_a_km": p.distance_from_a_km, "latitude": p.latitude,
            "longitude": p.longitude, "ground_elevation_m": p.ground_elevation_m,
            "earth_bulge_m": p.earth_bulge_m, "terrain_adjusted_m": p.terrain_adjusted_m,
            "los_height_m": p.los_height_m, "fresnel_radius_m": p.fresnel_radius_m,
            "clearance_m": p.clearance_m, "percent_fresnel_clear": p.percent_fresnel_clear,
            "critical": p is crit,
        })
    return rows

