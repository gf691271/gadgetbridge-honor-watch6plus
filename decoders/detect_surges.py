#!/usr/bin/env python3
"""Naive baseline: detect heart-rate surges from the beat series.

A surge = rise of >= RISE_BPM within WIN_S seconds, followed by a fall of
>= FALL_BPM within the next FALL_WIN_S seconds. Reported with time, magnitude
and duration, so it can be compared against published arousal criteria.
"""

import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

src = Path(sys.argv[1] if len(sys.argv) > 1 else "data/csv/sleep_beats.csv")
BIN_S = 10          # resample the RR series into 15s bins
RISE_BPM = 6        # Lachapelle 2022 / Adachi 2003 use >=6 bpm
WIN_S = 60          # rise must happen within this window
FALL_BPM = 3
FALL_WIN_S = 120

rows = []
with src.open(encoding="utf-8") as fh:
    for r in csv.DictReader(fh):
        rows.append((int(r["epoch_ms"]), int(r["peak"]), int(r["amp"])))
rows.sort()

# bin beats -> HR per bin
bins = {}
for ms, _, _ in rows:
    b = ms // (BIN_S * 1000)
    bins.setdefault(b, []).append(ms)

series = []
for b in sorted(bins):
    v = bins[b]
    if len(v) < 3:
        continue
    span = (v[-1] - v[0]) / 1000.0
    if span <= 0:
        continue
    hr = (len(v) - 1) / span * 60
    series.append((b * BIN_S, hr))

print(f"bins: {len(series)}  覆盖 {(series[-1][0]-series[0][0])/3600:.2f} h")

events = []
i = 0
while i < len(series):
    t, hr = series[i]
    peak_t, peak_hr = t, hr
    j = i
    while j + 1 < len(series) and series[j + 1][0] - t <= WIN_S:
        j += 1
        if series[j][1] > peak_hr:
            peak_t, peak_hr = series[j]
    if peak_hr - hr >= RISE_BPM:
        # look for the fall
        k = j
        low_hr = peak_hr
        while k + 1 < len(series) and series[k + 1][0] - peak_t <= FALL_WIN_S:
            k += 1
            low_hr = min(low_hr, series[k][1])
        if peak_hr - low_hr >= FALL_BPM:
            events.append((t, peak_t, hr, peak_hr, low_hr, (peak_t - t)))
            i = k + 1
            continue
    i += 1

print(f"\nsurge events (rise>={RISE_BPM}bpm in {WIN_S}s, then fall>={FALL_BPM}bpm): {len(events)}\n")
print(f"{'start':10} {'peak':10} {'from':>5} {'to':>5} {'drop':>5} {'rise_s':>7}")
for t, pt, hr0, hr1, low, rise in events:
    s = datetime.fromtimestamp(t, tz=timezone.utc).astimezone().strftime("%H:%M:%S")
    p = datetime.fromtimestamp(pt, tz=timezone.utc).astimezone().strftime("%H:%M:%S")
    print(f"{s:10} {p:10} {hr0:5.0f} {hr1:5.0f} {hr1-low:5.0f} {rise:7.0f}")

