#!/usr/bin/env python3
"""Per-display probe correction (three-colour method) and a corrected cross-display comparison.

The iPhone ALS is not colorimetric, and its error depends on the panel's spectrum. For each
display we know the true chromaticities of its primaries (EDID, a past colorimeter run): those
are fixed by the panel's physics and don't drift much. The white point is set by how bright each
primary is relative to the others, and that is what drifts and what we want to measure.

Three-colour method: build a 3x3 matrix C so that each measured primary lands on its known
chromaticity while keeping its measured luminance Y. White is NOT a reference, so the corrected
white (C applied to the measured white) is an independent estimate.

Usage:
  python3 -I probe_correction.py REF.json REF_PRIMARIES  OTHER.json OTHER_PRIMARIES
  where *_PRIMARIES is "rx,ry,gx,gy,bx,by".
"""
import json, math, sys

def inv(m):
    a, b, c = m[0]; d, e, f = m[1]; g, h, i = m[2]
    det = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
    return [[(e * i - f * h) / det, (c * h - b * i) / det, (b * f - c * e) / det],
            [(f * g - d * i) / det, (a * i - c * g) / det, (c * d - a * f) / det],
            [(d * h - e * g) / det, (b * g - a * h) / det, (a * e - b * d) / det]]
def mul(a, b): return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
def mv(m, v): return [sum(m[i][k] * v[k] for k in range(3)) for i in range(3)]
def xy(v): s = sum(v); return (v[0] / s, v[1] / s)
def cols(*vs): return [[v[i] for v in vs] for i in range(3)]

def load(path):
    r = json.load(open(path))
    m = {x["request"]["phase"]: x["mean"] for x in r["measurements"]}
    k = m["black"]
    return r, {p: [max(0.0, m[p][a] - k[a]) for a in "xyz"] for p in m if p != "black"}

def correction(sub, prim):
    """C maps probe XYZ to true XYZ for this panel."""
    meas = cols(sub["red"], sub["green"], sub["blue"])
    true = []
    for (x, y), p in zip(prim, ("red", "green", "blue")):
        Y = sub[p][1]
        true.append([x / y * Y, Y, (1 - x - y) / y * Y])
    return mul(cols(*true), inv(meas))

def lab(v, w):
    f = lambda t: t ** (1 / 3) if t > (6 / 29) ** 3 else t / (3 * (6 / 29) ** 2) + 4 / 29
    fx, fy, fz = (f(v[i] / w[i]) for i in range(3))
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)

def de00(l1, l2):
    L1, a1, b1 = l1; L2, a2, b2 = l2
    C1, C2 = math.hypot(a1, b1), math.hypot(a2, b2); Cb = (C1 + C2) / 2
    G = 0.5 * (1 - math.sqrt(Cb ** 7 / (Cb ** 7 + 25 ** 7)))
    a1p, a2p = a1 * (1 + G), a2 * (1 + G)
    C1p, C2p = math.hypot(a1p, b1), math.hypot(a2p, b2)
    h1 = math.degrees(math.atan2(b1, a1p)) % 360; h2 = math.degrees(math.atan2(b2, a2p)) % 360
    dL, dC = L2 - L1, C2p - C1p
    dh = 0 if C1p * C2p == 0 else (h2 - h1 - 360 if h2 - h1 > 180 else h2 - h1 + 360 if h2 - h1 < -180 else h2 - h1)
    dH = 2 * math.sqrt(C1p * C2p) * math.sin(math.radians(dh / 2))
    Lb, Cbp = (L1 + L2) / 2, (C1p + C2p) / 2
    hb = (h1 + h2) / 2 if abs(h1 - h2) <= 180 else (h1 + h2 + 360) / 2
    T = 1 - 0.17 * math.cos(math.radians(hb - 30)) + 0.24 * math.cos(math.radians(2 * hb)) \
        + 0.32 * math.cos(math.radians(3 * hb + 6)) - 0.20 * math.cos(math.radians(4 * hb - 63))
    SL = 1 + 0.015 * (Lb - 50) ** 2 / math.sqrt(20 + (Lb - 50) ** 2)
    SC, SH = 1 + 0.045 * Cbp, 1 + 0.015 * Cbp * T
    RT = -2 * math.sqrt(Cbp ** 7 / (Cbp ** 7 + 25 ** 7)) * math.sin(math.radians(60 * math.exp(-((hb - 275) / 25) ** 2)))
    return math.sqrt((dL / SL) ** 2 + (dC / SC) ** 2 + (dH / SH) ** 2 + RT * dC / SC * dH / SH)

def cct(x, y):
    n = (x - 0.3320) / (0.1858 - y); return 449 * n ** 3 + 3525 * n ** 2 + 6823.3 * n + 5520.33

def analyse(path, prim_arg):
    v = [float(t) for t in prim_arg.split(",")]
    prim = [(v[0], v[1]), (v[2], v[3]), (v[4], v[5])]
    r, sub = load(path)
    C = correction(sub, prim)
    w_raw = sub["white"]
    w = mv(C, w_raw)
    rgb_sum = [sub["red"][i] + sub["green"][i] + sub["blue"][i] for i in range(3)]
    add = w_raw[1] / rgb_sum[1]
    x, y = xy(w)
    print(f"## {r['display']['name']}")
    print(f"   additivity  white Y / (R+G+B) Y = {add:.3f}   (1.00 = additive; ALS sanity check)")
    print(f"   raw white   xy {xy(w_raw)[0]:.4f},{xy(w_raw)[1]:.4f}")
    print(f"   corrected   xy {x:.4f},{y:.4f}  ≈{cct(x, y):.0f} K   Y {w[1]:.1f}")
    d65 = (0.3127, 0.3290); dn = [d65[0] / d65[1], 1, (1 - sum(d65)) / d65[1]]
    wn = [t / w[1] for t in w]
    print(f"   vs D65      ΔE00 {de00(lab(dn, dn), lab(wn, dn)):.2f}")
    return r, C, w, sub

def main():
    a = analyse(sys.argv[1], sys.argv[2]); b = analyse(sys.argv[3], sys.argv[4])
    (_, _, wa, _), (rb, _, wb, _) = a, b
    an = [t / wa[1] for t in wa]; bn = [t / wb[1] for t in wb]
    print(f"\n{rb['display']['name']} vs reference: corrected white ΔE00 {de00(lab(an, an), lab(bn, an)):.2f}, "
          f"Y ratio {wb[1] / wa[1]:.2f}")
    # Per-channel linear gains on the secondary that move its white onto the reference white
    # (chromaticity only, brightness kept): solve in the secondary's own RGB.
    _, Cb, _, sb = b
    Mb = mul(Cb, cols(sb["red"], sb["green"], sb["blue"]))           # secondary RGB(linear) -> true XYZ
    target = [t * wb[1] for t in an]                                   # reference chromaticity at secondary's Y
    g = mv(inv(Mb), target)
    g = [t / max(g) for t in g]                                        # never boost: largest gain = 1
    print(f"suggested linear RGB gains on {rb['display']['name']}: R {g[0]:.3f}  G {g[1]:.3f}  B {g[2]:.3f}")

if __name__ == "__main__":
    main()
