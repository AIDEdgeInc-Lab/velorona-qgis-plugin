"""Missing-dependency detection and message. Pure stdlib -- runs without QGIS."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import dependencies  # noqa: E402


def test_missing_requirements_reports_only_absent_packages(monkeypatch):
    monkeypatch.setattr(dependencies, "_is_installed", lambda name: name != "aei_link_clearance")
    assert dependencies.missing_requirements() == ["aei-link-clearance"]


def test_missing_requirements_empty_when_all_present(monkeypatch):
    monkeypatch.setattr(dependencies, "_is_installed", lambda name: True)
    assert dependencies.missing_requirements() == []


def test_install_message_names_the_packages_to_install():
    msg = dependencies.install_message(["aei-link-clearance"], detail="No module named 'aei_link_clearance'")
    assert "pip install aei-link-clearance" in msg
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


def test_shared_core_is_reported_when_absent_and_never_suggested_to_pip(monkeypatch):
    monkeypatch.setattr(dependencies, "_is_installed", lambda name: name != "aei_workflow")
    monkeypatch.setattr(dependencies, "_shared_core_present", lambda: False)
    missing = dependencies.missing_requirements()
    assert missing == ["aei-workflow-runner"]
    msg = dependencies.install_message(missing, detail="No module named 'aei_workflow'")
    assert "release builds" in msg and "pip install aei-workflow-runner" not in msg and "-e path/to/aei-workflow-runner" in msg


def test_a_bundled_core_counts_as_present(monkeypatch, tmp_path):
    monkeypatch.setattr(dependencies, "_is_installed", lambda name: name != "aei_workflow")
    plugin_root = os.path.dirname(os.path.dirname(os.path.abspath(dependencies.__file__)))
    vendored = os.path.join(plugin_root, "_vendor", "aei_workflow")
    monkeypatch.setattr(dependencies.os.path, "isdir", lambda p: p == vendored)
    assert dependencies.missing_requirements() == []
