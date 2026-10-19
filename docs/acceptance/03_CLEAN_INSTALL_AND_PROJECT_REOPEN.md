# 03 — Clean install and saved-project reopening

## 1. Clean QGIS profile and candidate ZIP
1. Build the candidate (a release engineer, not part of this task): from the worktree `~/velorona-repos/_worktrees/qgis-finalize` run `./tools/package.sh` then `python3 tools/verify_package.py dist/velorona-<version>.zip`. Record the **commit hash** (the staged tree must be committed first by the owner, or record "uncommitted staged tree" plus `git diff --cached | shasum -a 256`) and the ZIP's **SHA-256**. These do not exist yet; do not invent them.
2. New profile: QGIS ▸ Settings ▸ User Profiles ▸ New Profile… name `velorona_acceptance`. Switch to it (QGIS restarts). Confirm Plugins ▸ Manage shows no Velorona.
3. Required libraries must be present in that QGIS's Python (README Requirements: `aei-link-clearance` 0.2.x, `aei-microwave-link-exposure` 0.2.x, `aei-geo-features`, `skyfield`). Record versions (Python console: `import importlib.metadata as m; print([m.version(x) for x in ('aei-link-clearance','aei-microwave-link-exposure','aei-geo-features','skyfield')])`).
4. Install from ZIP (INS-01). For the 1.1.9 comparison use a second profile `velorona_baseline` with the published ZIP.

## 2. Disposable test project
- Project ▸ New; Save As `~/velorona-acceptance/<date>/PRJ/accept.qgz` (a new folder; never an existing project).
- Settings ▸ Options ▸ Data Sources: note the *Save and restore memory layers*/*scratch layers* behaviour of this QGIS version; when saving a project that contains memory layers QGIS prompts — record exactly what the prompt offers and what you chose.

## 3. Scratch copies for edits
Export the needed features (Right-click layer ▸ Export ▸ Save Selected Features As… ▸ GeoPackage) into `~/velorona-acceptance/<date>/scratch/`. Edit only those.

## 4. Saved-project reopening tests
Velorona's public-data layers are in-memory layers. Whether QGIS restores them (with their features) on reopening depends on the QGIS save prompt; the test records the actual behaviour and checks Velorona's reaction to it. The plugin must stay enabled in the profile.

### PRJ-01 Save the project with the Velorona layers
- **Pre:** clean profile, plugin installed, disposable project. **Steps:** Explore: Load Public Data; select one Fixed Service link (Records row) and one site (map click); switch one USA imagery layer on (if the layer exists); optionally USA Data Setup (online) and note the saved setting; Project ▸ Save (answer the memory-layer prompt; record the answer).
- **Expect:** save completes without error. **Evidence:** screenshot of the prompt, file size of `accept.qgz`. **Severity:** S1 on error.

### PRJ-02 Close and reopen
- **Steps:** Project ▸ Close (or quit QGIS), restart, Project ▸ Open Recent ▸ `accept.qgz`.
- **Expect (record which case applies):** (a) memory layers not restored: the layer tree shows what QGIS restored; no Velorona error; Load Public Data repopulates **without duplicate layers or groups**. (b) layers restored with data: they appear once each, grouped as before.
- **Fail if:** Python error on open; duplicate groups/layers after Load Public Data; the Velorona panel referencing a layer that is not in the project. **Severity:** S1.

### PRJ-03 Plugin reconnects to the right layers
- **Steps (case b, or after Load Public Data in case a):** select a record by map click on each restored Velorona layer.
- **Expect:** Details open for the clicked record, **once** per click; Records dataset follows. In the Python console `qgis.utils.plugins['velorona']._wired_layers` has one entry per Velorona vector layer (keys = layer ids).
- **Fail if:** clicking does nothing (layer not wired), updates twice, or shows another record. **Severity:** S1.

### PRJ-04 No stale selection or details
- **Steps:** immediately after opening (before clicking anything) look at Records and Details.
- **Expect:** empty state, no highlighted row, no old record details, no selection restored on the map from the earlier session (QGIS does not persist selection; nothing should pretend otherwise). **Severity:** S1.

### PRJ-05 USA settings and imagery consistent
- **Steps:** after reopening open USA Data Setup… and the layer tree.
- **Expect:** the saved USA source (project setting `Velorona/usa_pack_source`) is shown if it was set and nothing else; global QGIS settings contain no Velorona keys (Settings ▸ Options ▸ Advanced, search "velorona"). The imagery group is named `USA Aerial Imagery & Topo (USGS)` exactly once; the layers keep their on/off state. **Variant:** open a project saved by 1.1.9 (create it in the `velorona_baseline` profile with the group `USA Imagery (optional)`), open it in the candidate profile and run Load Public Data: the group is renamed in place, no second imagery group appears, layer visibility preserved. **Severity:** S1 if duplicated, S2 otherwise.

### PRJ-06 No duplicates after repeated actions
- **Steps:** after reopening run Load Public Data three times; select a record each time.
- **Expect:** one set of layers; one Details update per selection (`_wired_layers` size unchanged between runs). **Severity:** S2.

### PRJ-07 Plugin reload while a project is open
- **Steps:** with layers present, Plugins ▸ Plugin Reloader (or disable/enable Velorona in the manager) then select a record.
- **Expect:** the record is shown once; no second panel; action count still 8. **Severity:** S1.

### PRJ-08 Remove a layer, save, reopen
- **Steps:** remove *Fixed Service links (CAN)*, save, reopen, Load Public Data. **Expect:** the layer is recreated once; Records lists it; no error. **Severity:** S2.
