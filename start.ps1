[CmdletBinding()]
param([ValidateRange(1,65535)][int]$Port = 8000, [switch]$OpenBrowser, [switch]$Demo)

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$url = "http://127.0.0.1:$Port"
try {
    $running = Invoke-RestMethod "$url/openapi.json" -TimeoutSec 2
} catch {
    $running = $null
}
if ($running.info.title -eq 'CenterAI Security Workflow') {
    Write-Host "CenterAI is already running at $url"
    if ($OpenBrowser) { Start-Process $url }
    exit 0
}
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
Write-Host "CenterAI: $url (Ctrl+C to stop)"
if ($Demo) {
    $demoArgs = @('scripts/demo_stack.py', '--port', $Port)
    if ($OpenBrowser) { $demoArgs += '--open-browser' }
    & $pythonPath @demoArgs
    exit $LASTEXITCODE
}
if ($OpenBrowser) {
    $browserJob = Start-Job -ArgumentList $url -ScriptBlock {
        param($address)
        for ($attempt = 0; $attempt -lt 60; $attempt++) {
            try {
                $schema = Invoke-RestMethod "$address/openapi.json" -TimeoutSec 2
                if ($schema.info.title -eq 'CenterAI Security Workflow') {
                    Start-Process $address
                    return
                }
            } catch {}
            Start-Sleep -Milliseconds 500
        }
    }
}
try {
    & $pythonPath -m uvicorn backend.api:app --host 127.0.0.1 --port $Port
    $serverExit = $LASTEXITCODE
} finally {
    if ($browserJob) { Remove-Job $browserJob -Force }
}
exit $serverExit
