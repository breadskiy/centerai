[CmdletBinding()]
param(
    [ValidateRange(1,65535)][int]$Port = 8000,
    [switch]$ConfigureGitHub,
    [switch]$SkipGitHub,
    [switch]$Vulkan
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
try {
    $running = Invoke-RestMethod "$url/openapi.json" -TimeoutSec 2
} catch {
    $running = $null
}
if ($running.info.title -in @('CenTRap Security Workflow', 'CenterAI Security Workflow')) {
    if ($ConfigureGitHub -or $SkipGitHub) {
        throw 'Stop the running CenTRap window with Ctrl+C before changing GitHub settings.'
    }
    if ($Vulkan) {
        throw 'Stop the running CenTRap window with Ctrl+C before selecting Vulkan.'
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
$owners = @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty OwningProcess -Unique)
if ($owners.Count -gt 0) {
    throw "Port $Port is already in use (PID: $($owners -join ', ')). Stop that program or use -Port to select another port."
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
$stackArgs = @('--port', $Port, '--release', $release)
if ($Vulkan) { $stackArgs += '--vulkan' }
& $pythonPath scripts/start_stack.py @stackArgs
exit $LASTEXITCODE
