"""Turn the beat stream off for the TruSleep experiment night, or back on.

fable's point: while the stream is open the optical sensor is being driven for us, and
whether the watch still writes its own raw sleep blob in that state has never been tested.
So tonight the stream is off and TruSleep stays on: one variable.

Also keeps the rest of the experiment configuration in place and verifies it by reading back.
"""
import argparse
import base64
import re
import subprocess
import time

ADB = r"D:\deepseek\toolchain\android-sdk\platform-tools\adb.exe"
PKG = "nodomain.freeyourgadget.gadgetbridge"
PREFS = "shared_prefs/devicesettings_00:A3:07:4F:7B:1E.xml"

ap = argparse.ArgumentParser()
ap.add_argument("state", choices=("off", "on", "show"))
args = ap.parse_args()


def sh(c, t=90):
    return subprocess.run([ADB, "shell", c], capture_output=True, text=True, timeout=t).stdout


def cat():
    return subprocess.run([ADB, "exec-out", "run-as", PKG, "cat", PREFS],
                          capture_output=True, timeout=30).stdout.decode("utf-8", "replace")


def show(xml, title):
    print("===", title)
    for key in ("trusleep", "pref_rri_stream_enabled", "huawei_sleep_breath",
                "heartrate_automatic_enable", "spo_automatic_enable",
                "pref_research_file_probes", "pref_research_raw_types",
                "pref_research_dict_sleep"):
        m = re.search(r'<boolean name="%s" value="([^"]*)"' % re.escape(key), xml or "")
        print("  %-32s = %s" % (key, m.group(1) if m else "(absent)"))


if args.state == "show":
    show(cat(), "current device prefs")
    raise SystemExit(0)

want = "false" if args.state == "off" else "true"
sh("am force-stop " + PKG)
time.sleep(2)
xml = cat()
key = "pref_rri_stream_enabled"
pat = r'<boolean name="%s"[^/]*/>' % re.escape(key)
repl = '<boolean name="%s" value="%s" />' % (key, want)
if re.search(pat, xml):
    xml = re.sub(pat, repl, xml)
else:
    xml = xml.replace("</map>", "    " + repl + "\n</map>", 1)
b64 = base64.b64encode(xml.encode("utf-8")).decode("ascii")
sh("run-as %s sh -c 'echo %s | base64 -d > %s'" % (PKG, b64, PREFS))
show(cat(), "after setting the stream %s" % args.state)
sh("am start -n %s/.activities.ControlCenterv2" % PKG)
print("app started")
