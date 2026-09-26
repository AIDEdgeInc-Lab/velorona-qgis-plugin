"""Velorona automation (QGIS side): the background task only. All workflow/run logic is the product-neutral
`aei_workflow` package (aei-workflow-runner), which the headless `velorona-run` CLI and this plugin share.

Where `aei_workflow` comes from, in this order:
  1. <plugin>/_vendor/aei_workflow, put there by tools/package.sh, so a release zip runs the exact version it was tested with
  2. an installed `aei-workflow-runner` (a source checkout: `pip install -e ../aei-workflow-runner`)
Importing this package never imports QGIS; only qgis_task.py does.
"""

import os
import sys

_VENDOR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "_vendor")
if os.path.isdir(os.path.join(_VENDOR, "aei_workflow")) and _VENDOR not in sys.path:
    sys.path.insert(0, _VENDOR)

INSTALL_HINT = ("Velorona batch runs need the aei-workflow-runner package. Release builds bundle it; for a source checkout run "
                "`pip install -e path/to/aei-workflow-runner` in QGIS's Python.")


def available() -> bool:
    try:
        import aei_workflow  # noqa: F401
    except ImportError:
        return False
    return True
