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
    bad = 0
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
                ts = struct.unpack_from("<i", chunk, 0)[0]
                # The 3 bytes after the timestamp are per-axis accelerometer activity,
                # 0x00 = no activity, 0xff = high (upstream HuaweiTruSleepParser: "the 3rd
                # axis is ignored as it's always high, due to gravity"). Upstream keeps only
                # the first two as a short; we keep all three so movement can be correlated
                # with snores later.
                axes = tuple(chunk[4:7]) if ln >= 7 else (chunk[4], chunk[5], 0)
                acc.append((ts, axes))
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
            except Exception as e:
                # Silent swallowing made bad records vanish from every statistic. Count them
                # and say so; a high number means the framing model is wrong.
                bad += 1
                if bad <= 3:
                    print(f"undecodable PPG record at {i}: {e}")
        else:
            i += 1

    # No sort: the records are already in file order and the peaks inside a record are
    # time offsets. Sorting the tuples reordered beats by timestamp value within a record,
    # which hid exactly the kind of ordering bug this decoder needs to surface.
    if bad:
        print(f"undecodable PPG records: {bad}")
    if beats:
        out_of_order = sum(1 for a, b in zip(beats, beats[1:]) if b[0] < a[0])
        if out_of_order:
            print(f"WARNING: {out_of_order} beats go backwards in time, framing is suspect")
    print(f"ACC={len(acc)}  beats={len(beats)}")
    if acc:
        # The two bytes after the timestamp are NOT three per-axis activity values. Read as a
        # little-endian 16-bit word they are a bitmap: one bit per ~4 s slot (16 x 4 s = the 64 s
        # ACC interval), 1 = movement in that slot. 0xFFFF means the watch was not on the wrist
        # (or was on the charger) for the whole interval, so it is a wear flag, not movement.
        off = sum(1 for a in acc if (a[1][0] << 8 | a[1][1]) == 0xFFFF)
        still = sum(1 for a in acc if (a[1][0] << 8 | a[1][1]) == 0x0000)
        moved = [
            bin((a[1][0] << 8) | a[1][1]).count("1")
            for a in acc
            if (a[1][0] << 8 | a[1][1]) not in (0x0000, 0xFFFF)
        ]
        print("ACC wear flag 0xFFFF (not on the wrist): %d of %d (%.0f%%)"
              % (off, len(acc), 100.0 * off / len(acc)))
        print("ACC all-zero slots (no movement)       : %d of %d (%.0f%%)"
              % (still, len(acc), 100.0 * still / len(acc)))
        if moved:
            print("ACC moving slots in the rest           : mean %.1f of 16"
                  % (sum(moved) / len(moved)))
    if not beats:
        return

    t0, t1 = beats[0][0], beats[-1][0]
    hrs = (t1 - t0) / 3600000
    print(f"span {datetime.fromtimestamp(t0/1000, tz=timezone.utc).astimezone():%H:%M} -> "
          f"{datetime.fromtimestamp(t1/1000, tz=timezone.utc).astimezone():%H:%M}  ({hrs:.2f} h)")
    print("mean HR approx %.1f bpm" % (len(beats) / hrs / 60))

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
