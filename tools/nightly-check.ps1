# nightly-check.ps1 — 每晚数据采集的自动验收
#
# 用途：不依赖人眼，跑一遍就知道昨晚的数据是否完整。
# 判定项与 docs/reproduction.md 的五步验收一致。
#
# 用法：
#   tools\nightly-check.ps1                  # 检查最近一晚
#   tools\nightly-check.ps1 -Verbose         # 附上原始匹配行

param(
    [switch]$Verbose
)

$ErrorActionPreference = 'Continue'
$adb = if ($env:ANDROID_HOME) { Join-Path $env:ANDROID_HOME 'platform-tools\adb.exe' } else { 'adb' }
$pkg = 'nodomain.freeyourgadget.gadgetbridge'
$log = Join-Path $env:TEMP 'gb-nightly.log'

function Fail($msg) { Write-Output "  [FAIL] $msg"; return 1 }
function Pass($msg) { Write-Output "  [ OK ] $msg"; return 0 }

# --- 连接 ---------------------------------------------------------------
$connected = $false
for ($i = 1; $i -le 20; $i++) {
    $d = (& $adb devices 2>&1) -join ' '
    if ($d -match '\tdevice') { $connected = $true; break }
    Start-Process -FilePath $adb -ArgumentList 'kill-server' -WindowStyle Hidden | Out-Null
    Start-Sleep -Seconds 2
    Start-Process -FilePath $adb -ArgumentList 'start-server' -WindowStyle Hidden | Out-Null
    Start-Sleep -Seconds 3
}
if (-not $connected) { Write-Output 'NO_DEVICE'; exit 1 }

$fails = 0
Write-Output "=== nightly check $(Get-Date -Format 'yyyy-MM-dd HH:mm') ==="

# --- 1. 认证 ------------------------------------------------------------
& $adb pull "/sdcard/Android/data/$pkg/files/gadgetbridge.log" $log 2>&1 | Out-Null
if (-not (Test-Path $log)) {
    $fails += Fail 'cannot read gadgetbridge.log'
} else {
    $auth = Select-String -Path $log -Pattern 'mutual auth OK' | Select-Object -Last 1
    if ($auth) { $fails += Pass 'authenticated' } else { $fails += Fail 'no mutual auth in log' }

    # --- 2. 同步完成 ----------------------------------------------------
    $busy = (Select-String -Path $log -Pattern 'Ignoring fetch activity data' | Measure-Object).Count
    $done = Select-String -Path $log -Pattern 'sync complete' | Select-Object -Last 1
    if ($done -and $busy -eq 0) { $fails += Pass 'sync completed, no ignored fetches' }
    elseif ($done)               { $fails += Fail "sync completed but $busy fetch(es) were ignored as busy" }
    else                         { $fails += Fail 'no sync completion in log' }

    # --- 3. 睡眠文件非 0 ------------------------------------------------
    $sd = Select-String -Path $log -Pattern 'FILEDL_INIT name=sleep_data' | Select-Object -Last 1
    if ($sd -and $sd.Line -match 'size=(\d+)') {
        $n = [int]$matches[1]
        if ($n -gt 60000) { $fails += Pass "sleep_data size=$n" }
        elseif ($n -eq 0) { $fails += Fail 'sleep_data size=0 (check trusleep is false)' }
        else              { $fails += Fail "sleep_data size=$n (expected >60000)" }
    } else { $fails += Fail 'no sleep_data download in log' }

    # --- 4. 逐拍归档 ----------------------------------------------------
    $dumps = (& $adb shell "ls -t /sdcard/Android/data/$pkg/files/dump/ 2>/dev/null | head -1" 2>&1) -join ''
    if ($dumps -match 'sleep_data_\d+\.bin') {
        $size = (& $adb shell "stat -c %s /sdcard/Android/data/$pkg/files/dump/$($dumps.Trim())" 2>&1) -join ''
        if ([int]$size -gt 60000) { $fails += Pass "archived $($dumps.Trim()) = $size bytes" }
        else { $fails += Fail "newest dump is only $size bytes" }
    } else { $fails += Fail 'no sleep_data dump file' }

    # --- 5. RRI ----------------------------------------------------------
    $rri = (& $adb shell "wc -l /sdcard/Android/data/$pkg/files/rri/rri_$(Get-Date -Format 'yyyyMMdd').csv 2>/dev/null" 2>&1) -join ''
    if ($rri -match '(\d+)') {
        $lines = [int]$matches[1]
        if ($lines -gt 100) { $fails += Pass "RRI rows=$lines" }
        else { $fails += Fail "RRI rows=$lines (stream may not be running)" }
    } else { $fails += Fail 'no RRI csv for today' }

    if ($Verbose) {
        Write-Output '--- last sleep_data entries ---'
        Select-String -Path $log -Pattern 'FILEDL_INIT name=sleep' | Select-Object -Last 4 | ForEach-Object { '   ' + $_.Line.Trim() }
        Write-Output '--- watchdog / health ---'
        Select-String -Path $log -Pattern 'HEALTHSW|BUSY_WATCHDOG' | Select-Object -Last 6 | ForEach-Object { '   ' + $_.Line.Trim() }
    }
}

Write-Output ''
if ($fails -eq 0) { Write-Output 'RESULT: PASS'; exit 0 } else { Write-Output "RESULT: $fails check(s) failed"; exit 1 }
