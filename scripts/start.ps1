[CmdletBinding()]
param(
    [ValidateRange(1,65535)][int]$Port = 8000,
    [switch]$ConfigureGitHub,
    [switch]$SkipGitHub
)

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
$url = "http://127.0.0.1:$Port"
try {
    $running = Invoke-RestMethod "$url/openapi.json" -TimeoutSec 2
} catch {
    $running = $null
}
if ($running.info.title -eq 'CenterAI Security Workflow') {
    if ($ConfigureGitHub -or $SkipGitHub) {
        throw 'Stop the running CenterAI window with Ctrl+C before changing GitHub settings.'
    }
    Write-Host "CenterAI is already running at $url"
    try {
        $github = Invoke-RestMethod "$url/api/v1/auth/github/status" -TimeoutSec 2
    } catch {
        $github = $null
    }
    if (-not $github.available) {
        Write-Warning 'This server has no GitHub OAuth configuration. Stop its window with Ctrl+C, then run Start-CenterAI.bat -ConfigureGitHub.'
    }
    Start-Process $url
    exit 0
}
. (Join-Path $PSScriptRoot 'local_services.ps1')
Initialize-CenterAIGitHub -Port $Port -Configure:$ConfigureGitHub -Skip:$SkipGitHub
Initialize-CenterAIOllama

$pythonPath = Join-Path (Get-Location) '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($launcher) {
        & $launcher.Source -3.13 -m venv .venv 2>$null
        if ($LASTEXITCODE -ne 0) {
            & $launcher.Source -3.12 -m venv .venv 2>$null
        }
    } else {
        python -m venv .venv
    }
    if (-not (Test-Path -LiteralPath $pythonPath)) {
        throw 'Python 3.12 or 3.13 is required to create the virtual environment.'
    }
}
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
& $pythonPath scripts/start_stack.py --port $Port
exit $LASTEXITCODE
