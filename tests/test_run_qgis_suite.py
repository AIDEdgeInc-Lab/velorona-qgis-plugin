"""tools/run_qgis_suite.py: tolerate a shutdown abort only after a complete, clean pass."""
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import run_qgis_suite as R  # noqa: E402


@pytest.mark.parametrize("rc,out,expected", [
    (0, "whatever", 0),
    (1, "===== 35/36 passed =====\nFAILED: x", 1),
    (134, "===== clean-install smoke: 36/36 passed =====\n", 0),     # clean pass, then abort at shutdown
    (-6, "===== 62/62 checks passed =====\n", 0),                    # same, subprocess-style signal code
    (134, "===== clean-install smoke: 35/36 passed =====\n", 134),   # abort AND incomplete pass
    (134, "  [FAIL] something\n===== 36/36 passed =====\n", 134),     # abort and a failure line
    (134, "crashed before any summary\n", 134),
    (2, "===== 36/36 passed =====\n", 2),                            # ordinary non-zero exit is never tolerated
])
def test_classify(rc, out, expected):
    code, _ = R.classify(rc, out)
    assert code == expected


def test_warning_is_visible_when_tolerated():
    code, msg = R.classify(134, "===== 36/36 passed =====\n")
    assert code == 0 and msg.startswith("::warning::")


def test_end_to_end_with_real_abort(tmp_path):
    script = tmp_path / "s.py"
    script.write_text("import os\nprint('===== 3/3 checks passed =====', flush=True)\nos.abort()\n")
    proc = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "run_qgis_suite.py"), str(script)],
                          capture_output=True, text=True)
    assert proc.returncode == 0 and "::warning::" in proc.stdout


def test_end_to_end_real_failure_is_not_hidden(tmp_path):
    script = tmp_path / "s.py"
    script.write_text("import sys\nprint('  [FAIL] x')\nprint('===== 2/3 checks passed =====')\nsys.exit(1)\n")
    proc = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "run_qgis_suite.py"), str(script)],
                          capture_output=True, text=True)
    assert proc.returncode == 1
