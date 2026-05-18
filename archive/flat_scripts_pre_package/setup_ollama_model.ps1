$ErrorActionPreference = "Stop"

Set-Location -LiteralPath $PSScriptRoot

$model = if ($args.Count -gt 0) { $args[0] } else { "llama3.2" }
$ollamaCandidates = @(
    "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe",
    "$env:ProgramFiles\Ollama\ollama.exe",
    "ollama"
)

$ollama = $null
foreach ($candidate in $ollamaCandidates) {
    if ($candidate -eq "ollama") {
        $command = Get-Command ollama -ErrorAction SilentlyContinue
        if ($command) {
            $ollama = $command.Source
            break
        }
    }
    elseif (Test-Path -LiteralPath $candidate) {
        $ollama = $candidate
        break
    }
}

if (-not $ollama) {
    throw "Could not find ollama.exe. Install Ollama from https://ollama.com/download/windows"
}

Write-Host "Using Ollama: $ollama"
& $ollama --version

Write-Host "Pulling model: $model"
& $ollama pull $model

python .\configure_bot.py --ai-model $model --preset ai-dry-run
python .\test_ai_response.py
