"""Missing-dependency detection and message. Pure stdlib -- runs without QGIS."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import dependencies  # noqa: E402

LC_REQUIREMENT = "aei-link-clearance>=0.3.0,<0.5"   # 0.2.0 corrected the earth-curvature sign; 0.3.0 adds the elevation seam this version needs; 0.4 tested (1.1.12)


def test_missing_requirements_reports_only_absent_packages(monkeypatch):
    monkeypatch.setattr(dependencies, "_is_installed", lambda name: name != "aei_link_clearance")
    assert dependencies.missing_requirements() == [LC_REQUIREMENT]


def test_missing_requirements_empty_when_all_present(monkeypatch):
    monkeypatch.setattr(dependencies, "_is_installed", lambda name: True)
    assert dependencies.missing_requirements() == []


def test_install_message_names_the_packages_to_install():
    msg = dependencies.install_message([LC_REQUIREMENT], detail="No module named 'aei_link_clearance'")
    assert f"pip install '{LC_REQUIREMENT}'" in msg      # quoted: an unquoted '>' or '<' is a shell redirect
    assert "No module named" in msg


def test_install_message_when_nothing_is_missing_does_not_claim_packages_are_missing():
    msg = dependencies.install_message([], detail="cannot import name 'x'")
    assert "missing" not in msg
    assert "cannot import name 'x'" in msg
    for _, pip in dependencies.REQUIREMENTS:
        assert pip in msg


def test_requirements_txt_matches_requirements_list():
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "requirements.txt")
    with open(path) as f:
        declared = [l.strip() for l in f if l.strip() and not l.startswith("#")]
    assert declared == [pip for _, pip in dependencies.REQUIREMENTS + dependencies.OPTIONAL_REQUIREMENTS]
    assert not set(dependencies.OPTIONAL_REQUIREMENTS) & set(dependencies.REQUIREMENTS)     # an optional package never blocks the plugin from loading


def test_link_clearance_requires_the_corrected_release_line():
    assert ("aei_link_clearance", LC_REQUIREMENT) in dependencies.REQUIREMENTS


def test_install_message_does_not_quote_plain_requirements():
    assert "pip install skyfield" in dependencies.install_message(["skyfield"])


def test_installed_link_clearance_is_inside_the_declared_range():
    from importlib.metadata import version
    major_minor = tuple(int(x) for x in version("aei-link-clearance").split(".")[:2])
    assert (0, 3) <= major_minor < (0, 5), "install the released aei-link-clearance>=0.3.0,<0.5 (see requirements.txt)"


# --- first-run guidance (stage 2): version range warning, actionable messages ----------------------------------------------------------------------
import pytest  # noqa: E402


def _installed(monkeypatch, version, per_dist=None):
    def fake(name):
        v = (per_dist or {}).get(name, version)
        if v is None:
            raise dependencies._metadata.PackageNotFoundError(name)
        return v
    monkeypatch.setattr(dependencies._metadata, "version", fake)


@pytest.mark.parametrize("v", ["0.3.0", "0.3.1", "0.3.17", "0.3.1.post1", "0.3.1rc1", "0.4.0", "0.4.9"])
def test_supported_library_versions_give_no_warning(monkeypatch, v):
    _installed(monkeypatch, v, {"aei-microwave-link-exposure": "0.2.0"})
    assert dependencies.library_range_warning() == ""


@pytest.mark.parametrize("v", ["0.1.0", "0.1.9", "0.2.1", "0.5.0", "1.0.0"])
def test_out_of_range_library_warns_with_the_fix(monkeypatch, v):
    _installed(monkeypatch, v)
    w = dependencies.library_range_warning()
    assert v in w and "aei-link-clearance>=0.3.0,<0.5" in w and "Python Console" in w and "restart QGIS" in w
    assert "'aei-link-clearance>=0.3.0,<0.5'" in w and w.count("Plugins > Python Console") == 1


def test_not_installed_or_unreadable_version_is_not_reported_here(monkeypatch):
    _installed(monkeypatch, None)
    assert dependencies.library_range_warning() == ""       # the missing-package path owns that message
    _installed(monkeypatch, "dev")
    assert dependencies.library_range_warning() == ""       # unknown is not a problem report


def test_missing_message_offers_the_python_console_route():
    msg = dependencies.install_message([LC_REQUIREMENT])
    assert "Plugins > Python Console" in msg and "from pip._internal.cli.main import main" in msg and "restart QGIS" in msg


def test_old_library_refusal_names_the_version_needed_and_how_to_install():
    import aei_link_clearance.terrain as t
    from types import SimpleNamespace
    from core.validation import LibraryOutOfDateError, require_corrected_clearance
    with pytest.raises(LibraryOutOfDateError) as exc:
        require_corrected_clearance(SimpleNamespace())
    assert "aei-link-clearance>=0.3.0,<0.5" in str(exc.value) and "Python Console" in str(exc.value) and t is not None


def test_old_rain_library_alone_is_flagged_with_its_own_fix(monkeypatch):
    _installed(monkeypatch, "0.3.0", {"aei-microwave-link-exposure": "0.1.5"})
    w = dependencies.library_range_warning()
    assert "aei-microwave-link-exposure 0.1.5" in w and "aei-microwave-link-exposure>=0.2.0,<0.4" in w and "P.838-3" in w
    assert "aei-link-clearance" not in w.split("In QGIS")[0]
    _installed(monkeypatch, "0.3.0", {"aei-microwave-link-exposure": "0.2.0"})
    assert dependencies.library_range_warning() == ""


def test_a_library_without_the_elevation_seam_is_refused_with_the_install_command():
    from types import SimpleNamespace
    from core.validation import LibraryOutOfDateError, require_elevation_seam
    for old in (SimpleNamespace(), SimpleNamespace(OpenMeteoProvider=object)):          # 0.2.x has neither provider / only one
        with pytest.raises(LibraryOutOfDateError) as exc:
            require_elevation_seam(old)
        assert "aei-link-clearance>=0.3.0,<0.5" in str(exc.value) and "Python Console" in str(exc.value) and "restart QGIS" in str(exc.value)
    import aei_link_clearance
    require_elevation_seam(aei_link_clearance)                                           # the pinned library passes


def test_terrain_analysis_with_an_old_library_is_refused_before_any_request(monkeypatch):
    import types
    from core.engines import terrestrial
    from core.validation import LibraryOutOfDateError
    monkeypatch.setattr(terrestrial, "_library", types.SimpleNamespace())
    with pytest.raises(LibraryOutOfDateError):
        terrestrial.analyze_endpoints(43.7, -79.4, 43.8, -79.2, {"site_a_height_m": 30.0, "site_b_height_m": 30.0, "frequency_ghz": 7.0}, "t")


@pytest.mark.parametrize("mw", ["0.2.0", "0.2.9", "0.3.0", "0.3.4"])
def test_supported_rain_library_versions_give_no_warning(monkeypatch, mw):
    """1.1.12: aei-microwave-link-exposure 0.3 (security baseline: NaN and missing rain refused, never read as 0) is accepted."""
    _installed(monkeypatch, "0.4.0", {"aei-microwave-link-exposure": mw})
    assert dependencies.library_range_warning() == ""


@pytest.mark.parametrize("mw", ["0.4.0", "1.0.0"])
def test_rain_library_above_the_tested_range_still_warns(monkeypatch, mw):
    _installed(monkeypatch, "0.4.0", {"aei-microwave-link-exposure": mw})
    w = dependencies.library_range_warning()
    assert f"aei-microwave-link-exposure {mw}" in w and "aei-microwave-link-exposure>=0.2.0,<0.4" in w

