$ErrorActionPreference = "Stop"

Set-Location -LiteralPath $PSScriptRoot

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

    python .\kick_oauth_login.py
}
finally {
    if ($secretPtr -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($secretPtr)
    }
    Remove-Item Env:\KICK_CLIENT_SECRET -ErrorAction SilentlyContinue
}
