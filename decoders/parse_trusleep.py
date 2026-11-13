#!/usr/bin/env python3
"""Python port of Gadgetbridge's HuaweiTruSleepParser, applied to the HONOR blob.

Format (per upstream):
  loop over bytes: tag=1 (ACC) | tag=2 (PPG); other bytes are padding
  ACC: length(1 byte) then payload -> timestamp(int32 LE) + flags(int16)
  PPG: length(2 bytes LE) then payload -> timestamp(int32 LE) + count(u8)
       + peak array (compressed) + amp array (compressed)
"""

import struct
import sys
from datetime import datetime, timezone
from pathlib import Path

TAG_ACC, TAG_PPG = 1, 2
RAW, COMP, RESTART = 0xAA, 0xBB, 0xFF


def decode_peak(count, buf, i):
    if count == 0:
        raise ValueError("count 0")
    tag = buf[i]; i += 1
    out = []
    if tag == RAW:
        for _ in range(count):
            out.append(struct.unpack_from("<h", buf, i)[0]); i += 2
    elif tag == COMP:
        working = struct.unpack_from("<h", buf, i)[0]; i += 2
        out.append(working); count -= 1
        while count > 0:
            c = buf[i]; i += 1
            if c == RESTART:
                working = struct.unpack_from("<h", buf, i)[0]; i += 2
            else:
                working = (working + c) & 0xFFFF
                if working >= 0x8000:
                    working -= 0x10000
            out.append(working); count -= 1
    else:
        raise ValueError(f"bad peak tag 0x{tag:02X}")
    return out, i


def decode_amp(count, buf, i):
    if count == 0:
        raise ValueError("count 0")
    tag = buf[i]; i += 1
    out = []
    if tag == RAW:
        for _ in range(count):
            out.append(struct.unpack_from("<H", buf, i)[0]); i += 2
    elif tag == COMP:
        offset = struct.unpack_from("<H", buf, i)[0]; i += 2
        working = 0
        while len(out) < count:
            c = buf[i]; i += 1
            if c == RESTART:
                working = struct.unpack_from("<H", buf, i)[0]; i += 2
            else:
                working = (working + c) & 0xFFFF
            out.append((working + offset) & 0xFFFF)
    else:
        raise ValueError(f"bad amp tag 0x{tag:02X}")
    return out, i


def main():
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "data/sleep_data_full.bin")
    buf = path.read_bytes()
    print(f"file {path.name} size={len(buf)}")

    acc, ppg = [], []
    i = 0
    errors = 0
    while i < len(buf):
        tag = buf[i]
        if tag == TAG_ACC:
            i += 1
            if i >= len(buf):
                break
            ln = buf[i]; i += 1
            if i + ln > len(buf):
                break
            chunk = buf[i:i + ln]; i += ln
            if ln >= 6:
                ts, flags = struct.unpack_from("<ih", chunk, 0)
                acc.append((ts, flags))
        elif tag == TAG_PPG:
            i += 1
            if i + 2 > len(buf):
                break
            ln = struct.unpack_from("<H", buf, i)[0]; i += 2
            if ln == 0 or i + ln > len(buf):
                i += 1
                continue
            chunk = buf[i:i + ln]; i += ln
            try:
                ts = struct.unpack_from("<i", chunk, 0)[0]
                count = chunk[4]
                peaks, j = decode_peak(count, chunk, 5)
                amps, j = decode_amp(count, chunk, j)
                ppg.append((ts, peaks, amps))
            except Exception:
                errors += 1
        else:
            i += 1

    print(f"ACC records: {len(acc)}   PPG records: {len(ppg)}   ppg errors: {errors}")
    if acc:
        ts0, ts1 = acc[0][0], acc[-1][0]
        span = (ts1 - ts0) / 3600 if ts1 > ts0 else 0
        print(f"ACC span: {datetime.fromtimestamp(ts0, tz=timezone.utc).astimezone():%m-%d %H:%M}"
              f" -> {datetime.fromtimestamp(ts1, tz=timezone.utc).astimezone():%m-%d %H:%M}  ({span:.1f}h)")
        for ts, fl in acc[:5]:
            print(f"   acc ts={ts} flags=0x{fl:04X}")
    if ppg:
        ts0, ts1 = ppg[0][0], ppg[-1][0]
        total = sum(len(p[1]) for p in ppg)
        print(f"PPG span: {datetime.fromtimestamp(ts0, tz=timezone.utc).astimezone():%m-%d %H:%M}"
              f" -> {datetime.fromtimestamp(ts1, tz=timezone.utc).astimezone():%m-%d %H:%M}  beats={total}")
        ts, peaks, amps = ppg[0]
        print(f"   first ppg ts={ts} peaks={peaks[:8]} amps={amps[:8]}")


if __name__ == "__main__":
    main()
