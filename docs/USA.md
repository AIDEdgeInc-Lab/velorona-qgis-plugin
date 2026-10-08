# United States data in Velorona for QGIS

Status: **first release; not validated.** Parity with Velorona Map is demonstrated on 20 frozen US fixtures (decision statuses, evidence, provenance, NO DATA), which shows the two products decide the same way from the same input. It is not a validation of the physics, of the FCC data, or of any operational outcome, and no severity rate is claimed for US links.

## Source
U.S. Federal Communications Commission, Universal Licensing System (ULS) public access database, microwave services (`l_micro`). The data is a public record; it is **licensee-reported record data, not a field measurement**. Attribution used on the layer and in exports (from the pack's own metadata): *"Source: U.S. Federal Communications Commission, Universal Licensing System (ULS) public access database, microwave services (l_micro). Data as published; not endorsed by the FCC."* The source-file date and the pack-build date are shown with it.

## Getting the data in
1. Obtain a Velorona USA data pack (the Velorona Map project builds it; see its `docs/USA_FCC_ULS_PACK.md`). It is a folder containing `index.json` and `tiles/`, about 14 MB, refreshed when the FCC file is. It is **not** inside the plugin (size and update cadence).
2. **Explore: Set USA Data Pack Source** — a folder path or an https address. The source is checked immediately and the result (found, missing, corrupt, wrong version, unreachable) is shown. It is saved in the QGIS **project** (Velorona never writes your global QGIS settings); if the project has none, the environment variable `VELORONA_USA_PACK` is used.
3. Zoom to an area and **Explore: Load USA Links in View**. Only the 1° tiles touching the view are read. The index's own counts are checked first: more than 20,000 links or 36 tiles is refused ("zoom in"). Links that cross a tile edge appear once.
4. A `.json` source (instead of a folder) is read as a *regional extract* (`velorona.usa-extract/1`), which also carries the licensee-reported FCC antenna height ("Height to Center RAAT").

## What is analysed, and what is assumed
* **Frequency** — highest of the record's frequencies, in MHz ÷ 1000 → GHz. Observed while unchanged; Assumed once you change it.
* **Antenna heights** — not in the standard pack: 30 m, **Assumed**. From an extract: the record value, Observed, labelled "antenna height to centre (FCC field 'Height to Center RAAT'), licensee-reported record value, metres, interpreted as above ground; not a field measurement". Outside 0.1–1000 m → NO DATA, never clamped.
* **Polarization, fade margin** — Assumed (not published by the FCC).
* **Weather** — Open-Meteo model values. The ECCC station/radar cross-check covers Canada only; for US links it reports "Not determined". A highest frequency below 1 GHz is outside the rain model's range: **weather NO DATA** (13,079 of 250,874 links, 5.21 %); terrain is still decided.
* **Terrain** — Open-Meteo elevation (Copernicus GLO-90, a 90 m surface model). A rate-limited or failed lookup is reported as unavailable elevation (NO DATA with the reason), never as a status.
* **Site A / Site B** follow the pack's ordering, not a transmit / receive role.

## Limits
* Only licences with status A are in the pack; flags on a record are review hints, not policy; some records are plainly wrong (e.g. a 7,577 km path) and are shown.
* The standard pack carries no antenna heights, gains, azimuths or power.
* The coordinate datum is not stated by the FCC definitions document (NAD83 is the FCC filing convention): treated as WGS84 degrees, an effect far below the 90 m terrain model's resolution (INFERRED, not measured).
* The Operator (licensee) filter covers the Canadian layers only; US layers can be searched in the Records table. The "shared endpoint" context lists only links in the currently loaded view.
