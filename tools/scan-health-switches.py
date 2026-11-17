"""Step 0 of the reply-19 experiment: what did we actually send, and how often did we reconnect?

Scans the rotated logs for the three health-switch commands and counts connections, so the
"density halved at 11-13 17:15" hypothesis can be checked against what really went over the
wire instead of against what the preference said.

  0x07/0x17  EnableAutomaticHeartrate   TLV 01 01 <value>
  0x07/0x1c  EnableRealtimeHeartRate    only sent when pref_huawei_heart_rate_realtime_mode
  0x07/0x24  EnableAutomaticSpo         TLV 01 01 <value>

Also counts `Connected to RFCOMM socket`, because pushHealthSwitches() runs once per connection:
the number of reconnects is the number of times the phone re-imposed its own values.

Usage: python scan-health-switches.py <log-or-zip-or-dir> [...]
"""
import io
import os
import re
import sys
import zipfile
from collections import Counter, defaultdict

SEND = re.compile(r"^(\d{2}):(\d{2}):(\d{2})\.\d{3}.*writing to socket:.*?00(07)(17|1c|24)0101([0-9a-fA-F]{2})")
CONN = re.compile(r"^(\d{2}):(\d{2}):(\d{2})\.\d{3}.*Connected to RFCOMM socket")

NAMES = {"17": "autoHR", "1c": "realtimeHR", "24": "autoSpO2"}


def lines_of(path):
    if path.lower().endswith(".zip"):
        with zipfile.ZipFile(path) as z:
            for name in z.namelist():
                if name.endswith(".log"):
                    with z.open(name) as fh:
                        for line in io.TextIOWrapper(fh, encoding="utf-8", errors="replace"):
                            yield line
        return
    with io.open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            yield line


def main():
    targets = []
    for arg in sys.argv[1:]:
        if os.path.isdir(arg):
            for root, _, files in os.walk(arg):
                for f in sorted(files):
                    if ".log" in f:
                        targets.append(os.path.join(root, f))
        else:
            targets.append(arg)

    grand = Counter()
    for path in sorted(targets):
        sends = defaultdict(list)   # cmd -> [(time, value)]
        conns = []
        for line in lines_of(path):
            m = SEND.match(line)
            if m:
                sends[m.group(5)].append((m.group(1) + ":" + m.group(2), m.group(6).lower()))
                continue
            m = CONN.match(line)
            if m:
                conns.append(m.group(1) + ":" + m.group(2))

        print("=" * 74)
        print(os.path.basename(path))
        print("  reconnects (Connected to RFCOMM socket): %d" % len(conns))
        if not sends:
            print("  no health-switch command sent")
            continue
        for cmd in sorted(sends):
            hits = sends[cmd]
            vals = Counter(v for _, v in hits)
            grand[cmd] += len(hits)
            desc = ", ".join("%s x%d" % (
                "ON" if v == "01" else "OFF" if v == "00" else v, n) for v, n in sorted(vals.items()))
            print("  0x%02X %-11s %3d sends: %s   first %s last %s"
                  % (int(cmd, 16), NAMES.get(cmd, "?"), len(hits), desc,
                     hits[0][0], hits[-1][0]))
    print("=" * 74)
    print("totals:", dict((NAMES.get(k, k), v) for k, v in grand.items()) or "none")
    return 0


if __name__ == "__main__":
    sys.exit(main())
