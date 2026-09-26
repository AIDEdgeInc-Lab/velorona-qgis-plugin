"""Automation dialog: saved workflows, background batch runs, run history, comparison, export.

QGIS-native widgets only. All analysis and storage logic lives in core.automation; this file wires
it to widgets and to a QgsTask, and owns no analysis logic of its own.
"""

from __future__ import annotations

from qgis.core import QgsApplication
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QAbstractItemView, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout,
    QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QProgressBar,
    QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget, QComboBox,
)

from ..core.automation import compare as compare_mod
from ..core.automation import inputs, report
from ..core.automation.qgis_task import WorkflowTask, default_store_root
from ..core.automation.schema import SchemaError
from ..core.automation.store import RunStore, StoreError
from ..core.automation.workflow import new_workflow, touch

RESULT_COLUMNS = ["Link", "Status", "Line of sight", "Clearance ratio", "Note"]


def _item(text, tooltip=None):
    it = QTableWidgetItem(str(text))
    it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
    if tooltip:
        it.setToolTip(tooltip)
    return it


def link_row_values(link: dict) -> list:
    r = link.get("result") or {}
    los = r.get("los_status", "")
    if r.get("near_threshold"):
        los += " (near threshold)"
    ratio = "" if r.get("clearance_ratio") is None else f"{r['clearance_ratio']:.3f}"
    note = " ".join(link.get("warnings", []))
    if link["status"] == "failed":
        note = f"{link['error']['type']}: {link['error']['message']}"
    elif link["status"] == "not_run":
        note = "Not run"
    return [link["link_id"], link["status"], los, ratio, note]


class AutomationDialog(QDialog):
    def __init__(self, parent=None, store_root: str = None, analyzer=None):
        super().__init__(parent)
        self.setWindowTitle("Velorona -- Batch Path Clearance Runs")
        self.setObjectName("VeloronaAutomationDialog")
        self.resize(980, 700)
        self.store = RunStore(store_root or default_store_root())
        self._analyzer = analyzer
        self._task = None
        self._validation = None
        self._source = None
        self._workflow = None        # the saved workflow currently loaded, or None for "new"
        self._compare_dialog = None

        tabs = QTabWidget(self)
        tabs.addTab(self._build_run_tab(), "Workflow and run")
        tabs.addTab(self._build_history_tab(), "History")
        self.tabs = tabs
        lay = QVBoxLayout(self)
        lay.addWidget(tabs)
        self.status = QLabel("", self)
        self.status.setWordWrap(True)
        lay.addWidget(self.status)

        recovered = self.store.recover_interrupted()
        if recovered:
            self._say(f"{len(recovered)} earlier run(s) did not finish and are now marked 'interrupted'; "
                      "their completed links were kept.")
        self._reload_workflows()
        self._reload_history()

    # -- Workflow and run tab ------------------------------------------------------------------------

    def _build_run_tab(self) -> QWidget:
        w = QWidget(self)
        lay = QVBoxLayout(w)

        top = QHBoxLayout()
        self.workflow_combo = QComboBox(w)
        self.workflow_combo.currentIndexChanged.connect(self._on_workflow_chosen)
        top.addWidget(QLabel("Saved workflow:", w))
        top.addWidget(self.workflow_combo, 1)
        self.new_button = QPushButton("New", w)
        self.new_button.clicked.connect(self._new_workflow)
        self.save_button = QPushButton("Save workflow", w)
        self.save_button.clicked.connect(self._save_workflow)
        top.addWidget(self.new_button)
        top.addWidget(self.save_button)
        lay.addLayout(top)

        box = QGroupBox("Configuration", w)
        form = QFormLayout(box)
        self.name_edit = QLineEdit(box)
        self.path_edit = QLineEdit(box)
        self.path_edit.setPlaceholderText("Links CSV (columns: link_id, site_a_lat, site_a_lon, site_a_height_m, "
                                          "site_b_lat, site_b_lon, site_b_height_m, frequency_ghz)")
        browse = QPushButton("Browse...", box)
        browse.clicked.connect(self._browse_csv)
        row = QHBoxLayout()
        row.addWidget(self.path_edit, 1)
        row.addWidget(browse)
        self.k_spin = QDoubleSpinBox(box)
        self.k_spin.setDecimals(4)
        self.k_spin.setRange(0.1, 10.0)
        self.k_spin.setToolTip("Effective earth radius factor (dimensionless). The library default is 4/3.")
        self.samples_spin = QSpinBox(box)
        self.samples_spin.setRange(2, 100)
        self.samples_spin.setSuffix(" points")
        self.attempts_spin = QSpinBox(box)
        self.attempts_spin.setRange(1, 5)
        self.attempts_spin.setToolTip("Attempts per link when the elevation service fails. 1 = never retry.")
        self.pause_spin = QDoubleSpinBox(box)
        self.pause_spin.setRange(0.0, 60.0)
        self.pause_spin.setSuffix(" s")
        self.pause_spin.setToolTip("Wait between links, to stay under an external service's rate limit.")
        self.retain_spin = QSpinBox(box)
        self.retain_spin.setRange(0, 10000)
        self.retain_spin.setSpecialValueText("keep all")
        self.retain_spin.setToolTip("Keep the newest N runs of this workflow. Older runs are moved to a "
                                    "_pruned folder next to the history, never deleted.")
        form.addRow("Name", self.name_edit)
        form.addRow("Links file", row)
        form.addRow("k-factor", self.k_spin)
        form.addRow("Elevation samples per link", self.samples_spin)
        form.addRow("Attempts per link", self.attempts_spin)
        form.addRow("Pause between links", self.pause_spin)
        form.addRow("Runs to keep", self.retain_spin)
        lay.addWidget(box)

        actions = QHBoxLayout()
        self.validate_button = QPushButton("Validate file", w)
        self.validate_button.clicked.connect(self.validate_input)
        self.run_button = QPushButton("Run", w)
        self.run_button.clicked.connect(self.start_run)
        self.run_button.setEnabled(False)
        self.cancel_button = QPushButton("Cancel run", w)
        self.cancel_button.clicked.connect(self.cancel_run)
        self.cancel_button.setEnabled(False)
        actions.addWidget(self.validate_button)
        actions.addWidget(self.run_button)
        actions.addWidget(self.cancel_button)
        actions.addStretch(1)
        lay.addLayout(actions)

        self.validation_view = QPlainTextEdit(w)
        self.validation_view.setReadOnly(True)
        self.validation_view.setMaximumHeight(90)
        lay.addWidget(self.validation_view)
        self.progress = QProgressBar(w)
        self.progress.setRange(0, 100)
        lay.addWidget(self.progress)
        self.results_table = self._make_table(RESULT_COLUMNS, w)
        lay.addWidget(self.results_table, 1)
        self._new_workflow()
        return w

    def _make_table(self, columns, parent, extended=False) -> QTableWidget:
        t = QTableWidget(0, len(columns), parent)
        t.setHorizontalHeaderLabels(columns)
        t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        t.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection if extended
                           else QAbstractItemView.SelectionMode.SingleSelection)
        t.horizontalHeader().setStretchLastSection(True)
        t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        t.verticalHeader().setVisible(False)
        return t

    def _say(self, text: str) -> None:
        self.status.setText(text)

    # -- workflows -------------------------------------------------------------------------------------

    def _reload_workflows(self, select_id: str = None) -> None:
        workflows, problems = self.store.list_workflows()
        self.workflow_combo.blockSignals(True)
        self.workflow_combo.clear()
        self.workflow_combo.addItem("(new workflow)", None)
        for wf in workflows:
            self.workflow_combo.addItem(wf["name"], wf["workflow_id"])
        index = self.workflow_combo.findData(select_id) if select_id else 0
        self.workflow_combo.setCurrentIndex(max(index, 0))
        self.workflow_combo.blockSignals(False)
        if problems:
            self._say(f"{len(problems)} saved workflow file(s) could not be read and were left untouched: "
                      + "; ".join(f"{p['file']} ({p['problem']})" for p in problems))

    def _on_workflow_chosen(self, _index) -> None:
        workflow_id = self.workflow_combo.currentData()
        if workflow_id is None:
            self._new_workflow(reset_combo=False)
            return
        try:
            wf = self.store.load_workflow(workflow_id)
        except (StoreError, SchemaError, ValueError) as exc:
            self._say(f"Could not open that workflow: {exc}")
            return
        self._workflow = wf
        self.name_edit.setText(wf["name"])
        self.path_edit.setText(wf["input"].get("path") or "")
        self.k_spin.setValue(wf["params"]["k_factor"])
        self.samples_spin.setValue(wf["params"]["n_samples"])
        self.attempts_spin.setValue(wf["execution"]["max_attempts"])
        self.pause_spin.setValue(wf["execution"]["pause_between_links_s"])
        self.retain_spin.setValue(wf["output"]["retain_runs"] or 0)
        self._invalidate_validation()

    def _new_workflow(self, reset_combo: bool = True) -> None:
        if reset_combo:
            self.workflow_combo.blockSignals(True)
            self.workflow_combo.setCurrentIndex(0)
            self.workflow_combo.blockSignals(False)
        blank = new_workflow("New workflow")
        self._workflow = None
        self.name_edit.setText("")
        self.path_edit.setText("")
        self.k_spin.setValue(blank["params"]["k_factor"])
        self.samples_spin.setValue(blank["params"]["n_samples"])
        self.attempts_spin.setValue(blank["execution"]["max_attempts"])
        self.pause_spin.setValue(blank["execution"]["pause_between_links_s"])
        self.retain_spin.setValue(0)
        self._invalidate_validation()

    def _current_workflow(self) -> dict:
        name = self.name_edit.text().strip()
        kwargs = dict(input_path=self.path_edit.text().strip() or None, k_factor=self.k_spin.value(),
                      n_samples=self.samples_spin.value(),
                      execution={"max_attempts": self.attempts_spin.value(),
                                 "pause_between_links_s": self.pause_spin.value()},
                      retain_runs=self.retain_spin.value() or None)
        if self._workflow is None:
            return new_workflow(name, **kwargs)
        wf = touch(self._workflow)
        wf["name"] = name
        wf["input"]["path"] = kwargs["input_path"]
        wf["params"] = {"k_factor": kwargs["k_factor"], "n_samples": kwargs["n_samples"]}
        wf["execution"] = {**wf["execution"], **kwargs["execution"]}
        wf["output"]["retain_runs"] = kwargs["retain_runs"]
        from ..core.automation.workflow import validate_workflow
        return validate_workflow(wf)

    def _save_workflow(self) -> bool:
        try:
            wf = self._current_workflow()
            self.store.save_workflow(wf)
        except (SchemaError, ValueError, OSError) as exc:
            QMessageBox.warning(self, "Velorona -- workflow not saved", str(exc))
            return False
        self._workflow = wf
        self._reload_workflows(select_id=wf["workflow_id"])
        self._say(f"Workflow '{wf['name']}' saved.")
        return True

    # -- input validation --------------------------------------------------------------------------------

    def _browse_csv(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Links CSV", self.path_edit.text(), "CSV files (*.csv);;All files (*)")
        if path:
            self.path_edit.setText(path)
            self._invalidate_validation()

    def _invalidate_validation(self) -> None:
        self._validation = None
        self._source = None
        self.run_button.setEnabled(False)
        self.validation_view.setPlainText("")

    def validate_input(self) -> bool:
        path = self.path_edit.text().strip()
        self._invalidate_validation()
        if not path:
            self._say("Choose a links CSV first.")
            return False
        try:
            text, sha, name = inputs.read_links_file(path)
            validation = inputs.validate_links_csv(text)
        except (OSError, inputs.InputFileError) as exc:
            self.validation_view.setPlainText(f"This file cannot be used: {exc}")
            return False
        self._validation, self._source = validation, {"name": name, "sha256": sha}
        acc, rej = validation["accepted"], validation["rejected"]
        lines = [f"{len(acc)} link(s) ready to analyse, {len(rej)} row(s) rejected.  (sha256 {sha[:12]}...)"]
        lines += [f"  {r['reason']}" for r in rej[:50]]
        if len(rej) > 50:
            lines.append(f"  ... and {len(rej) - 50} more (all are recorded in the run).")
        if rej:
            lines.append("Rejected rows will not be analysed; the run will be reported as partial.")
        self.validation_view.setPlainText("\n".join(lines))
        self.run_button.setEnabled(bool(acc) and self._task is None)
        self.results_table.setRowCount(0)
        for link in acc:
            self._append_result_row({"link_id": link["link_id"], "status": "queued", "warnings": [], "result": None})
        return True

    def _append_result_row(self, link: dict) -> None:
        r = self.results_table.rowCount()
        self.results_table.insertRow(r)
        values = link_row_values(link) if link["status"] != "queued" else [link["link_id"], "queued", "", "", ""]
        for c, v in enumerate(values):
            self.results_table.setItem(r, c, _item(v, tooltip=v if c == 4 else None))

    # -- running -----------------------------------------------------------------------------------------

    @property
    def running(self) -> bool:
        return self._task is not None

    def start_run(self) -> None:
        if self._task is not None:
            return
        # The file may have changed since "Validate": validate again so the run is exactly what is on disk.
        if not self.validate_input() or not self._validation["accepted"]:
            self._say("Nothing to run.")
            return
        if not self._save_workflow():
            return
        wf = self._workflow
        self._task = WorkflowTask(wf, self._validation, self._source, self.store, analyzer=self._analyzer)
        self._task.link_done.connect(self._on_link_done)
        self._task.run_finished.connect(self._on_run_finished)
        self.progress.setValue(0)
        for b in (self.run_button, self.validate_button, self.save_button, self.new_button):
            b.setEnabled(False)
        self.workflow_combo.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self._say("Running in the background. QGIS stays usable; progress is also shown in the Task Manager.")
        QgsApplication.taskManager().addTask(self._task)

    def cancel_run(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self.cancel_button.setEnabled(False)
            self._say("Cancelling: the link in progress finishes first (up to the HTTP timeout), "
                      "then the run stops and keeps what it has.")

    def _on_link_done(self, done: int, total: int, link: dict) -> None:
        self.progress.setValue(int(100 * done / total) if total else 100)
        for r in range(self.results_table.rowCount()):
            if self.results_table.item(r, 0).text() == link["link_id"]:
                for c, v in enumerate(link_row_values(link)):
                    self.results_table.setItem(r, c, _item(v, tooltip=v if c == 4 else None))
                break

    def _on_run_finished(self, run) -> None:
        task, self._task = self._task, None
        self.cancel_button.setEnabled(False)
        for b in (self.validate_button, self.save_button, self.new_button):
            b.setEnabled(True)
        self.workflow_combo.setEnabled(True)
        self.run_button.setEnabled(bool(self._validation and self._validation["accepted"]))
        if run is None:
            self._say(f"The run could not be completed: {task.error if task else 'unknown error'}. "
                      "Nothing was reported as a result.")
            self._reload_history()
            return
        self.progress.setValue(100)
        moved = self.store.apply_retention(self._workflow) if self._workflow else []
        c = run["counts"]
        msg = (f"Run {run['run_id']}: {run['status'].upper()} -- {c['ok']} analysed, {c['failed']} failed, "
               f"{c['rejected']} rejected, {c['not_run']} not run.")
        if run.get("error"):
            msg += f" {run['error']}"
        if moved:
            msg += f" {len(moved)} older run(s) moved to the _pruned folder."
        self._say(msg)
        self._reload_history(select_run=run["run_id"])

    def shutdown(self) -> None:
        """Called on plugin unload: ask a running task to stop (its finished links are already saved)."""
        if self._task is not None:
            self._task.cancel()

    # -- History tab -------------------------------------------------------------------------------------

    def _build_history_tab(self) -> QWidget:
        w = QWidget(self)
        lay = QVBoxLayout(w)
        self.history_table = self._make_table(["Started (UTC)", "Workflow", "Status", "Analysed", "Failed",
                                               "Rejected", "Run id"], w, extended=True)
        self.history_table.itemSelectionChanged.connect(self._history_selection_changed)
        lay.addWidget(self.history_table, 1)
        buttons = QHBoxLayout()
        self.open_button = QPushButton("Open", w)
        self.open_button.clicked.connect(self.open_selected_run)
        self.compare_button = QPushButton("Compare two runs", w)
        self.compare_button.clicked.connect(self.compare_selected_runs)
        self.export_button = QPushButton("Export result package...", w)
        self.export_button.clicked.connect(self.export_selected_run)
        backup = QPushButton("Back up history...", w)
        backup.clicked.connect(self.backup_history)
        restore = QPushButton("Restore from backup...", w)
        restore.clicked.connect(self.restore_history)
        for b in (self.open_button, self.compare_button, self.export_button):
            b.setEnabled(False)
            buttons.addWidget(b)
        buttons.addStretch(1)
        buttons.addWidget(backup)
        buttons.addWidget(restore)
        lay.addLayout(buttons)
        self.history_note = QLabel("", w)
        self.history_note.setWordWrap(True)
        lay.addWidget(self.history_note)
        return w

    def _reload_history(self, select_run: str = None) -> None:
        summaries, problems = self.store.list_runs()
        t = self.history_table
        t.setRowCount(0)
        for s in summaries:
            r = t.rowCount()
            t.insertRow(r)
            c = s.get("counts") or {}
            vals = [(s["started_at"] or "").replace("T", " ")[:19], s["workflow_name"], s["status"],
                    c.get("ok", ""), c.get("failed", ""), c.get("rejected", ""), s["run_id"]]
            for col, v in enumerate(vals):
                t.setItem(r, col, _item(v))
            if s["run_id"] == select_run:
                t.selectRow(r)
        self.history_note.setText(
            f"Stored in {self.store.root}. " +
            (f"{len(problems)} file(s) could not be read and were left untouched: "
             + "; ".join(f"{p['file']} ({p['problem']})" for p in problems) if problems else ""))

    def _selected_run_ids(self) -> list:
        rows = sorted({i.row() for i in self.history_table.selectedItems()})
        return [self.history_table.item(r, 6).text() for r in rows]

    def _history_selection_changed(self) -> None:
        n = len(self._selected_run_ids())
        self.open_button.setEnabled(n == 1)
        self.export_button.setEnabled(n == 1)
        self.compare_button.setEnabled(n == 2)

    def open_selected_run(self) -> None:
        ids = self._selected_run_ids()
        if len(ids) != 1:
            return
        try:
            run = self.store.load_run(ids[0])
        except (StoreError, SchemaError, ValueError, OSError) as exc:
            QMessageBox.warning(self, "Velorona -- run not opened", str(exc))
            return
        self.tabs.setCurrentIndex(0)
        self.results_table.setRowCount(0)
        for link in run["links"]:
            self._append_result_row(link)
        for rej in run["rejected_rows"]:
            self._append_result_row({"link_id": rej["link_id"] or f"row {rej['source_row']}", "status": "failed",
                                     "warnings": [], "result": None,
                                     "error": {"type": "Rejected input", "message": rej["reason"]}})
        self.validation_view.setPlainText(
            f"Stored run {run['run_id']} -- {run['status'].upper()}, started {run['started_at']}. "
            f"Input {run['input'].get('source_name')} (sha256 {str(run['input'].get('sha256'))[:12]}...). "
            "This is a saved record of what was calculated then, not a fresh analysis.")
        self.progress.setValue(100)

    def compare_selected_runs(self) -> None:
        ids = self._selected_run_ids()
        if len(ids) != 2:
            return
        try:
            runs = sorted((self.store.load_run(i) for i in ids), key=lambda r: r["started_at"])
        except (StoreError, SchemaError, ValueError, OSError) as exc:
            QMessageBox.warning(self, "Velorona -- comparison failed", str(exc))
            return
        self._compare_dialog = CompareDialog(self, compare_mod.compare_runs(runs[0], runs[1]))
        self._compare_dialog.show()

    def export_selected_run(self) -> None:
        ids = self._selected_run_ids()
        if len(ids) != 1:
            return
        dest = QFileDialog.getExistingDirectory(self, "Choose a folder for the result package")
        if not dest:
            return
        try:
            folder = report.export_package(self.store.load_run(ids[0]), dest)
        except (FileExistsError, ValueError, StoreError, SchemaError, OSError) as exc:
            QMessageBox.warning(self, "Velorona -- export failed", str(exc))
            return
        self._say(f"Result package written to {folder}")

    def backup_history(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Back up history", "velorona-history-backup.zip", "Zip (*.zip)")
        if not path:
            return
        try:
            info = self.store.export_backup(path)
        except (StoreError, OSError) as exc:
            QMessageBox.warning(self, "Velorona -- backup failed", str(exc))
            return
        self._say(f"Backed up {info['files']} file(s) to {path}")

    def restore_history(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Restore from backup", "", "Zip (*.zip)")
        if not path:
            return
        try:
            rep = self.store.import_backup(path)
        except StoreError as exc:
            QMessageBox.warning(self, "Velorona -- restore failed", str(exc))
            return
        self._reload_workflows()
        self._reload_history()
        self._say(f"Restored {len(rep['added'])} item(s); {len(rep['skipped_existing'])} already present (kept as they "
                  f"were); {len(rep['rejected'])} rejected" +
                  ("".join(f"\n  {r['file']}: {r['problem']}" for r in rep["rejected"]) if rep["rejected"] else "."))


class CompareDialog(QDialog):
    def __init__(self, parent, cmp: dict):
        super().__init__(parent)
        self.setWindowTitle("Velorona -- Compare runs")
        self.resize(900, 560)
        self.comparison = cmp
        lay = QVBoxLayout(self)
        a, b = cmp["run_a"], cmp["run_b"]
        head = QLabel(f"<b>First:</b> {a['started_at']} ({a['status']}) &nbsp; <b>Second:</b> {b['started_at']} ({b['status']})", self)
        lay.addWidget(head)
        verdict = QLabel(self)
        verdict.setWordWrap(True)
        if cmp["comparable"]:
            verdict.setText("Same method and data source: the per-link differences below are like-for-like. " + cmp["note"])
        else:
            verdict.setText("<b>Not a valid before/after comparison.</b> " + " ".join(cmp["reasons"]) +
                            " Differences are shown for information only. " + cmp["note"])
        lay.addWidget(verdict)
        context = []
        for c in cmp["parameter_changes"]:
            context.append(f"Parameter {c['field']}: {c['a']} -> {c['b']}")
        for c in cmp["data_source_changes"]:
            context.append(f"{c['field']}: {c['a']} -> {c['b']}")
        for c in cmp["version_changes"]:
            context.append(f"Version {c['field']}: {c['a']} -> {c['b']}")
        if cmp["input_file"]["file_changed"]:
            context.append("The input file's contents changed between the runs.")
        if not cmp["input_file"]["same_workflow"]:
            context.append("The runs belong to different workflows.")
        ctx = QLabel("<br>".join(context) if context else "No parameter, data-source, version or input-file changes.", self)
        ctx.setWordWrap(True)
        lay.addWidget(ctx)
        s = cmp["summary"]
        lay.addWidget(QLabel(f"{s['compared']} link(s) compared, {s['results_changed']} with changed results, "
                             f"{s['los_status_changed']} with a changed line-of-sight status; "
                             f"{s['only_in_first']} only in the first run, {s['only_in_second']} only in the second.", self))
        t = QTableWidget(0, 4, self)
        t.setHorizontalHeaderLabels(["Link", "Changes", "Input changes", "Explanation"])
        t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        t.verticalHeader().setVisible(False)
        t.horizontalHeader().setStretchLastSection(True)
        for l in cmp["links"]:
            r = t.rowCount()
            t.insertRow(r)
            changes = "; ".join(f"{c['field']}: {c['a']} -> {c['b']}" for c in l.get("result_changes", []))
            inputs_ = "; ".join(f"{c['field']}: {c['a']} -> {c['b']}" for c in l.get("input_changes", []))
            for col, v in enumerate([l["link_id"], changes, inputs_, l.get("note", "")]):
                t.setItem(r, col, _item(v, tooltip=v))
        t.resizeColumnsToContents()
        lay.addWidget(t, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
