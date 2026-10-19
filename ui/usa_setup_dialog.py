"""Friendly setup for the USA (FCC) data pack. Opens only when the user asks for US data; nothing here runs at plugin start.

Shows what the pack is, where it can come from, and an honest status (Not set up / Checking / Ready with the pack's own link count / Problem with what to do).
"Use this data" stays disabled until a check really succeeded. Cancel changes nothing."""

from __future__ import annotations

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (QApplication, QDialog, QDialogButtonBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                                 QTextBrowser, QVBoxLayout)

from ..core.countries import usa_setup

# Status colours are chosen to read on both light and dark QGIS themes (text colour only, no backgrounds).
_COLOURS = {usa_setup.NOT_CONFIGURED: "#8a8f98", usa_setup.LOADED: "#2e9e5b", usa_setup.ERROR: "#d9534f"}
_HEADLINE = {usa_setup.NOT_CONFIGURED: "Not set up yet", usa_setup.LOADED: "Ready", usa_setup.ERROR: "Problem"}


class UsaSetupDialog(QDialog):
    def __init__(self, parent, current_source: str = "", intro: bool = False, check=usa_setup.check_source, pick_folder=None, is_off: bool = False):
        super().__init__(parent)
        self.setWindowTitle("Velorona — USA data (FCC)")
        self.setMinimumWidth(560)
        self._check = check
        self._pick_folder = pick_folder or (lambda start: QFileDialog.getExistingDirectory(self, "Choose the USA data pack folder", start))
        self._result = usa_setup.SetupCheck(usa_setup.NOT_CONFIGURED)
        self.chosen_source = ""            # set only after a successful check
        self.remove_requested = False
        self.off_requested = False

        layout = QVBoxLayout(self)
        lead = ("USA data is turned off for this project. " if is_off else "") + \
            ("By default Velorona reads <b>Velorona's online USA data</b> (public FCC licence records, the same data Velorona Map shows) for the area you "
             "look at: USA links and sites appear as you move the map, and nothing is downloaded for areas you do not view. The data is <b>not included in "
             "the plugin</b>. Use this window to read it from a folder or another address instead, or to turn it off. <b>Canada works without it.</b>")
        self.lead = QLabel(lead)
        self.lead.setWordWrap(True)
        layout.addWidget(self.lead)

        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.RichText)
        self.status.setFrameShape(QFrame.Shape.StyledPanel)
        self.status.setMargin(8)
        layout.addWidget(self.status)

        row = QHBoxLayout()
        self.btn_online = QPushButton("Use Velorona's online USA data")
        self.btn_online.setToolTip(f"Reads only the tiles under the map view you ask for, from {usa_setup.VELORONA_ONLINE_PACK}")
        self.btn_folder = QPushButton("Choose a folder…")
        self.btn_folder.setToolTip("A folder on this computer that contains index.json and a tiles folder")
        row.addWidget(self.btn_online)
        row.addWidget(self.btn_folder)
        layout.addLayout(row)

        layout.addWidget(QLabel("Or a web address (https), the one that serves index.json:"))
        addr = QHBoxLayout()
        self.address = QLineEdit()
        self.address.setPlaceholderText("https://…/data/us/")
        self.btn_check = QPushButton("Check")
        addr.addWidget(self.address, 1)
        addr.addWidget(self.btn_check)
        layout.addLayout(addr)

        self.btn_help = QPushButton("How do I get the data?")
        self.btn_help.setFlat(True)
        layout.addWidget(self.btn_help, 0, Qt.AlignmentFlag.AlignLeft)
        self.help = QTextBrowser()
        self.help.setOpenExternalLinks(True)
        self.help.setHtml(usa_setup.help_html())
        self.help.setMinimumHeight(260)
        self.help.hide()
        layout.addWidget(self.help)

        self.buttons = QDialogButtonBox(self)
        self.btn_use = self.buttons.addButton("Use this data", QDialogButtonBox.ButtonRole.AcceptRole)
        self.btn_remove = self.buttons.addButton("Forget the saved setting (use the online data)", QDialogButtonBox.ButtonRole.DestructiveRole)
        self.btn_off = self.buttons.addButton("Turn USA data off", QDialogButtonBox.ButtonRole.DestructiveRole)
        self.btn_cancel = self.buttons.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
        layout.addWidget(self.buttons)

        self.btn_online.clicked.connect(lambda: self._run(usa_setup.VELORONA_ONLINE_PACK))
        self.btn_folder.clicked.connect(self._on_folder)
        self.btn_check.clicked.connect(lambda: self._run(self.address.text()))
        self.address.returnPressed.connect(lambda: self._run(self.address.text()))
        self.btn_help.clicked.connect(lambda: self.help.setVisible(not self.help.isVisible()))
        self.btn_use.clicked.connect(self._on_use)
        self.btn_remove.clicked.connect(self._on_remove)
        self.btn_off.clicked.connect(self._on_off)
        self.btn_cancel.clicked.connect(self.reject)

        self.btn_remove.setVisible(bool(current_source) or is_off)
        self.btn_off.setVisible(not is_off)
        self._render()
        if current_source:                       # an existing setting is re-checked so the status is true today, not remembered
            self.address.setText(current_source if current_source.lower().startswith("http") else "")
            self._run(current_source)

    # -- behaviour -----------------------------------------------------------------------------------------------------------
    def _on_folder(self):
        start = self._result.source if self._result.source and "://" not in self._result.source else ""
        folder = self._pick_folder(start)
        if folder:                                # an empty answer = the user cancelled the picker: nothing changes
            self._run(folder)

    def _run(self, text: str):
        self.status.setText(f"<b>Checking…</b> {usa_setup.normalise(text)[0] or ''}")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        QApplication.processEvents()
        try:
            self._result = self._check(text)
        finally:
            QApplication.restoreOverrideCursor()
        if self._result.source.lower().startswith("http"):
            self.address.setText(self._result.source)
        self._render()

    def _render(self):
        r = self._result
        colour = _COLOURS[r.state]
        parts = [f"<b style='color:{colour}'>{_HEADLINE[r.state]}</b> — {r.message}"]
        if r.next_step:
            parts.append(r.next_step)
        if r.note:
            parts.append(f"<i>{r.note}</i>")
        if r.ok:
            parts.append(f"<span style='color:{colour}'>Source: {r.source}</span>")
        self.status.setText("<br>".join(parts))
        self.btn_use.setEnabled(r.ok)

    def _on_use(self):
        if self._result.ok:
            self.chosen_source = self._result.source
            self.accept()

    def _on_remove(self):
        self.remove_requested = True
        self.accept()

    def _on_off(self):
        self.off_requested = True
        self.accept()
