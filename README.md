# Velorona for QGIS

**Velorona QGIS Plugin 1.1.5** — Telecom link evidence, inside QGIS.

## Explore → Select → Analyze → Evidence → Export

1. **Explore** — Load public telecom infrastructure and your own data.
2. **Select** — Choose a site, link, or two endpoints.
3. **Analyze** — Run path clearance, microwave weather exposure, or satellite geometry.
4. **Evidence** — See what is observed, what is calculated, and what is inferred.
5. **Export** — Take the evidence with you as a structured CSV result or an Excel (.xlsx) workbook.

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

**United States (FCC ULS microwave links).** Not bundled — the dataset is far larger than the plugin and the FCC refreshes it weekly. Point
Velorona at a Velorona USA data pack (a folder on your computer or an https address) with **Explore: Set USA Data Pack Source**, then zoom to the
area you want and run **Explore: Load USA Links in View**. Only the map tiles that touch the view are read, never the whole country, and a view
that would load more than 20,000 links is refused with a request to zoom in. Source: U.S. Federal Communications Commission, Universal Licensing
System (ULS) public access database (`l_micro`); the source-file date, pack date and attribution are shown on the layer and written into every
export. It is licensee-reported record data, not a field measurement. See [docs/USA.md](docs/USA.md).

## Analysis engines (Analyze)

Three, all reused unmodified:

- **Terrestrial Path Clearance** (`aei_link_clearance`) — Fresnel-zone /
  earth-curvature terrain clearance between two selected sites, or for ONE
  selected Fixed Service link (its endpoints and highest published frequency
  are used; the frequency is typed Observed only while you leave it unchanged).
- **Microwave Weather Exposure** (`aei_mw_exposure`) — ITU-R P.530
  rain-attenuation exposure between two selected sites, or for a selected
  link, with live Open-Meteo/ECCC weather evidence. The rain coefficients come
  from the library: `aei-microwave-link-exposure` up to 0.1.5 used a table that
  differs from ITU-R P.838-3 in 21 of 24 rows (rain loss understated, most at
  6-10 GHz); 0.2.0 evaluates the Recommendation's equations. Velorona spot-checks
  the installed model against the Recommendation's Table 5 (6, 10 and 38 GHz) and
  shows an open-issue notice on weather results while that check fails
  (docs/RAIN_COEFFICIENTS_CAVEAT.md). The check is not a validation of the model.
- **Satellite / Earth-Space** (`skyfield`/SGP4) — look-angle geometry
  (elevation, azimuth, slant range, visibility) between a selected ground
  station and satellite.

## Status, NO DATA and where a value came from

Every result has a status: **CLEAR, WATCH, AT RISK, CRITICAL or NO DATA**. NO DATA means a required input was missing or invalid (invalid
coordinates, identical endpoints, no elevation, an unusable weather interval, a frequency outside the rain model's 1–100 GHz range, an antenna
height outside 0.1–1000 m): the reason is shown and no status is guessed. A data-pack problem (missing, corrupt, wrong version, unreachable) is
reported as a pack problem, never as a link's NO DATA. Each input is typed **Observed** (a named source reports it), **Model-derived**,
**Calculated**, **Inferred** or **Assumed** (a default, or anything you typed or changed — never Observed). The 30 m antenna height is an
assumption unless the record carries a height. WATCH for terrain is a clearance ratio below 1.3, a provisional threshold that is neither
physics-validated nor operator-validated.

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
    skyfield 'aei-microwave-link-exposure>=0.2.0,<0.3' 'aei-link-clearance>=0.2.0,<0.3' aei-geo-features
```

`aei-microwave-link-exposure` must be 0.2.0 or newer (0.2.x): 0.2.0 evaluates the ITU-R P.838-3 rain equations. `aei-link-clearance` must be 0.2.0 or newer (0.2.x): 0.2.0 corrects the earth-curvature sign, and the plugin
refuses to run against an older release rather than show overstated clearance.

The ISED Fixed Service and SatNOGS snapshots the Explore step needs are
bundled in `data/` — no extra download or configuration. The USA data pack is
not bundled (see Data sources).

## Dark workspace

Velorona's dock inherits the QGIS palette and hard-codes no background
colours, so it follows whatever application theme you choose. To match the
CARTO Dark Matter basemap, set QGIS itself to a dark theme:

Settings → Options → General → **UI Theme → Night Mapping**, then restart
QGIS. Velorona does not change this setting for you — it is a global QGIS
preference that affects every plugin and project.

## Install

Velorona is distributed via the project's GitHub Release, not the QGIS
Plugin Repository. Download `velorona-1.1.5.zip` from the
[v1.1.5 release](https://github.com/AIDEdgeInc-Lab/velorona-qgis-plugin/releases/tag/v1.1.5),
then in QGIS: Plugins → Manage and Install Plugins → Install from ZIP, and
pick that file.

## Status

Version 1.1.5. Packaged and clean-profile install tested for QGIS 4.x.
Distributed via GitHub Release; not yet submitted to the QGIS Plugin
Repository.
