# wait-keepalive.ps1 - watch for the keepalive test to resolve, without typos.
#
# The 0006 test: screen off, force-stop, am start (so the UI never resumes), autoconnect
# off. Nothing should connect until KeepAliveReceiver fires, which proves the alarm is
# what rescues the link. This polls until either it fires or the deadline passes.

param(
    [string]$Adb = 'D:\deepseek\toolchain\android-sdk\platform-tools\adb.exe',
    [string]$Package = 'nodomain.freeyourgadget.gadgetbridge',
    [int]$Minutes = 30
)

$ErrorActionPreference = 'Continue'
$base = "/sdcard/Android/data/$Package/files"
$log = "$base/gadgetbridge.log"
$cap = "$base/rri/capture_$(Get-Date -Format yyyyMMdd).csv"

for ($i = 1; $i -le ($Minutes / 2); $i++) {
    Start-Sleep -Seconds 120
    $now = (& $adb shell date +%H:%M:%S 2>&1) -join ''
    $fired = (& $adb shell "grep -c 'KEEPALIVE connecting' $log" 2>&1) -join ''
    $tail = (& $adb shell "tail -1 $cap" 2>&1) -join ''
    $connected = (& $adb shell "grep -c 'Connected to RFCOMM socket' $log" 2>&1) -join ''
    Write-Host ("[{0}] {1}  keepalive_connecting={2}  rfcomm_connects={3}  last_capture={4}" -f
        $i, $now.Trim(), $fired.Trim(), $connected.Trim(), $tail.Trim())
    if ($fired.Trim() -match '^[1-9]') {
        Write-Host "=== KEEPALIVE FIRED ==="
        (& $adb shell "grep -E 'KEEPALIVE|Connected to RFCOMM|Will attempt to connect' $log | tail -8" 2>&1) |
            ForEach-Object { $_ }
        break
    }
}
Write-Host "=== done"
