[CmdletBinding()]
param(
    [ValidateRange(1,65535)][int]$Port = 8000,
    [switch]$ConfigureGitHub,
    [switch]$SkipGitHub
)

$ErrorActionPreference = 'Stop'
if ($ConfigureGitHub -and $SkipGitHub) { throw 'Choose either -ConfigureGitHub or -SkipGitHub.' }
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
$url = "http://127.0.0.1:$Port"
$pythonPath = Join-Path (Get-Location) '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    python -m venv .venv
    if ($LASTEXITCODE) { throw 'Python 3.13 is required to create the virtual environment.' }
}
$release = & $pythonPath scripts/start_stack.py --build-id
if ($LASTEXITCODE -or -not $release) { throw 'Could not identify the local CenTRap build.' }
try {
    $running = Invoke-RestMethod "$url/openapi.json" -TimeoutSec 2
} catch {
    $running = $null
}
if ($running.info.title -in @('CenTRap Security Workflow', 'CenterAI Security Workflow')) {
    if ($ConfigureGitHub -or $SkipGitHub) {
        throw 'Stop the running CenTRap window with Ctrl+C before changing GitHub settings.'
    }
    try {
        $current = Invoke-RestMethod "$url/api/v1/build" -TimeoutSec 2
    } catch {
        $current = $null
    }
    if ($current.release -ne $release) {
        throw "A different CenTRap build is listening at $url. Stop it with Ctrl+C in its launch window and run this file again."
    }
    Write-Host "CenTRap is already running the current build at $url"
    Start-Process "$url/?build=$release"
    exit 0
}
. (Join-Path $PSScriptRoot 'local_services.ps1')
Initialize-CenterAIGitHub -Port $Port -Configure:$ConfigureGitHub -Skip:$SkipGitHub
Initialize-CenterAIOllama

& $pythonPath -m pip --version 2>$null | Out-Null
if ($LASTEXITCODE) {
    python -m pip --python $pythonPath install pip
    if ($LASTEXITCODE) { throw 'Could not initialize pip.' }
}
& $pythonPath -m pip install --disable-pip-version-check -r backend/requirements.txt
if ($LASTEXITCODE) { throw 'Backend dependency installation failed.' }
Push-Location frontend
try {
    npm.cmd ci --no-audit --no-fund
    if ($LASTEXITCODE) { throw 'Frontend dependency installation failed.' }
    npm.cmd run build
    if ($LASTEXITCODE) { throw 'Frontend build failed.' }
} finally {
    Pop-Location
}
& $pythonPath scripts/start_stack.py --port $Port --release $release
exit $LASTEXITCODE
