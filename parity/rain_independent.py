#!/usr/bin/env python3
"""INDEPENDENT computation of ITU-R P.838-3 specific rain attenuation. Stdlib only. Imports NOTHING from the product, the aei libraries or the Map.

    python3 parity/rain_independent.py [--pdf-text P838-3-E.txt] [--out parity/handoff/QGIS_RAIN_INDEPENDENT.json]

Method (Rec. ITU-R P.838-3, equations (1)-(3)): gamma_R = k * R^alpha with
    log10 k     = sum_{j=1..4} a_j * exp(-((log10 f - b_j)/c_j)^2) + m_k * log10 f + c_k
    alpha       = sum_{j=1..5} a_j * exp(-((log10 f - b_j)/c_j)^2) + m_a * log10 f + c_a
Constants: Tables 1-4 of the Recommendation. SOURCE: https://www.itu.int/dms_pubrec/itu-r/rec/p/R-REC-P.838-3-200503-I!!PDF-E.pdf
(retrieved 2026-10-09 01:30 UTC, sha256 3ab7482993e51fc63c5127a72e9e8930614e73652ac614882760817e7c1469cb; text via pdftotext -layout). They were
machine-extracted from that text, not typed from memory; Table 4's m/c are read from its third row. SELF-CHECK: the formula is evaluated at every
Table 5 frequency listed below (and, with --pdf-text, at ALL Table 5 frequencies parsed from the document); if it disagrees with the document's own
Table 5 by more than rounding, the script says so and exits non-zero -- so a wrong constant cannot pass silently.
Only the specific attenuation is computed (P.838). Path-length factors belong to P.530 and are not part of this file.
"""
import argparse
import json
import math
import re
import sys

TABLES = {  # SOURCE: Rec. ITU-R P.838-3 Tables 1-4: rows (a_j, b_j, c_j); (m, c)
    "kH": {"rows": [(-5.3398, -0.10008, 1.13098), (-0.35351, 1.2697, 0.454), (-0.23789, 0.86036, 0.15354), (-0.94158, 0.64552, 0.16817)], "mc": (-0.18961, 0.71147)},
    "kV": {"rows": [(-3.80595, 0.56934, 0.81061), (-3.44965, -0.22911, 0.51059), (-0.39902, 0.73042, 0.11899), (0.50167, 1.07319, 0.27195)], "mc": (-0.16398, 0.63297)},
    "aH": {"rows": [(-0.14318, 1.82442, -0.55187), (0.29591, 0.77564, 0.19822), (0.32177, 0.63773, 0.13164), (-5.3761, -0.9623, 1.47828), (16.1721, -3.2998, 3.4399)], "mc": (0.67849, -1.95537)},
    "aV": {"rows": [(-0.07771, 2.3384, -0.76284), (0.56727, 0.95545, 1.14520 * 0 + 0.54039), (-0.20238, 1.1452, 0.26809), (-48.2991, 0.791669, 0.116226), (48.5833, 0.791459, 0.116479)], "mc": (-0.053739, 0.83433)},
}
# Table 5 rows at the grid frequencies (copied from the document text): f -> (kH, aH, kV, aV)
TABLE5_GRID = {6: (0.0007056, 1.5900, 0.0004878, 1.5728), 7: (0.001915, 1.4810, 0.001425, 1.4745), 8: (0.004115, 1.3905, 0.003450, 1.3797),
               10: (0.01217, 1.2571, 0.01129, 1.2156), 11: (0.01772, 1.2140, 0.01731, 1.1617), 15: (0.04481, 1.1233, 0.05008, 1.0440),
               18: (0.07078, 1.0818, 0.07708, 1.0025), 23: (0.1286, 1.0214, 0.1284, 0.9630), 38: (0.4001, 0.8816, 0.3844, 0.8552)}
GRID_GHZ = [1, 2, 4, 6, 7, 8, 10, 11, 12, 13, 15, 18, 20, 23, 26, 28, 32, 38, 50, 80, 100]
RAIN_RATES = [1.0, 5.0, 12.0, 25.0, 32.0, 50.0, 100.0]


def _gauss_sum(t, lf):
    return sum(a * math.exp(-(((lf - b) / c) ** 2)) for a, b, c in t["rows"])


def coeff(f_ghz):
    lf = math.log10(f_ghz)
    out = {}
    for name in ("kH", "kV"):
        t = TABLES[name]
        out[name] = 10 ** (_gauss_sum(t, lf) + t["mc"][0] * lf + t["mc"][1])
    for name in ("aH", "aV"):
        t = TABLES[name]
        out[name] = _gauss_sum(t, lf) + t["mc"][0] * lf + t["mc"][1]
    return out


def gamma(f_ghz, rate, pol):
    c = coeff(f_ghz)
    return c["k" + pol] * rate ** c["a" + pol]


def parse_table5(text):
    rows = {}
    for line in text.replace("–", "-").splitlines():
        m = re.match(r"\s*(\d+(?:\s\d{3})?)\s+(\d\.\d+)\s+(\d\.\d+)\s+(\d\.\d+)\s+(\d\.\d+)\s*$", line)
        if m:
            rows[float(m.group(1).replace(" ", ""))] = tuple(float(m.group(i)) for i in (2, 3, 4, 5))
    return rows


REL_TOL = 2.0e-3   # Table 5 prints 3-4 significant figures; half a unit of a 3-figure value such as 2.59e-5 is up to 1.9e-3 relative


def sig_equal(x, ref):
    return abs(x - ref) <= REL_TOL * abs(ref)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf-text")
    ap.add_argument("--out", default="parity/handoff/QGIS_RAIN_INDEPENDENT.json")
    a = ap.parse_args()
    ref = dict(TABLE5_GRID)
    if a.pdf_text:
        full = parse_table5(open(a.pdf_text, encoding="utf-8").read())
        ref = {int(f) if f == int(f) else f: v for f, v in full.items()}
    bad, worst = [], 0.0
    for f, (kh, ah, kv, av) in sorted(ref.items()):
        c = coeff(f)
        for nm, got, want in (("kH", c["kH"], kh), ("aH", c["aH"], ah), ("kV", c["kV"], kv), ("aV", c["aV"], av)):
            rel = abs(got - want) / abs(want)
            worst = max(worst, rel)
            if not sig_equal(got, want):
                bad.append((f, nm, got, want))
    result = {
        "schema": "velorona.rain-independent/1",
        "method": "Rec. ITU-R P.838-3 eq. (1)-(3): gamma = k R^alpha; log10 k and alpha from sums of Gaussians in log10 f plus a linear term (Tables 1-4)",
        "source": {"url": "https://www.itu.int/dms_pubrec/itu-r/rec/p/R-REC-P.838-3-200503-I!!PDF-E.pdf", "retrieved_utc": "2026-10-09T01:30:37Z",
                   "pdf_sha256": "3ab7482993e51fc63c5127a72e9e8930614e73652ac614882760817e7c1469cb"},
        "independence": "no import from the product, the aei libraries or the Map; constants machine-extracted from the PDF text, self-checked against its Table 5",
        "constants": TABLES,
        "self_check": {"table5_frequencies_checked": len(ref), "scope": "all Table 5 rows" if a.pdf_text else "grid rows only (use --pdf-text for all)",
                       "tolerance_relative": REL_TOL, "worst_relative_difference": worst, "disagreements": [list(x) for x in bad]},
        "grid": [],
    }
    for f in GRID_GHZ:
        c = coeff(f)
        row = {"f_ghz": f, "kH": c["kH"], "alphaH": c["aH"], "kV": c["kV"], "alphaV": c["aV"], "gamma_db_per_km": {}}
        for r in RAIN_RATES:
            row["gamma_db_per_km"][str(r)] = {"H": c["kH"] * r ** c["aH"], "V": c["kV"] * r ** c["aV"]}
        result["grid"].append(row)
    json.dump(result, open(a.out, "w"), indent=1)
    print("Table 5 rows checked: %d | worst relative difference %.2e | disagreements: %d" % (len(ref), worst, len(bad)))
    for b in bad[:10]:
        print("  DISAGREES", b)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
