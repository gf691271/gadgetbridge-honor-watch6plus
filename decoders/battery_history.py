#!/usr/bin/env python3
"""Export a battery history CSV from a Gadgetbridge database.

Usage: python battery_history.py <db> [out.csv]
"""

import csv
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

db = sys.argv[1] if len(sys.argv) > 1 else "data/gb_day2b.db"
out = Path(sys.argv[2] if len(sys.argv) > 2 else "data/csv/battery_history.csv")

con = sqlite3.connect(db)
cur = con.cursor()
cols = [r[1] for r in cur.execute("pragma table_info(BATTERY_LEVEL)")]
rows = list(cur.execute('select * from BATTERY_LEVEL order by TIMESTAMP'))

out.parent.mkdir(parents=True, exist_ok=True)
with out.open("w", newline="", encoding="utf-8") as fh:
    w = csv.writer(fh)
    w.writerow(["timestamp_local", "epoch_s", "level"])
    prev = None
    drop = []
    for row in rows:
        rec = dict(zip(cols, row))
        ts = float(rec.get("TIMESTAMP", 0))
        if ts > 1e11:
            ts /= 1000.0
        level = rec.get("LEVEL")
        when = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone()
        w.writerow([when.strftime("%Y-%m-%d %H:%M:%S"), int(ts), level])
        if prev and prev[1] is not None and level is not None and level < prev[1]:
            drop.append((when, prev[1], level))
        prev = (when, level)

print(f"wrote {out} ({len(rows)} rows)")
if rows:
    first = rows[0]
    last = rows[-1]
    def lv(r):
        rec = dict(zip(cols, r))
        return rec.get("LEVEL")
    print(f"range: {lv(first)}% → {lv(last)}%")
    if drop:
        print("drops detected:")
        for when, a, b in drop[-8:]:
            print(f"  {when.strftime('%m-%d %H:%M')}  {a}% → {b}%  (-{a-b})")
