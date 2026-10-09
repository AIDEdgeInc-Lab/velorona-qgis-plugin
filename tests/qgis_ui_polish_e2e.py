"""UI polish regression checks in real QGIS (offscreen): zoom-dependent cluster/link styling, link title, NO DATA
wording, baseline grouping, Records column show/hide. Run like qgis_usa_e2e.py (see tests/run_qgis_tests.sh)."""
import os
import sys

PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(PLUGIN_DIR))
sys.path.insert(0, os.path.join(PLUGIN_DIR, "tests"))

from qgis.core import (QgsApplication, QgsExpressionContext, QgsExpressionContextScope, QgsPointClusterRenderer,  # noqa: E402
                       QgsSymbolLayer, QgsSymbolLayerUtils)
from qgis.PyQt.QtCore import QMetaType, Qt  # noqa: E402
from qgis.PyQt.QtWidgets import QApplication  # noqa: E402

qgs = QgsApplication([], True)
qgs.initQgis()
RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  -- {detail}" if detail and not ok else ""))


from velorona.core import layers as L  # noqa: E402
from velorona.core.presentation.model import Change, link_title, Brief, NO_DATA, CLEAR  # noqa: E402
from velorona.ui import operational_view as OV  # noqa: E402
from velorona.ui.records_table import VeloronaRecordsTable  # noqa: E402


def ctx(scale):
    scope = QgsExpressionContextScope()
    scope.setVariable("map_scale", scale)
    c = QgsExpressionContext()
    c.appendScope(scope)
    return c


def dd(symbol_layer, prop, scale, default):
    p = symbol_layer.dataDefinedProperties().property(prop)
    value, ok = p.value(ctx(scale), default)
    if prop in (QgsSymbolLayer.Property.FillColor, QgsSymbolLayer.Property.StrokeColor):
        from qgis.PyQt.QtGui import QColor
        return value if isinstance(value, QColor) else QgsSymbolLayerUtils.decodeColor(str(value))
    return value


print("== scale regimes and threshold semantics ==")
check("thresholds are 600k / 150k", (L.VIEW_SCALE_WIDE, L.VIEW_SCALE_MEDIUM) == (600000, 150000))
check("alpha rises toward the viewer", L.CLUSTER_FILL_ALPHA_WIDE < L.CLUSTER_FILL_ALPHA_MEDIUM < L.CLUSTER_FILL_ALPHA)
check("size factors are <= 1 and rise", L.CLUSTER_SIZE_FACTOR_WIDE < L.CLUSTER_SIZE_FACTOR_MEDIUM <= 1.0)
check("link alpha/width factors rise",
      L.LINK_ALPHA_FACTOR_WIDE < L.LINK_ALPHA_FACTOR_MEDIUM < L.LINK_ALPHA_FACTOR_CLOSE <= 1.0 and L.LINK_WIDTH_FACTOR_WIDE < 1.0)
for dark in (True, False):
    tag = "dark" if dark else "light"
    for key, color in (("sites", "#7C9EE0"), ("fixed", "#5BC0BE")):
        sym = L.cluster_symbol(color, dark)
        disc = sym.symbolLayer(0)
        base = disc.color()
        rgb = (base.red(), base.green(), base.blue())
        got = {s: dd(disc, QgsSymbolLayer.Property.FillColor, s, base) for s in (700000, 600001, 600000, 150001, 150000, 1)}
        alphas = {s: c.alpha() for s, c in got.items()}
        check(f"{tag} cluster fill: regional above 600000 (exclusive)", alphas[700000] == alphas[600001] == L.CLUSTER_FILL_ALPHA_WIDE, alphas)
        check(f"{tag} cluster fill: 600000 and 150001 are medium", alphas[600000] == alphas[150001] == L.CLUSTER_FILL_ALPHA_MEDIUM, alphas)
        check(f"{tag} cluster fill: 150000 and closer are full strength", alphas[150000] == alphas[1] == L.CLUSTER_FILL_ALPHA, alphas)
        check(f"{tag} cluster hue unchanged at every scale", all((c.red(), c.green(), c.blue()) == rgb for c in got.values()))
        sizes = [dd(disc, QgsSymbolLayer.Property.Size, s, 10.0) for s in (700000, 300000, 100000)]
        check(f"{tag} cluster size grows toward close zoom", sizes[0] < sizes[1] < sizes[2], sizes)
    ls = L.link_symbol(dark)
    seg = ls.symbolLayer(0)
    a = [dd(seg, QgsSymbolLayer.Property.StrokeColor, s, ls.color()).alpha() for s in (700000, 300000, 100000)]
    w = [dd(seg, QgsSymbolLayer.Property.StrokeWidth, s, 1.0) for s in (700000, 300000, 100000)]
    check(f"{tag} link alpha rises toward close zoom", a[0] < a[1] < a[2], a)
    check(f"{tag} link width is thinner only at regional scale", w[0] < w[1] == w[2] == L.LINE_WIDTH_PX, w)

print("== styling does not touch data, clustering or selection ==")
fields = [("name", QMetaType.Type.QString)]
records = [{"name": f"s{i}", "latitude": 45 + i * 0.01, "longitude": -75 - i * 0.01} for i in range(40)]
layer = L.build_point_layer("t", records, fields, "#7C9EE0")
r = layer.renderer()
check("renderer is still the QGIS point-cluster renderer, tolerance 50 px",
      isinstance(r, QgsPointClusterRenderer) and r.tolerance() == L.CLUSTER_TOLERANCE_PX == 50)
check("every record is still in the layer", layer.featureCount() == 40)
sel = L.selection_symbol("#7C9EE0", True)
_PROPS = (QgsSymbolLayer.Property.FillColor, QgsSymbolLayer.Property.Size,
          QgsSymbolLayer.Property.StrokeColor, QgsSymbolLayer.Property.StrokeWidth)
_exprs = [sl.dataDefinedProperties().property(k).expressionString() for sl in sel.symbolLayers() for k in _PROPS]
check("selection symbol has no map_scale expression (not faded)", not any("map_scale" in e for e in _exprs))

print("== link title ==")
check("authorization shown", link_title("010029391-004") == "010029391-004 · Site A ↔ Site B")
check("whitespace normalised", link_title("  AB   12 ") == "AB 12 · Site A ↔ Site B")
for missing in (None, "", "  ", "link", "None", "nan"):
    check(f"missing/placeholder {missing!r} gives the plain pair", link_title(missing) == "Site A ↔ Site B")
check("absurdly long value is not used as a title", link_title("x" * 80) == "Site A ↔ Site B")


def brief(status, changes=(), heading="H"):
    return Brief(kind="weather", title="Weather exposure", location="loc", status=status, reason="Live weather could not be retrieved.",
                 answer="No answer: there is no weather data for this link.", heading=heading, changes=list(changes),
                 data={"driver_site": "Site A"})


print("== NO DATA wording ==")
html_nd, _ = OV.render_summary(brief(NO_DATA))
check("NO DATA keeps the status and the reason", "NO DATA" in html_nd and "Live weather could not be retrieved." in html_nd)
check("NO DATA does not repeat itself as an 'No answer' line", "No answer" not in html_nd)
html_ok, _ = OV.render_summary(brief(CLEAR))
check("other statuses keep their plain answer", "No answer: there is no weather data" in html_ok)
check("heading is shown (falls back to location)", "<h3>H</h3>" in html_ok and "<h3>loc</h3>" in OV.render_summary(brief(CLEAR, heading=""))[0])


def chg(label, baseline, v=1.0):
    return Change(label=label, unit="mm/h", current=v, previous=0.0, delta=v, direction="up", baseline=baseline,
                  current_time="20:00", previous_time="19:00", variable="rain")


print("== What changed grouped by baseline ==")
mixed = brief(CLEAR, [chg("Rain", "vs 1 hour ago"), chg("Rain", "vs 3 hours ago"), chg("Wind", "vs 1 hour ago")])
html_c, _ = OV.render_details(mixed)
i1, i3 = html_c.index("vs 1 hour ago"), html_c.index("vs 3 hours ago")
check("one heading per baseline, in first-seen order", html_c.count("vs 1 hour ago") == 1 and html_c.count("vs 3 hours ago") == 1 and i1 < i3)
check("rows stay under their own baseline", html_c.index("Wind") < i3)
none_b = OV.render_details(brief(CLEAR, [chg("Rain", "")]))[0]
check("a change without a baseline is labelled not determined, never merged", "Not determined" in none_b or "not determined" in none_b.lower())
check("no changes -> no section", "What changed" not in OV.render_details(brief(CLEAR))[0])

print("== Records column show/hide ==")
specs = [("authorization_number", QMetaType.Type.QString), ("licensee", QMetaType.Type.QString),
         ("frequencies_mhz", QMetaType.Type.QString), ("in_service_date", QMetaType.Type.QString), ("source", QMetaType.Type.QString)]
links = [{"authorization_number": f"A{i}", "licensee": "Op" if i % 2 else "Zed", "frequencies_mhz": "6000", "in_service_date": "2020",
          "source": "ISED", "site_a": {"latitude": 45, "longitude": -75}, "site_b": {"latitude": 45.1, "longitude": -75.1}} for i in range(6)]
ll = L.build_link_layer("l", links, specs, "#5BC0BE")
L.mark_velorona_owned(ll)
tbl = VeloronaRecordsTable()
tbl.resize(420, 400)
tbl.show()
tbl.set_layers({L.SOURCE_FIXED_LINKS: ll})
QApplication.processEvents()
names = tbl._column_names()
check("columns known", names[0] == "Authorization" and "Source" in names, names)
rows_before = tbl.proxy.rowCount()
check("hide a column", tbl.set_column_hidden("Source", True) and tbl.view.isColumnHidden(names.index("Source")))
check("hiding keeps every row and the model's data", tbl.proxy.rowCount() == rows_before == 6 and tbl.model.columnCount() == len(names))
tbl.view.sortByColumn(0, Qt.SortOrder.DescendingOrder)
tbl.search_edit.setText("A3")
QApplication.processEvents()
check("sort + search still work with a hidden column", tbl.proxy.rowCount() == 1)
chosen = []
tbl.featureChosen.connect(lambda lyr, fid, kind: chosen.append((lyr, fid)))
tbl.view.selectRow(0)
QApplication.processEvents()
check("row selection still resolves to the right feature", len(chosen) == 1 and ll.getFeature(chosen[0][1])["authorization_number"] == "A3")
tbl.search_edit.setText("")
check("search still matches a hidden column's text", (tbl.search_edit.setText("ISED") or True) and tbl.proxy.rowCount() == 6)
tbl.search_edit.setText("")
tbl.set_column_hidden("Source", False)
for n in names[:-1]:
    tbl.set_column_hidden(n, True)
check("the last visible column cannot be hidden", not tbl.set_column_hidden(names[-1], True)
      and sum(not tbl.view.isColumnHidden(i) for i in range(len(names))) == 1)
tbl._rebuild_columns_menu()
check("the menu offers every column, the last visible one disabled",
      len(tbl.columns_menu.actions()) == len(names) and sum(not a.isEnabled() for a in tbl.columns_menu.actions()) == 1)
check("unknown column is refused", not tbl.set_column_hidden("Nope", True))
for n in names:
    tbl.set_column_hidden(n, False)
check("all columns can be shown again", not any(tbl.view.isColumnHidden(i) for i in range(len(names))))
tbl.set_column_hidden("Licensee", True)
tbl.set_layers({})  # dataset goes away
tbl.set_layers({L.SOURCE_FIXED_LINKS: ll})
check("preference is remembered per dataset for the session", tbl.hidden_columns() == {"Licensee"})
tbl.populate_licensees({"Op": 3, "Zed": 3})
hint = tbl.operator_hint.text()
check("operator hint states operators and records", "2 operator" in hint and "6 records" in hint, hint)
check("first operator item has no count that could contradict the footer", tbl.licensee_combo.itemText(0) == "All operators")
check("controls have accessible names", all(w.accessibleName() for w in (tbl.licensee_combo, tbl.search_edit, tbl.columns_button, tbl.dataset_combo)))

passed = sum(1 for _, ok, _ in RESULTS if ok)
print(f"\n===== {passed}/{len(RESULTS)} checks passed =====")
sys.exit(0 if passed == len(RESULTS) else 1)
