[CmdletBinding()]
param([ValidateRange(1,65535)][int]$Port = 8000)

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
$url = "http://127.0.0.1:$Port"
try {
    $running = Invoke-RestMethod "$url/openapi.json" -TimeoutSec 2
} catch {
    $running = $null
}
if ($running.info.title -in @('CenTRap Security Workflow', 'CenterAI Security Workflow')) {
    Write-Host "CenTRap is already running at $url"
    Start-Process $url
    exit 0
}
$pythonPath = Join-Path (Get-Location) '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    python -m venv .venv
    if ($LASTEXITCODE) { throw 'Python 3.13 is required to create the virtual environment.' }
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
