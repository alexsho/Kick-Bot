param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$Channel,

    [switch]$PrintOnly,
    [switch]$SendEnabled
)

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

$ArgsList = @("-m", "kick_bot.add_channel", $Channel)
if ($PrintOnly) {
    $ArgsList += "--print-only"
}
if ($SendEnabled) {
    $ArgsList += "--send-enabled"
}

python @ArgsList
