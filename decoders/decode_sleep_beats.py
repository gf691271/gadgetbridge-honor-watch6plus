#!/usr/bin/env python3
"""Decode the TruSleep blob into per-beat CSV and per-window heart rate."""

import csv
import struct
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

TAG_ACC, TAG_PPG = 1, 2
RAW, COMP, RESTART = 0xAA, 0xBB, 0xFF


def decode_peak(count, buf, i):
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
    return out, i


def decode_amp(count, buf, i):
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
    return out, i


def main():
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "data/sleep_data_full.bin")
    buf = path.read_bytes()

    beats = []   # (epoch_ms, peak, amp)
    acc = []
    i = 0
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
                for p, a in zip(peaks, amps):
                    beats.append((ts * 1000 + p * 10, p, a))
            except Exception:
                pass
        else:
            i += 1

    beats.sort()
    print(f"ACC={len(acc)}  beats={len(beats)}")
    if not beats:
        return

    t0, t1 = beats[0][0], beats[-1][0]
    hrs = (t1 - t0) / 3600000
    print(f"span {datetime.fromtimestamp(t0/1000, tz=timezone.utc).astimezone():%H:%M} -> "
          f"{datetime.fromtimestamp(t1/1000, tz=timezone.utc).astimezone():%H:%M}  ({hrs:.2f} h)")
    print(f"mean HR ≈ {len(beats) / hrs / 60:.1f} bpm")

    # per 10-minute windows
    buckets = defaultdict(list)
    for ms, p, a in beats:
        buckets[ms // 600000].append(ms)
    print(f"\n{'window':14} {'beats':>6} {'HR':>5} {'meanRR':>8}")
    for b in sorted(buckets):
        v = buckets[b]
        if len(v) < 20:
            continue
        span = (v[-1] - v[0]) / 1000
        hr = len(v) / span * 60 if span else 0
        rr = span / (len(v) - 1) * 1000 if len(v) > 1 else 0
        start = datetime.fromtimestamp(b * 600, tz=timezone.utc).astimezone().strftime("%m-%d %H:%M")
        print(f"{start:14} {len(v):>6} {hr:>5.0f} {rr:>7.0f}ms")

    out = Path("data/csv/sleep_beats.csv")
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["epoch_ms", "utc", "peak", "amp"])
        for ms, p, a in beats:
            w.writerow([ms, datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat(), p, a])
    print(f"\nwrote {out} ({len(beats)} beats)")

    acc_out = Path("data/csv/sleep_acc.csv")
    with acc_out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["epoch_s", "utc", "flags"])
        for ts, fl in acc:
            w.writerow([ts, datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(), fl])
    print(f"wrote {acc_out} ({len(acc)} records)")


if __name__ == "__main__":
    main()
