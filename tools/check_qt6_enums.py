#!/usr/bin/env python3
"""Fail on unscoped Qt/QGIS enum access, which raises AttributeError under Qt6.

QGIS 4.x ships PyQt6, where enum members are only reachable through their
enum class: Qt.DockWidgetArea.RightDockWidgetArea, not Qt.RightDockWidgetArea.
The unscoped form imports fine and only fails when the line actually runs, so
it hides in rarely-exercised UI paths -- exactly how the Results Dock shipped
broken (Qt.LeftDockWidgetArea / Qt.RightDockWidgetArea raising on first use
under Qt 6.11.1).

Comments and string literals are blanked before matching, so prose mentioning
an unscoped name is not a false positive.

Run:  python3 tools/check_qt6_enums.py
Exit: 0 clean, 1 if any unscoped enum is found.
"""

from __future__ import annotations

import io
import os
import re
import sys
import tokenize

# Each pattern matches the UNSCOPED form only. Extend as new Qt classes are
# used; a name that never appears in this plugin costs nothing to list.
UNSCOPED_ENUM_PATTERNS = [
    r"\bQt\.(Left|Right|Top|Bottom|All)DockWidgetArea\b",
    r"\bQt\.Align(Left|Right|HCenter|VCenter|Center|Top|Bottom|Justify)\b",
    r"\bQt\.(WaitCursor|ArrowCursor|PointingHandCursor|CrossCursor|BusyCursor)\b",
    r"\bQt\.(SolidLine|DashLine|DotLine|DashDotLine|NoPen)\b",
    r"\bQt\.(LeftButton|RightButton|MiddleButton|MidButton|NoButton)\b",
    r"\bQt\.(Horizontal|Vertical)\b",
    r"\bQt\.(Checked|Unchecked|PartiallyChecked)\b",
    r"\bQt\.(KeepAspectRatio|IgnoreAspectRatio|KeepAspectRatioByExpanding)\b",
    r"\bQt\.(SmoothTransformation|FastTransformation)\b",
    r"\bQt\.(UserRole|DisplayRole|EditRole|DecorationRole)\b",
    r"\bQt\.(ScrollBarAlwaysOff|ScrollBarAlwaysOn|ScrollBarAsNeeded)\b",
    r"\bQt\.(ElideLeft|ElideRight|ElideMiddle|ElideNone)\b",
    r"\bQt\.(RichText|PlainText|AutoText)\b",
    r"\bQt\.Key_\w+\b",
    r"\bQt\.WA_\w+\b",
    r"\bQFrame\.(NoFrame|Box|Panel|StyledPanel|HLine|VLine|Sunken|Raised|Plain)\b",
    r"\bQFont\.(Thin|Light|Normal|Medium|DemiBold|Bold|ExtraBold|Black)\b",
    r"\bQMessageBox\.(Yes|No|Ok|Cancel|Abort|Retry|Ignore|Close|Save|Discard)\b",
    r"\bQMessageBox\.(Warning|Information|Critical|Question|NoIcon)\b",
    r"\bQDialogButtonBox\.(Ok|Cancel|Yes|No|Apply|Close|Save|Reset)\b",
    r"\bQEvent\.(Enter|Leave|MouseMove|MouseButtonPress|MouseButtonRelease|KeyPress)\b",
    r"\bQPainter\.(Antialiasing|SmoothPixmapTransform|TextAntialiasing)\b",
    r"\bQSizePolicy\.(Expanding|Fixed|Minimum|Maximum|Preferred|MinimumExpanding|Ignored)\b",
    r"\bQHeaderView\.(Stretch|ResizeToContents|Fixed|Interactive)\b",
    r"\bQAbstractItemView\.(NoEditTriggers|SingleSelection|NoSelection|SelectRows)\b",
    r"\bQFileDialog\.(AcceptOpen|AcceptSave|Directory|ExistingFile|AnyFile)\b",
    # Removed PyQt5 idioms -- not enums, but the same class of latent failure:
    # they import fine and raise only when the line runs.
    r"\.exec_\(\)",
    r"\bQDialog\.(Accepted|Rejected)\b",
    r"\bdialog\.(Accepted|Rejected)\b",
]

# Deliberately NOT checked: QGIS's own enum classes (QgsUnitTypes,
# QgsWkbTypes, QgsVertexMarker, ...). Verified against QGIS 4.2.2 / Qt 6.11.1
# that their unscoped aliases still resolve, so flagging them would be noise.
# Only Qt/PyQt classes dropped the unscoped form.

SKIP_DIRS = {".git", "__pycache__", "tools", "tests", "docs", "examples"}


def code_lines(path: str) -> list[str]:
    """File lines with comments and string literals blanked out."""
    with open(path, encoding="utf-8") as handle:
        source = handle.read()
    lines = source.splitlines()
    blanked = list(lines)
    try:
        tokens = tokenize.generate_tokens(io.StringIO(source).readline)
        for tok_type, tok_str, (srow, scol), (erow, ecol), _ in tokens:
            if tok_type not in (tokenize.COMMENT, tokenize.STRING):
                continue
            if srow == erow:
                line = blanked[srow - 1]
                blanked[srow - 1] = line[:scol] + " " * (ecol - scol) + line[ecol:]
            else:
                for row in range(srow, erow + 1):
                    blanked[row - 1] = " " * len(blanked[row - 1])
    except (tokenize.TokenError, IndentationError):
        return lines  # unparseable: match against the raw text rather than skip
    return blanked


def scan(root: str) -> list[tuple[str, int, str, str]]:
    findings = []
    patterns = [(re.compile(p), p) for p in UNSCOPED_ENUM_PATTERNS]
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for filename in sorted(filenames):
            if not filename.endswith(".py"):
                continue
            path = os.path.join(dirpath, filename)
            for lineno, line in enumerate(code_lines(path), start=1):
                for regex, pattern in patterns:
                    match = regex.search(line)
                    if match:
                        rel = os.path.relpath(path, root)
                        findings.append((rel, lineno, match.group(0), pattern))
    return findings


def main() -> int:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    findings = scan(root)
    if not findings:
        print("check_qt6_enums: no unscoped Qt/QGIS enum access found.")
        return 0
    print("check_qt6_enums: unscoped enum access found (breaks under Qt6/PyQt6):\n")
    for rel, lineno, text, _ in findings:
        print(f"  {rel}:{lineno}: {text}")
    print("\nUse the scoped form, e.g. Qt.DockWidgetArea.RightDockWidgetArea.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
