# ============================================================================
# run.ps1 - Wrapper for build_vdas.py on FTLPDC02
# ============================================================================
# Uses system Python (located via where.exe). Installs requirements if needed.
# Pure ASCII, no Unicode.
# ============================================================================

[CmdletBinding()]
param(
    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$ScriptPath = Join-Path $ProjectRoot "src\build_vdas.py"
$ReqPath = Join-Path $ProjectRoot "requirements.txt"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " PDS Citrix VDA Build - Wrapper" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " Host:       $env:COMPUTERNAME"
Write-Host " User:       $env:USERNAME"
Write-Host " Project:    $ProjectRoot"
Write-Host " Started:    $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Host "============================================================" -ForegroundColor Cyan

# Locate Python
$PythonExe = (where.exe python 2>$null | Select-Object -First 1)
if (-not $PythonExe) {
    Write-Host "ERROR: python not found on PATH. Install Python 3.10+ and retry." -ForegroundColor Red
    Read-Host "Press Enter to close"
    exit 1
}
Write-Host "Python:     $PythonExe"
& $PythonExe --version

# Install requirements
if (-not $SkipInstall) {
    Write-Host "`nInstalling requirements..." -ForegroundColor Yellow
    & $PythonExe -m pip install --upgrade pip --break-system-packages --quiet
    & $PythonExe -m pip install -r $ReqPath --break-system-packages --quiet
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: pip install failed." -ForegroundColor Red
        Read-Host "Press Enter to close"
        exit 1
    }
    Write-Host "Dependencies installed." -ForegroundColor Green
}

# Run main script
Write-Host "`nRunning build_vdas.py..." -ForegroundColor Yellow
Write-Host "============================================================`n" -ForegroundColor Cyan
& $PythonExe $ScriptPath
$ExitCode = $LASTEXITCODE

Write-Host "`n============================================================" -ForegroundColor Cyan
Write-Host " Completed with exit code: $ExitCode"
Write-Host " Finished: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Host "============================================================" -ForegroundColor Cyan

exit $ExitCode
