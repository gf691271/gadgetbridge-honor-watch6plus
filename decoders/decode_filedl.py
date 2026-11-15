#!/usr/bin/env python3
"""Decode FILEDL_RAW responses logged during the file-type sweep.

Two jobs:

1. **Experiment A** (no device needed). The 0x2C/0x01 init answer carries
   `01 = filename`, `02 = file type`, `03 = transfer id`, `04 = size`, or `7F = error`.
   A short answer (`len <= 6`) is an error-only packet, i.e. the device refused that
   type. Reading these apart answers "which file types does the device really accept",
   which the client used to muddle: `convertFileTypeFrom2C` mapped only 7 types and
   turned the rest into UNKNOWN, so the size the device sent was discarded and the
   download was aborted as a "wrong file" before anything was logged.

2. A per-type summary table, so the conclusion can be quoted from data instead of
   from memory.

Usage: python decode_filedl.py data/gb_probe_all.log
"""

import re
import sys
from collections import Counter, defaultdict
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


def big(value):
    return int.from_bytes(value, "big") if value else None


rows = []
for m in re.finditer(r"FILEDL_RAW len=(\d+) data=([0-9A-F]+)", text):
    ln, hexstr = int(m.group(1)), m.group(2)
    buf = bytes.fromhex(hexstr)
    tlv = parse(buf)
    name = tlv.get(0x01, b"").decode("ascii", "ignore")
    file_type = tlv.get(0x02)
    transfer_id = tlv.get(0x03)
    size = tlv.get(0x04)
    err = tlv.get(0x7F)
    full = 0x01 in tlv and 0x02 in tlv and 0x03 in tlv and 0x04 in tlv
    rows.append({
        "len": ln,
        "name": name,
        "file_type": file_type[0] if file_type else None,
        "transfer_id": transfer_id[0] if transfer_id else None,
        "size": big(size),
        "7F": big(err),
        "shape": "full" if full else ("error-only" if err is not None else "other"),
    })

print(f"responses parsed: {len(rows)}")

# ---- per-type table ---------------------------------------------------------
by_type = defaultdict(list)
for r in rows:
    by_type[r["file_type"]].append(r)

print("\nfile_type | answer shape | size | transfer_id | 7F  | example name")
print("----------|--------------|------|-------------|-----|-------------")
for t in sorted(by_type, key=lambda x: (x is None, x)):
    group = by_type[t]
    shapes = Counter(g["shape"] for g in group)
    shape = ", ".join(f"{k} x{v}" for k, v in shapes.items())
    sizes = sorted({g["size"] for g in group if g["size"] is not None})
    ids = sorted({g["transfer_id"] for g in group if g["transfer_id"] is not None})
    errs = sorted({g["7F"] for g in group if g["7F"] is not None})
    label = f"0x{t:02X}" if t is not None else "None"
    size_txt = ",".join(str(s) for s in sizes[:4]) or "-"
    id_txt = ",".join(str(s) for s in ids[:4]) or "-"
    err_txt = ",".join(f"0x{e:08X}" for e in errs[:2]) or "-"
    print(f"{label:9} | {shape:12} | {size_txt:8} | {id_txt:11} | {err_txt:19} | {group[0]['name'] or '-'}")

# ---- what the table means ---------------------------------------------------
full_nonzero = sorted({r["file_type"] for r in rows
                       if r["shape"] == "full" and (r["size"] or 0) > 0
                       and r["file_type"] is not None})
full_zero = sorted({r["file_type"] for r in rows
                    if r["shape"] == "full" and (r["size"] or 0) == 0
                    and r["file_type"] is not None})
only_error = sorted({r["file_type"] for r in rows
                     if r["shape"] == "error-only" and r["file_type"] is not None})


def hexlist(values):
    return ", ".join(f"0x{v:02X}" for v in values) or "-"


print("\n--- reading ---")
print(f"full answer, size > 0 : {hexlist(full_nonzero)}")
print(f"full answer, size = 0 : {hexlist(full_zero)}   (type accepted, no data right now)")
print(f"error-only answer     : {hexlist(only_error)}   (type refused)")

same = [r for r in rows
        if r["file_type"] is not None and r["file_type"] == r["transfer_id"]]
print(f"transfer_id == file_type: {len(same)} of {len(rows)}"
      "   (if nearly all, the device numbers the handle like the type)")
if rows:
    unknown_high = sorted({r["file_type"] for r in rows
                           if r["file_type"] is not None and r["file_type"] > 0x1B})
    print(f"file types above 0x1B (never seen in the APK string table): {hexlist(unknown_high)}")
