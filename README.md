# Velorona for QGIS

**Velorona QGIS Plugin 1.1.10** — Telecom link evidence, inside QGIS.

Velorona puts public fixed-service telecom infrastructure (Canada and the United States) on your QGIS map, checks whether a radio link has line-of-sight clearance, estimates its rain exposure, and gives you the evidence behind every answer: what was observed, what was calculated, and what was assumed. It is for telecom and microwave-link engineers, spectrum and infrastructure analysts, and GIS users who need an answer and its justification, not just a number.

## Explore → Select → Analyze → Evidence → Export

1. **Explore** — Load public telecom infrastructure and your own data.
2. **Select** — Choose a site, link, or two endpoints.
3. **Analyze** — Run path clearance (one link, or many links at once), microwave weather exposure, or satellite geometry.
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

Use **Explore: Load Public Data** to start a Velorona project. Each source covers its own real geography.

**Canada (bundled, no download).** ISED Fixed Service sites and links (national; snapshot dated 2026-09-01, 24,859 sites and 16,956 links) are on by default, drawn as clusters that become individual sites and links as you zoom in. Present but off by default: Ontario GeoHub tower structures (Ontario), ISED cellular/mobile sites (Canada-wide) — both queried live for the area you view — CelesTrak satellites (global, live) and SatNOGS ground/earth stations (global, bundled snapshot).

**United States (FCC ULS microwave links) — loaded automatically.** USA data is on by default, as in Velorona Map, and needs no setup:

* After **Explore: Load Public Data**, zoom to the United States. **At broad scales** you see pale **overview count bubbles** (layer *USA overview (counts, not records)*): approximate counts of FCC sites in 2° areas. They show where the infrastructure is; they are not individual records, cannot be selected and are not listed in Records.
* **Zoom into a smaller area** (about a state-sized window; the limit is 36 one-degree map tiles or 20,000 links per view) and the **detailed USA sites and links** of that view load by themselves (layers *Fixed Service sites (USA)* and *Fixed Service links (USA)*); the sites are drawn as the same subtle clusters as Canada's, and the bubbles disappear. **Pan or zoom and the data follows the map**; a view inside tiles already loaded reads nothing new. A view that is too large keeps the overview (and what was last loaded) and says so in the Records note; zoom in for records.
* **USA data needs internet access.** Velorona reads Velorona's online USA data (the pack Velorona Map serves) and downloads only the tiles under the view you look at, never the whole country. The data is not included in the plugin (size; the FCC refreshes it weekly). One message states that the online data is used. Nothing is read in a QGIS project that has no Velorona layers, and **Canada works without it**.
* **Controls.** **Explore: USA Data Setup…** lets you read the data from a folder on your computer or another https address instead, **Forget the saved setting** (back to the online default), or **Turn USA data off** (nothing is then loaded automatically; the same is set by the environment variable `VELORONA_USA_PACK=off`). **Explore: Load USA Links in View** loads the current view on demand and shows the USA links in Records. Switching every USA layer off also stops loading. A broken or unreachable source is a quiet note in Records (retried after a minute), not a pop-up on every pan.
* Source: U.S. Federal Communications Commission, Universal Licensing System (ULS) public access database (`l_micro`); the source-file date, pack date and attribution are shown on the layer and written into every export. It is licensee-reported record data, not a field measurement. See [docs/USA.md](docs/USA.md).

**Basemap imagery is not infrastructure data.** The base map and the optional **USA Aerial Imagery & Topo (USGS)** layers (off by default; US only) are pictures of the ground. They are not Velorona records and do not produce clusters; the USA sites, links, overview bubbles and clusters above are separate Velorona layers.

Import your own point data via QGIS's native Add Layer — it appears on the same map, analyzed the same way as public data.

## Analysis engines (Analyze)

Three, all reused unmodified:

- **Terrestrial Path Clearance** (`aei_link_clearance`) — Fresnel-zone /
  earth-curvature terrain clearance between two selected sites, or for ONE
  selected Fixed Service link (its endpoints, highest published frequency and,
  where the licensee reported them, antenna heights are used; the frequency is
  typed Observed only while you leave it unchanged).
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

### Many links at once (terrain clearance batch)

**Processing Toolbox ▸ Velorona ▸ Terrain clearance for many Fixed Service links**, or **Plugins ▸ Velorona ▸ Analyze: Terrain Clearance for Many Links (batch)**.

- Runs the Terrestrial Path Clearance above for every link of a line layer, or only its selected links, and writes **one row per link** with its status and reason. Each row is the same calculation as analysing that link on its own with the dialog's pre-filled values: the record's highest published frequency (Observed) and its antenna heights where the record carries them (Observed), otherwise 30 m (Assumed).
- **Statuses per link:** CLEAR, WATCH, AT RISK, CRITICAL (the terrain result), **NO DATA** (a required input is missing or invalid, or elevation could not be retrieved — the reason is in the table, nothing is guessed), **ERROR** (an unexpected failure for that link) and **NOT RUN** (not attempted: over the limit, or the run was cancelled). One failing link never stops the others, and the input layer is never changed.
- **Runs in the background** through QGIS's Processing framework, with progress and **Cancel**. Cancelling stops after the link in progress; links not reached are listed as NOT RUN, none are dropped.
- **Limits:** up to 100 links per run by default (1,000 at most; a larger input is refused up front), terrain clearance only (no weather or satellite batch). Each link makes one elevation request; the elevation service rate-limits requests made close together — a rate-limited link is reported as NO DATA (transient, "try again"), never as a result — so use the **pause between links** (0–30 s; several seconds for more than a handful of links). A record without a published frequency is NO DATA unless you give a **fallback frequency** (then typed Assumed). Layers that are not Velorona Fixed Service layers carry no record frequency or heights, so give a fallback frequency.
- Optional **CSV** output. See [docs/BATCH_TERRAIN.md](docs/BATCH_TERRAIN.md).

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
highlights its row. The Operator filter covers the Canadian layers (the USA layers can be searched in the table).

## Evidence (the Results/Evidence dock)

Every result is organized into sections, never QGIS's generic Attribute
Table, labeled Observed / Calculated / Inferred. Terrestrial Path Clearance
and Microwave Weather Exposure both export the full canonical structure. See
`docs/EVIDENCE_EXPORT_AUDIT.md` for the exact current export schema and
known gaps against a canonical Evidence/Type/Source/Observation-Input/
Calculated-result/Interpretation structure.

## Export

- **CSV** — a single result, a single record, a selection summary, and the batch. Exports carry product, library and data-source information as `#` comment lines above the table. **CSV safety:** text cells (names, identifiers, licensees, source and reason text) that begin with `=`, `+`, `-` or `@` are marked with a leading apostrophe so Excel and Numbers do not run them as formulas; calculated numbers, including negative ones, are unchanged. The apostrophe is visible when you open a CSV.
- **Excel (.xlsx)** — for terrain, weather and Fixed Service link results: Summary, Link Analysis, Weather, Weather History, Elevation-Terrain, Evidence, Raw Data (un-rounded values with unit, source and calculation) and Data Dictionary. Cells are stored as plain values and text, never as formulas, so the original text is kept without the CSV apostrophe.
- Satellite geometry is a computed snapshot at one instant and is not exported.

## Requirements

QGIS 4.0–4.99 (validated against QGIS 4.2.2 / Qt 6.11.1 / Python 3.12), with
`aei-microwave-link-exposure`, `aei-link-clearance`, `aei-geo-features` and
`skyfield` installed into QGIS's own Python environment (not your system
Python). On macOS that interpreter is:

```
/Applications/QGIS-final-4_2_2.app/Contents/MacOS/python3.12 -m pip install \
    skyfield 'aei-microwave-link-exposure>=0.2.0,<0.3' 'aei-link-clearance>=0.2.0,<0.3' aei-geo-features
```

**Installing the packages from inside QGIS** (any platform where QGIS's Python ships pip; verified on macOS QGIS 4.2.2): Plugins → Python Console, then run

```
from pip._internal.cli.main import main; main(['install', '-U', 'aei-link-clearance>=0.2.0,<0.3', 'aei-microwave-link-exposure>=0.2.0,<0.3', 'aei-geo-features', 'skyfield'])
```

and restart QGIS. **QGIS does not install Python packages for plugins** (the `plugin_dependencies` field in `metadata.txt` names other QGIS plugins only), so installing Velorona
from the Plugin Manager or from the ZIP leaves these packages to you; if they are missing Velorona loads a stub that shows this instruction, and if `aei-link-clearance` is
outside its supported range (`aei-link-clearance>=0.2.0,<0.3`, `aei-microwave-link-exposure>=0.2.0,<0.3`) it warns when QGIS starts and refuses the first terrain analysis with the same instruction.

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

Velorona is published in the **QGIS Plugin Repository** ([plugins.qgis.org/plugins/velorona](https://plugins.qgis.org/plugins/velorona/)) and as a ZIP on [GitHub Releases](https://github.com/AIDEdgeInc-Lab/velorona-qgis-plugin/releases). In QGIS: **Plugins → Manage and Install Plugins**, search for *Velorona* and install; or download the ZIP from GitHub and use **Install from ZIP**. Then install the Python packages listed under Requirements (QGIS does not install them for you).

## Version history

**1.1.10** — Terrain-clearance **batch** (Processing algorithm and menu action, cancellable, one row per link); **USA data on by default** with overview count bubbles when zoomed out and detailed sites, links and clusters that load automatically as you pan; selection and layer-lifecycle fixes (stale selection after a reload, removed layers, Records highlight, active layer); **CSV formula-injection protection**; clearer provenance wording in Details; imagery group renamed *USA Aerial Imagery & Topo (USGS)*. No change to terrain or weather calculations, thresholds, statuses, Canada data or the satellite engine.

Earlier releases: 1.1.9 field readability and stated data status; 1.1.8 satellite data path; 1.1.7 UI polish (also carries the 1.1.6 guided USA data setup); 1.1.5 corrected earth curvature, ITU-R P.838-3 rain model, five-level status contract, Observed/Assumed provenance, Canadian antenna heights and first USA support; 1.1.4 operational output (Summary / Details / Evidence, Ask, Excel). Full details: [CHANGELOG.md](CHANGELOG.md) and the [release pages](https://github.com/AIDEdgeInc-Lab/velorona-qgis-plugin/releases).

## Status

Version 1.1.10. Packaged and clean-profile install tested for QGIS 4.x (validated on QGIS 4.2.2). Velorona is decision support for operational analysis, not a field measurement and not an outage prediction.
