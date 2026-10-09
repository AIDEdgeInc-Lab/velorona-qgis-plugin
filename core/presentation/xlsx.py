"""A minimal .xlsx writer on the standard library.

QGIS's bundled Python has no openpyxl and the plugin should not ask operators to
install one for an export button, so this writes the small subset of
SpreadsheetML the workbook needs: text and number cells, bold header rows, a few
status fills, column widths and a frozen header. Numbers are stored as numbers
at full precision; the number format only changes how Excel displays them.
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from html import escape as _html_escape
from io import BytesIO
from typing import Any, Dict, List, Optional, Sequence, Tuple


def escape(text: str) -> str:
    """Escape & < > for XML text (the same result the standard library's SAX escape gives)."""
    return _html_escape(text, quote=False)


_ILLEGAL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f]")
_BAD_SHEET_CHARS = re.compile(r"[\\/*?:\[\]]")

FILLS = {  # status -> ARGB
    "CLEAR": "FFC6EFCE", "WATCH": "FFFFEB9C", "AT RISK": "FFFFCC99", "CRITICAL": "FFFFC7CE", "NO DATA": "FFD9D9D9",
}


@dataclass(frozen=True)
class Cell:
    value: Any
    bold: bool = False
    fmt: Optional[str] = None     # number format, e.g. "0.0"
    fill: Optional[str] = None    # ARGB
    wrap: bool = True


def header(*names) -> List[Cell]:
    return [Cell(n, bold=True, fill="FFD9E1F2") for n in names]


def sheet_name(name: str) -> str:
    """Excel forbids \\ / * ? : [ ] in sheet names and caps them at 31 characters."""
    return _BAD_SHEET_CHARS.sub("-", name)[:31]


class _Styles:
    def __init__(self):
        self.fonts = ['<font><sz val="11"/><name val="Calibri"/></font>',
                      '<font><b/><sz val="11"/><name val="Calibri"/></font>']
        self.fills = ['<fill><patternFill patternType="none"/></fill>', '<fill><patternFill patternType="gray125"/></fill>']
        self.numfmts: Dict[str, int] = {}
        self.xfs = ['<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>']
        self._index: Dict[Tuple, int] = {}

    def index(self, cell: Cell) -> int:
        key = (cell.bold, cell.fmt, cell.fill, cell.wrap)
        if key == (False, None, None, False):
            return 0
        if key in self._index:
            return self._index[key]
        font = 1 if cell.bold else 0
        fill = 0
        if cell.fill:
            self.fills.append(f'<fill><patternFill patternType="solid"><fgColor rgb="{cell.fill}"/>'
                              f'<bgColor indexed="64"/></patternFill></fill>')
            fill = len(self.fills) - 1
        numfmt = 0
        if cell.fmt:
            numfmt = self.numfmts.setdefault(cell.fmt, 164 + len(self.numfmts))
        align = '<alignment vertical="top" wrapText="1"/>' if cell.wrap else '<alignment vertical="top"/>'
        self.xfs.append(f'<xf numFmtId="{numfmt}" fontId="{font}" fillId="{fill}" borderId="0" xfId="0" '
                        f'applyNumberFormat="1" applyFont="1" applyFill="1" applyAlignment="1">{align}</xf>')
        self._index[key] = len(self.xfs) - 1
        return self._index[key]

    def xml(self) -> str:
        nf = "".join(f'<numFmt numFmtId="{i}" formatCode="{escape(code)}"/>' for code, i in self.numfmts.items())
        return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                + (f'<numFmts count="{len(self.numfmts)}">{nf}</numFmts>' if nf else "")
                + f'<fonts count="{len(self.fonts)}">{"".join(self.fonts)}</fonts>'
                + f'<fills count="{len(self.fills)}">{"".join(self.fills)}</fills>'
                + '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
                + '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
                + f'<cellXfs count="{len(self.xfs)}">{"".join(self.xfs)}</cellXfs>'
                + '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
                + '</styleSheet>')


def _col(n: int) -> str:
    s = ""
    n += 1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _cell_xml(ref: str, cell: Cell, styles: _Styles) -> str:
    v = cell.value
    s = styles.index(cell)
    attr = f' s="{s}"' if s else ""
    if v is None or v == "":
        return f'<c r="{ref}"{attr}/>' if s else ""
    if isinstance(v, bool):
        return f'<c r="{ref}"{attr} t="inlineStr"><is><t>{"TRUE" if v else "FALSE"}</t></is></c>'
    if isinstance(v, (int, float)):
        if v != v or v in (float("inf"), float("-inf")):  # NaN/inf are not valid cell numbers
            return f'<c r="{ref}"{attr} t="inlineStr"><is><t>{"inf" if v > 0 else "-inf" if v < 0 else "NaN"}</t></is></c>'
        return f'<c r="{ref}"{attr}><v>{repr(v)}</v></c>'
    text = escape(_ILLEGAL.sub("", str(v)))
    return f'<c r="{ref}"{attr} t="inlineStr"><is><t xml:space="preserve">{text}</t></is></c>'


def _sheet_xml(rows: Sequence[Sequence], widths: Sequence[float], styles: _Styles, freeze: int) -> str:
    body = []
    for r, row in enumerate(rows, start=1):
        cells = []
        for c, item in enumerate(row):
            cell = item if isinstance(item, Cell) else Cell(item)
            xml = _cell_xml(f"{_col(c)}{r}", cell, styles)
            if xml:
                cells.append(xml)
        body.append(f'<row r="{r}">{"".join(cells)}</row>')
    cols = "".join(f'<col min="{i}" max="{i}" width="{w}" customWidth="1"/>' for i, w in enumerate(widths, start=1))
    pane = (f'<sheetViews><sheetView workbookViewId="0"><pane ySplit="{freeze}" topLeftCell="A{freeze + 1}" '
            f'activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>') if freeze else \
        '<sheetViews><sheetView workbookViewId="0"/></sheetViews>'
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            + pane + '<sheetFormatPr defaultRowHeight="15"/>'
            + (f"<cols>{cols}</cols>" if cols else "") + f'<sheetData>{"".join(body)}</sheetData></worksheet>')


@dataclass
class Sheet:
    name: str
    rows: List[List]
    widths: Sequence[float] = ()
    freeze: int = 0   # rows frozen at the top


def write_workbook(sheets: Sequence[Sheet]) -> bytes:
    """Serialize `sheets` to .xlsx bytes."""
    styles = _Styles()
    names = []
    for s in sheets:
        n = sheet_name(s.name)
        if n in names:
            raise ValueError(f"duplicate sheet name {n!r}")
        names.append(n)
    sheet_xml = [_sheet_xml(s.rows, s.widths, styles, s.freeze) for s in sheets]

    ct = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
          '<Default Extension="xml" ContentType="application/xml"/>'
          '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
          '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
          + "".join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                    for i in range(1, len(sheets) + 1)) + '</Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            '</Relationships>')
    wb = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
          'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
          + "".join(f'<sheet name="{escape(n)}" sheetId="{i}" r:id="rId{i}"/>' for i, n in enumerate(names, start=1))
          + '</sheets></workbook>')
    wb_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
               '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
               + "".join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>'
                         for i in range(1, len(sheets) + 1))
               + f'<Relationship Id="rId{len(sheets) + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
               '</Relationships>')

    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", ct)
        z.writestr("_rels/.rels", rels)
        z.writestr("xl/workbook.xml", wb)
        z.writestr("xl/_rels/workbook.xml.rels", wb_rels)
        z.writestr("xl/styles.xml", styles.xml())
        for i, xml in enumerate(sheet_xml, start=1):
            z.writestr(f"xl/worksheets/sheet{i}.xml", xml)
    return buf.getvalue()
