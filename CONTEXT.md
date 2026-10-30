# Velorona

Velorona answers one question for a telecom link: what does public data say about it right now, and how sure is that? This vocabulary is shared by Velorona Map, the QGIS plugin and the `aei-*` libraries.

## Language

**Site**: a point with coordinates from a public register (a tower, a station). _Avoid_: node, asset.

**Link**: a licensed point-to-point path between two sites, from one authorization record. _Avoid_: hop, connection.

**Record value**: a value the licensee submitted to a public register (frequency, antenna height). It is a declaration, not a measurement.

**Analysis**: one run of a defined method on one selection: terrain path clearance, weather (rain) exposure, or satellite look angles.

**Status**: the analysis outcome on a fixed scale: CLEAR, WATCH, AT RISK, CRITICAL, or NO DATA.

**NO DATA**: the analysis could not be completed honestly; the reason is stated and nothing is substituted. _Avoid_: zero, unknown, default.

**Evidence**: the table behind a status. Every row has a type:
- **Observed**: reported by a source as observed (a station reading, a register field).
- **Model-derived**: a model's value for a place and time (e.g. Open-Meteo weather), not a measurement.
- **Reference data (DEM)**: a value read from a fixed elevation dataset (online 90 m model or the user's raster). Never Observed.
- **Calculated**: derived by a stated formula from other rows.
- **Assumed**: a default or a value the user typed.
- **Inferred**: an interpretation, never a measurement.

**Estimated rain fade**: rain attenuation computed from the current model rain rate. _Avoid_: predicted, forecast.

**Data pack**: a versioned extract of a public register shipped with or served to the products (e.g. Canada ISED Fixed Service, USA FCC ULS), with its source, dates and verification level.

**History**: weather values the user's own analyses fetched, kept on the user's computer only, with "what changed" comparisons that compare like with like.

**Message ID**: the registry identifier of a message (`E-`/`W-`/`I-` + area + name). It links to the user guide.
