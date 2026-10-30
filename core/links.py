"""Where the plugin's Help entries lead. Each opens a public page in the browser; the plugin sends nothing and counts nothing (no telemetry).

The bug link pre-fills only the plugin version (shown in the form, editable, sent only if the user submits the issue on GitHub)."""

from __future__ import annotations

from urllib.parse import urlencode

REPOSITORY_URL = "https://github.com/AIDEdgeInc-Lab/velorona-qgis-plugin"
ISSUES_URL = REPOSITORY_URL + "/issues/new"
DOCS_URL = REPOSITORY_URL + "#readme"


def bug_url(plugin_version: str = "") -> str:
    query = {"template": "bug.yml"}
    if plugin_version:
        query["plugin_version"] = plugin_version
    return f"{ISSUES_URL}?{urlencode(query)}"


def feature_url() -> str:
    return f"{ISSUES_URL}?{urlencode({'template': 'feature.yml'})}"


def open_url(url: str) -> bool:
    from qgis.PyQt.QtCore import QUrl
    from qgis.PyQt.QtGui import QDesktopServices
    return bool(QDesktopServices.openUrl(QUrl(url)))
