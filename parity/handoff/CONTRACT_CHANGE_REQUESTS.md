# CONTRACT_CHANGE_REQUESTS — QGIS workstream (append-only). The frozen spec 0.3 and `canonical.py` are NOT edited.

## QCCR-1 — two wordings for the FCC antenna-height source text  (2026-10-08, severity PRESENTATION_ONLY)
* **Need.** One string, so a reviewer sees the same words in both products.
* **Evidence.** `parity/contract/USA_PACK_SCHEMA.md` §3.3: "antenna height to centre (FCC field 'Height to Center RAAT'), licensee-reported record value, metres, interpreted as above ground; not a field measurement". `parity/fixtures/us-*.json` `link.site_*.height_source`: "FCC ULS AN 'Height to Center RAAT' (m), licensee-reported record value, interpreted as above ground; not a field measurement". QGIS uses the contract text (`core/record_source.py` `FCC_HEIGHT_LABEL`).
* **Recommended resolution.** Keep the contract text; regenerate `height_source` in the fixtures from it (the comparator ignores source text, so no result changes).

## QCCR-2 — CCR-1 (heights Observed in `canonical.expected_types`) is accepted by QGIS  (2026-10-08, severity PRESENTATION_ONLY)
* **Need.** Nothing from QGIS beyond the Map's own one-line change.
* **Evidence.** With record heights typed by origin, QGIS agrees with the fixtures' `height_origin` on all 20 US fixtures (pairwise provenance MATCH, 1,106/1,106 stages).
* **Recommended resolution.** As proposed in CCR-1.

## QCCR-3 — spec G: where identity / version lines go  (2026-10-08, severity PRESENTATION_ONLY)
* **Need.** G.1 asks for product/spec/library versions in every export; neither product had it. QGIS now writes them as `# ` preamble lines so the evidence table is unchanged.
* **Recommended resolution.** Say in G that container-level identity may be preamble/metadata (IP4), and add the same lines to the Map's CSV/HTML export.

## QCCR-4 — no text may call the rain coefficients ITU-R P.838-3 (CCR-2)  (2026-10-08, severity DECISION_CHANGING for weather, owner decision)
* **Need.** QGIS exports, README and `metadata.txt` say "ITU-R P.530 / P.838-3". Until the table is verified, QGIS adds a caveat line to weather exports (not a removal of the method reference). Replacing the table is a library release (D-4) and re-freezes weather expectations in both products.
* **Recommended resolution.** As CCR-2: owner decision D-4, then re-freeze; QGIS pins the new library range in the same release.
