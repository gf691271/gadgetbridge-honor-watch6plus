#!/usr/bin/env python3
"""Which TruSleep value did Gadgetbridge actually send on a given night?

Why: the repo notes say the preference was switched to true on 11-11, but the battery table
in docs/experiments-2026-11-16.md labels 11-12 as "TruSleep off". The two disagree, and the
whole `sleep_data` hypothesis rests on which is right. The device log records every outgoing
0x07/0x16 with its TLV, so the answer is in the logs, not in the notes.

Layout: a SetTruSleepRequest write looks like
    5A xxxx 00 07 16 01 01 <value> ...
so the value is the byte after `0007160101` (0x01 = on, 0x00 = off).

Usage
    python scan-trusleep-sends.py <file-or-dir> [...]
Accepts .log, .log.zip (read in memory) and directories (scanned recursively).
"""
import io
import os
import re
import sys
import zipfile

SEND = re.compile(r"^(\d{2}):(\d{2}):(\d{2})\.\d{3}.*writing to socket:.*?0007160101([0-9a-fA-F]{2})")


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


def scan(path):
    hits = []
    for line in lines_of(path):
        m = SEND.match(line)
        if m:
            hits.append(("%s:%s:%s" % (m.group(1), m.group(2), m.group(3)), m.group(4).lower()))
    return hits


def main():
    targets = []
    for arg in sys.argv[1:]:
        if os.path.isdir(arg):
            for root, _, files in os.walk(arg):
                for f in files:
                    if ".log" in f:
                        targets.append(os.path.join(root, f))
        else:
            targets.append(arg)
    if not targets:
        print(__doc__)
        return 1

    for path in sorted(targets):
        hits = scan(path)
        name = os.path.basename(path)
        if not hits:
            print("%-42s no 0x07/0x16 write found" % name)
            continue
        vals = {}
        for _, v in hits:
            vals[v] = vals.get(v, 0) + 1
        shown = ", ".join("%s x%d (%s)" % ("ON" if v == "01" else "OFF" if v == "00" else v,
                                           n, v) for v, n in sorted(vals.items()))
        print("%-42s %3d sends: %s" % (name, len(hits), shown))
        print("%-42s   first %s, last %s" % ("", hits[0][0], hits[-1][0]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
