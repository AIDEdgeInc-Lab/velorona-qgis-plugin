"""Generic small parameter dialog, built from an engine's PARAM_SPEC list
of {key, label, type: 'float'|'choice', default, suffix?, choices?}.
Shared by the terrestrial and microwave-exposure engines so each doesn't
need its own hand-built dialog class."""

from __future__ import annotations

from qgis.PyQt.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QVBoxLayout,
)


class ParamDialog(QDialog):
    def __init__(self, parent, title: str, param_spec: list, defaults: dict):
        super().__init__(parent)
        self.setWindowTitle(title)
        self._spec = param_spec
        self._widgets = {}

        form = QFormLayout()
        for p in param_spec:
            if p["type"] == "float":
                widget = QDoubleSpinBox(self)
                widget.setRange(0.1, 100000.0)
                widget.setDecimals(2)
                if p.get("suffix"):
                    widget.setSuffix(p["suffix"])
                widget.setValue(float(defaults.get(p["key"], p["default"])))
            elif p["type"] == "choice":
                widget = QComboBox(self)
                widget.addItems(p["choices"])
                widget.setCurrentText(str(defaults.get(p["key"], p["default"])))
            else:
                raise ValueError(f"unknown param type: {p['type']}")
            self._widgets[p["key"]] = widget
            form.addRow(p["label"], widget)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def values(self) -> dict:
        out = {}
        for p in self._spec:
            widget = self._widgets[p["key"]]
            out[p["key"]] = widget.value() if p["type"] == "float" else widget.currentText()
        return out
