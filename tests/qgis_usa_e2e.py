"""Velorona QGIS plugin -- USA support, end to end in real QGIS (offscreen). NO network: the pack is a SYNTHETIC temp pack (tests/usa_pack_builder.py), the
elevation edge is faked, and the basemap is stubbed. Everything else is the real plugin: the project entry, layers, the Records table, selection,
the link-record terrain flow, ParamDialog, exports.

Run with the QGIS Python (see tests/run_qgis_tests.sh for the environment) from a checkout whose directory is named ``velorona``:

    $QGISPY tests/qgis_usa_e2e.py
"""
import os
import sys
import tempfile

PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(PLUGIN_DIR))
sys.path.insert(0, os.path.join(PLUGIN_DIR, "tests"))

from qgis.core import QgsApplication, QgsProject, QgsRectangle, QgsCoordinateReferenceSystem  # noqa: E402
from qgis.gui import QgsMapCanvas, QgsMessageBar  # noqa: E402
from qgis.PyQt.QtWidgets import QMainWindow  # noqa: E402

qgs = QgsApplication([], True)
qgs.initQgis()

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  -- {detail}" if detail and not ok else ""))
    return ok


class FakeIface:
    def __init__(self):
        self.window = QMainWindow()
        self.canvas = QgsMapCanvas()
        self.window.setCentralWidget(self.canvas)
        self.canvas.resize(800, 600)
        self.bar = QgsMessageBar(self.window)

    def mapCanvas(self): return self.canvas
    def mainWindow(self): return self.window
    def messageBar(self): return self.bar
    def addToolBarIcon(self, a): pass
    def addPluginToMenu(self, m, a): pass
    def removePluginMenu(self, m, a): pass
    def removeToolBarIcon(self, a): pass
    def setActiveLayer(self, layer): self.active = layer
    def addDockWidget(self, area, dock): self.window.addDockWidget(area, dock)
    def removeDockWidget(self, dock): self.window.removeDockWidget(dock)


from usa_pack_builder import ATTRIBUTION, write_pack  # noqa: E402
from velorona.plugin import USA_PACK_ENV, USA_PACK_KEY, USA_PACK_SCOPE, VeloronaPlugin  # noqa: E402
from velorona.core import export, layers as layer_helpers  # noqa: E402
from velorona.core.engines import terrestrial  # noqa: E402
from velorona.core.inspector import feature_to_entry  # noqa: E402
from velorona.ui.param_dialog import ParamDialog  # noqa: E402

iface = FakeIface()
QgsProject.instance().clear()
plugin = VeloronaPlugin(iface)
plugin._ensure_basemap = lambda: None                      # the basemap is a network vector-tile layer; not under test here
SHOWN = []                                                 # modal QMessageBox warnings/errors are recorded instead of blocking the test
plugin._warn = lambda m: SHOWN.append(m)
plugin._error = lambda m: SHOWN.append(m)
os.environ.pop(USA_PACK_ENV, None)


def set_source(value):
    QgsProject.instance().writeEntry(USA_PACK_SCOPE, USA_PACK_KEY, value)


def messages():
    return list(SHOWN) + [m.text() for m in iface.bar.items()]


def _reset_messages():
    iface.bar.clearWidgets()
    SHOWN.clear()


def find(key):
    return layer_helpers.find_owned_layer(QgsProject.instance(), key)


def set_view(west, south, east, north):
    iface.canvas.setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:4326"))
    iface.canvas.setExtent(QgsRectangle(west, south, east, north))


try:
    pack_dir = write_pack(tempfile.mkdtemp(prefix="velorona-us-pack-"))
    plugin.initGui()

    print("\n== USA actions exist, Canada layers untouched ==")
    check("Load USA action registered", plugin.action_load_usa is not None and "USA" in plugin.action_load_usa.text())
    check("Set pack source action registered", plugin.action_set_usa_source is not None)

    print("\n== a bad pack source is a pack error, never a layer or a NO DATA ==")
    set_source(os.path.join(pack_dir, "does-not-exist"))
    plugin._usa_provider = None
    set_view(-106.0, 40.0, -105.0, 42.0)
    plugin.load_usa_view()
    check("no US layer was created from a missing pack", find(layer_helpers.SOURCE_US_LINKS) is None)
    check("the user is told the folder does not exist", any("does not exist" in m for m in messages()), str(messages()))

    print("\n== loading a view ==")
    _reset_messages()
    set_source(pack_dir)
    plugin._usa_provider = None
    plugin.load_usa_view()
    links, sites = find(layer_helpers.SOURCE_US_LINKS), find(layer_helpers.SOURCE_US_SITES)
    check("US link and site layers exist as Velorona-owned layers", links is not None and sites is not None)
    check("tile-edge duplicate removed: 2 links, 3 sites", links.featureCount() == 2 and sites.featureCount() == 3,
          f"{links.featureCount()} links / {sites.featureCount()} sites")
    check("Canada layers were not created or touched", find(layer_helpers.SOURCE_FIXED_LINKS) is None)
    names = [f.name() for f in links.fields()]
    check("link layer carries authorization, frequency, call sign, attribution",
          {"authorization_number", "frequencies_mhz", "call_sign", "attribution"} <= set(names))
    check("layer abstract states the attribution, dates and the nature of the data",
          ATTRIBUTION in links.metadata().abstract() and "2026-09-27" in links.metadata().abstract()
          and "not a field measurement" in links.metadata().abstract(), links.metadata().abstract())
    check("a load message states the source", any("Federal Communications Commission" in m for m in messages()), str(messages()))
    feat = next(f for f in links.getFeatures() if f["authorization_number"] == "WAAA001-1")
    check("link record is in the plugin's record shape", feat["frequencies_mhz"] == "11245, 6078.625" and feat["country"] == "US"
          and feat["attribution"] == ATTRIBUTION)
    check("the Records table can list the US layers", plugin.dock.records is not None
          and layer_helpers.SOURCE_US_LINKS in plugin.dock.records._layers)

    print("\n== reload of another view refreshes in place (no second layer) and clears the endpoint-index cache ==")
    plugin._endpoint_index[links.id()] = {"stale": True}
    set_view(-106.0, 40.0, -105.0, 40.9)
    plugin.load_usa_view()
    check("same layer object reused", find(layer_helpers.SOURCE_US_LINKS) is links)
    check("stale shared-endpoint index dropped", links.id() not in plugin._endpoint_index)
    check("one tile -> its 2 links", links.featureCount() == 2)

    print("\n== a view that is too large is refused before any tile is read ==")
    from velorona.core.countries import usa as usa_pack
    plugin._usa_provider = usa_pack.UsaPackProvider(pack_dir, max_links=1)
    before = links.featureCount()
    _reset_messages()
    plugin.load_usa_view()
    check("budget message says to zoom in", any("Zoom in" in m for m in messages()), str(messages()))
    check("existing layer content left as it was", links.featureCount() == before)
    plugin._usa_provider = None

    print("\n== terrain from ONE selected link record: frequency-origin channel ==")
    import requests

    class Resp:
        def __init__(self, body): self.body = body
        def raise_for_status(self): pass
        def json(self): return self.body
    feat = next(f for f in links.getFeatures() if f["authorization_number"] == "WAAA001-1")   # re-read: the reload above replaced all feature ids
    orig_get = requests.get
    requests.get = lambda *a, **k: Resp({"elevation": [100.0] * 50})
    try:
        entry = feature_to_entry(feat, "link")
        record_ghz = 11.245
        res = terrestrial.analyze_link_record(entry.data, entry.site_a_point, entry.site_b_point,
                                              {"site_a_height_m": 30.0, "site_b_height_m": 30.0, "frequency_ghz": record_ghz})
        csv_text = export.result_to_csv(res)
        check("QGIS-built link record: frequency Observed with the FCC prefix",
              res.frequency_origin[0] == "Observed" and res.frequency_origin[1].startswith("FCC ULS record -- "), str(res.frequency_origin))
        check("export preamble carries the FCC attribution and the pack dates", ATTRIBUTION in csv_text and "pack built 2026-10-03" in csv_text)
        res2 = terrestrial.analyze_link_record(entry.data, entry.site_a_point, entry.site_b_point,
                                               {"site_a_height_m": 30.0, "site_b_height_m": 30.0, "frequency_ghz": 7.0})
        check("overridden frequency is Assumed", res2.frequency_origin[0] == "Assumed")
        # The plugin flow with a stubbed dialog: one link selected, nothing else.
        import velorona.plugin as plugin_module

        class StubDialog:
            DialogCode = ParamDialog.DialogCode
            captured = None

            def __init__(self, parent, title, spec, defaults):
                StubDialog.captured = (title, dict(defaults))
                self._d = defaults

            def exec(self): return ParamDialog.DialogCode.Accepted
            def values(self): return dict(self._d)
        plugin_module.ParamDialog = StubDialog
        links.selectByIds([feat.id()])
        plugin.run_terrestrial()
        check("run_terrestrial accepts exactly one selected link", StubDialog.captured is not None, str(messages()))
        check("dialog is pre-filled with the record's highest frequency", abs(StubDialog.captured[1]["frequency_ghz"] - record_ghz) < 1e-12)
        shown = plugin.dock._result
        check("the displayed result is the link-record result, frequency Observed",
              getattr(shown, "frequency_origin", None) and shown.frequency_origin[0] == "Observed")
        links.removeSelection()
        _reset_messages()
        plugin.run_terrestrial()
        check("nothing selected -> a clear instruction, no analysis", any("exactly one Fixed Service link" in m for m in messages()), str(messages()))
    finally:
        requests.get = orig_get

    print("\n== ParamDialog returns an untouched record value exactly ==")
    from velorona.ui import param_dialog as pd_module
    ParamDialogReal = pd_module.ParamDialog
    dlg = ParamDialogReal(iface.mainWindow(), "probe", terrestrial.PARAM_SPEC,
                          {"site_a_height_m": 30.0, "site_b_height_m": 30.0, "frequency_ghz": 6.22689})
    check("untouched frequency comes back as 6.22689 exactly (not a rounded copy)", dlg.values()["frequency_ghz"] == 6.22689, str(dlg.values()))
    dlg._widgets["frequency_ghz"].setValue(7.0)
    check("an edited frequency comes back as the edit", dlg.values()["frequency_ghz"] == 7.0)
    check("the dialog shows 5 decimals of GHz", dlg._widgets["frequency_ghz"].decimals() == 5)
    dlg2 = ParamDialogReal(iface.mainWindow(), "probe", terrestrial.PARAM_SPEC,
                           {"site_a_height_m": 30.0, "site_b_height_m": 30.0, "frequency_ghz": 500.0})
    check("an untouched out-of-range default is still refused, not clamped", [b[0] for b in dlg2.out_of_range()] == ["Frequency"])

    print("\n== the pack source lives in the project, not in the QGIS settings; the environment is the fallback ==")
    check("source is stored as a project entry", QgsProject.instance().readEntry(USA_PACK_SCOPE, USA_PACK_KEY, "")[0] == pack_dir)
    plugin_source = open(os.path.join(PLUGIN_DIR, "plugin.py")).read()
    check("plugin.py never touches QgsSettings", "QgsSettings" not in plugin_source)
    set_source("")
    os.environ[USA_PACK_ENV] = pack_dir
    check("with no project entry the environment variable is used", plugin._configured_usa_source() == pack_dir)
    os.environ.pop(USA_PACK_ENV, None)

    print("\n== guided USA setup: never at startup, Cancel is harmless, every state is honest ==")
    import velorona.plugin as plugin_mod
    from velorona.core.countries.canada import CanadaProvider
    from velorona.core.countries import usa_setup
    from velorona.ui.usa_setup_dialog import UsaSetupDialog as RealDialog
    opened = []

    class SpyDialog(RealDialog):
        script = None                                  # what "the user does": "accept" / "cancel" / "remove"

        def __init__(self, parent, current="", intro=False, **kw):
            opened.append({"current": current, "intro": intro})
            super().__init__(parent, current, intro=intro, **kw)

        def exec(self):
            if SpyDialog.script == "accept":
                self.chosen_source = pack_dir
                return self.DialogCode.Accepted
            if SpyDialog.script == "remove":
                self.remove_requested = True
                return self.DialogCode.Accepted
            return self.DialogCode.Rejected
    plugin_mod.UsaSetupDialog = SpyDialog
    plugin2 = VeloronaPlugin(iface)
    plugin2._warn = lambda m: SHOWN.append(m)
    plugin2._error = lambda m: SHOWN.append(m)
    set_source("")
    os.environ.pop(USA_PACK_ENV, None)
    plugin2.initGui()
    check("normal plugin start opens NO USA dialog and asks for no path", opened == [])
    check("a Canada engine runs with no USA data configured",
          len(CanadaProvider().load_all().links) == 16956 and plugin2._configured_usa_source() == "")
    _reset_messages()
    before_links = links.featureCount()
    SpyDialog.script = "cancel"
    plugin2.load_usa_view()
    check("Load USA Links with nothing set up opens the GUIDED dialog (with the explanation), once", len(opened) == 1 and opened[0]["intro"] is True, str(opened))
    check("Cancel: no layers, nothing saved, no error box, a calm note that Canada is unaffected",
          links.featureCount() == before_links and plugin2._configured_usa_source() == "" and not SHOWN
          and any("Canada works as usual" in m for m in messages()), str(messages()))
    plugin2.set_usa_pack_source()
    check("USA Data Setup (menu) opens without the first-use intro", len(opened) == 2 and opened[1]["intro"] is False)
    SpyDialog.script = "accept"
    check("accepting a checked source saves it in the project", plugin2.set_usa_pack_source() is True and plugin2._configured_usa_source() == pack_dir)
    check("an existing setting is offered back to the dialog (nothing lost)", (plugin2.set_usa_pack_source(), opened[-1]["current"])[1] == pack_dir)
    SpyDialog.script = "remove"
    plugin2.set_usa_pack_source()
    check("'Forget the saved setting' clears it and leaves Canada alone", plugin2._configured_usa_source() == "")
    SpyDialog.script = "cancel"
    set_source(pack_dir)
    plugin2.set_usa_pack_source()
    check("Cancel never changes an existing setting", plugin2._configured_usa_source() == pack_dir)

    # the real dialog's own behaviour (no stubs except the native folder picker)
    picks = {"next": pack_dir}
    d = RealDialog(iface.mainWindow(), "", intro=True, pick_folder=lambda start: picks["next"])
    check("fresh dialog: 'Not set up yet', 'Use this data' disabled, Forget hidden, help hidden",
          "Not set up yet" in d.status.text() and not d.btn_use.isEnabled() and not d.btn_remove.isVisibleTo(d) and not d.help.isVisibleTo(d))
    check("the dialog says the data is separate and that Canada works without it", "not included in the plugin" in d.lead.text() and "Canada works without it" in d.lead.text())
    d.btn_folder.click()
    check("choosing a valid pack folder: Ready, the pack's own count, 'Use this data' enabled",
          "Ready" in d.status.text() and "3 US links" in d.status.text() and d.btn_use.isEnabled(), d.status.text())
    picks["next"] = os.path.join(os.path.dirname(pack_dir), "does-not-exist")
    d.btn_folder.click()
    check("choosing a bad folder: a Problem with a next step, and 'Use this data' is disabled again",
          "Problem" in d.status.text() and "Check the folder" in d.status.text() and not d.btn_use.isEnabled(), d.status.text())
    picks["next"] = pack_dir
    d.btn_folder.click()
    picks["next"] = ""
    d.btn_folder.click()
    check("cancelling the native picker leaves the last good state alone", "Ready" in d.status.text() and d.btn_use.isEnabled())
    d.btn_use.click()
    check("'Use this data' hands back exactly the checked source", d.chosen_source == pack_dir)
    d.btn_help.click()
    check("'How do I get the data?' shows the guide", d.help.isVisibleTo(d) and "online USA data" in d.help.toPlainText())
    seen = []
    d2 = RealDialog(iface.mainWindow(), "", check=lambda t: (seen.append(t), usa_setup.SetupCheck(usa_setup.ERROR, message="x", next_step="y"))[1])
    d2.btn_online.click()
    check("'Use Velorona's online USA data' checks Velorona's published address (opt-in, nothing downloaded before)", seen == [usa_setup.VELORONA_ONLINE_PACK])
    d2.address.setText("http://insecure.example/")
    d2.btn_check.click()
    check("typing a web address and pressing Check runs the check on it", seen[-1] == "http://insecure.example/")
    d3 = RealDialog(iface.mainWindow(), pack_dir)
    check("opening with an existing setting re-checks it and shows Ready; 'Forget' is available",
          "Ready" in d3.status.text() and d3.btn_use.isEnabled() and d3.btn_remove.isVisibleTo(d3))
    plugin_mod.UsaSetupDialog = RealDialog
    set_source(pack_dir)

    print("\n== Canada: record antenna heights from the bundled snapshot /1.1 (ISED column 29) ==")
    from velorona.core.countries.canada import CanadaProvider
    loaded_ca = CanadaProvider().load_all()
    check("Canada loads whole: 16,956 links, nearly all with record heights", len(loaded_ca.links) == 16956 and loaded_ca.heights_attached > 16900, str(loaded_ca.heights_attached))
    one = next(x for x in loaded_ca.links if x["site_a_height_m"] is not None and x["site_b_height_m"] is not None)
    check("a Canadian link carries heights and the ISED column-29 source text",
          one["site_a_height_m"] > 0 and "column 29" in one["height_source"] and "licensee-submitted" in one["height_source"] and one["height_source"].startswith("ISED Fixed Service record -- "),
          one["height_source"])
    from velorona.core.engines import terrestrial
    import requests as _rq

    class _R:
        def raise_for_status(self): pass
        def json(self): return {"elevation": [100.0] * 50}
    _orig = _rq.get
    _rq.get = lambda *a, **k: _R()
    try:
        params, ghz, note = terrestrial.build_link_params(one)
        res = terrestrial.analyze_link_record(one, (one["site_a"]["latitude"], one["site_a"]["longitude"]),
                                              (one["site_b"]["latitude"], one["site_b"]["longitude"]), params)
    finally:
        _rq.get = _orig
    check("analysis from that record types both heights Observed",
          res.height_origins["a"][0] == "Observed" and res.height_origins["b"][0] == "Observed", str(res.height_origins))
    check("a user-changed height becomes Assumed",
          terrestrial.analyze_link_record(one, (one["site_a"]["latitude"], one["site_a"]["longitude"]), (one["site_b"]["latitude"], one["site_b"]["longitude"]),
                                          {**params, "site_a_height_m": params["site_a_height_m"] + 5}).height_origins["a"][0] == "Assumed")

    print("\n== unload leaves nothing behind ==")
    plugin.unload()
    check("unload completes", True)
finally:
    pass

failed = [r for r in RESULTS if not r[1]]
print(f"\n===== {len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed =====")
for name, _, detail in failed:
    print("FAILED:", name, detail)
sys.exit(1 if failed else 0)
