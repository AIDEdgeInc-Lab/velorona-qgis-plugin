#!/usr/bin/env python3
"""Fails if a pytest junit report contains any skipped test that is not on the allowlist.

    python3 tools/check_skips.py pytest.xml

A skipped gate is no gate: a test that silently starts skipping (missing dependency, renamed marker) must break CI,
not shrink it. The two allowed skips need real USA data that lives in the Velorona Map repo (see the skip messages);
they are covered by the synthetic-pack tests in the QGIS runtime lane instead.
"""
import sys
import xml.etree.ElementTree as ET

ALLOWED = {
    "tests.test_usa_provider::test_real_pack_dedup_matches_the_index",
    "tests.test_usa_provider::test_real_extract_loads_whole_with_contract_counts",
}


def main(path):
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root)
    skipped, tests = [], 0
    for suite in suites:
        tests += int(suite.get("tests", 0))
        for tc in suite.iter("testcase"):
            if tc.find("skipped") is not None:
                skipped.append(f"{tc.get('classname')}::{tc.get('name')}")
    unexpected = sorted(set(skipped) - ALLOWED)
    missing = sorted(ALLOWED - set(skipped))
    print(f"tests={tests} skipped={len(skipped)} allowed={len(ALLOWED)}")
    for s in unexpected:
        print(f"UNEXPECTED SKIP: {s}")
    for s in missing:
        # Not fatal: an allowed skip that now runs is good news, but the allowlist should then be tightened.
        print(f"note: allowlisted skip no longer skipped (remove it from ALLOWED): {s}")
    return 1 if unexpected else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
