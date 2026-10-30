"""The one "Include my site names" question asked before an export that could carry the user's own names (History CSV, link study).
Default off: only private codes / Site A, Site B leave the computer unless the user ticks the box."""

from __future__ import annotations

from typing import Optional

from qgis.PyQt.QtWidgets import QCheckBox, QDialog, QDialogButtonBox, QLabel, QVBoxLayout

CHECKBOX_NAME = "veloronaIncludeNames"


def ask_include_names(parent, title: str, lead: str) -> Optional[bool]:
    """False (default) / True, or None when cancelled."""
    box = QDialog(parent)
    box.setWindowTitle(title)
    layout = QVBoxLayout(box)
    label = QLabel(lead, box)
    label.setWordWrap(True)
    layout.addWidget(label)
    include = QCheckBox("Include my site names", box)
    include.setObjectName(CHECKBOX_NAME)
    include.setChecked(False)
    include.setToolTip("Adds the names you gave your own sites and links. Leave it off if the file will be shared.")
    layout.addWidget(include)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, box)
    buttons.accepted.connect(box.accept)
    buttons.rejected.connect(box.reject)
    layout.addWidget(buttons)
    if box.exec() != QDialog.DialogCode.Accepted:
        return None
    return include.isChecked()
