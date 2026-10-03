"""The Canada snapshot bundled in this plugin must be byte-identical to the one in Velorona Map (AIDEdgeInc-Lab/velorona-map, web/fixed_service_snapshot.json).

The hash below is the corrected snapshot (ISED Fixed Service file of 2026-09-01, built 2026-09-09; the 2026-10 correction fixed one site's role value that
carried literal quote characters). If you update the snapshot, update it in BOTH repositories and change this hash in the same commit.
"""
import hashlib
import json
from pathlib import Path

SNAP = Path(__file__).resolve().parent.parent / "data" / "fixed_service_snapshot.json"
SHA256 = "f9daa05e51a38a8083d50513d63c7c173caa1ffd5257011af54aed11ce1387c8"


def test_bundled_canada_snapshot_is_the_shared_corrected_file():
    data = SNAP.read_bytes()
    assert hashlib.sha256(data).hexdigest() == SHA256, "the bundled snapshot differs from Velorona Map's; update both repositories together"


def test_counts_and_role_values():
    d = json.loads(SNAP.read_text(encoding="utf-8"))
    assert (len(d["sites"]), len(d["links"])) == (24859, 16956)
    assert {r for s in d["sites"] for r in s["roles"]} == {"RX", "TX"}, "a role value other than TX/RX (literal quote characters?) is back"
    assert (d["generated_date"], d["source_file_updated"]) == ("2026-09-09", "2026-09-01")
