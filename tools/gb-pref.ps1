# gb-pref.ps1 — read or set a Gadgetbridge preference from adb.
#
# Written because two kinds of preference live in different files and both are needed
# constantly: app-wide flags in nodomain.freeyourgadget.gadgetbridge_preferences.xml and
# per-device research switches in devicesettings_<MAC>.xml. SharedPreferences caches in
# memory, so every write here stops the app first and the caller must start it again.
#
#   .\tools\gb-pref.ps1 -List
#   .\tools\gb-pref.ps1 -Get general_autoconnectonbluetooth
#   .\tools\gb-pref.ps1 -Set general_autoconnectonbluetooth false
#   .\tools\gb-pref.ps1 -Scope device -Get pref_research_file_probes
#   .\tools\gb-pref.ps1 -Scope device -Set pref_keepalive_connect true
#
# Exit codes: 0 ok, 1 adb/device problem, 2 preference not found.

param(
    [ValidateSet('app', 'device')]
    [string]$Scope = 'app',
    [string]$Get,
    [string[]]$Set,          # exactly two elements: key value
    [switch]$List,
    [string]$Serial = '',
    [string]$Adb = 'D:\deepseek\toolchain\android-sdk\platform-tools\adb.exe',
    [string]$Package = 'nodomain.freeyourgadget.gadgetbridge',
    [switch]$NoRestart
)

$ErrorActionPreference = 'Stop'

if (-not (Test-Path $Adb)) { Write-Error "adb not found: $Adb"; exit 1 }
$serialArgs = @()
if ($Serial) { $serialArgs = @('-s', $Serial) }

function Invoke-Adb { param([string[]]$Argv) & $Adb @serialArgs @Argv 2>&1 }

$devices = (Invoke-Adb @('devices')) -join "`n"
if ($devices -notmatch '\sdevice\s*$' -and $devices -notmatch '\sdevice\b[\s\S]*device') {
    Write-Error "no device attached"
    exit 1
}

# Pick the device settings file for this watch.
$prefsDir = (Invoke-Adb @('shell', "run-as $Package ls shared_prefs")) -join "`n"
$fileName = if ($Scope -eq 'app') {
    'nodomain.freeyourgadget.gadgetbridge_preferences.xml'
} else {
    $match = [regex]::Match($prefsDir, 'devicesettings_[0-9A-Fa-f:]+\.xml')
    if (-not $match.Success) { Write-Error "no devicesettings_*.xml found"; exit 1 }
    $match.Value
}
$relPath = "shared_prefs/$fileName"

function Read-Prefs {
    $raw = (Invoke-Adb @('exec-out', 'run-as', $Package, 'cat', $relPath)) -join "`n"
    if (-not $raw) { Write-Error "could not read $relPath"; exit 1 }
    return $raw
}

if ($List) {
    $xml = Read-Prefs
    [regex]::Matches($xml, '<(boolean|string|int|long|float) name="([^"]+)"[^>]*?(?:value="([^"]*)")?') |
        ForEach-Object {
            "{0,-52} = {1}" -f $_.Groups[2].Value, $_.Groups[3].Value
        } | Sort-Object
    exit 0
}

if ($Get) {
    $xml = Read-Prefs
    $m = [regex]::Match($xml, '<[a-z]+ name="' + [regex]::Escape($Get) + '"[^>/]*?(?:value="([^"]*)")?/?>')
    if (-not $m.Success) { Write-Host "(absent: default applies)"; exit 2 }
    Write-Output $m.Groups[1].Value
    exit 0
}

if (-not $Set -or $Set.Count -ne 2) {
    Write-Error 'usage: -Set key value   (e.g. -Set general_autoconnectonbluetooth false)'
    exit 1
}
$key, $value = $Set[0], $Set[1]

# SharedPreferences keeps its values in memory; a write under a live process is lost.
Invoke-Adb @('shell', "am force-stop $Package") | Out-Null
Start-Sleep -Milliseconds 1500

$xml = Read-Prefs
$boolTag = '<boolean name="' + [regex]::Escape($key) + '"[^/]*/>'
if ($xml -match $boolTag) {
    $xml = [regex]::Replace($xml, $boolTag, '<boolean name="' + $key + '" value="' + $value + '" />')
    Write-Output "updated existing key $key"
} else {
    $xml = $xml.Replace('</map>', '    <boolean name="' + $key + '" value="' + $value + '" />' + "`n</map>")
    Write-Output "added key $key"
}

$bytes = [Text.Encoding]::UTF8.GetBytes(($xml -replace "`r`n", "`n"))
$b64 = [Convert]::ToBase64String($bytes)
Invoke-Adb @('shell', "run-as $Package sh -c 'echo $b64 | base64 -d > $relPath'") | Out-Null

$check = Read-Prefs
$m = [regex]::Match($check, '<boolean name="' + [regex]::Escape($key) + '" value="([^"]*)"')
if (-not $m.Success) { Write-Error "write did not take effect"; exit 1 }
Write-Output "$key = $($m.Groups[1].Value)"

if (-not $NoRestart) {
    Invoke-Adb @('shell', "am start -n $Package/.activities.ControlCenterv2") | Out-Null
    Write-Output "app restarted"
}
exit 0
