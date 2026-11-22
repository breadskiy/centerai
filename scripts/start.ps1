[CmdletBinding()]
param(
    [ValidateRange(1,65535)][int]$Port = 8000,
    [switch]$ConfigureGitHub,
    [switch]$SkipGitHub
)

$ErrorActionPreference = 'Stop'
if ($ConfigureGitHub -and $SkipGitHub) { throw 'Choose either -ConfigureGitHub or -SkipGitHub.' }
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
$mailEnvironment = @('SMTP_HOST', 'SMTP_PORT', 'SMTP_SECURITY', 'SMTP_FROM', 'SMTP_USER', 'SMTP_PASSWORD', 'PUBLIC_URL', 'ALLOWED_HOSTS')
if (Test-Path -LiteralPath '.env' -PathType Leaf) {
    foreach ($line in Get-Content -LiteralPath '.env' -Encoding UTF8) {
        if ($line -match '^\s*([A-Z_][A-Z0-9_]*)\s*=\s*(.*)$' -and $Matches[1] -cin $mailEnvironment) {
            $name, $value = $Matches[1], $Matches[2].Trim()
            if (-not (Test-Path -LiteralPath "Env:$name")) {
                if ($value -match '^"([^"]*)"(?:\s*#.*)?$' -or $value -match "^'([^']*)'(?:\s*#.*)?$") {
                    $value = $Matches[1]
                } else {
                    $value = ($value -replace '\s+#.*$', '').TrimEnd()
                }
                [Environment]::SetEnvironmentVariable($name, $value, 'Process')
            }
        }
    }
}
$url = "http://127.0.0.1:$Port"
$listeners = @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
if ($listeners.Count -gt 0) {
    $owners = @($listeners.OwningProcess | Sort-Object -Unique)
    $ownerList = $owners -join ', '
    $running = $null
    try {
        $running = Invoke-RestMethod "$url/openapi.json" -TimeoutSec 2
    } catch {}
    if ($owners.Count -ne 1 -or $running.info.title -notin @('CenTRap Security Workflow', 'CenterAI Security Workflow')) {
        throw "Port $Port is in use (PID: $ownerList). Close that program and retry."
    }
    $server = Get-CimInstance Win32_Process -Filter "ProcessId=$($owners[0])"
    $commandPattern = "(?:^|\s)-m\s+uvicorn\s+backend\.api:app\s+--host\s+127\.0\.0\.1\s+--port\s+$Port(?:\s|$)"
    if ($server.Name -ne 'python.exe' -or $server.CommandLine -notmatch $commandPattern) {
        throw "Cannot verify the CenTRap process on port $Port (PID: $ownerList). Stop it in its launch window and retry."
    }
    $currentOwners = @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique)
    if ($currentOwners.Count -ne 1 -or $currentOwners[0] -ne $server.ProcessId) {
        throw "The process on port $Port changed during startup. Run this file again."
    }
    Write-Host "Stopping the previous CenTRap server on port $Port (PID: $($server.ProcessId))."
    Stop-Process -Id $server.ProcessId
    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        if (-not (Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)) { break }
        Start-Sleep -Milliseconds 250
    }
    if (Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue) {
        throw "Port $Port did not become free after stopping CenTRap."
    }
}
$pythonPath = Join-Path (Get-Location) '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($launcher) {
        & $launcher.Source -3.13 -m venv .venv
        if ($LASTEXITCODE -or -not (Test-Path -LiteralPath $pythonPath)) {
            & $launcher.Source -3.12 -m venv .venv
        }
    } else {
        python -m venv .venv
    }
    if ($LASTEXITCODE -or -not (Test-Path -LiteralPath $pythonPath)) {
        throw 'Python 3.12 or 3.13 is required to create the virtual environment.'
    }
}
$release = & $pythonPath scripts/start_stack.py --build-id
if ($LASTEXITCODE -or -not $release) { throw 'Could not identify the local CenTRap build.' }
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
