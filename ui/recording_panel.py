"""The "Automatic recording" box of the History window: one clear on/off (off by default), the interval, the recorded links, and what it is doing.
All decisions are core/auto_record.py's; ``control`` is the plugin side (see plugin.py ``_RecordingControl``)."""

from __future__ import annotations

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (QCheckBox, QComboBox, QGroupBox, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton,
                                 QVBoxLayout)

from ..core import auto_record, messages
from .guide_button import guide_button


class RecordingPanel(QGroupBox):
    def __init__(self, control, parent=None):
        super().__init__("Automatic recording", parent)
        self._control = control
        self.setObjectName("veloronaRecording")
        self.enabled_box = QCheckBox("Record these links automatically while QGIS is open", self)
        self.interval_combo = QComboBox(self)
        for minutes in auto_record.INTERVAL_CHOICES_MIN:
            self.interval_combo.addItem(f"every {minutes} min", minutes)
        self.status = QLabel(self)
        self.status.setWordWrap(True)
        self.status_help = guide_button(auto_record.OFF, self)
        self.links = QListWidget(self)
        self.links.setMaximumHeight(110)
        self.remove_button = QPushButton("Remove", self)
        self.add_button = QPushButton("Record the link in the results panel", self)
        self.add_names = QCheckBox("Include my site names", self)
        self.add_names.setChecked(False)
        self.add_names.setToolTip("For your own sites and links: store their names on this computer next to the private code. Off: only the code.")
        note = QLabel("Stops when QGIS closes. Gaps are normal when the computer sleeps; nothing is filled in.", self)
        note.setWordWrap(True)
        note.setStyleSheet("color: palette(mid);")

        row1 = QHBoxLayout(); row1.addWidget(self.enabled_box, 1); row1.addWidget(self.interval_combo)
        row2 = QHBoxLayout(); row2.addWidget(self.status, 1); row2.addWidget(self.status_help)
        row3 = QHBoxLayout(); row3.addWidget(self.add_button); row3.addWidget(self.add_names); row3.addStretch(1); row3.addWidget(self.remove_button)
        layout = QVBoxLayout(self)
        layout.addLayout(row1); layout.addLayout(row2); layout.addWidget(self.links); layout.addLayout(row3); layout.addWidget(note)

        self.enabled_box.toggled.connect(self._on_enabled)
        self.interval_combo.currentIndexChanged.connect(lambda _i: self._control.set_interval(self.interval_combo.currentData()) or self.refresh())
        self.add_button.clicked.connect(self._on_add)
        self.remove_button.clicked.connect(self._on_remove)
        self.refresh()

    def refresh(self, message_id: str = "") -> None:
        rec = self._control.recorder
        self.enabled_box.blockSignals(True); self.enabled_box.setChecked(rec.enabled); self.enabled_box.blockSignals(False)
        self.interval_combo.blockSignals(True)
        self.interval_combo.setCurrentIndex(max(0, self.interval_combo.findData(rec.interval_min)))
        self.interval_combo.blockSignals(False)
        self.links.clear()
        for w in rec.round():
            when = self._control.time_text(w.last_ok) if w.last_ok else "not yet"
            item = QListWidgetItem(f"{w.label}  (last recorded: {when}{'; ' + w.last_error if w.last_error else ''})")
            item.setData(Qt.ItemDataRole.UserRole, w.key)
            self.links.addItem(item)
        mid = message_id or rec.status_id
        self.status.setText(f"{messages.text(mid, N=self._n_for(mid), M=rec.interval_min)}  {mid}")
        self.status_help.setProperty("guideId", mid)
        self.add_button.setEnabled(self._control.current_label() is not None)
        self.remove_button.setEnabled(self.links.count() > 0)

    def _n_for(self, mid: str):
        rec = self._control.recorder
        return {auto_record.ON: len(rec.links), auto_record.LIMIT: rec.max_links,
                auto_record.BUSY: rec.interval_min * rec.backoff}.get(mid, "")

    def _on_enabled(self, on: bool) -> None:
        self.refresh(self._control.set_enabled(on))

    def _on_add(self) -> None:
        self.refresh(self._control.add_current(self.add_names.isChecked()))

    def _on_remove(self) -> None:
        item = self.links.currentItem() or (self.links.item(0) if self.links.count() == 1 else None)
        if item is not None:
            self._control.remove(item.data(Qt.ItemDataRole.UserRole))
        self.refresh()
