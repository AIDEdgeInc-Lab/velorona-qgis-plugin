# Velorona for QGIS

**Velorona QGIS Plugin 1.0.0** — Telecom link evidence, inside QGIS.

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

## Records (the Velorona dock)

The Velorona dock has two tabs. **Records** is a curated table over the
Velorona layers already loaded — dataset picker, search, sortable columns —
so you can browse and find a link without reading QGIS's generic Attribute
Table (which stays available if you want it). Selecting a row selects that
feature on the map and opens its evidence; selecting a feature on the map
highlights its row.

## Evidence (the Results/Evidence dock)

Every result is organized into sections, never QGIS's generic Attribute
Table, labeled Observed / Calculated / Inferred. Terrestrial Path Clearance
and Microwave Weather Exposure both export the full canonical structure. See
`docs/EVIDENCE_EXPORT_AUDIT.md` for the exact current export schema and
known gaps against a canonical Evidence/Type/Source/Observation-Input/
Calculated-result/Interpretation structure.

## Requirements

QGIS 4.0–4.99 (validated against QGIS 4.2.2 / Qt 6.11.1 / Python 3.12), with
`aei-microwave-link-exposure`, `aei-link-clearance`, `aei-geo-features` and
`skyfield` installed into QGIS's own Python environment (not your system
Python). On macOS that interpreter is:

```
/Applications/QGIS-final-4_2_2.app/Contents/MacOS/python3.12 -m pip install \
    skyfield aei-microwave-link-exposure aei-link-clearance aei-geo-features
```

The ISED Fixed Service and SatNOGS snapshots the Explore step needs are
bundled in `data/` — no extra download or configuration.

## Dark workspace

Velorona's dock inherits the QGIS palette and hard-codes no background
colours, so it follows whatever application theme you choose. To match the
CARTO Dark Matter basemap, set QGIS itself to a dark theme:

Settings → Options → General → **UI Theme → Night Mapping**, then restart
QGIS. Velorona does not change this setting for you — it is a global QGIS
preference that affects every plugin and project.

## Install

Velorona is distributed via the project's GitHub Release, not the QGIS
Plugin Repository. Download `velorona-1.0.0.zip` from the
[v1.0.0 release](https://github.com/AIDEdgeInc-Lab/velorona-qgis-plugin/releases/tag/v1.0.0),
then in QGIS: Plugins → Manage and Install Plugins → Install from ZIP, and
pick that file.

## Status

Version 1.0.0. Packaged and clean-profile install tested for QGIS 4.x.
Distributed via GitHub Release; not yet submitted to the QGIS Plugin
Repository.
