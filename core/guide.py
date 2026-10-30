"""Links from the plugin to the Velorona user guide (https://map.velorona.ai/guide#<id>).

A panel keeps ONE line of text; whatever needs more words is explained in the guide under a message ID. The IDs follow the Velorona Map registry
(web/messages.json): E-/W-/I- + area + name, lower case, e.g. ``I-terrain-elevation-source``. The same situation uses the same ID and wording in the Map
and here. IDs that exist only in the plugin are listed in CHANGES.md (PLUGIN_MESSAGE_IDS below is the same list) so they can be added to the registry.
Nothing is sent anywhere: the browser opens the page, the plugin passes no data in the address."""

from __future__ import annotations

import re

GUIDE_URL = "https://map.velorona.ai/guide"
_ID = re.compile(r"^[EWI]-[a-z0-9]+(?:-[a-z0-9]+)+$")

# Plugin-only message IDs (until the registry has them): id -> the one line the panel shows.
PLUGIN_MESSAGE_IDS = {
    "I-terrain-elevation-source": "Ground heights: Velorona's online 90 m elevation data, or a raster of yours.",
    "I-usa-data-source": "USA data is Velorona's online data, not included in the plugin. Canada works without it.",
}


def is_message_id(message_id: str) -> bool:
    return bool(_ID.match(message_id or ""))


def guide_url(message_id: str = "") -> str:
    """The guide page, or its section for ``message_id`` (an invalid ID opens the top of the guide rather than a broken anchor)."""
    return f"{GUIDE_URL}#{message_id}" if is_message_id(message_id) else GUIDE_URL


def open_guide(message_id: str = "") -> bool:
    from qgis.PyQt.QtCore import QUrl
    from qgis.PyQt.QtGui import QDesktopServices
    return bool(QDesktopServices.openUrl(QUrl(guide_url(message_id))))
