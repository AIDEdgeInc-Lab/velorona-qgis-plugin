"""Test helper: read back what core.presentation.xlsx.write_workbook wrote.

Lives with the tests, not in the plugin, so the shipped package contains no XML
parsing. It understands only this writer's output, not arbitrary workbooks.
"""
import re
import zipfile
from io import BytesIO
from typing import Dict, List

def read_workbook(data: bytes) -> Dict[str, List[List]]:
    """Read back what write_workbook wrote (sheet name -> rows of values).
    Used by the tests to prove the file holds exactly the calculated numbers;
    it understands only this writer's output, not arbitrary workbooks."""
    import xml.etree.ElementTree as ET
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    out: Dict[str, List[List]] = {}
    with zipfile.ZipFile(BytesIO(data)) as z:
        wb = ET.fromstring(z.read("xl/workbook.xml"))
        for i, sh in enumerate(wb.find("m:sheets", ns), start=1):
            root = ET.fromstring(z.read(f"xl/worksheets/sheet{i}.xml"))
            rows = []
            for row in root.find("m:sheetData", ns):
                values: List = []
                for c in row:
                    col = re.match(r"[A-Z]+", c.get("r")).group(0)
                    idx = 0
                    for ch in col:
                        idx = idx * 26 + ord(ch) - 64
                    idx -= 1
                    values += [None] * (idx - len(values))
                    if c.get("t") == "inlineStr":
                        values.append("".join(t.text or "" for t in c.iter("{%s}t" % ns["m"])))
                    else:
                        v = c.find("m:v", ns)
                        values.append(None if v is None else float(v.text))
                rows.append(values)
            out[sh.get("name")] = rows
    return out
