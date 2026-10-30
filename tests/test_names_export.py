"""Single-result exports and the link study: the user's own names only when ticked; names from any public source in packs.json stay."""
import csv
import io
import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from aei_mw_exposure import MicrowaveLink, MicrowaveSite, Provenance, calculate_exposure  # noqa: E402
from aei_mw_exposure.representativeness import assess_representativeness  # noqa: E402

import presentation_fixtures as F  # noqa: E402
from core import export, names, public_sources, study_export  # noqa: E402

ISED = "ISED SMS Authorization Data Extract: Fixed Service, Open Government Licence - Canada"
FCC = "FCC ULS public access database: Microwave (l_micro), U.S. Federal Communications Commission"


def terrain(a="Tower North 12", b="=Hilltop Repeater", public=False):
    r = F.terrain_result()
    r.site_a_name, r.site_b_name = a, b
    r.site_a_public = r.site_b_public = public
    return r


def weather(source_a, source_b, a="Tower North 12", b="Hill Repeater"):
    sa = MicrowaveSite(id="s-1", name=a, latitude=F.A[0], longitude=F.A[1], provenance=Provenance.USER_PROVIDED, source=source_a)
    sb = MicrowaveSite(id="s-2", name=b, latitude=F.B[0], longitude=F.B[1], provenance=Provenance.USER_PROVIDED, source=source_b)
    link = MicrowaveLink(id="my-link-77", site_a=sa, site_b=sb, frequency_ghz=18.0, polarization="V", fade_margin_db=32.0,
                         provenance=Provenance.USER_PROVIDED, source="test")
    by = {"s-1": F.obs(sa, 2.4), "s-2": F.obs(sb, 0.5)}
    reps = {s.id: assess_representativeness(site=s, nearest_station=None, station_distance_km=None, station_reports_precipitation=True,
                                            model_observation=by[s.id]) for s in (sa, sb)}
    return SimpleNamespace(kind="microwave-exposure", exposure=calculate_exposure(link, by), representativeness=reps, weather_errors={}, history={})


def test_every_pack_and_other_public_dataset_is_public_and_a_user_layer_is_not():
    for src in (ISED, FCC, "Ontario GeoHub -- Tower dataset (MNRF), Open Government Licence - Ontario",
                "ISED Spectrum Licences Site Data (cellular/mobile), via Esri Canada mirror", "SatNOGS Network -- Ground Stations, static snapshot"):
        assert public_sources.is_public(src), src
    for src in ("Selected QGIS feature", "", None, "my survey 2024", "test"):
        assert not public_sources.is_public(src), src


def test_a_pack_added_to_packs_json_is_public_without_code(monkeypatch):
    from core import packs
    monkeypatch.setattr(packs, "registry", lambda: {"xx": {"source": {"agency": "Ofcom", "dataset": "Wireless Telegraphy Register, fixed links"}}})
    public_sources.pack_markers.cache_clear()
    try:
        assert public_sources.is_public("Ofcom Wireless Telegraphy Register: point-to-point")
    finally:
        public_sources.pack_markers.cache_clear()


def test_single_csv_leaves_own_names_out_unless_ticked():
    r = terrain()
    plain = export.export_csv(r)
    assert "Tower North 12" not in plain and "Hilltop Repeater" not in plain and "Site A" in plain
    named = export.export_csv(r, include_names=True)
    strip = lambda t: [line for line in t.splitlines() if not line.startswith("# Generated:")]   # noqa: E731
    assert strip(named) == strip(export.result_to_csv(r)) and "Tower North 12" in named
    rows = list(csv.reader(io.StringIO("\n".join(line for line in named.splitlines() if not line.startswith("#")))))
    assert not any(c.startswith(("=", "+", "@")) for row in rows for c in row)          # still formula-guarded


def test_public_register_names_stay_in_single_exports():
    r = terrain("TORONTO CN TOWER", "MISSISSAUGA", public=True)
    assert "TORONTO CN TOWER" in export.export_csv(r) and not names.has_private_names(r)


def test_weather_on_two_public_sites_keeps_their_names():
    r = weather(ISED, FCC)
    assert not names.has_private_names(r)
    assert "Tower North 12" in export.export_csv(r) and "Tower North 12" in study_export.study_to_csv([r])


def test_weather_with_one_own_site_hides_that_site_and_the_link_id_only():
    r = weather(ISED, "Selected QGIS feature")
    text = export.export_csv(r)
    assert "Tower North 12" in text and "Hill Repeater" not in text and "my-link-77" not in text


def test_excel_leaves_own_names_out_unless_ticked():
    import zipfile
    r = weather("Selected QGIS feature", "Selected QGIS feature")

    def strings(data):
        z = zipfile.ZipFile(io.BytesIO(data))
        return "".join(z.read(n).decode("utf-8", "replace") for n in z.namelist() if n.endswith(".xml"))
    assert "Tower North 12" not in strings(export.result_to_xlsx(r, include_names=False))
    assert "Tower North 12" in strings(export.result_to_xlsx(r, include_names=True))
