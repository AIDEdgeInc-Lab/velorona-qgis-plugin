# Velorona for QGIS

Telecom link evidence, inside QGIS.

## Explore → Select → Analyze → Evidence → Export

1. **Explore** — Load public telecom infrastructure and your own data.
2. **Select** — Choose a site, link, or two endpoints.
3. **Analyze** — Run path clearance, microwave weather exposure, or satellite geometry.
4. **Evidence** — See what is observed, what is calculated, and what is inferred.
5. **Export** — Take the evidence with you as a structured CSV/GeoJSON result.

## What this is

A local QGIS plugin that runs Velorona's existing, unmodified engineering
libraries — [`aei-link-clearance`](https://github.com/AIDEdgeInc-Lab) and
[`aei-microwave-link-exposure`](https://github.com/AIDEdgeInc-Lab/aei-microwave-link-exposure)
— against public telecom/space data or your own imported data, inside QGIS.
No new engineering logic lives here; this plugin only adapts QGIS features
into those libraries' existing function calls and presents their existing
results.

## Data sources (Explore)

Every public source Velorona Map already ships, each at its own real
geographic coverage — hero (on by default): ISED Fixed Service sites and
links (national); context (present, off by default): Ontario GeoHub tower
structures (Ontario), ISED cellular/mobile sites (Canada-wide), CelesTrak
satellites (global), SatNOGS ground/earth stations (global). Import your
own point data via QGIS's native Add Layer — it appears on the same map,
analyzed the same way as public data.

## Analysis engines (Analyze)

Three, all reused unmodified:

- **Terrestrial Path Clearance** (`aei_link_clearance`) — Fresnel-zone /
  earth-curvature terrain clearance between two selected sites.
- **Microwave Weather Exposure** (`aei_mw_exposure`) — ITU-R P.530/P.838-3
  rain-attenuation exposure between two selected sites, with live
  Open-Meteo/ECCC weather evidence.
- **Satellite / Earth-Space** (`skyfield`/SGP4) — look-angle geometry
  (elevation, azimuth, slant range, visibility) between a selected ground
  station and satellite.

## Evidence (the Results/Evidence dock)

Every result is organized into sections, never QGIS's generic Attribute
Table, labeled Observed / Calculated / Inferred wherever the underlying
result distinguishes them (currently: Microwave Weather Exposure). See
`docs/EVIDENCE_EXPORT_AUDIT.md` for the exact current export schema and
known gaps against a canonical Evidence/Type/Source/Observation-Input/
Calculated-result/Interpretation structure.

## Requirements

QGIS 3.22–4.99, with `aei-microwave-link-exposure`, `aei-link-clearance`,
and `skyfield` installed into QGIS's own Python environment (not your
system Python) — see `docs/` for the exact install commands verified
against this project's QGIS install.

## Status

Experimental / local development plugin — not yet packaged for the QGIS
Plugin Repository.
