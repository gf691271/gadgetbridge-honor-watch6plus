#!/usr/bin/env python3
"""Check the framing of a TruSleep sleep_data.bin without any second data source.

Why this exists: the beat decoder only proves `count` (how many beats a record claims),
not that the peaks were decoded in the right order or that record boundaries are right.
`ts`, `count` and a wrong decoder still produce "2-3 万拍 / mean HR 72", so neither of
those numbers validates anything. This script checks the blob against itself:

C1  every byte between records is 0x00            (no data mistaken for padding)
C2  each PPG record is consumed exactly           (boundary + compression grammar)
C3  peaks rise inside a record, both delta signs  (decides signed vs unsigned)
C4  ACC timestamps rise with a stable step        (timestamp field, byte order)
C5  a PPG record does not start before the previous one ended
C6  share of beat intervals inside 300-2000 ms    (physiology, reference only)

Usage: python check_trusleep_framing.py sleep_data.bin

Reading the result:

    C1 = 0, C2 = 100 %, C3 unsigned ~100 % and signed clearly lower
        framing and grammar are right, the delta is unsigned, the Python decoder is
        correct about beat timing -> add the C2 assertion to decode_sleep_beats.py
    C2 = 100 %, C3 signed ~100 % and unsigned lower
        upstream Java is right and the Python port is wrong -> every RR series computed
        so far has to be recomputed
    C2 well below 100 % with many "short"
        bytes at the end of a record are not explained -> paste 3 hex records
    C2 well below 100 % with "over"/"undecodable"
        compression grammar does not match this firmware -> do not use the blob for HRV
    C1 large
        a record tag other than 1 or 2 exists -> paste the most common skipped byte
"""

import struct
import sys

RAW, COMP, RESTART = 0xAA, 0xBB, 0xFF


def peaks(buf, i, count, signed):
    """Decode `count` peak values starting at buf[i]. Returns (values, next index)."""
    tag = buf[i]
    i += 1
    out = []
    if tag == RAW:
        for _ in range(count):
            out.append(struct.unpack_from("<h", buf, i)[0])
            i += 2
    elif tag == COMP:
        cur = struct.unpack_from("<h", buf, i)[0]
        i += 2
        out.append(cur)
        while len(out) < count:
            c = buf[i]
            i += 1
            if c == RESTART:
                cur = struct.unpack_from("<h", buf, i)[0]
                i += 2
            else:
                cur += c - 256 if (signed and c >= 0x80) else c
            out.append(cur)
    else:
        raise ValueError("peak tag 0x%02X" % tag)
    return out, i


def skip_amps(buf, i, count):
    """Walk over `count` amp values. Only the byte count matters here."""
    tag = buf[i]
    i += 1
    if tag == RAW:
        return i + 2 * count
    if tag != COMP:
        raise ValueError("amp tag 0x%02X" % tag)
    i += 2
    for _ in range(count):
        c = buf[i]
        i += 1
        if c == RESTART:
            i += 2
    return i


def main():
    buf = open(sys.argv[1], "rb").read()
    i = n_acc = n_ppg = junk = 0
    exact = short = over = failed = 0
    zero_pad = 0
    mono_u = mono_s = beats = 0
    acc_ts, ppg_ts, rr = [], [], []
    overrun = 0
    while i < len(buf):
        tag = buf[i]
        if tag == 1 and i + 2 <= len(buf) and i + 2 + buf[i + 1] <= len(buf):
            ln = buf[i + 1]
            if ln >= 6:
                acc_ts.append(struct.unpack_from("<i", buf, i + 2)[0])
            n_acc += 1
            i += 2 + ln
        elif tag == 2 and i + 3 <= len(buf):
            ln = struct.unpack_from("<H", buf, i + 1)[0]
            rec = buf[i + 3:i + 3 + ln]
            if ln < 6 or len(rec) < ln:
                junk += 1
                i += 1
                continue
            n_ppg += 1
            ts, count = struct.unpack_from("<i", rec, 0)[0], rec[4]
            try:
                pu, j = peaks(rec, 5, count, signed=False)
                ps, _ = peaks(rec, 5, count, signed=True)
                j = skip_amps(rec, j, count)
            except (ValueError, IndexError, struct.error):
                failed += 1
                i += 3 + ln
                continue
            if j == ln:
                exact += 1
            elif j == ln - 1 and rec[j] == 0:
                # Measured on a real 11-09 blob: all 596 records end with exactly one 0x00
                # byte that the two streams do not explain. Treating it as a terminator makes
                # the framing exact; counting it as "short" made C2 look like a failure.
                exact += 1
                zero_pad += 1
            elif j < ln:
                short += 1
            else:
                over += 1
            mono_u += all(b > a for a, b in zip(pu, pu[1:]))
            mono_s += all(b > a for a, b in zip(ps, ps[1:]))
            beats += count
            rr += [(b - a) * 10 for a, b in zip(pu, pu[1:])]
            if ppg_ts and pu and ts * 1000 + pu[0] * 10 < ppg_ts[-1][1]:
                overrun += 1
            ppg_ts.append((ts, ts * 1000 + (pu[-1] * 10 if pu else 0)))
            i += 3 + ln
        else:
            junk += tag != 0
            i += 1

    def pct(a, b):
        return "%d of %d (%.1f%%)" % (a, b, 100.0 * a / b if b else 0)

    acc_step = sorted(b - a for a, b in zip(acc_ts, acc_ts[1:]))
    ok_rr = sum(300 <= x <= 2000 for x in rr)
    print("bytes %d  ACC %d  PPG %d  beats %d" % (len(buf), n_acc, n_ppg, beats))
    print("C1 non-zero bytes between records : %d" % junk)
    print("C2 PPG records consumed exactly   : %s   short %d  over %d  undecodable %d"
          % (pct(exact, n_ppg), short, over, failed))
    print("C2b of those ending in one 0x00   : %d" % zero_pad)
    print("C3 peaks rising, delta unsigned   : %s" % pct(mono_u, n_ppg))
    print("C3 peaks rising, delta signed     : %s" % pct(mono_s, n_ppg))
    print("C4 ACC timestamps rising          : %s   median step %s s"
          % (pct(sum(x > 0 for x in acc_step), len(acc_step)),
             acc_step[len(acc_step) // 2] if acc_step else "-"))
    print("C5 PPG record starts before previous record ended: %d" % overrun)
    print("C6 beat intervals in 300-2000 ms  : %s" % pct(ok_rr, len(rr)))


if __name__ == "__main__":
    main()
