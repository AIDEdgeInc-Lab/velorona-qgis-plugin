# Session handoff — 2026-09-18

What shipped, what was deliberately deferred, and what's still open — so
the next session doesn't have to re-derive any of it. Everything below is
verified against the actual merged state, not assumed.

## Repo state

| | velorona-qgis-plugin | aei-microwave-link-exposure |
|---|---|---|
| URL | https://github.com/AIDEdgeInc-Lab/velorona-qgis-plugin | https://github.com/AIDEdgeInc-Lab/aei-microwave-link-exposure |
| Visibility | **Private** | **Public** (published on PyPI) |
| `main` commit | `7950b28` | `b58ddaa` |
| Working tree | clean, in sync with `origin/main` | clean, in sync with `origin/main` |
| Test suite | **427/427** (`tests/run_qgis_tests.sh`), exit 0 | **113/113** (`pytest tests`) |
| Local branches | `main` only | `main`, plus a pre-existing local-only `web/map-first-ui` (predates this session, no remote counterpart — not touched) |

Plugin confirmed to actually import and boot in real QGIS from this exact
`main` checkout (not a branch): `Load Public Data` returns 24,859 Fixed
Service sites, 16,956 links, 4,461 Ground/Earth Stations; the dock and
Operator combo construct correctly. Installed `aei_mw_exposure` is **0.1.4**
(`~/.local/lib/python3.12/site-packages`), with the frequency-precision fix
present in the installed copy, not just on disk in the library repo.

## Shipped this session

| # | PR | Merge commit | What |
|---|---|---|---|
| 1 | [velorona-qgis-plugin#1](https://github.com/AIDEdgeInc-Lab/velorona-qgis-plugin/pull/1) | `9627a10` | Multi-record selection export (previously `NotExportable`) + provenance preamble (filter, count, extent, timestamp) |
| 2 | [velorona-qgis-plugin#2](https://github.com/AIDEdgeInc-Lab/velorona-qgis-plugin/pull/2) | `227d691` | Bulk export cap raised 200 → 25,000, split into three named constants (`SELECTION_TABLE_LIMIT` / `SELECTION_LISTING_LIMIT` / `SELECTION_SCAN_LIMIT`) so the Records-widget render cost and the export-capture cost stop sharing one budget |
| 3 | [velorona-qgis-plugin#3](https://github.com/AIDEdgeInc-Lab/velorona-qgis-plugin/pull/3) | `2fe11d0` | Numeric precision fixes: frequency/height/fade-margin no longer truncated in evidence rows (`_exact()` shortest-round-trip formatting); parameter bounds added with sourcing — ITU-R P.838-3 tabulated range, library-enforced `>0` checks, or an explicitly labelled engineering judgment where no citable source exists |
| 4 | [velorona-qgis-plugin#4](https://github.com/AIDEdgeInc-Lab/velorona-qgis-plugin/pull/4) | `9d0a290` | Six-colour layer-type system (CIEDE2000-separated, deuteranopia/protanopia/tritanopia-checked, per-appearance contrast floors) wired into the cluster renderer; Operator filter exposed — sites+links+cellular, anchored matching (not exact-string), visible from dock creation |
| 5 | [velorona-qgis-plugin#5](https://github.com/AIDEdgeInc-Lab/velorona-qgis-plugin/pull/5) | `38d394c` | CelesTrak fetch timeout: split `(connect, read)` timeout + bail out on `ConnectionError` instead of retrying a dead host 5×. Measured 75.1s → 5.0s against the live (unreachable) host |
| 6 | [velorona-qgis-plugin#6](https://github.com/AIDEdgeInc-Lab/velorona-qgis-plugin/pull/6) | `7950b28` | Status message on `iface.messageBar()` while the (now-bounded) satellite fetch runs, with a plain failure explanation instead of silently reverting to blank |
| — | [aei-microwave-link-exposure#3](https://github.com/AIDEdgeInc-Lab/aei-microwave-link-exposure/pull/3) | `417ee6f` | `estimate_rain_attenuation()`'s `assumption` string reproduces the caller's frequency exactly (was `.0f`-truncated, contradicting the same value shown elsewhere in the same evidence row) |
| — | [aei-microwave-link-exposure#4](https://github.com/AIDEdgeInc-Lab/aei-microwave-link-exposure/pull/4) | `b58ddaa` | Release 0.1.4, shipping the above fix; built and installed locally so the running plugin actually has it, not just the library repo |

## Deliberately deferred

From the original UX audit — still valid findings, not urgent, not
started:

- **Export filename derived from result identity** (audit item #4) — the
  export dialog still offers a generic default filename rather than one
  built from the record/selection being exported.
- **Session-scoped parameter persistence** (audit item #5) — analysis
  parameters (frequency, fade margin, antenna height) don't carry over
  between runs within a session. Explicitly **not** `QgsSettings` —
  `tests/qgis_e2e.py` asserts the plugin never writes one; any persistence
  fix has to hold in-memory, per-session state instead.
- **Persistent hover-hint cards in `param_dialog.py`** (audit item #6) —
  no inline help text for what each analysis parameter means.
- **Shared blocking-call wrapper across `plugin.py`** (audit item #7) —
  the wait-cursor/`processEvents()`/`finally`-restore pattern is
  duplicated at each blocking call site (weather fetch, satellite fetch,
  terrestrial analysis) rather than factored into one helper. The
  satellite-fetch status message added this session (PR #6) is scoped
  narrowly to Satellites only, by design — it does not attempt this
  wrapper.
- **`rain_rate_mm_h` precision** — flagged as a possible truncation
  concern earlier in this session, but never reproduced live: Open-Meteo
  was returning 503s or CelesTrak-adjacent outages for most of this
  session's live-data work, so the actual precision Open-Meteo returns for
  rain rate was never directly observed end-to-end. Worth a real check
  next time the provider is confirmed healthy, before assuming it needs a
  fix.

## Known open items (not code, or need a decision first)

- **map.velorona.ai**: minimal onboarding/About panel — not yet built.
- **velorona.ai**: the Map → QGIS → SDK → Pilot showcase page — design
  only, not yet built anywhere.
- **A real, successful CelesTrak fetch has never been measured this
  session.** CelesTrak was unreachable (TCP connect hangs, confirmed
  repeatedly via direct `curl`) for the entire duration of this session's
  satellite work. PR #5's 75.1s → 5.0s numbers are the **failure** path,
  measured against the actual dead host, not simulated. Propagation itself
  was benchmarked separately on real TLEs from AMSAT (0.089 ms/satellite,
  linear to at least 1,200 satellites) since that stage doesn't need
  CelesTrak specifically. What's still unmeasured: how long a *working*
  5-group fetch takes, and the real deduped satellite count. If a
  successful fetch turns out slow enough to be felt, moving it off the GUI
  thread (audit item #7's territory) is the natural follow-up — worth
  timing once the service is reachable, before building that speculatively.

## Correction to this handoff's own brief

The task that produced this document assumed both repos are private.
**`aei-microwave-link-exposure` is public** — it's the PyPI-published
package (`pip install aei-microwave-link-exposure`), and was already
public before this session started. Only `velorona-qgis-plugin` is
private. Noted here rather than silently confirmed.
