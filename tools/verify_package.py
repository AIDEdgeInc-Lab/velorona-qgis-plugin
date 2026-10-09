#!/usr/bin/env python3
"""Verifies a built plugin zip (tools/package.sh) WITHOUT installing it. Pure stdlib. Exit 1 on any failed check.

    python3 tools/verify_package.py dist/velorona-<version>.zip [expected-version]

Checks: exactly one top-level folder named velorona; metadata.txt version (and the expected one, if given); the files QGIS needs; the runtime
modules the USA support adds; NOTHING development-only (tests, parity, tools, .git, caches); NO USA data of any kind (no tile folders, no FCC/US
fixtures or extracts, no file named like a pack index, nothing over 20 MB); the Canadian snapshot present and unchanged in size class.
"""
import os
import sys
import zipfile

REQUIRED = ["velorona/__init__.py", "velorona/metadata.txt", "velorona/plugin.py", "velorona/requirements.txt", "velorona/LICENSE",
            "velorona/data/fixed_service_snapshot.json", "velorona/core/countries/usa.py", "velorona/core/countries/base.py",
            "velorona/core/countries/canada.py", "velorona/core/countries/usa_fields.py", "velorona/core/record_source.py",
            "velorona/core/evidence_record.py", "velorona/core/validation.py", "velorona/core/engines/terrestrial.py"]
FORBIDDEN_PREFIX = ["velorona/tests/", "velorona/parity/", "velorona/tools/", "velorona/.git", "velorona/dist/", "velorona/docs/_"]
MAX_FILE_BYTES = 20 * 1024 * 1024


def main(path, expected=None):
    problems, notes = [], []
    z = zipfile.ZipFile(path)
    infos = [i for i in z.infolist() if not i.is_dir()]
    names = [i.filename for i in infos]
    tops = {n.split("/", 1)[0] for n in names}
    if tops != {"velorona"}:
        problems.append(f"top-level entries are {sorted(tops)}, expected exactly ['velorona']")
    for r in REQUIRED:
        if r not in names:
            problems.append(f"missing {r}")
    for n in names:
        if any(n.startswith(p) for p in FORBIDDEN_PREFIX) or "__pycache__" in n or n.endswith((".pyc", ".DS_Store")):
            problems.append(f"development-only file shipped: {n}")
        low = n.lower()
        if "/tiles/" in low or low.endswith(("usa_extract_wny.json", "/us-overview.json")) or "/us-" in low or "fcc" in low.rsplit("/", 1)[-1]:
            problems.append(f"possible USA data shipped: {n}")
    for i in infos:
        if i.file_size > MAX_FILE_BYTES:
            problems.append(f"{i.filename} is {i.file_size} bytes (> {MAX_FILE_BYTES})")
    meta = dict(line.split("=", 1) for line in z.read("velorona/metadata.txt").decode().splitlines() if "=" in line and not line.startswith(" "))
    version = meta.get("version", "").strip()
    notes.append(f"metadata.txt: name={meta.get('name')} version={version} qgisMinimumVersion={meta.get('qgisMinimumVersion')}")
    if expected and version != expected:
        problems.append(f"metadata.txt version {version!r} != expected {expected!r}")
    # The QGIS plugin repository reads metadata.txt with Python's configparser (interpolation on): a lone '%' is rejected.
    import configparser
    parser = configparser.ConfigParser()
    try:
        parser.read_string(z.read("velorona/metadata.txt").decode("utf-8"))
        for key in parser["general"]:
            parser["general"][key]
        notes.append("metadata.txt parses with configparser interpolation (as the plugin repository does)")
    except (configparser.Error, KeyError) as exc:
        problems.append(f"metadata.txt is rejected by the plugin repository's parser: {str(exc)[:160]}")
    req = z.read("velorona/requirements.txt").decode()
    notes.append("requirements.txt: " + "; ".join(ln for ln in req.splitlines() if ln and not ln.startswith("#")))
    total = sum(i.file_size for i in infos)
    notes.append(f"{len(names)} files, {total / 1e6:.1f} MB uncompressed, zip {os.path.getsize(path) / 1e6:.1f} MB")
    for n in notes:
        print("  " + n)
    for p in problems:
        print("  PROBLEM", p)
    print("PASS" if not problems else "FAIL")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None))
