#!/usr/bin/env python3
"""Decode FILEDL_RAW responses logged during the file-type sweep."""

import re
import sys
from collections import Counter
from pathlib import Path

log = Path(sys.argv[1] if len(sys.argv) > 1 else "data/gb_probe_all.log")
text = log.read_text(encoding="utf-8", errors="replace")


def parse(buf: bytes):
    """Return dict tag -> value for flat TLVs (containers skipped)."""
    out = {}
    i = 0
    while i + 2 <= len(buf):
        tag = buf[i]
        ln = buf[i + 1]
        start, end = i + 2, i + 2 + ln
        if end > len(buf):
            break
        out.setdefault(tag, buf[start:end])
        i = end
    return out


rows = []
for m in re.finditer(r"FILEDL_RAW len=(\d+) data=([0-9A-F]+)", text):
    ln, hexstr = int(m.group(1)), m.group(2)
    if ln <= 6:
        continue
    buf = bytes.fromhex(hexstr)
    tlv = parse(buf)
    name = tlv.get(0x01, b"").decode("ascii", "ignore")
    file_id = tlv.get(0x02)
    size = tlv.get(0x04)
    err = tlv.get(0x7F)
    rows.append((
        name,
        file_id[0] if file_id and len(file_id) >= 1 else None,
        int.from_bytes(size, "big") if size else None,
        int.from_bytes(err, "big") if err else None,
    ))

print(f"responses parsed: {len(rows)}")

hits = [r for r in rows if r[2] and r[2] > 0]
print(f"\nentries WITH data (size > 0): {len(hits)}")
for name, fid, size, err in sorted(set(hits), key=lambda x: -x[2])[:40]:
    print(f"  {name:26} fileId=0x{fid:02X} size={size}")

print("\ntop types seen (count):")
types = Counter(r[1] for r in rows)
for t, n in sorted(types.items(), key=lambda x: -x[1])[:10]:
    print(f"  0x{t:02X}  x{n}" if t is not None else "  None")

