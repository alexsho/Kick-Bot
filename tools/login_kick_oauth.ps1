$ErrorActionPreference = "Stop"

Set-Location -LiteralPath (Join-Path $PSScriptRoot "..")

$clientId = Read-Host "Kick Client ID"
$secureSecret = Read-Host "Kick Client Secret" -AsSecureString
$secretPtr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureSecret)

try {
    $clientSecret = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($secretPtr)

    $env:KICK_CLIENT_ID = $clientId
    $env:KICK_CLIENT_SECRET = $clientSecret
    if (-not $env:KICK_REDIRECT_URI) {
        $env:KICK_REDIRECT_URI = "http://localhost:8421/callback"
    }
    if (-not $env:KICK_OAUTH_SCOPES) {
        $env:KICK_OAUTH_SCOPES = "chat:write user:read"
    }

    $srcPath = Join-Path (Get-Location) "src"
    if ($env:PYTHONPATH) {
        $env:PYTHONPATH = "$srcPath;$env:PYTHONPATH"
    }
    else {
        $env:PYTHONPATH = $srcPath
    }

    python -m kick_bot.oauth_login
}
finally {
    if ($secretPtr -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($secretPtr)
    }
    Remove-Item Env:\KICK_CLIENT_SECRET -ErrorAction SilentlyContinue
}
