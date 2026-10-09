# ISED column 29 — verified citation (QGIS workstream, 2026-10-09)

The Map workstream's note (HEIGHT_AND_PLAUSIBILITY_MAP.md) gave the source; this file records that the QGIS workstream fetched and read it itself.

| item | value |
|---|---|
| Document | Spectrum Management System (SMS) Authorization Data Extract – Field Descriptions (ISED Canada), PDF, 21 pages, created 2019-04-09 |
| URL | https://ised-isde.canada.ca/site/spectrum-management-system/sites/default/files/attachments/2022/tafl_description_ltaf.pdf |
| Retrieved | 2026-10-09 ~01:36 UTC (HTTP 200, 967,013 bytes) |
| sha256 | `8ee1ef262e44e512b8fb914a4b292575cdb442acc5a207a9422ad54f45c6ab5c` (identical to the Map workstream's copy) |
| Scope | one column table (columns 1–61) shared by the seven service files "Aeronautical, Broadcast, Fixed, Maritime, Satellite (earth stations), Spectrum Licensing", CSV only, monthly |
| Column 29 | **"Height above ground level [m]"** (fr. "Hauteur au-dessus du niveau du sol [m]"), NUMERIC, section ANTENNA INFORMATION |
| Related | 1 Station function (TX/RX) · 2 Frequency [MHz] · 41 Latitude (WGS84) · 42 Longitude (WGS84) · 43 Ground elevation above mean sea level [m] · 44 Antenna structure height above ground level [m] · 48 Authorization number |
| NOT stated | whether the height is to the antenna centre or tip; what several values at one endpoint mean. Also: the document is dated 2019/2022 while the data file is 2026-09-01 — checked only by layout (61 columns on all 109,292 rows, column 1 ∈ {TX,RX}, 2/41/42 numeric) |
| Consistency with the data (OBSERVED, `stage1/results/q8/col29_profile.out`) | 100 % filled; ≤ column 44 in 99.4 %; far below column 43; column 43 matches the DEM (median ratio 0.9979) |
| Raw copy | `~/velorona-parity-audit/snapshots/raw/ised/tafl_description_ltaf.pdf` (+ `d.txt`, pdftotext -layout) |

Provenance wording used by the plugin: "ISED SMS Authorization Data Extract (Fixed Service), column 29 'Height above ground level [m]', record-reported value, source file dated YYYY-MM-DD".

## Update 2026-10-09 (stage 2, final)
The plugin no longer reads the raw CSV. It bundles the Map's snapshot schema `velorona.ca-ised-fixed/1.1` (sha256 `e10a3ad16d23c6ca07334bc66bf985b2574b5db8de777d4ce5978d1a0e88c50e`, byte-identical), whose builder checks the column layout fail-closed on every build (Map `HEIGHTS_CONTRACT.md` section 1). Value rule: the first raw row (file order) per endpoint (the QGIS "lowest in-range" proposal was withdrawn to match the Map).
