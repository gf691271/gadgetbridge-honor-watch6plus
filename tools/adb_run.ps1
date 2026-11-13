# adb_run.ps1 - 等待设备上线后执行一条 adb 命令（自动重启 adb 服务）
param(
    [Parameter(Mandatory = $true)][string]$AdbArgs,
    [string]$Adb = '',
    [int]$MaxTries = 24
)

if (-not $Adb) {
    $Adb = if ($env:ANDROID_HOME) { Join-Path $env:ANDROID_HOME 'platform-tools\adb.exe' } else { 'adb' }
}

$connected = $false
for ($i = 1; $i -le $MaxTries; $i++) {
    $d = (& $Adb devices 2>&1) -join ' '
    if ($d -match '\tdevice') { $connected = $true; break }
    Start-Process -FilePath $Adb -ArgumentList 'kill-server' -WindowStyle Hidden | Out-Null
    Start-Sleep -Seconds 3
    Start-Process -FilePath $Adb -ArgumentList 'start-server' -WindowStyle Hidden | Out-Null
    Start-Sleep -Seconds 6
}

if (-not $connected) {
    Write-Output 'NO_DEVICE_AFTER_RETRIES'
    exit 1
}

$out = & $Adb @($AdbArgs.Split(' ')) 2>&1
$out
exit $LASTEXITCODE
