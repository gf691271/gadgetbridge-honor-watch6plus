#!/usr/bin/env python3
"""Check whether consecutive RRI packets repeat beats.

Input : rri_YYYYMMDD.csv  (epoch_s,rri_ms,sqi), as written by the patched Gadgetbridge.
        All rows of one packet share one epoch_s and keep the beat order.

Why   : protocol-findings.md section 8.1 says a packet arrives about every 4 s and
        carries 14 beats. At 60-100 bpm only 4-7 beats happen in 4 s, so either the
        packets are further apart than 4 s, or each packet repeats beats that the
        previous one already carried. If they repeat, every HRV figure computed from
        the file counts beats twice.

Output: per file, how many packets there are, the median spacing, how much beat time
        one packet carries compared with that spacing, and how many packets begin with
        a run of beats that ends the previous packet (an overlap).

Usage : python check_rri_packets.py data/raw-rri_20261114.csv
"""

import csv
import sys
from pathlib import Path


def load_packets(path: Path):
    """Return [(epoch_s, [rri_ms, ...]), ...] in file order."""
    packets = []
    with path.open(encoding="utf-8") as fh:
        for rec in csv.DictReader(fh):
            try:
                ts = int(rec["epoch_s"])
                rri = int(rec["rri_ms"])
            except (KeyError, ValueError):
                continue
            if packets and packets[-1][0] == ts:
                packets[-1][1].append(rri)
            else:
                packets.append((ts, [rri]))
    return packets


def overlap(prev, cur):
    """Longest k so that the last k beats of prev equal the first k beats of cur."""
    for k in range(min(len(prev), len(cur)), 0, -1):
        if prev[-k:] == cur[:k]:
            return k
    return 0


def median(values):
    values = sorted(values)
    return values[len(values) // 2] if values else 0


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    path = Path(sys.argv[1])
    packets = load_packets(path)
    if len(packets) < 2:
        print("fewer than 2 packets, nothing to compare")
        return 1

    # Only compare neighbours: a long pause between two packets is a gap, not a pair.
    spacing, carried, overlaps = [], [], []
    for (t0, b0), (t1, b1) in zip(packets, packets[1:]):
        dt = t1 - t0
        if dt <= 0 or dt > 60:
            continue
        spacing.append(dt)
        carried.append(sum(b1) / 1000.0)
        # Two equal beats in a row are common, so one matching beat proves nothing.
        k = overlap(b0, b1)
        overlaps.append(k if k >= 3 else 0)

    if not spacing:
        print("no neighbouring packets within 60 s")
        return 1

    beats = sum(len(b) for _, b in packets)
    repeated = sum(overlaps)
    with_overlap = sum(1 for k in overlaps if k)
    med_spacing = median(spacing)
    med_carried = median(carried)

    print(f"file              : {path.name}")
    print(f"packets / beats   : {len(packets)} / {beats}")
    print(f"beats per packet  : median {median([len(b) for _, b in packets])}")
    print(f"packet spacing    : median {med_spacing} s")
    print(f"beat time/packet  : median {med_carried:.1f} s")
    print(f"packets that repeat the end of the previous one (>=3 beats): "
          f"{with_overlap} of {len(overlaps)}  ({repeated} repeated beats)")

    if with_overlap > 0.2 * len(overlaps):
        print("RESULT: OVERLAP - packets repeat beats; deduplicate before any HRV analysis")
        return 3
    if med_carried > 1.5 * med_spacing:
        print("RESULT: SUSPECT - a packet carries much more beat time than the spacing "
              "between packets, but no literal repeat was found; inspect by hand")
        return 4
    print("RESULT: OK - packets do not repeat beats")
    return 0


if __name__ == "__main__":
    sys.exit(main())
