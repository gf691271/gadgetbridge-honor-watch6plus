# dump_ui.ps1 - 健壮的 uiautomator dump：自动重启 adb、重试、拉取并解析
param(
    [int]$MinY = 0,
    [int]$MaxY = 2420,
    [switch]$Full
)
$ErrorActionPreference = 'Continue'
$adb = if ($env:ANDROID_HOME) { Join-Path $env:ANDROID_HOME 'platform-tools\adb.exe' } else { 'adb' }
$out = '<REPO_ROOT>\capture\_ui.xml'
$remote = '/sdcard/_ui.xml'
$py = '<USER_HOME>\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'

if (Test-Path $out) { Remove-Item $out -Force -ErrorAction SilentlyContinue }

function Ensure-Adb {
    for ($k = 0; $k -lt 3; $k++) {
        $d = (& $adb devices 2>&1) -join ' '
        if ($d -match '\tdevice') { return $true }
        Start-Process -FilePath $adb -ArgumentList 'kill-server' -WindowStyle Hidden | Out-Null
        Start-Sleep -Seconds 2
        Start-Process -FilePath $adb -ArgumentList 'start-server' -WindowStyle Hidden | Out-Null
        Start-Sleep -Seconds 4
    }
    return $false
}

for ($i = 1; $i -le 6; $i++) {
    if (-not (Ensure-Adb)) { Start-Sleep -Seconds 3; continue }
    & $adb shell "uiautomator dump $remote" 2>&1 | Out-Null
    & $adb pull $remote $out 2>&1 | Out-Null
    if ((Test-Path $out) -and ((Get-Item $out).Length -gt 100)) { break }
    Start-Sleep -Seconds 3
}

if (-not (Test-Path $out)) { 'DUMP_FAILED'; exit 1 }

$env:PYTHONIOENCODING = 'utf-8'
if ($Full) {
    & $py '<REPO_ROOT>\tools\ui_nodes.py' $out $MinY $MaxY 2>&1
} else {
    & $py '<REPO_ROOT>\tools\ui_nodes.py' $out $MinY $MaxY 2>&1
}


