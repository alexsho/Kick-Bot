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


## Speech Listener

```powershell
python -m kick_bot.speech_listener --channel CHANNEL_NAME --chunk-seconds 8 --model small --device cpu
```

If installed in editable mode:

```powershell
kick-bot-speech --channel CHANNEL_NAME --chunk-seconds 8 --model small --device cpu
```

## Trigger Suggestions

```powershell
kick-bot-suggest-triggers --channel CHANNEL_NAME
```

## FFmpeg Path Override

If `ffmpeg` is not on PATH, set an explicit executable path before starting the bot:

```powershell
$env:FFMPEG_EXE="C:\path\to\ffmpeg.exe"
kick-bot-web
```
