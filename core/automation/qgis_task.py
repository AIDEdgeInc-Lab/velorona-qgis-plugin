"""QGIS integration for the automation core: background task, storage location, version discovery.

The task runs core.automation.runner.execute on a QgsTask worker thread, so the QGIS interface stays
responsive and the run appears in QGIS's own Task Manager (with its own cancel button). The worker
touches no QGIS objects and no widgets: it emits Qt signals, which Qt delivers to the GUI thread.
"""

from __future__ import annotations

import os
import time

from qgis.core import Qgis, QgsApplication, QgsTask
from qgis.PyQt.QtCore import pyqtSignal

from . import engine
from .runner import execute

CHECKPOINT_INTERVAL_S = 2.0


def default_store_root() -> str:
    """Per QGIS profile, next to the profile's other settings; a customer can move, back up or delete
    the folder with ordinary tools. Nothing is sent anywhere."""
    return os.path.join(QgsApplication.qgisSettingsDirPath(), "velorona", "automation")


def plugin_version() -> str:
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "metadata.txt")
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.startswith("version="):
                    return line.split("=", 1)[1].strip()
    except OSError:
        pass
    return None


def collect_versions() -> dict:
    return engine.collect_versions(plugin_version=plugin_version(), qgis_version=Qgis.version())


class WorkflowTask(QgsTask):
    link_done = pyqtSignal(int, int, object)   # (done, total, link entry) -- emitted from the worker
    run_finished = pyqtSignal(object)          # the run record, or None if the runner itself broke

    def __init__(self, workflow: dict, validation: dict, source: dict, store, analyzer=None, versions: dict = None):
        super().__init__(f"Velorona: {workflow['name']}", QgsTask.Flag.CanCancel)
        self._workflow, self._validation, self._source = workflow, validation, source
        self._store = store
        self._analyzer = analyzer or engine.analyze_link_row
        self._versions = versions if versions is not None else collect_versions()
        self._last_save = 0.0
        self.run_id = None
        self.run_record = None
        self.error = None

    def run(self) -> bool:
        try:
            self.run_record = execute(
                self._workflow, self._validation, self._analyzer, source=self._source, versions=self._versions,
                on_progress=self._on_progress, on_checkpoint=self._on_checkpoint, is_canceled=self.isCanceled,
            )
        except Exception as exc:  # anything execute() itself could not absorb
            self.error = f"{type(exc).__name__}: {exc}"
            return False
        # A canceled or partly failed run is still a valid, saved record; only an unusable one is False.
        return True

    def _on_progress(self, done: int, total: int, link: dict) -> None:
        self.setProgress(100.0 * done / total if total else 100.0)
        self.link_done.emit(done, total, link)

    def _on_checkpoint(self, run: dict) -> None:
        """Save the in-flight record, at most every CHECKPOINT_INTERVAL_S, and always at the end. A
        crash therefore loses at most the last couple of seconds, without rewriting a large run's file
        after every single link."""
        self.run_id = run["run_id"]
        now = time.monotonic()
        if run["status"] == "running" and now - self._last_save < CHECKPOINT_INTERVAL_S and self._last_save:
            return
        self._store.save_run(run)
        self._last_save = now

    def finished(self, result: bool) -> None:   # GUI thread
        self.run_finished.emit(self.run_record)
