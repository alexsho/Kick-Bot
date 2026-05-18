# Commands

## Run Chat Listener

```powershell
python .\run_bot.py
```

After installing the package in editable mode:

```powershell
python -m pip install -e .
kick-bot
```

## Configure AI Dry Run

```powershell
python .\configure.py --preset ai-dry-run --ai-trigger ngannou --ai-trigger netflix --personality hype --response-chance 0.35
```

## One Confirmed Live Send

```powershell
python .\configure.py --channel rampagejackson --broadcaster-user-id 5633492 --preset one-send-live
python .\run_bot.py
```

## Test Ollama AI

```powershell
python -m kick_bot.test_ai_response
```
