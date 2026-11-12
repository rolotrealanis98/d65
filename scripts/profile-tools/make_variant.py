#!/usr/bin/env python3
"""Make a v2 matrix/TRC display profile that keeps a source profile's primaries
and white point (rXYZ/gXYZ/bXYZ/wtpt copied byte-for-byte) but uses a pure
power-law tone curve.

Usage: python3 make_variant.py SOURCE.icc OUT.icc "Description" GAMMA
"""
import sys, struct

src, out, desc, gamma = sys.argv[1], sys.argv[2], sys.argv[3], float(sys.argv[4])
d = open(src, "rb").read()
n = struct.unpack(">I", d[128:132])[0]
tags = {}
for i in range(n):
    sig, off, sz = struct.unpack(">4sII", d[132 + 12 * i:144 + 12 * i])
    tags[sig] = d[off:off + sz]

def desc_tag(s):
    a = s.encode("ascii") + b"\0"
    return b"desc" + b"\0" * 4 + struct.pack(">I", len(a)) + a + b"\0" * 8 + b"\0" * 3 + b"\0" * 67

def text_tag(s): return b"text" + b"\0" * 4 + s.encode("ascii") + b"\0"

curv = b"curv" + b"\0" * 4 + struct.pack(">IH", 1, round(gamma * 256)) + b"\0\0"
new = [
    (b"desc", desc_tag(desc)),
    (b"cprt", text_tag("No copyright, derived from EDID-based display profile")),
    (b"wtpt", tags[b"wtpt"]),
    (b"rXYZ", tags[b"rXYZ"]), (b"gXYZ", tags[b"gXYZ"]), (b"bXYZ", tags[b"bXYZ"]),
    (b"rTRC", curv), (b"gTRC", curv), (b"bTRC", curv),
]
table_len = 4 + 12 * len(new)
off = 128 + table_len
body, table = b"", struct.pack(">I", len(new))
offsets = {}
for sig, data in new:
    if sig in (b"gTRC", b"bTRC"):  # share rTRC data
        table += struct.pack(">4sII", sig, offsets[b"rTRC"][0], offsets[b"rTRC"][1]); continue
    while (off + len(body)) % 4: body += b"\0"
    o = off + len(body); offsets[sig] = (o, len(data))
    table += struct.pack(">4sII", sig, o, len(data)); body += data
while (128 + len(table) + len(body)) % 4: body += b"\0"
size = 128 + len(table) + len(body)
hdr = bytearray(d[:128])
hdr[0:4] = struct.pack(">I", size)
hdr[8:12] = bytes([2, 0x20, 0, 0])          # v2.2
hdr[12:16] = b"mntr"; hdr[16:20] = b"RGB "; hdr[20:24] = b"XYZ "
hdr[84:100] = b"\0" * 16                     # clear profile ID (v2)
open(out, "wb").write(bytes(hdr) + table + body)
print("wrote", out, size, "bytes")
