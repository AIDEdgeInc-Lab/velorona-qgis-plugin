"""The History window: timeline per link ('N hours ago'), a 'what changed' panel, observed and model-derived kept apart, CSV export, retention
setting, clear this link / clear everything. Everything shown comes from the local file; nothing is sent anywhere."""

from __future__ import annotations

import os
import time
from typing import Dict, Optional

from qgis.PyQt.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QSpinBox, QTextBrowser,
                                 QVBoxLayout)

from ..core import history_changes, history_view, messages
from ..core.history_store import HistoryError, HistoryStore
from . import theme


class HistoryDialog(QDialog):
    def __init__(self, parent, store: HistoryStore, known_labels: Optional[Dict[str, str]] = None, entity_id: Optional[str] = None,
                 dark: bool = True, clock=time.time):
        super().__init__(parent)
        self.setWindowTitle("Velorona -- History")
        self.resize(820, 620)
        self._store, self._known, self._dark, self._clock = store, known_labels or {}, dark, clock
        self._wanted_entity = entity_id

        self.entity_combo = QComboBox(self)
        self.entity_combo.setToolTip("History is kept per link or site, on this computer only. Your own sites and links are stored under a private code; the names you see are kept next to it in the same file.")
        self.window_combo = QComboBox(self)
        for hours in (1, 3, 6, 24):
            self.window_combo.addItem(f"Compare with {hours} h ago", hours)
        self.window_combo.setCurrentIndex(2)
        self.stats_label = QLabel(self)
        self.stats_label.setWordWrap(True)
        self.retention = QSpinBox(self)
        self.retention.setRange(1, 24 * 7)
        self.retention.setSuffix(" h kept")
        self.retention.setToolTip("How long values are kept on this computer: 1 hour to 7 days (168 h). Older values are deleted.")
        self.apply_retention = QPushButton("Apply", self)
        self.view = QTextBrowser(self)
        self.export_button = QPushButton("Export CSV...", self)
        self.clear_entity_button = QPushButton("Clear this link's history", self)
        self.clear_all_button = QPushButton("Clear all my history", self)
        close = QPushButton("Close", self)

        top = QHBoxLayout(); top.addWidget(self.entity_combo, 1); top.addWidget(self.window_combo)
        ret = QHBoxLayout(); ret.addWidget(self.stats_label, 1); ret.addWidget(self.retention); ret.addWidget(self.apply_retention)
        bottom = QHBoxLayout()
        for w in (self.export_button, self.clear_entity_button, self.clear_all_button):
            bottom.addWidget(w)
        bottom.addStretch(1); bottom.addWidget(close)
        layout = QVBoxLayout(self)
        layout.addLayout(top); layout.addLayout(ret); layout.addWidget(self.view, 1); layout.addLayout(bottom)

        self.entity_combo.currentIndexChanged.connect(lambda _i: self.refresh(keep_entity=True))
        self.window_combo.currentIndexChanged.connect(lambda _i: self.refresh(keep_entity=True))
        self.apply_retention.clicked.connect(self._on_apply_retention)
        self.export_button.clicked.connect(self._on_export)
        self.clear_entity_button.clicked.connect(self._on_clear_entity)
        self.clear_all_button.clicked.connect(self._on_clear_all)
        close.clicked.connect(self.accept)
        self.refresh()

    # -- state --------------------------------------------------------------------------------------------------------------------------

    def _selected_entity(self) -> Optional[str]:
        return self.entity_combo.currentData()

    def refresh(self, keep_entity: bool = False) -> None:
        style = theme.report_stylesheet(self._dark)
        try:
            entities = self._store.entities() if _exists(self._store) else []
            stats = self._store.stats() if entities else None
            retention = self._store.retention_hours()
        except HistoryError as exc:
            self.view.setHtml(style + history_view.error_html(str(exc)))
            self._enable(False)
            return
        current = self._selected_entity() if keep_entity else (self._wanted_entity or self._selected_entity())
        self.entity_combo.blockSignals(True)
        self.entity_combo.clear()
        self.entity_combo.addItem("All links and sites", None)
        for entity_id, _etype, rows, _newest in entities:
            self.entity_combo.addItem(f"{history_view.label_for(entity_id, self._known)}  ({rows} values)", entity_id)
        index = self.entity_combo.findData(current)
        self.entity_combo.setCurrentIndex(index if index >= 0 else 0)
        self.entity_combo.blockSignals(False)
        self.retention.setValue(retention)
        self.stats_label.setText(
            f"{stats.rows:,} values, {stats.bytes / 1024:.0f} KB of {stats.max_bytes // 1024 // 1024} MB (at most {stats.max_rows:,} values); "
            f"{(stats.oldest or '')[:16].replace('T', ' ')} to {(stats.newest or '')[:16].replace('T', ' ')} UTC. Kept {retention} h. "
            f"{history_view.LOCAL_ONLY}" if stats else f"No history stored. Kept {retention} h when there is. {history_view.LOCAL_ONLY}")
        self._enable(True)
        self.clear_entity_button.setEnabled(self._selected_entity() is not None)
        self.export_button.setEnabled(bool(entities))
        self.clear_all_button.setEnabled(bool(entities))
        self._render(style)

    def _enable(self, on: bool) -> None:
        for w in (self.entity_combo, self.window_combo, self.retention, self.apply_retention, self.export_button, self.clear_entity_button,
                  self.clear_all_button):
            w.setEnabled(on)

    def _render(self, style: str) -> None:
        entity = self._selected_entity()
        now = self._clock()
        try:
            records = self._store.records(entity)
        except HistoryError as exc:
            self.view.setHtml(style + history_view.error_html(str(exc)))
            return
        body = ""
        if entity is not None and records:
            hours = self.window_combo.currentData()
            summary = history_changes.compute_changes(records, entity, now, hours, entity_label=history_view.label_for(entity, self._known))
            lines = history_changes.sentences(summary)
            body += ("<div class='sec'>What changed</div>" + "".join(f"<p>{history_view._esc(t)}</p>" for t in lines)) if lines else ""
        body += history_view.timeline_html(records, now, self._known)
        self.view.setHtml(style + body)

    # -- actions ------------------------------------------------------------------------------------------------------------------------

    def _on_apply_retention(self) -> None:
        try:
            self._store.set_retention_hours(self.retention.value())
        except HistoryError as exc:
            QMessageBox.warning(self, "Velorona", f"The retention was not changed.\n\n{exc}")
        self.refresh(keep_entity=True)

    def _ask_include_names(self) -> Optional[bool]:
        """The export options: False (the default) writes only the private codes; True also writes the names you gave your sites and links.
        None = cancelled. Replaceable in tests."""
        box = QDialog(self)
        box.setWindowTitle("Export history as CSV")
        layout = QVBoxLayout(box)
        layout.addWidget(QLabel("The file lists the stored values. Your own sites and links appear under their private codes."))
        include = QCheckBox("Include my site names", box)
        include.setChecked(False)
        include.setToolTip("Adds a column with the names you see in the History window. Leave it off if the file will be shared.")
        layout.addWidget(include)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, box)
        buttons.accepted.connect(box.accept)
        buttons.rejected.connect(box.reject)
        layout.addWidget(buttons)
        include.setObjectName("veloronaIncludeNames")
        if box.exec() != QDialog.DialogCode.Accepted:
            return None
        return include.isChecked()

    def _on_export(self) -> None:
        include_names = self._ask_include_names()
        if include_names is None:
            return
        try:
            name, text = self._store.export_csv(self._selected_entity(), include_names=include_names)
        except HistoryError as exc:
            QMessageBox.warning(self, "Velorona", f"History could not be exported.\n\n{exc}")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export history as CSV", name, "CSV files (*.csv)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(text)
        except OSError as exc:
            QMessageBox.warning(self, "Velorona", f"The file could not be written.\n\n{exc}")
            return
        QMessageBox.information(self, "Velorona", messages.text("I-EXPORT-DONE", file=os.path.basename(path)) + "\n\nThis file is yours; Velorona does not upload it.")

    def _on_clear_entity(self) -> None:
        entity = self._selected_entity()
        if entity is None:
            return
        if QMessageBox.question(self, "Velorona", f"Delete the stored history of {history_view.label_for(entity, self._known)}? This cannot be undone.") \
                != QMessageBox.StandardButton.Yes:
            return
        self._store.clear_entity(entity)
        self.refresh()

    def _on_clear_all(self) -> None:
        if QMessageBox.question(self, "Velorona", "Delete ALL stored history from this computer? This cannot be undone.") != QMessageBox.StandardButton.Yes:
            return
        try:
            self._store.clear_all()
        except HistoryError as exc:
            QMessageBox.warning(self, "Velorona", f"History could not be deleted.\n\n{exc}")
        self.refresh()


def _exists(store: HistoryStore) -> bool:
    import os
    return os.path.exists(store.path)
