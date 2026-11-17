"""Phase 1 of the reply-19 experiment: turn off exactly one switch.

Spec: heartrate_automatic_enable -> false; everything else frozen
      (spo_automatic_enable stays true, realtime mode stays false, TruSleep stays true,
       sync interval stays 6 h, beat stream stays off).

Prints every value it reads back, so the "frozen" claim is visible rather than asserted.
"""
import base64
import re
import subprocess
import time

ADB = r"D:\deepseek\toolchain\android-sdk\platform-tools\adb.exe"
PKG = "nodomain.freeyourgadget.gadgetbridge"
DEV = "shared_prefs/devicesettings_00:A3:07:4F:7B:1E.xml"
APP = "shared_prefs/nodomain.freeyourgadget.gadgetbridge_preferences.xml"

CHANGE = {"heartrate_automatic_enable": "false"}
FROZEN_DEV = {
    "spo_automatic_enable": "true",
    "pref_huawei_heart_rate_realtime_mode": "false",
    "trusleep": "true",
    "pref_rri_stream_enabled": "false",
    "huawei_sleep_breath": "true",
}
FROZEN_APP_STRING = {"pref_periodic_sync_interval": "6"}


def sh(c, t=90):
    return subprocess.run([ADB, "shell", c], capture_output=True, text=True, timeout=t).stdout


def cat(p):
    return subprocess.run([ADB, "exec-out", "run-as", PKG, "cat", p],
                          capture_output=True, timeout=30).stdout.decode("utf-8", "replace")


def set_bool(path, key, value):
    xml = cat(path)
    pat = r'<boolean name="%s"[^/]*/>' % re.escape(key)
    repl = '<boolean name="%s" value="%s" />' % (key, value)
    xml = re.sub(pat, repl, xml) if re.search(pat, xml) else \
        xml.replace("</map>", "    " + repl + "\n</map>", 1)
    sh("run-as %s sh -c 'echo %s | base64 -d > %s'"
       % (PKG, base64.b64encode(xml.encode()).decode(), path))


sh("am force-stop " + PKG)
time.sleep(2)

for key, value in CHANGE.items():
    set_bool(DEV, key, value)

dev = cat(DEV)
app = cat(APP)

print("== changed ==")
for key, want in CHANGE.items():
    m = re.search(r'<boolean name="%s" value="([^"]*)"' % re.escape(key), dev)
    got = m.group(1) if m else "MISSING"
    print("  %-38s = %-6s %s" % (key, got, "ok" if got == want else "!! want " + want))

print("== frozen (device) ==")
for key, want in FROZEN_DEV.items():
    m = re.search(r'<boolean name="%s" value="([^"]*)"' % re.escape(key), dev)
    got = m.group(1) if m else "MISSING"
    print("  %-38s = %-6s %s" % (key, got, "ok" if got == want else "!! want " + want))

print("== frozen (app) ==")
for key, want in FROZEN_APP_STRING.items():
    m = re.search(r'<string name="%s"[^>]*>([^<]*)</string>' % re.escape(key), app)
    got = m.group(1) if m else "MISSING"
    print("  %-38s = %-6s %s" % (key, got, "ok" if got == want else "!! want " + want))

sh("am start -n %s/.activities.ControlCenterv2" % PKG)
print("\napp started")
