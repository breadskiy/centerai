function Save-CenterAIGitHubCredential {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][pscredential]$Credential
    )

    $parent = Split-Path -Parent $Path
    [IO.Directory]::CreateDirectory($parent) | Out-Null
    $temporary = Join-Path $parent ([guid]::NewGuid().ToString() + '.tmp')
    try {
        Export-Clixml -LiteralPath $temporary -InputObject $Credential
        if ([IO.File]::Exists($Path)) {
            [IO.File]::Replace($temporary, $Path, [NullString]::Value)
        } else {
            [IO.File]::Move($temporary, $Path)
        }
    } finally {
        if ([IO.File]::Exists($temporary)) { [IO.File]::Delete($temporary) }
    }
}

function Initialize-CenterAIGitHub {
    param(
        [Parameter(Mandatory)][int]$Port,
        [switch]$Configure,
        [switch]$Skip,
        [string]$SettingsDirectory = (Join-Path $env:LOCALAPPDATA 'CenterAI')
    )

    if ($Skip -and $Configure) { throw 'Choose either -ConfigureGitHub or -SkipGitHub.' }
    if ($Skip) {
        Remove-Item Env:GITHUB_CLIENT_ID, Env:GITHUB_CLIENT_SECRET -ErrorAction SilentlyContinue
        return
    }
    if (-not $env:GITHUB_OAUTH_CALLBACK_URL) {
        $env:GITHUB_OAUTH_CALLBACK_URL = "http://127.0.0.1:$Port/api/v1/auth/github/callback"
    }
    if (-not $Configure -and ($env:GITHUB_CLIENT_ID -or $env:GITHUB_CLIENT_SECRET)) {
        if (-not $env:GITHUB_CLIENT_ID -or -not $env:GITHUB_CLIENT_SECRET) {
            throw 'Set both GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET.'
        }
        Write-Host 'GitHub OAuth is set for this launch.'
        return
    }

    $settingsPath = Join-Path $SettingsDirectory "github-oauth-$Port.clixml"
    if (-not $Configure -and (Test-Path -LiteralPath $settingsPath)) {
        try {
            $credential = Import-Clixml -LiteralPath $settingsPath
            if ($credential -isnot [pscredential] -or -not $credential.UserName -or -not $credential.Password.Length) {
                throw 'Invalid local credential.'
            }
        } catch {
            throw 'Cannot read the saved GitHub keys. Run Start-CenterAI.bat -ConfigureGitHub.'
        }
    } else {
        Write-Host ''
        if ($Configure) {
            Write-Host 'GitHub OAuth repair. Enter the Client ID and Client Secret from your GitHub OAuth App.'
        } else {
            Write-Host 'GitHub OAuth setup. Press Enter at Client ID to launch without GitHub.'
        }
        Write-Host "Homepage URL: http://127.0.0.1:$Port"
        Write-Host "Authorization callback URL: $env:GITHUB_OAUTH_CALLBACK_URL"
        $clientId = (Read-Host 'GitHub Client ID').Trim()
        if (-not $clientId) {
            if ($Configure) { throw 'A GitHub Client ID is required to configure OAuth.' }
            Remove-Item Env:GITHUB_CLIENT_ID, Env:GITHUB_CLIENT_SECRET -ErrorAction SilentlyContinue
            return
        }
        if ($clientId -notmatch '^[A-Za-z0-9_-]{5,150}$') {
            throw 'Invalid GitHub Client ID.'
        }
        $clientSecret = Read-Host 'GitHub Client Secret' -AsSecureString
        if (-not $clientSecret.Length) { throw 'A GitHub Client Secret is required.' }
        $credential = [pscredential]::new($clientId, $clientSecret)
        try {
            Save-CenterAIGitHubCredential -Path $settingsPath -Credential $credential
            Write-Host "GitHub OAuth saved for your Windows account on port $Port."
        } catch {
            Write-Warning 'Windows could not save the encrypted GitHub keys. They will work only for this launch.'
        }
    }
    $env:GITHUB_CLIENT_ID = $credential.UserName
    $env:GITHUB_CLIENT_SECRET = $credential.GetNetworkCredential().Password
    Write-Host 'GitHub OAuth keys loaded.'
}

function Initialize-CenterAIOllama {
    if ($env:AI_PROVIDER -or $env:AI_BASE_URL -or $env:AI_MODEL -or $env:AI_API_KEY) { return }
    $base = 'http://127.0.0.1:11434'
    $model = 'qwen3:4b'
    try {
        $null = Invoke-RestMethod "$base/api/version" -TimeoutSec 1
    } catch {
        $cli = Join-Path $env:LOCALAPPDATA 'Programs/Ollama/ollama.exe'
        if (-not (Test-Path -LiteralPath $cli)) {
            $command = Get-Command ollama.exe -ErrorAction SilentlyContinue
            if (-not $command) { return }
            $cli = $command.Source
        }
        Start-Process -FilePath $cli -ArgumentList 'serve' -WindowStyle Hidden
        for ($i = 0; $i -lt 15; $i++) {
            try {
                $null = Invoke-RestMethod "$base/api/version" -TimeoutSec 1
                break
            } catch { Start-Sleep -Milliseconds 300 }
        }
    }

    try {
        $models = (Invoke-RestMethod "$base/api/tags" -TimeoutSec 2).models
        if ($model -in @($models.name)) {
            $env:AI_PROVIDER = 'ollama'
            $env:AI_BASE_URL = $base
            $env:AI_MODEL = $model
            Write-Host "Ollama ready: $model"
            return
        }
        Write-Host "Ollama model $model is not downloaded. Using built-in GPU model."
    } catch {
        Write-Host "Ollama not running. Using built-in GPU model."
    }
}
