"""Daily report for the phase-1 experiment (auto heart rate off, everything else frozen).

The metric is the one the review asked for: rows per hour in HUAWEI_ACTIVITY_SAMPLE with
SOURCE=11 and HEART_RATE>0. 60 rows/hour was the median before the switch was flipped on
2026-11-13 17:15; 25-50 afterwards.

Usage: python phase1-daily.py <local-copy-of-Gadgetbridge.db>
Prints one line per day plus the median before/after the change, and the current switch values
read from the phone so the report cannot claim a frozen setting it did not check.
"""
import datetime
import sqlite3
import statistics
import subprocess
import sys

ADB = r"D:\deepseek\toolchain\android-sdk\platform-tools\adb.exe"
PKG = "nodomain.freeyourgadget.gadgetbridge"
DEV = "shared_prefs/devicesettings_00:A3:07:4F:7B:1E.xml"
CUT = int(datetime.datetime(2026, 11, 13, 17, 0).timestamp())
PHASE1 = int(datetime.datetime(2026, 11, 17, 16, 33).timestamp())


def switches():
    out = subprocess.run([ADB, "exec-out", "run-as", PKG, "cat", DEV],
                         capture_output=True, timeout=30).stdout.decode("utf-8", "replace")
    vals = {}
    for key in ("heartrate_automatic_enable", "spo_automatic_enable"):
        marker = 'name="%s" value="' % key
        i = out.find(marker)
        vals[key] = out[i + len(marker):i + len(marker) + 5].split('"')[0] if i >= 0 else "?"
    return vals


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "Gadgetbridge.db"
    con = sqlite3.connect("file:%s?mode=ro" % path.replace("\\", "/"), uri=True)
    cur = con.cursor()
    cur.execute(
        "SELECT CAST((TIMESTAMP - TIMESTAMP % 3600) / 3600 AS INTEGER) AS h, COUNT(*) "
        "FROM HUAWEI_ACTIVITY_SAMPLE WHERE SOURCE = 11 AND HEART_RATE > 0 "
        "GROUP BY h ORDER BY h")
    per_hour = cur.fetchall()

    by_day = {}
    for h, c in per_hour:
        d = datetime.datetime.fromtimestamp(h * 3600).strftime("%Y-%m-%d")
        by_day.setdefault(d, []).append(c)

    sw = switches()
    print("switches now: autoHR=%s  autoSpO2=%s  (phase 1 = autoHR off since 2026-11-17 16:33)"
          % (sw["heartrate_automatic_enable"], sw["spo_automatic_enable"]))
    print()
    print("%-12s %6s %14s %5s %5s" % ("date", "hours", "median rows/h", "min", "max"))
    for d in sorted(by_day):
        v = by_day[d]
        tag = ""
        if d >= "2026-11-18":
            tag = "  <- phase 1"
        print("%-12s %6d %14.0f %5d %5d%s"
              % (d, len(v), statistics.median(v), min(v), max(v), tag))

    before = [c for h, c in per_hour if h * 3600 < CUT]
    after = [c for h, c in per_hour if h * 3600 >= CUT and h * 3600 < PHASE1]
    phase = [c for h, c in per_hour if h * 3600 >= PHASE1]
    print()
    if before:
        print("before 11-13 17:00 : %3d hours, median %.0f rows/h" % (len(before), statistics.median(before)))
    if after:
        print("11-13 17:00 -> phase1: %3d hours, median %.0f rows/h" % (len(after), statistics.median(after)))
    if phase:
        print("phase 1 so far      : %3d hours, median %.0f rows/h  %s"
              % (len(phase), statistics.median(phase),
                 "RECOVERED" if statistics.median(phase) >= 55 else "not yet"))
    else:
        print("phase 1 so far      : no hours yet")
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
