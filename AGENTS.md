# Velorona QGIS plugin

Visibility: **PUBLIC**. Every committed change must be safe for public disclosure: no private notes, no tokens, no customer or operator data, no internal URLs.

## Scope

A QGIS 4 (Qt6) plugin for telecom infrastructure analysis: public site/link records (Canada ISED, USA FCC ULS), terrain path clearance, microwave rain exposure and satellite look angles, with typed evidence (Observed, Model-derived, Reference data (DEM), Calculated, Assumed, Inferred) and NO DATA instead of guesses. It is the desktop twin of Velorona Map (https://map.velorona.ai); both must give the same status, evidence and NO DATA for the same input.

Read `CONTEXT.md` for the vocabulary. Read `docs/QUALITY.md` before changing tests or release steps.

Important areas:

- `plugin.py`: entry point, menu, selection, background tasks.
- `core/engines/`: thin wrappers around the shared libraries `aei-link-clearance` and `aei-mw-exposure` (never re-implement their physics here).
- `core/validation.py`, `core/presentation/`, `core/export.py`: NO DATA rules, evidence typing, exports.
- `core/history_*.py`: local history; the rules come from the shared package `aei-history-contract` (never fork them in the plugin).
- `core/messages.json` / `core/messages.py`: a copy of the Map's message registry (IDs + short texts). Refresh with `tools/sync_messages.py`; never edit by hand.
- `ui/`: dock, dialogs, Records table.
- `parity/`: the Map/QGIS parity runner.
- `tests/`: pure-Python tests (`test_*.py`) and real-QGIS offscreen suites (`qgis_*_e2e.py`).

## Commands

```sh
python -m pytest -q tests                 # pure-Python tests
sh tools/gate.sh                          # the local release gate (unit, Qt6 enums, ruff, bandit, package, QGIS suites, parity)
sh tools/package.sh                       # dist/velorona-<version>.zip
python tools/sync_messages.py <Map>/web/messages.json
```

The QGIS suites import `velorona.*`: run them through a directory link named `velorona` that points at this checkout (see `tools/gate.sh`). Set `MAP_REPO` to a Velorona Map checkout for the parity lane.

## Conventions and safety

- Use `qgis.PyQt` imports and fully qualified Qt6 enums (`tools/check_qt6_enums.py`).
- Never invent a value: a missing input is NO DATA with a stated reason. Never call a model value observed, never call elevation Observed.
- Network calls happen in `QgsTask` workers, never on the interface thread; respect HTTP 429 (back off, then NO DATA "try again in a minute").
- Same situation as the Map = same message ID and wording (from the registry).
- The plugin sends no telemetry and writes nothing outside the user's QGIS profile and the files the user chooses.
- Leave generated artifacts alone: `dist/`, `__pycache__/`, `.pytest_cache/`, `.ruff_cache/`.
- Public interfaces with other repositories: the PyPI libraries (`aei-link-clearance`, `aei-mw-exposure`, `aei-history-contract`), the Map's message registry and data packs. Coordinate changes with the Map.
