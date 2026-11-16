#!/usr/bin/env python3
"""Answer two questions about the beat stream that only the log can answer.

Q1  While the stream was silent, was the 15 s "open" request still being written to the
    socket? If yes and nothing came back, the silence is the device's own duty cycle, not
    a lost write. If no, our own scheduler stopped retrying and the gap is our bug.

Q2  Every RRI_LINKSTALE in the log says the link was declared dead. Was it? A pause in
    the beat stream alone is not proof: if other traffic (battery, notification,
    service 0x01/0x07/0x2c) arrived at the same moment, the link was alive and the
    watchdog cut a healthy connection.

Input
    the Gadgetbridge log (one text file) and the rri_YYYYMMDD.csv of the same night.

Usage
    python check_open_requests.py <gadgetbridge.log> <rri_YYYYMMDD.csv>

Clocks: the CSV carries the device's own time stamp (tag 0x01 of each packet), the log
carries the phone's time of day with no date. Both are wall clock at the moment the row
was written, so the two are aligned by matching the first beat packet in each: the offset
derived from that pair is applied to every log time. Midnight rollover inside the log is
detected, because a log that spans two days otherwise looks like time running backwards.
"""

import argparse
import csv
import datetime
import io
import re
import sys

# "writing to socket: 5A0022 00 2C 01 ..." — after 5A + 2-byte length + 1 flag byte come
# serviceId and commandId, so 0x19/0x01 appears as ...00 1901...
WRITE = re.compile(r"^(\d{2}):(\d{2}):(\d{2})\.(\d{3}).*writing to socket: ([0-9A-Fa-f]+)")
RECV = re.compile(r"^(\d{2}):(\d{2}):(\d{2})\.(\d{3}).*Received (\d+) bytes")
BEAT = re.compile(r"^(\d{2}):(\d{2}):(\d{2})\.(\d{3}).*HRRRI_RAW")
LINKSTALE = re.compile(r"^(\d{2}):(\d{2}):(\d{2})\.(\d{3}).*RRI_LINKSTALE(.*)$")

# 0x19/0x01 carries one TLV: tag 01, length 01, value = type (3 = open, 4 = close).
SERVICE_CMD = "001901"
OPEN_TLV = "010103"
CLOSE_TLV = "010104"


def to_seconds(hh, mm, ss):
    return int(hh) * 3600 + int(mm) * 60 + int(ss)


def load_packets(path):
    """One entry per beat packet: the epoch second repeated for every beat of that packet."""
    packets = []
    with io.open(path, encoding="utf-8") as fh:
        for rec in csv.DictReader(fh):
            try:
                ts = int(rec["epoch_s"])
            except (KeyError, ValueError, TypeError):
                continue
            if not packets or packets[-1] != ts:
                packets.append(ts)
    return packets


def scan_log(path):
    """Collect log events as seconds-of-day, with midnight rollover removed."""
    opens, closes, beats, received, stale = [], [], [], [], []
    prev = None
    roll = 0

    def sec_of(m):
        return to_seconds(m.group(1), m.group(2), m.group(3))

    for line in io.open(path, encoding="utf-8", errors="replace"):
        m = WRITE.match(line)
        if m:
            s = sec_of(m)
            if prev is not None and s < prev - 3600:
                roll += 86400
            prev = s
            s += roll
            hexstr = m.group(5)
            if SERVICE_CMD in hexstr:
                if OPEN_TLV in hexstr:
                    opens.append(s)
                elif CLOSE_TLV in hexstr:
                    closes.append(s)
            continue

        m = BEAT.match(line)
        if m:
            beats.append(sec_of(m))
            continue

        m = RECV.match(line)
        if m:
            received.append(sec_of(m))
            continue

        m = LINKSTALE.match(line)
        if m:
            stale.append((sec_of(m), m.group(5).strip()))

    return opens, closes, beats, received, stale


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("log")
    ap.add_argument("csv")
    ap.add_argument("--pause-min", type=int, default=6,
                    help="shortest gap to report as a pause (default 6 s)")
    ap.add_argument("--alive-window", type=int, default=120,
                    help="a LINKSTALE is a false positive if an inbound frame arrived this "
                         "many seconds before it (default 120)")
    args = ap.parse_args()

    packets = load_packets(args.csv)
    if len(packets) < 3:
        print("not enough packets in the CSV")
        return 1
    opens, closes, beats, received, stale = scan_log(args.log)

    # Align the two clocks on the first beat packet.
    if not beats:
        print("no HRRRI_RAW lines in the log: cannot align the clocks")
        return 1
    offset = packets[0] - beats[0]

    def epoch(s):
        return s + offset

    def stamp(e):
        return datetime.datetime.fromtimestamp(e).strftime("%m-%d %H:%M:%S")

    print("CSV   : %d packets, %s -> %s (%.2f h)" % (
        len(packets), stamp(packets[0]), stamp(packets[-1]),
        (packets[-1] - packets[0]) / 3600.0))
    print("log   : %d open, %d close, %d beat frames, %d RX frames, %d LINKSTALE"
          % (len(opens), len(closes), len(beats), len(received), len(stale)))
    print("clock : log -> CSV offset %+d s (from the first beat packet)" % offset)

    # ---- Q1 -------------------------------------------------------------------
    gaps = sorted(((a, b - a) for a, b in zip(packets, packets[1:])
                   if b - a > args.pause_min), key=lambda x: -x[1])
    print("\nQ1  was the open request still being written during the silence?")
    print("%-16s %8s %8s %8s %10s" % ("pause started", "length", "opens", "expect", "verdict"))
    if not gaps:
        print("  (no pause longer than %d s)" % args.pause_min)
    silent_but_open = 0
    for start, gap in gaps[:20]:
        inside = [t for t in opens if start <= epoch(t) <= start + gap]
        expect = max(0, int(gap // 15) - 1)
        if inside:
            verdict = "retried, no data"
            silent_but_open += 1
        elif expect:
            verdict = "NOT retried"
        else:
            verdict = "too short to judge"
        print("%-16s %7ds %8d %8d %10s"
              % (stamp(start), gap, len(inside), expect, verdict))
    print("  -> %d of %d pauses were silent while we kept asking the device to open"
          " (device-side duty cycle, not our bug)" % (silent_but_open, len(gaps[:20])))

    # ---- Q2 -------------------------------------------------------------------
    print("\nQ2  each RRI_LINKSTALE: was the link really dead?")
    if not stale:
        print("  (no RRI_LINKSTALE in this log)")
    # Only traffic BEFORE the event counts: after dropConnection the socket is gone, so a
    # frame that arrives later says nothing about whether the watchdog was right.
    order = sorted(epoch(t) for t in received)
    wrong = 0
    for s, rest in stale:
        e = epoch(s)
        before = [t for t in order if t <= e]
        age = (e - before[-1]) if before else None
        if age is None:
            verdict = "LINK DEAD (no inbound frame at all before it) -> correct"
        elif age <= args.alive_window:
            wrong += 1
            verdict = "LINK ALIVE (%d s since last inbound frame <= %d) -> false positive" % (
                age, args.alive_window)
        else:
            verdict = "LINK DEAD (%d s since last inbound frame) -> correct" % age
        print("  %s  %-58s %s" % (stamp(e), rest[:58], verdict))
    if stale:
        print("  -> %d of %d were false positives" % (wrong, len(stale)))

    # ---- how aggressively we re-open ------------------------------------------
    if opens:
        span = opens[-1] - opens[0]
        print("\nopen requests: %d over %.2f h = one every %.1f s"
              % (len(opens), span / 3600.0, span / (len(opens) - 1) if len(opens) > 1 else 0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
