#!/usr/bin/env python3
"""Runs one QGIS test script in CI and classifies how it ended.

    python3 tools/run_qgis_suite.py tests/clean_install_smoke.py

Exit code of this wrapper:
  0  the script exited 0, OR the script printed a complete passing summary (N/N passed, no failure lines) and was
     then killed by an abort/segfault signal during interpreter shutdown. The second case prints a ::warning:: so it is
     visible, never silent: all assertions passed, the crash is QGIS runtime teardown, not a failed check.
  1+ anything else: an assertion failed, the summary line is missing or incomplete, or the script exited non-zero.

Why this exists: on QGIS 4.0.3 (the plugin's declared minimum) `qgs.exitQgis()` with live widgets aborts the process
(std::bad_alloc, exit 134) AFTER the suite has finished and printed "36/36 passed"; 4.2 exits cleanly. See the
issue linked from docs/QUALITY.md. Remove the tolerance when the harness or QGIS no longer aborts.
"""
import re
import subprocess
import sys

ABORT_CODES = {134, 139, -6, -11}   # shell-style (128+SIGABRT/SIGSEGV) and subprocess-style (-SIGABRT/-SIGSEGV)
SUMMARY = re.compile(r"(\d+)/(\d+)\s+(?:checks\s+)?passed")
FAILURE_LINE = re.compile(r"\[FAIL\]|^\s*FAILED:", re.M)


def classify(returncode, output):
    """Return (exit_code, message_or_None)."""
    if returncode == 0:
        return 0, None
    summaries = SUMMARY.findall(output)
    complete = bool(summaries) and all(a == b for a, b in summaries[-1:])
    if returncode in ABORT_CODES and complete and not FAILURE_LINE.search(output):
        return 0, (f"::warning::all checks passed ({summaries[-1][0]}/{summaries[-1][1]}) but the process was killed at "
                   f"shutdown (exit {returncode}): QGIS runtime teardown, not a failed assertion")
    return (returncode if returncode > 0 else 1), None


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    proc = subprocess.run([sys.executable, *argv[1:]], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    sys.stdout.write(proc.stdout)
    code, message = classify(proc.returncode, proc.stdout)
    if message:
        print(message)
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv))
