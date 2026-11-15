#!/usr/bin/env python3
"""combine.py STOCK_COMBINED BASE_DTB PATCHED_DTB OUT

Qualcomm's combined-dtb.dtb is a plain concatenation of device trees. Replace the one entry that
is byte-identical to BASE_DTB with PATCHED_DTB and copy every other entry unchanged.
"""
import struct
import sys

stock = open(sys.argv[1], 'rb').read()
base = open(sys.argv[2], 'rb').read()
patched = open(sys.argv[3], 'rb').read()

MAGIC = 0xd00dfeed


def check(blob, what):
    magic, total = struct.unpack('>II', blob[:8])
    if magic != MAGIC or total != len(blob):
        sys.exit('%s is not a well-formed single DTB (magic %x, totalsize %d, len %d)'
                 % (what, magic, total, len(blob)))


check(base, 'base'); check(patched, 'patched')
out, off, hits, n = [], 0, 0, 0
while off < len(stock):
    magic, total = struct.unpack('>II', stock[off:off + 8])
    if magic != MAGIC or off + total > len(stock):
        sys.exit('stock combined file is not a clean concatenation at offset %d' % off)
    entry = stock[off:off + total]
    if entry == base:
        out.append(patched); hits += 1
        print('entry #%d (offset %d, %d bytes) -> patched (%d bytes)' % (n, off, total, len(patched)))
    else:
        out.append(entry)
    off += total; n += 1
if hits != 1:
    sys.exit('expected exactly one entry matching the base DTB, found %d' % hits)
open(sys.argv[4], 'wb').write(b''.join(out))
print('%d entries, %d -> %d bytes' % (n, len(stock), sum(map(len, out))))
