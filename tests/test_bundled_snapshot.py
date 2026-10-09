"""The Canada snapshot bundled in this plugin must be byte-identical to the one in Velorona Map (AIDEdgeInc-Lab/velorona-map, web/fixed_service_snapshot.json).

The hash below is snapshot schema /1.1 (ISED Fixed Service file of 2026-09-01; /1.1 adds per-endpoint record heights, ISED column 29, to each link; sites and every
earlier link field are byte-identical to /1). If you update the snapshot, update it in BOTH repositories and change this hash in the same commit.
"""
import hashlib
import json
from pathlib import Path

SNAP = Path(__file__).resolve().parent.parent / "data" / "fixed_service_snapshot.json"
SHA256 = "e10a3ad16d23c6ca07334bc66bf985b2574b5db8de777d4ce5978d1a0e88c50e"


def test_bundled_canada_snapshot_is_the_shared_corrected_file():
    data = SNAP.read_bytes()
    assert hashlib.sha256(data).hexdigest() == SHA256, "the bundled snapshot differs from Velorona Map's; update both repositories together"


def test_counts_and_role_values():
    d = json.loads(SNAP.read_text(encoding="utf-8"))
    assert (len(d["sites"]), len(d["links"])) == (24859, 16956)
    assert {r for s in d["sites"] for r in s["roles"]} == {"RX", "TX"}, "a role value other than TX/RX (literal quote characters?) is back"
    assert (d["generated_date"], d["source_file_updated"]) == ("2026-09-09", "2026-09-01")


def test_bundled_snapshot_carries_documented_record_heights():
    """Schema /1.1: ISED column 29 'Height above ground level [m]' per endpoint (Map contract parity/contract/HEIGHTS_CONTRACT.md)."""
    d = json.loads(SNAP.read_text(encoding="utf-8"))
    h = d["heights"]
    assert h["unit"] == "m" and h["reference"] == "above ground level" and "column 29" in h["field"]
    assert h["document_sha256"] == "8ee1ef262e44e512b8fb914a4b292575cdb442acc5a207a9422ad54f45c6ab5c"
    assert sum(1 for lk in d["links"] if lk.get("site_a_height_m") is not None and lk.get("site_b_height_m") is not None) > 16900


def test_every_canadian_fixture_that_carries_record_heights_gets_them_from_this_snapshot():
    """Closes the loop fixture <-> bundled data: the heights the Map froze into ca-h-* / rs-ca-* are exactly what this plugin's snapshot holds for that link."""
    d = json.loads(SNAP.read_text(encoding="utf-8"))
    links = {lk["authorization_number"]: lk for lk in d["links"]}
    fixtures = Path(__file__).resolve().parent.parent / "parity" / "fixtures"
    checked = 0
    for path in sorted(fixtures.glob("ca-h-*.json")) + sorted((fixtures / "real-snapshot").glob("rs-ca-*.json")):
        fx = json.loads(path.read_text(encoding="utf-8"))
        link = links[fx["selection"]["link_id"]]
        for key, site in (("site_a_height_m", fx["link"]["site_a"]), ("site_b_height_m", fx["link"]["site_b"])):
            if site.get("height_origin") == "Observed":
                assert link[key] == site["height_m"], (path.name, key)
                checked += 1
    assert checked >= 38        # 9 + 10 fixtures x 2 ends (ca-h-height-zero is the NO DATA case and keeps its own inputs)
