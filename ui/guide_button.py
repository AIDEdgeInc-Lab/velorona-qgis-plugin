"""The small "?" next to a one-line panel message: opens that message's section of the user guide in the browser."""

from __future__ import annotations

from qgis.PyQt.QtWidgets import QToolButton

from ..core import guide


def guide_button(message_id: str, parent=None) -> QToolButton:
    b = QToolButton(parent)
    b.setText("?")
    b.setAutoRaise(True)
    b.setToolTip("Open the guide for this message in your browser")
    b.setAccessibleName("Guide")
    b.setProperty("guideId", message_id)
    b.clicked.connect(lambda _=False, mid=message_id: guide.open_guide(mid))
    return b
