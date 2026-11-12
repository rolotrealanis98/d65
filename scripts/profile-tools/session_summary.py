#!/usr/bin/env python3
"""Summarise d65 session records side by side: per-patch Y and xy (black subtracted), white,
gray-ramp gamma, primaries, and the white-to-white difference between the first record and
the others (same probe, so relative).

Usage: python3 -I session_summary.py reference.json [other.json ...]
"""
import json, math, sys

GREY = {"grey20": 0.2, "grey40": 0.4, "grey60": 0.6, "grey80": 0.8}

def load(path):
    r = json.load(open(path))
    m = {x["request"]["phase"]: x["mean"] for x in r["measurements"]}
    black = m.get("black", {"x": 0, "y": 0, "z": 0})
    sub = {k: tuple(max(0.0, v[a] - black[a]) for a in "xyz") for k, v in m.items() if k != "black"}
    return r, black, sub

def xy(v):
    s = sum(v); return (v[0] / s, v[1] / s) if s > 0 else (float("nan"),) * 2

def gamma(sub):
    wy = sub["white"][1]; pts = [(math.log(f), math.log(sub[k][1] / wy)) for k, f in GREY.items() if k in sub and sub[k][1] > 0]
    if len(pts) < 2: return float("nan")
    return sum(a * b for a, b in pts) / sum(a * a for a, _ in pts)

def lab(v, white):
    f = lambda t: t ** (1 / 3) if t > (6 / 29) ** 3 else t / (3 * (6 / 29) ** 2) + 4 / 29
    fx, fy, fz = (f(v[i] / white[i]) for i in range(3))
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)

def de00(l1, l2):
    L1, a1, b1 = l1; L2, a2, b2 = l2
    C1, C2 = math.hypot(a1, b1), math.hypot(a2, b2); Cb = (C1 + C2) / 2
    G = 0.5 * (1 - math.sqrt(Cb ** 7 / (Cb ** 7 + 25 ** 7)))
    a1p, a2p = a1 * (1 + G), a2 * (1 + G)
    C1p, C2p = math.hypot(a1p, b1), math.hypot(a2p, b2)
    h1 = math.degrees(math.atan2(b1, a1p)) % 360; h2 = math.degrees(math.atan2(b2, a2p)) % 360
    dL, dC = L2 - L1, C2p - C1p
    dh = h2 - h1
    if C1p * C2p == 0: dh = 0
    elif dh > 180: dh -= 360
    elif dh < -180: dh += 360
    dH = 2 * math.sqrt(C1p * C2p) * math.sin(math.radians(dh / 2))
    Lb, Cbp = (L1 + L2) / 2, (C1p + C2p) / 2
    hb = (h1 + h2) / 2 if abs(h1 - h2) <= 180 else (h1 + h2 + 360) / 2
    if C1p * C2p == 0: hb = h1 + h2
    T = 1 - 0.17 * math.cos(math.radians(hb - 30)) + 0.24 * math.cos(math.radians(2 * hb)) \
        + 0.32 * math.cos(math.radians(3 * hb + 6)) - 0.20 * math.cos(math.radians(4 * hb - 63))
    SL = 1 + 0.015 * (Lb - 50) ** 2 / math.sqrt(20 + (Lb - 50) ** 2)
    SC, SH = 1 + 0.045 * Cbp, 1 + 0.015 * Cbp * T
    RT = -2 * math.sqrt(Cbp ** 7 / (Cbp ** 7 + 25 ** 7)) * math.sin(math.radians(60 * math.exp(-((hb - 275) / 25) ** 2)))
    return math.sqrt((dL / SL) ** 2 + (dC / SC) ** 2 + (dH / SH) ** 2 + RT * dC / SC * dH / SH)

def main():
    runs = [load(p) for p in sys.argv[1:]]
    for r, black, sub in runs:
        w = sub["white"]
        print(f"## {r['display']['name']}  ({r['id'][:8]}, {r['outcome']})  settings {r['display'].get('monitorSettings')}")
        print(f"   black Y {black['y']:.2f}   white Y {w[1]:.1f}   white xy {xy(w)[0]:.4f},{xy(w)[1]:.4f}   gray-ramp gamma {gamma(sub):.2f}")
        print("   primaries " + "  ".join(f"{k[0].upper()} {xy(sub[k])[0]:.3f},{xy(sub[k])[1]:.3f}" for k in ("red", "green", "blue") if k in sub))
        print("   grays (Y/white) " + "  ".join(f"{k} {sub[k][1] / w[1]:.3f}" for k in GREY if k in sub))
    if len(runs) > 1:
        ref = runs[0][2]["white"]; ref_n = tuple(v / ref[1] for v in ref)
        for r, _, sub in runs[1:]:
            w = sub["white"]; w_n = tuple(v / w[1] for v in w)
            d = de00(lab(ref_n, ref_n), lab(w_n, ref_n))
            print(f"\n{r['display']['name']} vs {runs[0][0]['display']['name']}: white ΔE00 {d:.2f} (chromaticity only, same probe)"
                  f", Y ratio {w[1] / ref[1]:.2f}, gamma {gamma(sub):.2f} vs {gamma(runs[0][2]):.2f}")

if __name__ == "__main__":
    main()
