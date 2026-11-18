<#
.SYNOPSIS
    Native Windows acceptance test for Spotify RAM Optimizer.

.DESCRIPTION
    Verifies the Windows host, the Python environment, source imports, the full
    pytest suite, the source smoke test, the release executable, its SHA-256,
    its version metadata and the packaged smoke test.  Every exit code is
    recorded and a consolidated Markdown report is written.

    This script is intentionally non-destructive:
      * it never writes to the developer's Spotify profile, cache or registry;
      * the pytest suite redirects APPDATA/LOCALAPPDATA to temporary folders and
        mocks the registry;
      * it never elevates, deletes a backup or publishes anything.

    A passing smoke test is NOT a GUI click-through test.  Manual checks
    (navigation, highlighting, dialogs, scaling) are listed in the report as
    NOT AUTOMATED and must be performed by a person.

.PARAMETER Build
    Build a fresh executable with PyInstaller before verifying it.  The
    previously recorded checksum will not match a fresh build; the script
    reports the new hash instead of failing.

.PARAMETER CaptureScreenshots
    Run scripts/capture_screenshots.py after the checks.  Requires an
    interactive desktop session.

.PARAMETER SkipTests
    Skip pytest and the two smoke tests (useful for an artifact-only check).

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\scripts\windows_acceptance.ps1

.EXAMPLE
    .\scripts\windows_acceptance.ps1 -Build -CaptureScreenshots
#>
#Requires -Version 5.1
[CmdletBinding()]
param(
    [switch]$Build,
    [switch]$CaptureScreenshots,
    [switch]$SkipTests,
    [string]$ExpectedSha256 = "16aebc52e23705588f53c6b32439f4cab55fec796a2270c108bf52be9944e67a",
    [string]$ReportPath = "docs\acceptance\windows_acceptance_report.md"
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

$script:Results = New-Object System.Collections.ArrayList
$script:Notes = New-Object System.Collections.ArrayList
$script:StartTime = Get-Date
$script:Executable = Join-Path $RepoRoot "release\SpotifyOptimizer.exe"
$script:BuildPerformed = [bool]$Build

function Add-Result {
    param(
        [Parameter(Mandatory = $true)][string]$Step,
        [Parameter(Mandatory = $true)][ValidateSet("PASS", "FAIL", "WARN", "SKIP", "INFO")][string]$Status,
        [string]$Detail = "",
        [int]$ExitCode = -1
    )
    $null = $script:Results.Add([pscustomobject]@{
        Step     = $Step
        Status   = $Status
        Detail   = $Detail
        ExitCode = $ExitCode
    })
    $line = "[{0}] {1}  {2}" -f $Status, $Step, $Detail
    switch ($Status) {
        "FAIL" { Write-Host $line -ForegroundColor Red }
        "WARN" { Write-Host $line -ForegroundColor Yellow }
        "PASS" { Write-Host $line -ForegroundColor Green }
        default { Write-Host $line -ForegroundColor Gray }
    }
}

function Invoke-Native {
    <#
        Runs a native command, captures merged output and returns the real exit
        code.  $LASTEXITCODE is read immediately so a formatting pipeline cannot
        hide a failure.
    #>
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [string[]]$Arguments = @()
    )
    $output = & $FilePath @Arguments 2>&1 | Out-String
    $code = $LASTEXITCODE
    return [pscustomobject]@{ Output = $output; ExitCode = $code }
}

function Get-ShortOutput {
    param([string]$Text, [int]$Lines = 12)
    if ([string]::IsNullOrWhiteSpace($Text)) { return "(no output)" }
    $trimmed = $Text.Trim() -split "`r?`n"
    if ($trimmed.Count -le $Lines) { return ($trimmed -join "`n") }
    return (($trimmed | Select-Object -Last $Lines) -join "`n")
}

function Quote-ReportCell {
    param([string]$Value)
    if ($null -eq $Value) { return "" }
    return ($Value -replace "`r?`n", " " -replace "\|", "\|").Trim()
}

Write-Host ""
Write-Host "Spotify RAM Optimizer - Windows acceptance test" -ForegroundColor Cyan
Write-Host ("Repository: {0}" -f $RepoRoot)
Write-Host ("Started:    {0:o}" -f $script:StartTime)
Write-Host ""

# ---------------------------------------------------------------------------
# 1. Windows version and architecture
# ---------------------------------------------------------------------------
try {
    if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
        Add-Result -Step "Windows host" -Status "FAIL" -Detail "Not running on Windows."
        throw "This acceptance script must run on a native Windows machine."
    }
    $os = Get-CimInstance -ClassName Win32_OperatingSystem
    $osText = "{0} (build {1})" -f $os.Caption.Trim(), $os.BuildNumber
    $arch = $env:PROCESSOR_ARCHITECTURE
    Add-Result -Step "Windows host" -Status "PASS" -Detail ("{0}; {1}" -f $osText, $arch)
    if ([int]$os.BuildNumber -lt 10240) {
        Add-Result -Step "Minimum Windows build" -Status "FAIL" `
            -Detail ("build {0} is below 10240" -f $os.BuildNumber)
    }
} catch {
    Add-Result -Step "Windows host" -Status "FAIL" -Detail $_.Exception.Message
}

# ---------------------------------------------------------------------------
# 2. Python and dependencies
# ---------------------------------------------------------------------------
$python = $null
try {
    $python = (Get-Command python -ErrorAction Stop).Source
    $version = Invoke-Native -FilePath $python -Arguments @("--version")
    Add-Result -Step "Python available" -Status $(if ($version.ExitCode -eq 0) { "PASS" } else { "FAIL" }) `
        -Detail (Get-ShortOutput $version.Output 1) -ExitCode $version.ExitCode
} catch {
    Add-Result -Step "Python available" -Status "FAIL" -Detail "python is not on PATH."
}

if ($python) {
    $deps = Invoke-Native -FilePath $python -Arguments @(
        "-c",
        "import customtkinter, PIL, psutil, pytest; print('customtkinter', customtkinter.__version__); print('Pillow', PIL.__version__); print('psutil', psutil.__version__); print('pytest', pytest.__version__)"
    )
    Add-Result -Step "Runtime and test dependencies" `
        -Status $(if ($deps.ExitCode -eq 0) { "PASS" } else { "FAIL" }) `
        -Detail (Get-ShortOutput $deps.Output 4) -ExitCode $deps.ExitCode

    # -----------------------------------------------------------------------
    # 3. Application imports
    # -----------------------------------------------------------------------
    $imports = Invoke-Native -FilePath $python -Arguments @(
        "-c",
        "import main, src.gui.app, src.gui.insight_pages, src.gui.navigation, src.gui.workspace_pages, src.gui.system_pages, src.core.engine, src.core.diagnostics, src.core.history; print('imports ok')"
    )
    Add-Result -Step "Application imports" `
        -Status $(if ($imports.ExitCode -eq 0) { "PASS" } else { "FAIL" }) `
        -Detail (Get-ShortOutput $imports.Output 5) -ExitCode $imports.ExitCode
}

# ---------------------------------------------------------------------------
# Optional build (explicit opt-in, never publishes)
# ---------------------------------------------------------------------------
if ($Build) {
    if (-not $python) {
        Add-Result -Step "PyInstaller build" -Status "FAIL" -Detail "Python unavailable."
    } else {
        Write-Host "Building a fresh executable..."
        $build = Invoke-Native -FilePath $python -Arguments @(
            "-m", "PyInstaller", "--clean", "--noconfirm",
            "--distpath", "release", "--workpath", ".release-build",
            "spotify_optimizer.spec"
        )
        Add-Result -Step "PyInstaller build" `
            -Status $(if ($build.ExitCode -eq 0) { "PASS" } else { "FAIL" }) `
            -Detail (Get-ShortOutput $build.Output 8) -ExitCode $build.ExitCode
    }
}

# ---------------------------------------------------------------------------
# 4. Full pytest suite
# ---------------------------------------------------------------------------
if (-not $SkipTests -and $python) {
    Write-Host "Running the full test suite (this takes a few minutes)..."
    $tests = Invoke-Native -FilePath $python -Arguments @("-m", "pytest", "tests", "-q")
    $summary = ($tests.Output -split "`r?`n" | Where-Object {
        $_ -match "passed|failed|error" -and $_ -match "====="
    } | Select-Object -Last 1)
    if (-not $summary) {
        $summary = Get-ShortOutput $tests.Output 6
    }
    Add-Result -Step "pytest tests" `
        -Status $(if ($tests.ExitCode -eq 0) { "PASS" } else { "FAIL" }) `
        -Detail $summary.Trim() -ExitCode $tests.ExitCode

    # -----------------------------------------------------------------------
    # 5. Source smoke test
    # -----------------------------------------------------------------------
    $smoke = Invoke-Native -FilePath $python -Arguments @("main.py", "--smoke-test")
    $smokeLine = ($smoke.Output -split "`r?`n" | Where-Object { $_ -match "SMOKE TEST (PASSED|FAILED)" } |
        Select-Object -Last 1)
    Add-Result -Step "Source smoke test" `
        -Status $(if ($smoke.ExitCode -eq 0) { "PASS" } else { "FAIL" }) `
        -Detail $(if ($smokeLine) { $smokeLine.Trim() } else { (Get-ShortOutput $smoke.Output 6) }) `
        -ExitCode $smoke.ExitCode
}

# ---------------------------------------------------------------------------
# 6-8. Release executable, checksum and version metadata
# ---------------------------------------------------------------------------
if (-not (Test-Path -LiteralPath $script:Executable)) {
    Add-Result -Step "Release executable" -Status "FAIL" -Detail "release\SpotifyOptimizer.exe is missing."
} else {
    $exeItem = Get-Item -LiteralPath $script:Executable
    Add-Result -Step "Release executable" -Status "PASS" `
        -Detail ("{0:N0} bytes, written {1:o}" -f $exeItem.Length, $exeItem.LastWriteTime)

    $hash = (Get-FileHash -LiteralPath $script:Executable -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($script:BuildPerformed) {
        Add-Result -Step "SHA-256" -Status "INFO" `
            -Detail ("fresh build: {0} (previously recorded {1})" -f $hash, $ExpectedSha256)
    } elseif ($hash -eq $ExpectedSha256.ToLowerInvariant()) {
        Add-Result -Step "SHA-256" -Status "PASS" -Detail $hash
    } else {
        Add-Result -Step "SHA-256" -Status "FAIL" `
            -Detail ("expected {0}, got {1}" -f $ExpectedSha256, $hash)
    }

    $versionInfo = $exeItem.VersionInfo
    $versionDetail = "FileVersion={0}; ProductVersion={1}; Company={2}" -f `
        $versionInfo.FileVersion, $versionInfo.ProductVersion, $versionInfo.CompanyName
    if ($versionInfo.FileVersion) {
        Add-Result -Step "Version metadata" -Status "PASS" -Detail $versionDetail
    } else {
        Add-Result -Step "Version metadata" -Status "FAIL" -Detail "No version resource found."
    }

    # -----------------------------------------------------------------------
    # 9. Packaged smoke test
    # -----------------------------------------------------------------------
    if (-not $SkipTests) {
        Write-Host "Running the packaged smoke test..."
        $stdout = Join-Path $env:TEMP ("spotify_optimizer_smoke_{0}.log" -f ([guid]::NewGuid()))
        try {
            $process = Start-Process -FilePath $script:Executable `
                -ArgumentList "--smoke-test" -Wait -PassThru -NoNewWindow `
                -RedirectStandardOutput $stdout
            $packagedCode = $process.ExitCode
            $packagedOutput = ""
            if (Test-Path -LiteralPath $stdout) {
                $packagedOutput = Get-Content -LiteralPath $stdout -Raw
            }
            $packagedLine = ($packagedOutput -split "`r?`n" |
                Where-Object { $_ -match "SMOKE TEST (PASSED|FAILED)" } | Select-Object -Last 1)
            Add-Result -Step "Packaged smoke test" `
                -Status $(if ($packagedCode -eq 0) { "PASS" } else { "FAIL" }) `
                -Detail $(if ($packagedLine) { $packagedLine.Trim() } else { (Get-ShortOutput $packagedOutput 6) }) `
                -ExitCode $packagedCode
        } catch {
            Add-Result -Step "Packaged smoke test" -Status "FAIL" -Detail $_.Exception.Message
        } finally {
            if (Test-Path -LiteralPath $stdout) { Remove-Item -LiteralPath $stdout -Force }
        }
    }
}

# ---------------------------------------------------------------------------
# Optional screenshots (requires an interactive desktop)
# ---------------------------------------------------------------------------
if ($CaptureScreenshots) {
    if (-not $python) {
        Add-Result -Step "Screenshots" -Status "FAIL" -Detail "Python unavailable."
    } else {
        $shots = Invoke-Native -FilePath $python -Arguments @("scripts/capture_screenshots.py")
        Add-Result -Step "Screenshots" `
            -Status $(if ($shots.ExitCode -eq 0) { "PASS" } else { "FAIL" }) `
            -Detail (Get-ShortOutput $shots.Output 8) -ExitCode $shots.ExitCode
    }
}

# ---------------------------------------------------------------------------
# Screenshot inventory (source of truth for the documentation table)
# ---------------------------------------------------------------------------
$shotDir = Join-Path $RepoRoot "docs\screenshots"
$shotCount = 0
if (Test-Path -LiteralPath $shotDir) {
    $shotCount = (Get-ChildItem -LiteralPath $shotDir -Filter *.png -File).Count
}
Add-Result -Step "Screenshot inventory" -Status "INFO" `
    -Detail ("{0} PNG capture(s) in docs\screenshots (12 expected for the current source)" -f $shotCount)

if ($shotCount -lt 12) {
    Add-Result -Step "Screenshot coverage" -Status "WARN" `
        -Detail "Diagnostics and/or Privacy Center have no genuine capture yet."
}

# ---------------------------------------------------------------------------
# 11. Consolidated Markdown report
# ---------------------------------------------------------------------------
$failed = @($script:Results | Where-Object { $_.Status -eq "FAIL" })
$warned = @($script:Results | Where-Object { $_.Status -eq "WARN" })
$overall = if ($failed.Count -eq 0) { "PASS" } else { "FAIL" }

$commit = "unknown"
$dirty = "unknown"
try {
    $commit = (& git rev-parse --short HEAD 2>$null | Out-String).Trim()
    $statusText = (& git status --porcelain 2>$null | Out-String).Trim()
    $dirty = if ([string]::IsNullOrWhiteSpace($statusText)) { "clean" } else { "modified (uncommitted)" }
} catch {
    $script:Notes.Add("Git metadata unavailable: $($_.Exception.Message)") | Out-Null
}

$report = New-Object System.Collections.Generic.List[string]
$report.Add("# Spotify RAM Optimizer - Windows acceptance report")
$report.Add("")
$report.Add("- Generated: {0:o}" -f (Get-Date))
$report.Add("- Host: $env:COMPUTERNAME")
$report.Add("- Windows: $(if ($osText) { $osText } else { 'unknown' }) / $arch")
$report.Add("- Python: $(if ($version) { (Get-ShortOutput $version.Output 1) } else { 'unavailable' })")
$report.Add("- Repository: $RepoRoot")
$report.Add("- Commit: $commit ($dirty)")
$report.Add("- Overall: **$overall**")
$report.Add("- Fresh build performed: $($script:BuildPerformed)")
$report.Add("")
$report.Add("## Results")
$report.Add("")
$report.Add("| Step | Status | Exit code | Detail |")
$report.Add("| --- | --- | --- | --- |")
foreach ($item in $script:Results) {
    $code = if ($item.ExitCode -ge 0) { $item.ExitCode } else { "" }
    $report.Add("| {0} | {1} | {2} | {3} |" -f `
        (Quote-ReportCell $item.Step), $item.Status, $code, (Quote-ReportCell $item.Detail))
}
$report.Add("")
$report.Add("## Not automated by this script")
$report.Add("")
$report.Add("A passing smoke test proves the window opens, all twelve destinations render and the")
$report.Add("thread-safe dispatcher delivers a worker update. It does **not** replace a click-through:")
$report.Add("")
$report.Add("- Navigate all twelve destinations and confirm sidebar highlighting and header text.")
$report.Add("- Open Optimizations, cancel a preview, and confirm no file changed.")
$report.Add("- Run a preview, apply it against a disposable Spotify tree, then restore it.")
$report.Add("- Exercise the restore dialog's component selection and conflict opt-in.")
$report.Add("- Resize to 1366x768, 1920x1080 and 2560x1440 at 100%, 125% and 150% scaling.")
$report.Add("- Confirm Diagnostics findings expand and Privacy Center controls work.")
$report.Add("- Verify clean shutdown (no orphaned python/SpotifyOptimizer processes).")
$report.Add("")
$report.Add("## Safety")
$report.Add("")
$report.Add("No test in this script writes to the developer's Spotify profile, cache or registry.")
$report.Add("The suite redirects APPDATA/LOCALAPPDATA and mocks the registry; real system writes")
$report.Add("must be exercised only against a disposable Windows account or VM.")
if ($script:Notes.Count -gt 0) {
    $report.Add("")
    $report.Add("## Notes")
    $report.Add("")
    foreach ($note in $script:Notes) { $report.Add("- $note") }
}
$report.Add("")

$reportFull = Join-Path $RepoRoot $ReportPath
$reportDir = Split-Path -Parent $reportFull
if ($reportDir -and -not (Test-Path -LiteralPath $reportDir)) {
    New-Item -ItemType Directory -Path $reportDir -Force | Out-Null
}
$report -join "`r`n" | Set-Content -LiteralPath $reportFull -Encoding UTF8

Write-Host ""
Write-Host ("Report written to {0}" -f $reportFull) -ForegroundColor Cyan
Write-Host ("Overall: {0}  ({1} failed, {2} warning(s))" -f $overall, $failed.Count, $warned.Count) `
    -ForegroundColor $(if ($failed.Count -eq 0) { "Green" } else { "Red" })

if ($failed.Count -gt 0) { exit 1 }
exit 0
