"""Marker colors. The 7 original layers are ported 1:1 from
aei-link-clearance/web/app.js's COLORS constant -- same hues, same
WCAG-contrast rationale already established there, not re-derived.

'weather-evidence' and 'terrain' are new (no map-layer equivalent existed
in Velorona Map) -- picked for a distinct hue from all 7 existing colors,
but NOT independently re-verified against WCAG contrast the way the
original 7 were measured; flagging that honestly rather than claiming a
check that wasn't done.
"""

COLORS = {
    "towers": "#B98CE0",
    "cellular": "#F2994A",
    "fixed-sites": "#5F98D1",
    "fixed-links": "#99C6F3",
    "mine": "#EF7BB0",
    "satellites": "#5CD699",
    "ground-stations": "#9DD161",
    "weather-evidence": "#3DBFE0",
    "terrain": "#C9A227",
}
