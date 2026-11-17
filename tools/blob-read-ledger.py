"""Read ledger for the sleep blob: what was fetched when, and what it actually covered.

The review asked for one table with time / length / sha256 / last record time for every read,
because the interesting questions (does reading consume it, does it keep growing) can only be
answered by comparing reads, and that comparison needs the reads written down.

The fetch time is in the dump file name (`sleep_data_<epoch_ms>.bin`); the coverage comes from
the records themselves, so the two are independent facts in the same row.

Usage: python blob-read-ledger.py <dump-dir> [...]
"""
import datetime
import glob
import hashlib
import os
import struct
import sys


def scan(path):
    """First and last ACC/PPG timestamps by a plain tag walk."""
    data = open(path, "rb").read()
    n = len(data)
    acc = []
    ppg = []
    beats = 0
    i = 0
    while i < n:
        tag = data[i]
        if tag == 1 and i + 2 <= n and i + 2 + data[i + 1] <= n:
            if data[i + 1] == 7:
                acc.append(struct.unpack_from("<i", data, i + 2)[0])
            i += 2 + data[i + 1]
            continue
        if tag == 2 and i + 3 <= n:
            ln = struct.unpack_from("<H", data, i + 1)[0]
            if ln and i + 3 + ln <= n:
                ppg.append(struct.unpack_from("<i", data, i + 3)[0])
                beats += data[i + 7]
                i += 3 + ln
                continue
        i += 1
    return acc, ppg, beats


def fmt(t):
    return datetime.datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M:%S")


def main():
    paths = []
    for arg in sys.argv[1:]:
        paths.extend(glob.glob(os.path.join(arg, "sleep_data_*.bin")))
    if not paths:
        print(__doc__)
        return 1
    rows = []
    for p in sorted(paths, key=lambda x: os.path.getsize(x)):
        name = os.path.basename(p)
        try:
            fetch_ms = int(name.rsplit("_", 1)[1].split(".")[0])
        except Exception:
            fetch_ms = 0
        acc, ppg, beats = scan(p)
        sha = hashlib.sha256(open(p, "rb").read()).hexdigest()
        rows.append((fetch_ms, name, os.path.getsize(p), sha, acc, ppg, beats))

    rows.sort(key=lambda r: r[0])
    print("%-19s %10s %-17s %-17s %9s %6s %6s" %
          ("fetched (local)", "bytes", "sha256[:16]", "last PPG record", "last-first", "ACC", "beats"))
    for fetch_ms, name, size, sha, acc, ppg, beats in rows:
        span = (ppg[-1] - ppg[0]) / 3600.0 if ppg else 0
        print("%-19s %10d %-17s %-17s %8.2fh %6d %6d" % (
            datetime.datetime.fromtimestamp(fetch_ms / 1000.0).strftime("%Y-%m-%d %H:%M:%S"),
            size, sha[:16], fmt(ppg[-1]) if ppg else "-", span, len(acc), beats))

    print()
    print("same night, successive reads (the 11-16 -> 17 session):")
    same = [r for r in rows if r[0] // 86400 in
            (datetime.datetime(2026, 11, 17).timestamp() // 86400,)]
    for fetch_ms, name, size, sha, acc, ppg, beats in same:
        print("  %s  %7d B  sha %s  last PPG %s" % (
            datetime.datetime.fromtimestamp(fetch_ms / 1000.0).strftime("%H:%M:%S"),
            size, sha[:16], fmt(ppg[-1])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
