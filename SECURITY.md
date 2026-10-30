# Security

Velorona for QGIS is public source software. It has no server account, stores no credentials and sends no telemetry.

## Reporting a vulnerability

Please report privately through GitHub: **Security > Report a vulnerability** on https://github.com/AIDEdgeInc-Lab/velorona-qgis-plugin. If that is not available to you, write to the maintainer address in `metadata.txt` with "Velorona security" in the subject. Do not open a public issue for a vulnerability. We aim to answer within 5 working days.

## What the plugin does with data

- **Network:** it reads public sources only (Open-Meteo weather and elevation, ECCC stations, CelesTrak, the public Velorona data packs, the user's chosen pack folder or address). It sends the coordinates of the selected sites to those services, nothing else. It never uploads layers, projects or history.
- **On disk:** history and its site/link names live in `<QGIS profile>/velorona/history.sqlite`; caches in the same folder. Exports are written only where the user chooses. Site names are written to an export only when the user ticks "Include my site names".
- **Untrusted input:** CSV/GeoJSON imports and pack files are treated as data, never executed. Exported text cells that start with `= + - @` are neutralised against spreadsheet formula injection.

## When reporting a problem

Use synthetic coordinates and names. Do not paste private network data, customer information or the contents of `history.sqlite` into issues or screenshots.

## Before a release

`tools/gate.sh` must pass (it includes `bandit` at medium severity and a package verification of the exact ZIP). Release ZIPs are built once, checksummed, and the published copy is compared against that checksum (`.github/workflows/published-verify.yml`).
