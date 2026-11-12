#!/usr/bin/env python3
"""Audit display ICC profiles: true primaries (chad undone), white point, TRC,
gamut coverage vs sRGB / Display P3 / Rec.2020, and deviation from a reference
(the monitor's EDID primaries).

Usage: python3 icc_audit.py [--ref rx,ry,gx,gy,bx,by,wx,wy] profile1.icc [profile2 ...]
"""
import sys, struct, os, math, hashlib

D50 = (0.9642, 1.0, 0.8249)
BRADFORD = [[0.8951, 0.2664, -0.1614], [-0.7502, 1.7135, 0.0367], [0.0389, -0.0685, 1.0296]]

STD = {
    "sRGB":    [(0.640, 0.330), (0.300, 0.600), (0.150, 0.060)],
    "P3":      [(0.680, 0.320), (0.265, 0.690), (0.150, 0.060)],
    "Rec2020": [(0.708, 0.292), (0.170, 0.797), (0.131, 0.046)],
}

def matmul(a, b): return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
def matvec(m, v): return [sum(m[i][k] * v[k] for k in range(3)) for i in range(3)]
def inv(m):
    a, b, c = m[0]; d, e, f = m[1]; g, h, i = m[2]
    det = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
    return [[(e * i - f * h) / det, (c * h - b * i) / det, (b * f - c * e) / det],
            [(f * g - d * i) / det, (a * i - c * g) / det, (c * d - a * f) / det],
            [(d * h - e * g) / det, (b * g - a * h) / det, (a * e - b * d) / det]]

def bradford_adapt(src, dst):
    s = matvec(BRADFORD, src); d = matvec(BRADFORD, dst)
    scale = [[d[0] / s[0], 0, 0], [0, d[1] / s[1], 0], [0, 0, d[2] / s[2]]]
    return matmul(inv(BRADFORD), matmul(scale, BRADFORD))

def xy(v):
    s = sum(v); return (v[0] / s, v[1] / s) if s else (0, 0)

def s15(b, o): return struct.unpack(">i", b[o:o + 4])[0] / 65536

def parse_trc(t):
    typ = t[:4]
    if typ == b"curv":
        n = struct.unpack(">I", t[8:12])[0]
        if n == 0: return "linear", 1.0
        if n == 1: g = struct.unpack(">H", t[12:14])[0] / 256; return f"gamma {g:.3f}", g
        vals = [struct.unpack(">H", t[12 + 2 * i:14 + 2 * i])[0] / 65535 for i in range(n)]
        mid = vals[n // 2]; x = (n // 2) / (n - 1)
        g = math.log(mid) / math.log(x) if 0 < mid < 1 else float("nan")
        return f"{n}-pt curve (~{g:.2f} @50%)", g
    if typ == b"para":
        fn = struct.unpack(">H", t[8:10])[0]
        p = [s15(t, 12 + 4 * i) for i in range({0: 1, 1: 3, 2: 4, 3: 5, 4: 7}[fn])]
        def f(x):
            g = p[0]
            if fn == 0: return x ** g
            a, b = p[1], p[2]
            if fn == 3:
                c, d = p[3], p[4]
                return (a * x + b) ** g if x >= d else c * x
            return (a * x + b) ** g if x >= -b / a else 0
        y = f(0.5); eg = math.log(y) / math.log(0.5) if y > 0 else float("nan")
        name = "sRGB curve" if fn == 3 and abs(p[0] - 2.4) < 0.01 else f"param type {fn} g={p[0]:.3f}"
        return f"{name} (~{eg:.2f} @50%)", eg
    return typ.decode(errors="replace"), float("nan")

def parse(path):
    d = open(path, "rb").read()
    ver = d[8]
    n = struct.unpack(">I", d[128:132])[0]
    tags = {}
    for i in range(n):
        sig, off, sz = struct.unpack(">4sII", d[132 + 12 * i:144 + 12 * i])
        tags[sig] = d[off:off + sz]
    out = {"version": f"v{ver}", "md5": hashlib.md5(d).hexdigest()[:8], "desc": ""}
    t = tags.get(b"desc")
    if t is not None:
        if t[:4] == b"desc":
            ln = struct.unpack(">I", t[8:12])[0]; out["desc"] = t[12:12 + ln].rstrip(b"\0").decode("latin1")
        elif t[:4] == b"mluc":
            cnt = struct.unpack(">I", t[8:12])[0]
            if cnt:
                ln, off = struct.unpack(">II", t[20:28]); out["desc"] = t[off:off + ln].decode("utf-16-be")
    if not all(k in tags for k in (b"rXYZ", b"gXYZ", b"bXYZ")):
        out["error"] = "not a matrix/TRC profile"; return out
    cols = [[s15(tags[k], 8 + 4 * j) for j in range(3)] for k in (b"rXYZ", b"gXYZ", b"bXYZ")]
    wtpt = [s15(tags[b"wtpt"], 8 + 4 * j) for j in range(3)] if b"wtpt" in tags else list(D50)
    if b"chad" in tags:
        chad = [[s15(tags[b"chad"], 8 + 4 * (3 * r + c)) for c in range(3)] for r in range(3)]
        undo = inv(chad)
        src_white = matvec(undo, list(D50))
    else:
        src_white = wtpt
        undo = bradford_adapt(D50, src_white) if abs(xy(src_white)[0] - xy(D50)[0]) > 1e-3 else [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
    out["prim"] = [xy(matvec(undo, c)) for c in cols]
    out["white"] = xy(src_white)
    out["trc"] = parse_trc(tags[b"rTRC"])[0] if b"rTRC" in tags else "?"
    out["vcgt"] = b"vcgt" in tags
    return out

def to_uv(p):
    x, y = p; den = -2 * x + 12 * y + 3; return (4 * x / den, 9 * y / den)

def area(poly):
    return abs(sum(poly[i][0] * poly[i - 1][1] - poly[i - 1][0] * poly[i][1] for i in range(len(poly)))) / 2

def clip(subject, clipper):
    def inside(p, a, b): return (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0]) >= 0
    def inter(p, q, a, b):
        x1, y1 = p; x2, y2 = q; x3, y3 = a; x4, y4 = b
        den = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
        t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / den
        return (x1 + t * (x2 - x1), y1 + t * (y2 - y1))
    out = subject
    for i in range(len(clipper)):
        a, b = clipper[i - 1], clipper[i]
        inp, out = out, []
        if not inp: break
        for j in range(len(inp)):
            p, q = inp[j - 1], inp[j]
            if inside(q, a, b):
                if not inside(p, a, b): out.append(inter(p, q, a, b))
                out.append(q)
            elif inside(p, a, b):
                out.append(inter(p, q, a, b))
    return out

def ccw(poly):
    s = sum(poly[i][0] * poly[i - 1][1] - poly[i - 1][0] * poly[i][1] for i in range(len(poly)))
    return poly if s < 0 else poly[::-1]

def coverage(prim, std):
    a = ccw([to_uv(p) for p in prim]); b = ccw([to_uv(p) for p in std])
    return 100 * area(clip(a, b)) / area(b)

def main():
    args = sys.argv[1:]; ref = None
    if args and args[0] == "--ref":
        v = [float(x) for x in args[1].split(",")]; ref = ([(v[0], v[1]), (v[2], v[3]), (v[4], v[5])], (v[6], v[7])); args = args[2:]
    if ref:
        print("REFERENCE (EDID native):", " ".join(f"{c}={p[0]:.4f},{p[1]:.4f}" for c, p in zip("RGB", ref[0])),
              f"W={ref[1][0]:.4f},{ref[1][1]:.4f}",
              " | cov sRGB {:.0f}% P3 {:.0f}% 2020 {:.0f}%".format(*(coverage(ref[0], STD[k]) for k in STD)))
        print()
    for path in args:
        try: r = parse(path)
        except Exception as e: print(os.path.basename(path), "ERROR", e); continue
        print(f"## {os.path.basename(path)}  [{r['version']} md5 {r['md5']}] desc='{r['desc']}'")
        if "error" in r: print("   ", r["error"]); continue
        P = r["prim"]
        print("   prim  " + "  ".join(f"{c} {p[0]:.4f},{p[1]:.4f}" for c, p in zip("RGB", P)) + f"   white {r['white'][0]:.4f},{r['white'][1]:.4f}")
        print(f"   TRC   {r['trc']}   vcgt={'yes' if r['vcgt'] else 'no'}")
        print("   cov   sRGB {:.1f}%  P3 {:.1f}%  Rec2020 {:.1f}%".format(*(coverage(P, STD[k]) for k in STD)))
        if ref:
            du = [math.dist(to_uv(a), to_uv(b)) for a, b in zip(P, ref[0])]
            dw = math.dist(to_uv(r["white"]), to_uv(ref[1]))
            print("   vs EDID  Δu'v' R {:.4f} G {:.4f} B {:.4f} W {:.4f}  ({})".format(*du, dw,
                  "matches panel" if max(du + [dw]) < 0.006 else "DOES NOT match panel native gamut"))
        print()

if __name__ == "__main__":
    main()
