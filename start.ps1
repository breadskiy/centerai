[CmdletBinding()]
param([int]$Port = 8000)

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$pythonPath = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
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
Write-Host "CenterAI: http://127.0.0.1:$Port"
& $pythonPath -m uvicorn backend.api:app --host 127.0.0.1 --port $Port
exit $LASTEXITCODE
