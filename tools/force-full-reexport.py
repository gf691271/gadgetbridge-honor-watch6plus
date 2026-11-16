#!/usr/bin/env python3
"""Make the exporter re-send everything since a given day.

Context: the delta export used to look back one hour while the database is filled every six
hours, so roughly six hours of activity rows per day never reached any CSV (fixed in patch
0008, 48 h lookback). Patch 0008 only protects the last 48 hours going forward; the rows
between 11-08 and the fix are still in the database and in no CSV.

This rewinds the delta cursor, triggers one export, and reads the resulting manifest back so
the outcome can be checked instead of assumed. The exporter advances the cursor itself once a
batch completes, so nothing has to be restored afterwards.

Usage
    python force-full-reexport.py --since 2026-11-08 [--dry-run]
"""
import argparse
import base64
import datetime
import json
import os
import re
import subprocess
import sys
import tempfile
import time

ADB = r"D:\deepseek\toolchain\android-sdk\platform-tools\adb.exe"
PKG = "nodomain.freeyourgadget.gadgetbridge"
STATE = "/sdcard/Android/data/%s/files/export_state.txt" % PKG
OUT = "/sdcard/Download/mailuo/gb"


def sh(cmd, t=120):
    return subprocess.run([ADB, "shell", cmd], capture_output=True, text=True, timeout=t).stdout


def attached():
    out = subprocess.run([ADB, "devices"], capture_output=True, text=True, timeout=30).stdout
    return any(line.strip().endswith("device") for line in out.splitlines()[1:])


def read_state():
    return subprocess.run([ADB, "shell", "cat", STATE],
                          capture_output=True, text=True, timeout=60).stdout


def write_state(text):
    """export_state.txt sits in the app's external dir; run-as cannot write there, the adb
    shell user usually can. Try, then verify by reading back."""
    payload = text if text.endswith("\n") else text + "\n"
    b64 = base64.b64encode(payload.encode()).decode()
    sh("echo %s | base64 -d > %s" % (b64, STATE))
    return read_state()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2026-11-08")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--timeout", type=int, default=240)
    args = ap.parse_args()

    if not attached():
        print("no device attached")
        return 1

    target = int(datetime.datetime.strptime(args.since, "%Y-%m-%d").timestamp())
    before = read_state().strip()
    print("cursor before: %r" % before)
    if "last_delta_sec=" not in before:
        print("!! export_state.txt does not contain last_delta_sec, refusing to guess")
        return 1

    new = re.sub(r"last_delta_sec=\d+", "last_delta_sec=%d" % target, before) + "\n"
    print("rewinding last_delta_sec -> %d (%s)" % (target, args.since))

    if args.dry_run:
        print("dry run, nothing written")
        return 0

    after = write_state(new).strip()
    print("cursor after : %r" % after)
    if "last_delta_sec=%d" % target not in after:
        print("!! the write did not take; the exporter will not re-send the old window")
        return 1

    print("triggering the export")
    sh("am broadcast -a nodomain.freeyourgadget.gadgetbridge.command.TRIGGER_DATABASE_EXPORT -p " + PKG)

    deadline = time.time() + args.timeout
    newest = None
    while time.time() < deadline:
        time.sleep(10)
        name = sh("ls -t %s | grep '^manifest-' | head -1" % OUT).strip()
        if name and name != newest:
            newest = name
            print("  manifest:", name)
            break
    if not newest:
        print("no new manifest within %ds" % args.timeout)
        return 1

    local = os.path.join(tempfile.gettempdir(), "reexport-manifest.json")
    subprocess.run([ADB, "pull", "%s/%s" % (OUT, newest), local], capture_output=True)
    data = json.load(open(local, encoding="utf-8"))
    print("\nmanifest schema %s, batch %s" % (data.get("schema"), data.get("batch")))
    print("window %s -> %s" % (
        datetime.datetime.fromtimestamp(data["window_from_epoch_s"]).strftime("%m-%d %H:%M"),
        datetime.datetime.fromtimestamp(data["window_to_epoch_s"]).strftime("%m-%d %H:%M")))
    print("failed tables:", data.get("failed_tables") or "none")
    print("\n%-18s %8s %10s" % ("kind", "rows", "bytes"))
    for f in data.get("files", []):
        print("%-18s %8d %10d" % (f["kind"], f["rows"], f.get("bytes", -1)))
    print("\ncursor now:", read_state().strip())
    return 0


if __name__ == "__main__":
    sys.exit(main())
