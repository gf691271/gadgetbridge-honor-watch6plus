# build-gb.ps1 - 编译 Gadgetbridge，自动绕过 Windows 权限导致的目录删除失败
param(
    [string]$Project = '<GB_WORK>',
    [string]$AndroidHome = '<TOOLCHAIN>\android-home4',
    [int]$MaxAttempts = 8
)
$ErrorActionPreference = 'Continue'

$g = '<TOOLCHAIN>\gradle-home\wrapper\dists\gradle-9.8.2-bin\8wepis63pzuhrlfaiy04bagwu\gradle-9.8.2\bin\gradle.bat'
$log = '<WORK>\gb-build.log'
$cache = Join-Path (Split-Path $Project) ('gb-cache-' + (Split-Path $Project -Leaf))

$env:JAVA_HOME = '<TOOLCHAIN>\jdk21'
$env:GRADLE_USER_HOME = '<TOOLCHAIN>\gradle-home'
$env:ANDROID_USER_HOME = $AndroidHome
Set-Location $Project

for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
    Get-Process java, javaw -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
    Write-Output "=== attempt $attempt ($Project) ==="
    & $g --project-cache-dir $cache assembleMainlineDebug -x buildGitChangelog --no-daemon --console=plain *> $log
    if ($LASTEXITCODE -eq 0) {
        Write-Output 'BUILD_OK'
        Get-Content $log -Tail 2
        exit 0
    }

    $text = Get-Content $log -Raw
    $target = $null
    if ($text -match "Unable to delete directory '([^']+)'") { $target = $Matches[1] }
    elseif ($text -match 'AccessDeniedException: ([^\r\n]+)') { $target = Split-Path $Matches[1].Trim() -Parent }
    elseif ($text -match 'Could not update timestamp for ([^\r\n]+)') { $target = Split-Path $Matches[1].Trim() -Parent }

    if ($target) {
        Write-Output "blocked: $target"
        cmd /c "rd /s /q `"$target`"" 2>&1 | Out-Null
        Write-Output "removed: $(-not (Test-Path $target))"
        continue
    }

    Write-Output 'unrecognised failure'
    $i = (Select-String -Path $log -Pattern 'What went wrong' | Select-Object -First 1).LineNumber
    if ($i) { Get-Content $log | Select-Object -Skip ($i-1) -First 6 }
    exit 1
}

Write-Output 'BUILD_GAVE_UP'
exit 1

