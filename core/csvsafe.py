"""Spreadsheet-formula safety for CSV exports.

A spreadsheet application opening a CSV treats a cell that BEGINS with = + - @ (or a tab / carriage return) as a formula, and quoting the field does
not stop that. Several exported cells come from data Velorona does not control (licensee names, call signs, identifiers, the source and reason text of an
imported layer). The standard mitigation (OWASP "CSV injection") is applied here: such a cell gets a leading apostrophe, which spreadsheets read as
"this is text".

What is NOT touched: the numbers Velorona calculates, including negative ones ("-34.39 m", "-5.085", "-5.08x the required minimum ..."). A cell that
starts with a number (optionally followed by a unit or words) is recognised as such, unless what follows could itself be a formula (an operator, a
function call "NAME(", a pipe, a quote ...). Anything else that starts with a trigger character is neutralised.

Known limitations: the apostrophe is visible when the CSV is opened in some applications (it is the text marker in Excel's typed entry, but a CSV
import shows it literally); a user who needs the exact original text must read it from the Excel export, where cells are stored as plain strings and
never as formulas. Leading whitespace before a trigger is not treated specially (the applications checked treat it as text).
"""

from __future__ import annotations

import contextlib
import contextvars
import csv
import re

_TRIGGERS = ("=", "+", "-", "@", "\t", "\r")
# A number at the start of the cell, ended by the end of the cell or by something that is not an operator (a space, a unit letter, %, degree, x ...).
_NUMBER_START = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?(?=$|[\s%°×·/²³µΩA-Za-z])")
# Characters that can make the remainder of a "number then text" cell evaluate as a formula or reach another application.
_FORMULA_CHARS = re.compile(r"[=+@|!\"'<>&{}\[\]^*~\\]|\w\(")
_HYPHEN_IN_WORD = re.compile(r"(?<=\w)-(?=\w)")


def _is_calculated_number_text(text: str) -> bool:
    match = _NUMBER_START.match(text)
    if match is None:
        return False
    rest = _HYPHEN_IN_WORD.sub("", text[match.end():])
    return _FORMULA_CHARS.search(rest) is None and "-" not in rest


_ENABLED = contextvars.ContextVar("velorona_csv_safe", default=True)


@contextlib.contextmanager
def disabled():
    """For the one internal reader that wants the original text back: the Excel export builds its EVIDENCE sheet from the CSV rows, and a workbook
    stores every cell as a plain string (never a formula), so it needs no apostrophe."""
    token = _ENABLED.set(False)
    try:
        yield
    finally:
        _ENABLED.reset(token)


def neutralize(value):
    """The value, made safe for a spreadsheet: only strings that start with a trigger character and are not a calculated number are changed."""
    if not isinstance(value, str) or not value or value[0] not in _TRIGGERS:
        return value
    if value[0] in "+-" and _is_calculated_number_text(value):
        return value
    return "'" + value


class SafeWriter:
    """A csv.writer whose text cells are neutralised. Same interface for the parts of csv.writer Velorona uses."""

    def __init__(self, buf, **kwargs):
        self._writer = csv.writer(buf, **kwargs)

    def writerow(self, row):
        return self._writer.writerow([neutralize(cell) for cell in row] if _ENABLED.get() else row)

    def writerows(self, rows):
        for row in rows:
            self.writerow(row)


def writer(buf, **kwargs) -> SafeWriter:
    return SafeWriter(buf, **kwargs)
