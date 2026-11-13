# install-gb.ps1 - 在 adb 不稳定的情况下反复尝试安装，直到 lastUpdateTime 变化
param(
    [string]$Apk = '<GB_WORK>\app\build\outputs\apk\mainline\debug\app-mainline-debug.apk',
    [int]$MaxAttempts = 12
)
$ErrorActionPreference = 'Continue'
$adb = if ($env:ANDROID_HOME) { Join-Path $env:ANDROID_HOME 'platform-tools\adb.exe' } else { 'adb' }
$pkg = 'nodomain.freeyourgadget.gadgetbridge'

function Reset-Adb {
    & $adb kill-server 2>&1 | Out-Null
    Start-Sleep -Seconds 2
    Get-Process adb -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
    & $adb start-server 2>&1 | Out-Null
    Start-Sleep -Seconds 4
}

function Wait-Device([int]$TimeoutSec = 40) {
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        $d = (& $adb devices 2>&1) -join ' '
        if ($d -match '\tdevice') { return $true }
        Start-Sleep -Seconds 3
    }
    return $false
}

function Get-UpdateTime {
    $t = (& $adb shell "dumpsys package $pkg | grep lastUpdateTime" 2>&1) -join ' '
    if ($t -match 'lastUpdateTime=([0-9\- :]+)') { return $Matches[1].Trim() }
    return ''
}

$before = ''
if (Wait-Device 20) { $before = Get-UpdateTime }
Write-Output "before: $before"

for ($i = 1; $i -le $MaxAttempts; $i++) {
    Write-Output "=== attempt $i ==="
    if (-not (Wait-Device 30)) { Reset-Adb; continue }

    & $adb push $Apk /data/local/tmp/gb_install.apk 2>&1 | Select-Object -Last 1
    Start-Sleep -Seconds 2

    $out = (& $adb shell "pm install -r -d /data/local/tmp/gb_install.apk" 2>&1) -join ' '
    Write-Output "install: $out"

    Start-Sleep -Seconds 3
    if (-not (Wait-Device 20)) { Reset-Adb; continue }
    $now = Get-UpdateTime
    Write-Output "after: $now"
    if ($now -and $now -ne $before) {
        Write-Output 'INSTALL_OK'
        exit 0
    }
    if ($out -match 'Success') {
        Write-Output 'INSTALL_OK (pm reported Success)'
        exit 0
    }
    Reset-Adb
}

Write-Output 'INSTALL_FAILED'
exit 1


