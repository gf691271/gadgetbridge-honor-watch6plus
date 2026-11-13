# gb_action.ps1 - 只在确认 GB 在前台时才点击，避免误触其他应用
param(
    [string]$Action = 'sync'    # sync | connect | home
)
$ErrorActionPreference = 'Continue'
$adb = if ($env:ANDROID_HOME) { Join-Path $env:ANDROID_HOME 'platform-tools\adb.exe' } else { 'adb' }
$pkg = 'nodomain.freeyourgadget.gadgetbridge'
$py  = '<USER_HOME>\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
$dump = '<REPO_ROOT>\capture\_gb.xml'

function Get-Top {
    $t = (& $adb shell "dumpsys activity activities | grep topResumedActivity | head -1" 2>&1) -join ' '
    return $t
}

function Ensure-GB {
    for ($k = 0; $k -lt 5; $k++) {
        $t = Get-Top
        if ($t -match 'gadgetbridge') { return $true }
        & $adb shell "am start -n $pkg/.activities.ControlCenterv2" 2>&1 | Out-Null
        Start-Sleep -Seconds 4
    }
    return $false
}

function Dump-Ui {
    for ($k = 0; $k -lt 4; $k++) {
        & $adb shell "uiautomator dump /sdcard/_gb.xml" 2>&1 | Out-Null
        & $adb pull /sdcard/_gb.xml $dump 2>&1 | Out-Null
        if ((Test-Path $dump) -and ((Get-Item $dump).Length -gt 200)) { return $true }
        Start-Sleep -Seconds 2
    }
    return $false
}

if (-not (Ensure-GB)) { 'GB 无法置前，中止'; exit 1 }

# 始终回到设备页
& $adb shell "input tap 900 2348" 2>&1 | Out-Null
Start-Sleep -Seconds 3
if (-not (Dump-Ui)) { 'dump 失败'; exit 1 }

$env:PYTHONIOENCODING = 'utf-8'
$nodes = & $py '<REPO_ROOT>\tools\ui_dump.py' $dump 400 1200 2>&1

$sync = ($nodes | Select-String -Pattern '同步' | Select-Object -First 1)
if ($sync -and $sync -match '\((\d+),(\d+)\)') {
    $x = $matches[1]; $y = $matches[2]
    "点击同步 ($x,$y)"
    & $adb shell "input tap $x $y" 2>&1 | Out-Null
    Start-Sleep -Seconds 45
    'sync_clicked'
} elseif ($nodes -match '未连接') {
    "设备未连接，先点击卡片"
    & $adb shell "input tap 540 425" 2>&1 | Out-Null
    Start-Sleep -Seconds 30
    'connect_clicked'
} else {
    "未找到同步按钮。当前节点:"
    $nodes | Select-Object -First 8
}


