"""Links from the plugin to the Velorona user guide (https://map.velorona.ai/guide#<id>).

A panel keeps ONE line of text; whatever needs more words is explained in the guide under a message ID. The IDs are the Velorona Map registry's (core/messages.py, a copy of web/messages.json): upper case, e.g. ``I-TERRAIN-ELEVATION-SOURCE``.
Nothing is sent anywhere: the browser opens the page, the plugin passes no data in the address."""

from __future__ import annotations

from . import messages

GUIDE_URL = "https://map.velorona.ai/guide"
JOIN_URL = "https://map.velorona.ai/join"      # "Get updates": the Map's sign-up page; the plugin only opens it, it sends and counts nothing


def is_message_id(message_id: str) -> bool:
    """A well-formed registry ID (upper case, e.g. ``I-TERRAIN-ELEVATION-SOURCE``) that the registry knows."""
    return messages.is_message_id(message_id) and messages.has(message_id)


def guide_url(message_id: str = "") -> str:
    """The guide page, or its section for ``message_id`` (an invalid ID opens the top of the guide rather than a broken anchor)."""
    return f"{GUIDE_URL}#{message_id}" if is_message_id(message_id) else GUIDE_URL


def open_guide(message_id: str = "") -> bool:
    from qgis.PyQt.QtCore import QUrl
    from qgis.PyQt.QtGui import QDesktopServices
    return bool(QDesktopServices.openUrl(QUrl(guide_url(message_id))))


def open_join() -> bool:
    """Menu item "Get updates": opens the sign-up page in the browser. No data is passed in the address and nothing is sent by the plugin."""
    from qgis.PyQt.QtCore import QUrl
    from qgis.PyQt.QtGui import QDesktopServices
    return bool(QDesktopServices.openUrl(QUrl(JOIN_URL)))
