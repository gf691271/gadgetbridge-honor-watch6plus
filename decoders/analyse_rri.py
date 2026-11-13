#!/usr/bin/env python3
"""Analyse an RRI (beat-to-beat) CSV and produce HRV metrics per time window.

Input : rri_YYYYMMDD.csv  (epoch_s,rri_ms,sqi)
Output: per-window HR / SDNN / RMSSD / pNN50 and the worst moments.

Usage: python analyse_rri.py data/rri_20261108.csv [window_minutes]
"""

import csv
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


def load(path: Path):
    rows = []
    with path.open(encoding="utf-8") as fh:
        for rec in csv.DictReader(fh):
            try:
                ts = int(rec["epoch_s"])
                rri = int(rec["rri_ms"])
                sqi = int(rec["sqi"])
            except (KeyError, ValueError):
                continue
            if 250 <= rri <= 2500 and sqi > 0:
                rows.append((ts, rri, sqi))
    rows.sort()
    return rows


def fmt(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone().strftime("%m-%d %H:%M")


def main():
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "data/rri_20261108.csv")
    win = int(sys.argv[2]) if len(sys.argv) > 2 else 10

    rows = load(path)
    if not rows:
        print("no valid samples")
        return
    print(f"samples: {len(rows)}   span: {fmt(rows[0][0])} → {fmt(rows[-1][0])}")

    buckets = defaultdict(list)
    for ts, rri, sqi in rows:
        buckets[ts // (win * 60)].append(rri)

    print(f"\n{'window':16} {'beats':>6} {'HR':>6} {'SDNN':>7} {'RMSSD':>7} {'pNN50':>7}")
    worst = []
    for b in sorted(buckets):
        vals = buckets[b]
        if len(vals) < 5:
            continue
        hrs = [60000 / v for v in vals]
        mean_hr = sum(hrs) / len(hrs)
        diffs = [vals[i + 1] - vals[i] for i in range(len(vals) - 1)]
        sdnn = (sum((v - sum(vals) / len(vals)) ** 2 for v in vals) / len(vals)) ** 0.5
        rmssd = (sum(d * d for d in diffs) / len(diffs)) ** 0.5
        pnn50 = 100.0 * sum(1 for d in diffs if abs(d) > 50) / len(diffs)
        start = b * win * 60
        print(f"{fmt(start):16} {len(vals):>6} {mean_hr:>6.0f} {sdnn:>7.1f} {rmssd:>7.1f} {pnn50:>6.1f}%")
        worst.append((rmssd, start, mean_hr))

    if worst:
        worst.sort()
        print("\nlowest RMSSD windows (possible apnoea / deep sleep):")
        for rmssd, start, hr in worst[:3]:
            print(f"  {fmt(start)}  RMSSD={rmssd:.1f}ms  HR={hr:.0f}")


if __name__ == "__main__":
    main()
