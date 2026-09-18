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
    QMessageBox,
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
                # Each parameter's own envelope, with its basis recorded beside
                # it in the engine's PARAM_SPEC. A single 0.1-100000.0 range for
                # every float let "fade margin 100000 dB" through to be computed
                # and exported typed "Calculated".
                #
                # The spin box range is set one step wider than the real bound so
                # Qt cannot silently clamp an out-of-range entry to the limit: a
                # clamped value would be a wrong number reported back as though
                # the operator had chosen it, which is the same defect as
                # rounding their input. validate() refuses instead.
                low, high = float(p.get("min", 0.1)), float(p.get("max", 100000.0))
                widget.setDecimals(2)
                widget.setRange(low - 1.0 if low > 1.0 else 0.0, high + 1.0)
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
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def out_of_range(self) -> list:
        """[(label, value, min, max, basis)] for every float outside its own
        envelope. Empty when the dialog's values are all usable."""
        bad = []
        for p in self._spec:
            if p["type"] != "float":
                continue
            low, high = p.get("min"), p.get("max")
            if low is None and high is None:
                continue
            value = self._widgets[p["key"]].value()
            if (low is not None and value < low) or (high is not None and value > high):
                bad.append((p["label"], value, low, high, p.get("basis", "")))
        return bad

    def _on_accept(self):
        """Refuse an out-of-range value instead of clamping it. Clamping would
        substitute a number the operator did not choose and then export it
        typed as their input -- the dialog says what is wrong and why, and the
        operator fixes it."""
        bad = self.out_of_range()
        if not bad:
            self.accept()
            return
        details = "\n\n".join(
            f"{label}: {value:g} is outside {low:g} to {high:g}.\n{basis}"
            for label, value, low, high, basis in bad)
        QMessageBox.warning(self, "Velorona -- value out of range",
                            "This analysis will not run with the value(s) below. "
                            "Nothing was computed.\n\n" + details)

    def values(self) -> dict:
        out = {}
        for p in self._spec:
            widget = self._widgets[p["key"]]
            out[p["key"]] = widget.value() if p["type"] == "float" else widget.currentText()
        return out
