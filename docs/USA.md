# United States data in Velorona for QGIS

Status: **first release; not validated.** Parity with Velorona Map is demonstrated on 20 frozen US fixtures (decision statuses, evidence, provenance, NO DATA), which shows the two products decide the same way from the same input. It is not a validation of the physics, of the FCC data, or of any operational outcome, and no severity rate is claimed for US links.

## Source
U.S. Federal Communications Commission, Universal Licensing System (ULS) public access database, microwave services (`l_micro`). The data is a public record; it is **licensee-reported record data, not a field measurement**. Attribution used on the layer and in exports (from the pack's own metadata): *"Source: U.S. Federal Communications Commission, Universal Licensing System (ULS) public access database, microwave services (l_micro). Data as published; not endorsed by the FCC."* The source-file date and the pack-build date are shown with it.

## Getting the data in (guided)
Nothing here runs at plugin start. Open **Explore: USA Data Setup…**, or press **Explore: Load USA Links in View** the first time; the same window opens.
1. **Use Velorona's online USA data** — the pack Velorona Map serves at `https://map.velorona.ai/data/us/`. Nothing is downloaded until you load a view. Or
2. **Choose a folder…** — a USA data pack on your computer: one folder that directly contains `index.json` and `tiles/` (about 14 MB). If you pick the folder above it, Velorona finds the pack inside when there is exactly one. Or
3. **A web address (https)** — the address that serves `index.json`.
The window then checks the data (index plus one real tile) and shows **Ready** with the link count and source date from the data itself, or **Problem** with what to do (folder not found, `index.json` missing, incomplete or damaged data, a data version this release does not understand, address unreachable). **Use this data** is enabled only after a successful check; **Cancel** changes nothing; **Forget the saved setting** removes it. The setting is saved in the QGIS project (never in your global QGIS settings); the environment variable `VELORONA_USA_PACK` is the fallback.
4. Zoom to an area and **Explore: Load USA Links in View**. Only the 1° tiles touching the view are read. The index's own counts are checked first: more than 20,000 links or 36 tiles is refused ("zoom in"). Links that cross a tile edge appear once. If you cancel the first-time window, a note says that nothing was loaded and Canada is unaffected.
A `.json` source (an older regional-extract file, set through the environment variable or a project that already uses it) is still read; its raw FCC antenna-height values are ignored (see below).

## What is analysed, and what is assumed
* **Frequency** — highest of the record's frequencies, in MHz ÷ 1000 → GHz. Observed while unchanged; Assumed once you change it.
* **Antenna heights** — 30 m, **Assumed**. The FCC field "Height to Center RAAT" exists in the raw record, but the FCC's field documentation states neither its unit nor its reference (and does not define "RAAT"), so by the shared heights contract it is not used in any decision (Map `parity/contract/HEIGHTS_CONTRACT.md` section 2). A height you enter is Assumed.
* **Polarization, fade margin** — Assumed (not published by the FCC).
* **Weather** — Open-Meteo model values. The ECCC station/radar cross-check covers Canada only; for US links it reports "Not determined". A highest frequency below 1 GHz is outside the rain model's range: **weather NO DATA** (13,079 of 250,874 links, 5.21 %); terrain is still decided.
* **Terrain** — Open-Meteo elevation (Copernicus GLO-90, a 90 m surface model). A rate-limited or failed lookup is reported as unavailable elevation (NO DATA with the reason), never as a status.
* **Site A / Site B** follow the pack's ordering, not a transmit / receive role.

## Limits
* Only licences with status A are in the pack; flags on a record are review hints, not policy; some records are plainly wrong (e.g. a 7,577 km path) and are shown.
* The standard pack carries no antenna heights, gains, azimuths or power.
* The coordinate datum is not stated by the FCC definitions document (NAD83 is the FCC filing convention): treated as WGS84 degrees, an effect far below the 90 m terrain model's resolution (INFERRED, not measured).
* The Operator (licensee) filter covers the Canadian layers only; US layers can be searched in the Records table. The "shared endpoint" context lists only links in the currently loaded view.
