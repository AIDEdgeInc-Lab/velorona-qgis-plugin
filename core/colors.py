"""Marker colors.

Six infrastructure layer types -- Fixed Service sites, Fixed Service links,
Cellular/Mobile sites, Ontario Tower structures, Ground/Earth Stations,
Satellites -- each get their own colour PER MAP APPEARANCE, not the same
pastel dimmed for dark mode: a hue picked for contrast against Voyager's
cream land does not automatically hold up against CARTO Dark Matter's
near-black land, and vice versa.

Chosen by measurement, not by eye. Hues are anchored to the product's
existing semantic bands (blue family for Fixed Service, orange for
cellular, violet for towers, green for the space layers) and then searched
in CIELCh space for the placement, within each band, that maximises the
worst-case pairwise CIEDE2000 separation *after* simulating deuteranopia,
protanopia and tritanopia (Vienot/Brettel/Mollon linear-RGB matrices) on
every pair -- not just normal vision -- subject to a WCAG contrast floor
against the real backdrop colour:

    dark  (CARTO Dark Matter, #181E18): floor 4.5:1 -- achieved min dE 17.3
    light (CARTO Voyager,     #FAF6F0): floor 2.5:1 -- achieved min dE 16.9

The light floor is deliberately held below WCAG's 3:1 non-text minimum: it
is the closest the search gets to genuinely soft/pastel tones while keeping
real separation. Raising it to 3.0:1 was checked, not assumed, and measured
*worse* separation (13.8) for the extra contrast -- muted mid-tones, not
pastels, and less distinguishable. 2.5:1 was chosen as the better trade.

Everything about this six-colour system is verified by measurement in
tests/qgis_e2e.py -- pairwise CIEDE2000 across every simulated vision type,
contrast against each real backdrop, and (since colour choices are only as
good as the code that actually applies them) that the cluster and line
symbols built from these values carry the right colour, not just that the
constants are distinct.

'mine', 'weather-evidence' and 'terrain' are single values, independent of
map appearance -- they are not part of the six-type distinctness system
above (no reported ambiguity for them) and are unchanged from before.
'weather-evidence'/'terrain' are new picks with no map-layer equivalent in
Velorona Map; 'mine' and the original 7 are ported 1:1 from
aei-link-clearance/web/app.js's COLORS constant.
"""

COLORS_DARK = {
    "fixed-sites": "#C1CEFF",
    "fixed-links": "#00B3CD",
    "cellular": "#FFBA7C",
    "towers": "#FFBDF0",
    "ground-stations": "#97BF6D",
    "satellites": "#629D81",
}

COLORS_LIGHT = {
    "fixed-sites": "#9895E8",
    "fixed-links": "#0090A6",
    "cellular": "#DA8460",
    "towers": "#CA80C3",
    "ground-stations": "#799B4A",
    "satellites": "#508167",
}


def layer_color(kind: str, dark: bool = True) -> str:
    """The appearance-correct colour for one of the six typed layers above."""
    return (COLORS_DARK if dark else COLORS_LIGHT)[kind]


# Unaffected by map appearance -- not part of the six-type system above.
COLORS = {
    "mine": "#EF7BB0",
    "weather-evidence": "#3DBFE0",
    "terrain": "#C9A227",
}
