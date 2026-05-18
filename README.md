# Kick Local Bot

A local Python-based Kick chatbot framework with live chat monitoring, keyword triggers, Ollama-powered AI responses, OAuth chat sending, web dashboard controls, and local speech-to-text stream awareness.

## Features

- Connects to Kick livestream chat through the Pusher websocket.
- Watches one or more configured channels.
- Prints and logs live chat locally.
- Detects static keyword triggers.
- Sends selected trigger context to local Ollama for AI response candidates.
- Can post through Kick's official `chat:write` API after OAuth setup.
- Includes a local browser dashboard for configuration and runtime control.
- Supports local speech-to-text from Kick stream audio using FFmpeg, yt-dlp, and faster-whisper.
- Defaults to dry-run / no-send behavior in the example config.

## Project Layout

```text
config/             local configuration examples
docs/               architecture and command notes
src/kick_bot/       application source
src/kick_bot/web/   dashboard UI
tools/              helper scripts
```

Runtime-only local folders are intentionally ignored by Git:

```text
logs/               generated chat/trigger logs
tokens/             OAuth token files
.env                local OAuth client settings
config/bot_config.json
```

## Requirements

- Python 3.10+
- A Kick account
- A Kick developer app, only required for OAuth chat sending
- Ollama, only required for local AI responses
- FFmpeg, only required for speech-to-text stream audio

Check Python:

```powershell
python --version
```

## Installation

Clone the repository:

```powershell
git clone https://github.com/alexsho/Kick-Bot.git
cd Kick-Bot
```

Install in editable mode:

```powershell
python -m pip install -e .
```

This installs command shortcuts such as:

```powershell
kick-bot
kick-bot-web
kick-bot-config
kick-bot-login
kick-bot-channel-lookup
kick-bot-test-ai
kick-bot-speech
kick-bot-suggest-triggers
```

## First-Time Local Setup

Create your local environment file:

```powershell
copy .env.example .env
```

Create your local runtime config:

```powershell
copy config\bot_config.example.json config\bot_config.json
```

On Git Bash or macOS/Linux:

```bash
cp .env.example .env
cp config/bot_config.example.json config/bot_config.json
```

Then edit:

```text
.env
config/bot_config.json
```

Do not commit `.env`, `tokens/`, `logs/`, or `config/bot_config.json`.

## Configure a Kick Channel

The runtime config file is:

```text
config/bot_config.json
```

Each channel entry looks like:

```json
{
  "name": "example_channel",
  "chatroom_id": "",
  "enabled": true,
  "send_enabled": false,
  "broadcaster_user_id": null,
  "max_sends_per_run": 1
}
```

You can add/resolve a channel with:

```powershell
kick-bot-add-channel CHANNEL_NAME
```

or:

```powershell
python -m kick_bot.add_channel CHANNEL_NAME
```

The dashboard also has a **Lookup & Add** button that can add a channel by name.

## Run the Web Dashboard

Start the local dashboard:

```powershell
kick-bot-web
```

or:

```powershell
python -m kick_bot.web_app
```

Then open:

```text
http://127.0.0.1:8080
```

The dashboard can:

- start and stop the bot
- show live chat
- show speech-to-text events
- edit channel settings
- edit AI/trigger settings
- save `.env` values
- test Ollama
- suggest trigger words from recent chat/speech context

The dashboard is local HTTP only by default. Do not expose it to the public internet without authentication and HTTPS.

## Run the Chat Listener

After configuring at least one channel:

```powershell
kick-bot
```

or:

```powershell
python -m kick_bot.listener
```

Dry-run mode means the bot can print response candidates but cannot post.

## Local AI with Ollama

Install Ollama:

```text
https://ollama.com/download
```

Pull a local model:

```powershell
ollama pull llama3.2
```

Test AI:

```powershell
kick-bot-test-ai
```

or:

```powershell
python -m kick_bot.test_ai_response
```

To enable AI candidates while keeping live posting disabled:

```powershell
kick-bot-config --preset ai-dry-run --ai-trigger "game" --ai-trigger "clip" --personality casual --response-chance 0.25
kick-bot
```

Expected output when a trigger matches:

```text
[AI RESPONSE CANDIDATE] channel_name topic_ai/game: ...
```

## OAuth Setup for Live Chat Sending

Live posting requires a Kick developer app and OAuth token.

Create a Kick developer app at:

```text
https://kick.com/settings/developer
```

Use this redirect URL:

```text
http://localhost:8421/callback
```

Required scopes:

```text
chat:write user:read channel:read
```

Add your values to `.env`:

```env
KICK_CLIENT_ID=
KICK_CLIENT_SECRET=
KICK_OAUTH_SCOPES=chat:write user:read channel:read
KICK_REDIRECT_URI=http://localhost:8421/callback
```

Run OAuth login:

```powershell
kick-bot-login
```

or:

```powershell
python -m kick_bot.oauth_login
```

The token is saved locally:

```text
tokens/kick_user_token.json
```

Do not commit `.env` or `tokens/`.

## One Confirmed Live Send Test

A safe first live-send setup should use:

```json
{
  "dry_run": false,
  "outbound": {
    "enabled": true,
    "confirm_before_send": true,
    "max_sends_per_run": 1
  }
}
```

The target channel must also have:

```json
"send_enabled": true
```

When confirmation is enabled, the bot asks in the terminal before posting. Only the exact confirmation input will send.

## Speech-to-Text Stream Audio

The bot can listen to Kick stream audio and transcribe it locally. The transcript becomes a `StreamAudio` pseudo-message, then passes through the same trigger, AI, send-limit, and Kick-sender pipeline as normal chat.

Pipeline:

```text
Kick stream
→ yt-dlp resolves a temporary m3u8 stream URL
→ FFmpeg extracts audio
→ faster-whisper transcribes locally
→ transcript appears as StreamAudio
→ KeywordEngine checks trigger words
→ AI/static response is generated
→ KickChatSender posts if outbound is enabled
```

Install FFmpeg and make sure it is available on PATH:

```powershell
ffmpeg -version
```

Install speech dependencies:

```powershell
python -m pip install faster-whisper "yt-dlp[curl-cffi]" curl-cffi
```

Check yt-dlp browser impersonation support:

```powershell
python -m yt_dlp --list-impersonate-targets
```

Resolve a Kick stream URL manually:

```powershell
python -m yt_dlp -g --impersonate "Chrome-110:Windows-10" https://kick.com/CHANNEL_NAME
```

Run the speech listener manually:

```powershell
kick-bot-speech --channel CHANNEL_NAME --chunk-seconds 8 --model small --device cpu
```

or:

```powershell
python -m kick_bot.speech_listener --channel CHANNEL_NAME --chunk-seconds 8 --model small --device cpu
```

CPU-friendly starting settings:

```text
model: small
chunk_seconds: 8 to 10
device: cpu
```

Dashboard speech events appear as:

```text
[speech/channel] StreamAudio: transcript text
[speech-ai] channel topic_ai / trigger: generated response
```

Speech-to-text can mishear livestream audio. Use conservative live-send settings at first:

```json
{
  "response_chance": 0.15,
  "cooldown_seconds": 90,
  "min_seconds_between_sends": 30,
  "max_sends_per_run": 5
}
```

## Trigger Suggestions

The project can suggest trigger words from recent logged chat/speech context.

Run from the command line:

```powershell
kick-bot-suggest-triggers --channel CHANNEL_NAME
```

or:

```powershell
python -m kick_bot.trigger_suggester --channel CHANNEL_NAME
```

The dashboard can also suggest triggers from recent live events. Review suggestions before applying them.

## Day-to-Day Commands

Run dashboard:

```powershell
kick-bot-web
```

Run bot without dashboard:

```powershell
kick-bot
```

Run speech listener:

```powershell
kick-bot-speech --channel CHANNEL_NAME --chunk-seconds 8 --model small --device cpu
```

Return to safe no-send mode:

```powershell
kick-bot-config --dry-run true --outbound-enabled false --send-enabled false
```

Test AI:

```powershell
kick-bot-test-ai
```

Suggest triggers:

```powershell
kick-bot-suggest-triggers --channel CHANNEL_NAME
```

## Safety Checklist

Live posting is off unless all of these are true:

- `dry_run` is `false`
- `outbound.enabled` is `true`
- channel `send_enabled` is `true`
- OAuth token exists
- send limit has not been reached
- confirmation prompt is accepted, when enabled

Recommended testing values:

```json
{
  "dry_run": true,
  "outbound": {
    "enabled": false,
    "confirm_before_send": true,
    "max_sends_per_run": 1
  }
}
```

For speech-to-text mode, start with lower response chance and longer cooldown because transcription can be imperfect.

## Webhooks

The current local bot uses the Pusher websocket listener for chat monitoring.

The optional webhook listener is:

```text
src/kick_bot/webhook_listener.py
```

Webhooks are a separate official Kick event flow that require a public HTTPS server. They are not required for the local dashboard, chat listener, AI responses, or speech-to-text workflow.

## Public Repo Notes

This repository should include:

```text
README.md
pyproject.toml
requirements.txt
.env.example
config/bot_config.example.json
docs/
src/
tools/
```

This repository should not include:

```text
.env
tokens/
logs/
config/bot_config.json
*.egg-info/
__pycache__/
```

## More Notes

See:

- [docs/architecture.md](docs/architecture.md)
- [docs/commands.md](docs/commands.md)
- [docs/web-dashboard.md](docs/web-dashboard.md)
