"""Set up an experiment night for the HONOR Watch 6 Plus.

  trusleep = true                   -> does the watch record the raw blob only then?
  pref_periodic_sync_interval = 24  -> next PERIODIC_SYNC lands at 08:00, no 02:00 run
  pref_keepalive_connect = true     -> keep the link alive all night
  all research probes off           -> a clean result

Usage: python setup-experiment-night.py [--dry-run]

Note on SharedPreferences XML: a String preference stores its value as the element text
(<string name="k">v</string>), not in a value attribute. Writing value="v" makes the app
read null, which is how this script once left the sync interval empty and the scheduler
silently fell back to its 6 h default.
"""
import base64
import re
import subprocess
import sys

ADB = r"D:\deepseek\toolchain\android-sdk\platform-tools\adb.exe"
PKG = "nodomain.freeyourgadget.gadgetbridge"
APP = "shared_prefs/nodomain.freeyourgadget.gadgetbridge_preferences.xml"
DEV = "shared_prefs/devicesettings_00:A3:07:4F:7B:1E.xml"

APP_SET = {
    "pref_periodic_sync_interval": ("string", "24"),
    "pref_keepalive_connect": ("boolean", "true"),
    "general_autoconnectonbluetooth": ("boolean", "true"),
}
DEV_SET = {
    "trusleep": ("boolean", "true"),
    "pref_research_file_probes": ("boolean", "false"),
    "pref_research_raw_types": ("boolean", "false"),
    "pref_research_dict_sleep": ("boolean", "false"),
    "heartrate_automatic_enable": ("boolean", "true"),
    "spo_automatic_enable": ("boolean", "true"),
    "huawei_sleep_breath": ("boolean", "true"),
}

DRY = "--dry-run" in sys.argv


def sh(cmd, timeout=60):
    return subprocess.run([ADB, "shell", cmd], capture_output=True,
                          text=True, timeout=timeout).stdout


def cat(path):
    return subprocess.run([ADB, "exec-out", "run-as", PKG, "cat", path],
                          capture_output=True, timeout=30).stdout.decode("utf-8", "replace")


def element(kind, key, value):
    """The exact XML SharedPreferences expects for this type."""
    if kind == "string":
        return '<string name="%s">%s</string>' % (key, value)
    return '<%s name="%s" value="%s" />' % (kind, key, value)


def apply(path, settings):
    xml = cat(path)
    if not xml:
        print("!! cannot read", path)
        return None
    for key, (kind, value) in settings.items():
        # any existing element with this name, whatever type it was written as
        pat = re.compile(r'<%s name="%s"\s*/>|<%s name="%s"[^>]*>.*?</%s>'
                         % (kind, re.escape(key), kind, re.escape(key), kind), re.S)
        repl = element(kind, key, value)
        if pat.search(xml):
            xml = pat.sub(repl, xml)
        else:
            # a different type may occupy the name; replace it wholesale
            other = re.compile(r'<(boolean|int|long|float|string) name="%s"\s*/>'
                               r'|<(boolean|int|long|float|string) name="%s"[^>]*>.*?</\2>'
                               % (re.escape(key), re.escape(key)), re.S)
            if other.search(xml):
                xml = other.sub(repl, xml)
            else:
                xml = xml.replace("</map>", "    " + repl + "\n</map>", 1)
    if DRY:
        return xml
    b64 = base64.b64encode(xml.encode("utf-8")).decode("ascii")
    sh("run-as %s sh -c 'echo %s | base64 -d > %s'" % (PKG, b64, path))
    return cat(path)


def show(xml, settings, title):
    print("===", title)
    for key, (kind, want) in settings.items():
        if kind == "string":
            m = re.search(r'<string name="%s"[^>]*>([^<]*)</string>' % re.escape(key), xml or "")
        else:
            m = re.search(r'<boolean name="%s" value="([^"]*)"' % re.escape(key), xml or "")
        got = m.group(1) if m else "MISSING"
        flag = "ok" if got == want else "!! want " + want
        print("  %-32s = %-6s %s" % (key, got, flag))


if not DRY:
    sh("am force-stop " + PKG)
    import time
    time.sleep(2)

dev_xml = apply(DEV, DEV_SET)
app_xml = apply(APP, APP_SET)
show(dev_xml, DEV_SET, "device prefs")
show(app_xml, APP_SET, "app prefs")

if not DRY:
    sh("am start -n %s/.activities.ControlCenterv2" % PKG)
    print("\napp started; verify with:")
    print("  adb shell dumpsys alarm | grep -A3 gadgetbridge.PERIODIC_SYNC | grep origWhen")
