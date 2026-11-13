#!/usr/bin/env python3
"""ACAT / Fcv — cyclic variation of heart rate, following Hayano et al. 2020.

Input: data/csv/sleep_beats.csv (per-beat timestamps from the watch's PPG).

Steps (Hayano 2020, Methods):
  1. RR interval series, artefacts removed
  2. smooth with a 20 s window, 2nd-order polynomial
  3. envelopes = 95th / 5th percentile in a 130 s sliding window
  4. valley: width 10-120 s, depth/width > 0.7 ms/s, depth > 40% of envelope range
  5. cycle length between valleys 25-130 s
  6. mean morphological correlation with the +/-2 neighbouring valleys > 0.4
  7. Fcv = qualifying valleys per hour of *valid* recording time
"""

import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

GRID_HZ = 1.0
SMOOTH_WIN_S = 20
ENV_WIN_S = 130
DEPTH_FRAC = 0.40
DEPTH_PER_WIDTH = 0.7
WIDTH_MIN, WIDTH_MAX = 10, 120
CYCLE_MIN, CYCLE_MAX = 25, 130
CORR_MIN = 0.4
GAP_MAX_S = 30          # a pause longer than this is not counted as valid time


def load(path):
    t, rr = [], []
    with path.open(encoding="utf-8") as fh:
        beats = [(int(r["epoch_ms"]) / 1000.0) for r in csv.DictReader(fh)]
    beats.sort()
    for a, b in zip(beats, beats[1:]):
        t.append(b)
        rr.append((b - a) * 1000.0)
    return np.array(t), np.array(rr)


def clean(t, rr):
    keep = (rr >= 400) & (rr <= 1400)
    # reject beats deviating >20% from a local mean (Hayano 2020 filter)
    med = np.array([np.median(rr[max(0, i - 5):i + 6]) for i in range(len(rr))])
    keep &= np.abs(rr - med) <= 0.20 * med
    return t[keep], rr[keep]


def poly_smooth(y, win):
    k = int(win / 2)
    out = np.empty_like(y)
    x = np.arange(-k, k + 1)
    for i in range(len(y)):
        lo, hi = max(0, i - k), min(len(y), i + k + 1)
        xs = np.arange(lo - i, hi - i)
        ys = y[lo:hi]
        if len(xs) < 3:
            out[i] = y[i]
            continue
        c = np.polyfit(xs, ys, 2)
        out[i] = np.polyval(c, 0)
    return out


def rolling_percentile(y, win, q):
    k = int(win / 2)
    out = np.empty_like(y)
    for i in range(len(y)):
        lo, hi = max(0, i - k), min(len(y), i + k + 1)
        out[i] = np.percentile(y[lo:hi], q)
    return out


def main():
    src = Path(sys.argv[1] if len(sys.argv) > 1 else "data/csv/sleep_beats.csv")
    t, rr = load(src)
    t, rr = clean(t, rr)
    print(f"clean beats: {len(rr)}")

    # valid time = sum of intervals, excluding long gaps
    gaps = np.diff(t)
    valid_s = float(np.sum(gaps[gaps <= GAP_MAX_S]))
    print(f"valid recording time: {valid_s/3600:.2f} h  "
          f"(excluded {(np.sum(gaps>GAP_MAX_S))/60:.1f} min of gaps)")

    # regular grid, zero-order hold of RR
    grid = np.arange(t[0], t[-1], 1.0 / GRID_HZ)
    idx = np.searchsorted(t, grid, side="right") - 1
    idx = np.clip(idx, 0, len(rr) - 1)
    y = rr[idx]

    ys = poly_smooth(y, SMOOTH_WIN_S * GRID_HZ)
    hi = rolling_percentile(ys, ENV_WIN_S * GRID_HZ, 95)
    lo = rolling_percentile(ys, ENV_WIN_S * GRID_HZ, 5)
    rng = np.maximum(hi - lo, 1.0)

    # local minima
    valleys = []
    n = len(ys)
    i = 1
    while i < n - 1:
        if ys[i] <= ys[i - 1] and ys[i] < ys[i + 1]:
            depth = hi[i] - ys[i]
            if depth / rng[i] >= DEPTH_FRAC:
                # width: where the curve rises 40% of range above the minimum
                thr = ys[i] + DEPTH_FRAC * rng[i]
                a = i
                while a > 0 and ys[a] < thr:
                    a -= 1
                b = i
                while b < n - 1 and ys[b] < thr:
                    b += 1
                width = (b - a) / GRID_HZ
                if WIDTH_MIN <= width <= WIDTH_MAX:
                    per_width = depth / width
                    if per_width > DEPTH_PER_WIDTH:
                        valleys.append((i, width, depth, per_width))
        i += 1

    print(f"candidate valleys: {len(valleys)}")

    # cycle length filter + morphology
    kept = []
    for k, (i, width, depth, pw) in enumerate(valleys):
        if k == 0 or k == len(valleys) - 1:
            continue
        cyc_prev = (valleys[k][0] - valleys[k - 1][0]) / GRID_HZ
        cyc_next = (valleys[k + 1][0] - valleys[k][0]) / GRID_HZ
        if not (CYCLE_MIN <= cyc_prev <= CYCLE_MAX and CYCLE_MIN <= cyc_next <= CYCLE_MAX):
            continue
        # morphology: correlate a 60 s window around this valley with neighbours
        half = int(30 * GRID_HZ)
        seg = ys[max(0, i - half):min(n, i + half)]
        corrs = []
        for d in (-2, -1, 1, 2):
            j = k + d
            if 0 <= j < len(valleys):
                jj = valleys[j][0]
                seg2 = ys[max(0, jj - half):min(n, jj + half)]
                m = min(len(seg), len(seg2))
                if m > 10:
                    a, b = seg[:m], seg2[:m]
                    if a.std() > 0 and b.std() > 0:
                        corrs.append(float(np.corrcoef(a, b)[0, 1]))
        if corrs and float(np.mean(corrs)) > CORR_MIN:
            kept.append((i, width, depth))

    # Hayano rule (d): three consecutive cycles must be regular,
    # (3-2l1/s)(3-2l2/s)(3-2l3/s) > 0.8 with s = mean(l1,l2,l3)
    regular = []
    for k in range(len(kept) - 3):
        idxs = [kept[k + j][0] for j in range(4)]
        cycles = [(idxs[j + 1] - idxs[j]) / GRID_HZ for j in range(3)]
        s = sum(cycles) / 3.0
        if s <= 0:
            continue
        prod = 1.0
        for c in cycles:
            prod *= (3 - 2 * c / s)
        if prod > 0.8:
            regular.extend(kept[k:k + 3])

    # de-duplicate, keep chronological order
    seen = set()
    kept_final = []
    for item in regular:
        if item[0] not in seen:
            seen.add(item[0])
            kept_final.append(item)
    kept = sorted(kept_final)

    fcv = len(kept) / (valid_s / 3600) if valid_s > 0 else 0
    print(f"\nqualifying CVHR valleys: {len(kept)}")
    print(f"Fcv = {fcv:.1f} /h")

    print(f"\n{'time':8} {'width_s':>8} {'depth_ms':>9}")
    for i, width, depth in kept:
        tt = grid[i]
        print(f"{datetime.fromtimestamp(tt, tz=timezone.utc).astimezone():%H:%M:%S} "
              f"{width:8.0f} {depth:9.1f}")

    print("\nreference (Hayano 2020): cutoff Fcv >= 11/h -> AHI>=15, sens 82%, spec 89%")
    print("interpretation: this is a CVHR burden index, NOT an AHI value.")


if __name__ == "__main__":
    main()
