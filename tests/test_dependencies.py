"""Missing-dependency detection and message. Pure stdlib -- runs without QGIS."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import dependencies  # noqa: E402

LC_REQUIREMENT = "aei-link-clearance>=0.2.0,<0.3"   # 0.2.0 corrected the earth-curvature sign; 0.3 is not yet vetted


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
    assert declared == [pip for _, pip in dependencies.REQUIREMENTS]


def test_link_clearance_requires_the_corrected_release_line():
    assert ("aei_link_clearance", LC_REQUIREMENT) in dependencies.REQUIREMENTS


def test_install_message_does_not_quote_plain_requirements():
    assert "pip install skyfield" in dependencies.install_message(["skyfield"])


def test_installed_link_clearance_is_inside_the_declared_range():
    from importlib.metadata import version
    major_minor = tuple(int(x) for x in version("aei-link-clearance").split(".")[:2])
    assert (0, 2) <= major_minor < (0, 3), "install the released aei-link-clearance>=0.2.0,<0.3 (see requirements.txt)"
