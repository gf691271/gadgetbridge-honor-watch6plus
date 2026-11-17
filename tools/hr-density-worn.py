"""Refined density metric: count only hours where the watch was demonstrably being worn.

The plain median (rows per hour with HEART_RATE>0) mixes in hours when the watch sat on the
charger or on a table, which drags the median down and makes the switch look worse or better
than it is. Two exclusions, as the review asked:

  charging hour : battery level rose during the hour
  not worn hour : no heart-rate rows AND no steps AND no sleep-stage rows

A sleep hour legitimately has zero steps, so the stage rows are what keeps it in the sample.

Reports numerator and denominator, e.g. "worn 18 of 24 hours, median 52".
"""
import datetime
import sqlite3
import statistics
import sys
from collections import defaultdict


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "Gadgetbridge.db"
    con = sqlite3.connect("file:%s?mode=ro" % path.replace("\\", "/"), uri=True)
    cur = con.cursor()

    def hourly(sql):
        cur.execute(sql)
        return dict(cur.fetchall())

    hr = hourly("SELECT CAST((TIMESTAMP - TIMESTAMP % 3600)/3600 AS INTEGER) h, COUNT(*) "
                "FROM HUAWEI_ACTIVITY_SAMPLE WHERE SOURCE = 11 AND HEART_RATE > 0 GROUP BY h")
    steps = hourly("SELECT CAST((TIMESTAMP - TIMESTAMP % 3600)/3600 AS INTEGER) h, SUM(STEPS) "
                   "FROM HUAWEI_ACTIVITY_SAMPLE WHERE STEPS > 0 GROUP BY h")
    stages = hourly("SELECT CAST((TIMESTAMP - TIMESTAMP % 3600)/3600 AS INTEGER) h, COUNT(*) "
                    "FROM HUAWEI_ACTIVITY_SAMPLE WHERE RAW_KIND IN (6,7,8) GROUP BY h")
    # battery: level at the end of the hour minus the level at its start
    cur.execute("SELECT TIMESTAMP, LEVEL FROM BATTERY_LEVEL ORDER BY TIMESTAMP")
    rows = cur.fetchall()
    batt = defaultdict(list)
    for ts, level in rows:
        batt[ts // 3600].append(level)
    rising = set()
    ordered = sorted(batt)
    for h in ordered:
        lv = batt[h]
        first, last = lv[0], lv[-1]
        if last > first:
            rising.add(h)
        elif h - 1 in batt and batt[h - 1][-1] < first:
            rising.add(h)

    hours = sorted(set(hr) | set(steps) | set(stages))
    by_day = defaultdict(lambda: {"worn": 0, "all": 0, "hr": []})
    for h in hours:
        d = datetime.datetime.fromtimestamp(h * 3600).strftime("%Y-%m-%d")
        by_day[d]["all"] += 1
        worn = (h not in rising) and (hr.get(h, 0) > 0 or steps.get(h, 0) > 0 or stages.get(h, 0) > 0)
        if worn:
            by_day[d]["worn"] += 1
            by_day[d]["hr"].append(hr.get(h, 0))

    print("date         worn/all hours   median rows/h (worn only)   min  max")
    for d in sorted(by_day):
        v = by_day[d]["hr"]
        med = statistics.median(v) if v else float("nan")
        print("%-12s %5d / %-5d %12.0f %18d %4d"
              % (d, by_day[d]["worn"], by_day[d]["all"], med,
                 min(v) if v else 0, max(v) if v else 0))

    cut = int(datetime.datetime(2026, 11, 13, 17, 0).timestamp())
    phase = int(datetime.datetime(2026, 11, 17, 16, 33).timestamp())
    for label, lo, hi in (("before 11-13 17:00", 0, cut),
                          ("11-13 17:00 .. phase 1", cut, phase),
                          ("phase 1", phase, 1 << 40)):
        vals = []
        for h in hours:
            if not (lo <= h * 3600 < hi):
                continue
            worn = (h not in rising) and (hr.get(h, 0) > 0 or steps.get(h, 0) > 0 or stages.get(h, 0) > 0)
            if worn:
                vals.append(hr.get(h, 0))
        if vals:
            print("%-24s worn %3d hours, median %.0f rows/h"
                  % (label, len(vals), statistics.median(vals)))
        else:
            print("%-24s worn 0 hours" % label)
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
