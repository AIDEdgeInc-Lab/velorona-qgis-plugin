"""One-link study export: the Map's evidence-file layout, only the same link, no history, the user's own names only when ticked."""
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
from core import study_export as S  # noqa: E402
from core.export import EVIDENCE_HEADER, NotExportable  # noqa: E402

NAMES = ("Tower North 12", "=Hilltop Repeater")


def terrain(names=NAMES, source="Selected QGIS feature", public=False):
    r = F.terrain_result()
    r.site_a_name, r.site_b_name = names
    r.site_a_source = r.site_b_source = source
    r.site_a_public = r.site_b_public = public
    return r


def weather(names=NAMES):
    sa = MicrowaveSite(id="own-1", name=names[0], latitude=F.A[0], longitude=F.A[1], provenance=Provenance.USER_PROVIDED, source="test")
    sb = MicrowaveSite(id="own-2", name=names[1], latitude=F.B[0], longitude=F.B[1], provenance=Provenance.USER_PROVIDED, source="test")
    link = MicrowaveLink(id="my-link-77", site_a=sa, site_b=sb, frequency_ghz=18.0, polarization="V", fade_margin_db=32.0,
                         provenance=Provenance.USER_PROVIDED, source="test")
    by_site = {"own-1": F.obs(sa, 2.4), "own-2": F.obs(sb, 0.5)}
    reps = {s.id: assess_representativeness(site=s, nearest_station=None, station_distance_km=None, station_reports_precipitation=True,
                                            model_observation=by_site[s.id]) for s in (sa, sb)}
    return SimpleNamespace(kind="microwave-exposure", exposure=calculate_exposure(link, by_site), representativeness=reps, weather_errors={},
                           history={"own-1": "MUST NOT APPEAR"})


def parse(text):
    pre = [line for line in text.splitlines() if line.startswith("#") or line.startswith('"#')]
    body = [line for line in text.splitlines() if not (line.startswith("#") or line.startswith('"#'))]
    return pre, list(csv.reader(io.StringIO("\n".join(body))))


def test_layout_is_the_maps_evidence_file():
    pre, rows = parse(S.study_to_csv([terrain(), weather()], generated="2026-10-30T12:00:00Z"))
    assert pre[0] == "# Velorona QGIS -- link study evidence export" and pre[1].startswith("# Analyses: 2 (one link:")
    assert "# Generated: 2026-10-30T12:00:00Z" in pre and "# Type key:" in pre and pre[-1] == "#"
    assert any(p.startswith("#   Reference data (DEM) = ") for p in pre) and any(p.startswith("# Earth-curvature convention:") for p in pre)
    assert any(p.startswith("# Data limits (https://map.velorona.ai/guide#limits)") for p in pre)
    assert any("It does not replace a field survey or a regulatory filing." in p for p in pre)
    assert rows[0] == ["Analysis", *EVIDENCE_HEADER]
    kinds = {r[0].split(":")[0] for r in rows[1:]}
    assert kinds == {"Path clearance", "Weather exposure"}
    assert all(len(r) == 7 for r in rows[1:])
    elev = [r for r in rows if r[1] == "Ground elevation profile"]
    assert elev and elev[0][2] == "Reference data (DEM)"


def test_rows_are_the_single_exports_rows():
    from core.export import result_to_csv
    t = terrain(names=("A1", "B1"))
    single = [r for r in csv.reader(io.StringIO("\n".join(line for line in result_to_csv(t).splitlines() if not line.startswith("#"))))][1:]
    _, rows = parse(S.study_to_csv([t], include_names=True))
    assert [r[1:] for r in rows[1:]] == single


def test_own_names_are_left_out_by_default_and_included_when_ticked():
    text = S.study_to_csv([terrain(), weather()])
    for secret in (*NAMES, "my-link-77", "own-1", "own-2"):
        assert secret not in text, secret
    assert "Site A" in text and "Names: your own site and link names are replaced" in text
    named = S.study_to_csv([terrain(), weather()], include_names=True)
    assert "Tower North 12" in named and "=Hilltop Repeater" in named
    _, rows = parse(named)
    assert not any(c.startswith(("=", "+", "@")) for r in rows for c in r)      # no cell a spreadsheet would run as a formula


def test_public_register_names_are_kept():
    text = S.study_to_csv([terrain(names=("TORONTO CN TOWER", "MISSISSAUGA"), source="ISED Fixed Service (TAFL)", public=True)])
    assert "TORONTO CN TOWER" in text


def test_no_history_is_exported():
    text = S.study_to_csv([weather()])
    assert "MUST NOT APPEAR" not in text and "What changed" not in text.replace("Not included: stored history (What changed)", "")


def test_only_the_same_link_and_the_newest_of_each_kind():
    t_old, t_new, w = terrain(), terrain(), weather()
    other = F.terrain_result()
    other.result = SimpleNamespace(profile=[SimpleNamespace(latitude=1.0, longitude=2.0), SimpleNamespace(latitude=1.1, longitude=2.1)])
    assert S.same_study([t_old, other, w, t_new], w) == [t_new, w]
    assert S.study_key(t_new) == S.study_key(w)                    # same endpoints, either order


def test_nothing_to_export_says_so():
    with pytest.raises(NotExportable):
        S.study_to_csv([SimpleNamespace(kind="site")])


def test_a_risky_preamble_line_is_one_quoted_cell():
    assert S._comment("Link: a, =HYPERLINK(1)").startswith('"# ')
    assert S._comment("Analyses: 2, -1.5 dB") == "# Analyses: 2, -1.5 dB"
