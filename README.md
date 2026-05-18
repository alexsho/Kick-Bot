# Kick Local Bot

Local Python Kick chat listener with keyword triggers, local Ollama AI response candidates, OAuth-based chat sending, and safety limits.

## What It Does

- Connects to Kick livestream chat through the Pusher websocket.
- Watches one or more configured channels.
- Prints and logs live chat.
- Detects static keyword triggers.
- Sends selected trigger context to local Ollama for AI response candidates.
- Can post through Kick's official `chat:write` API after OAuth setup.
- Defaults to dry-run mode so it does not send messages until explicitly enabled.

## Fast Start From Scratch

Run these first from PowerShell:

```powershell
cd D:\work\Kick_Bot
python --version
python -m pip install -e .
kick-bot
```

The important install command is:

```powershell
python -m pip install -e .
```

That means: use Python to run `pip`, install this current folder, and keep it editable while you are developing.

## Project Layout

```text
config/             local bot configuration
docs/               architecture and command notes
logs/               runtime chat/trigger logs
src/kick_bot/       application source
tokens/             local OAuth token files
tools/              helper scripts
archive/            old pre-package scripts
```

## 1. Requirements

- Windows with Python 3.10+
- A Kick account
- A Kick developer app for OAuth sending
- Ollama for local AI responses
- FFmpeg for speech-to-text stream audio

Check Python:

```powershell
python --version
```

## 2. Install The Project

From the project folder:

```powershell
cd D:\work\Kick_Bot
python -m pip install -e .
```

If that succeeds, you can use the project commands directly from the terminal.

This installs command shortcuts such as:

```powershell
kick-bot
kick-bot-web
kick-bot-config
kick-bot-login
kick-bot-channel-lookup
kick-bot-test-ai
kick-bot-speech
```

You can also use the wrapper scripts without installing:

```powershell
python .\run_bot.py
python .\configure.py --help
```

## 3. Configure A Kick Channel

The main config file is:

```text
config\bot_config.json
```

Each channel needs:

```json
{
  "name": "rampagejackson",
  "chatroom_id": "5512091",
  "enabled": true,
  "send_enabled": false,
  "broadcaster_user_id": 5633492,
  "max_sends_per_run": 1
}
```

To get a `chatroom_id`, open the Kick channel in your browser and inspect:

```text
https://kick.com/api/v2/channels/CHANNEL_NAME/chatroom
```

Use the returned `id` as `chatroom_id`.

You can also let the project do this lookup for you:

```powershell
.\tools\add_kick_channel.ps1 rampagejackson
```

or:

```powershell
python -m kick_bot.add_channel rampagejackson
```

That resolves `chatroom_id` from Kick's web chatroom endpoint and resolves
`broadcaster_user_id` from the official Kick API when your OAuth token is available.
If the chatroom endpoint returns `403`, install the browser-like TLS helper:

```powershell
python -m pip install tls-client
```

## 4. Run Chat Listener In Dry Run

```powershell
cd D:\work\Kick_Bot
python .\run_bot.py
```

or:

```powershell
kick-bot
```

You should see subscription output, then live chat messages.

Dry-run means the bot can print response candidates but cannot post.

## 4b. Run The Browser Dashboard

Start the local control panel:

```powershell
kick-bot-web
```

or:

```powershell
python .\web_dashboard.py
```

Then open:

```text
http://127.0.0.1:8080
```

The dashboard can start/stop the bot, show live chat, edit config, save `.env` values, and test Ollama.
It shows configured channels as cards, so you can click `rampagejackson`, edit its IDs/settings, or add another channel for multi-channel listening.
Use `Lookup & Add` to add a channel by name without manually finding the IDs.
Use `Apply Changes` after edits. `Start` and `Restart` also apply the visible settings before launching the listener.

The dashboard is local HTTP only by default. Do not expose it to the public internet without authentication and HTTPS.

## 4c. Speech-to-Text Stream Audio

The bot can also listen to Kick stream audio and transcribe it locally using faster-whisper. This is separate from typed chat: the stream audio is converted into a `StreamAudio` pseudo-message, then passed through the same keyword trigger, AI response, send limiter, and Kick sender pipeline used by normal chat.

Pipeline:

```text
Kick stream
→ yt-dlp resolves the temporary m3u8 stream URL
→ FFmpeg extracts audio
→ faster-whisper transcribes locally
→ transcript appears as StreamAudio
→ KeywordEngine checks trigger words
→ AI/static response is generated
→ KickChatSender posts if outbound is enabled
```

External requirement:

- FFmpeg must be installed and available on PATH.

Check FFmpeg:

```powershell
ffmpeg -version
```

If Windows cannot find `ffmpeg`, verify the WinGet link path or add the folder containing `ffmpeg.exe` to PATH. A common WinGet path is:

```text
C:\Users\Alexander\AppData\Local\Microsoft\WinGet\Links
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
python -m yt_dlp -g --impersonate "Chrome-110:Windows-10" https://kick.com/larrywheels
```

Run the speech listener manually:

```powershell
python -m kick_bot.speech_listener --channel larrywheels --chunk-seconds 8 --model small --device cpu
```

If installed as an editable package, you can also use:

```powershell
kick-bot-speech --channel larrywheels --chunk-seconds 8 --model small --device cpu
```

CPU-friendly starting settings:

```text
model: small
chunk_seconds: 8 to 10
device: cpu
```

Dashboard-integrated speech events appear in the live feed as:

```text
[speech/channel] StreamAudio: transcript text
[speech-ai] channel topic_ai / trigger: generated response
```

The speech listener loads config at startup. After changing trigger words, enabled channels, response chance, cooldown, or outbound settings, click `Apply Changes`, then `Restart`.

Speech-to-text can mishear livestream audio. Use conservative live-send settings at first:

```json
{
  "response_chance": 0.15,
  "cooldown_seconds": 90,
  "min_seconds_between_sends": 30,
  "max_sends_per_run": 5
}
```

## 5. Install And Test Ollama

Install Ollama for Windows:

```text
https://ollama.com/download/windows
```

If `ollama` is not on PATH, this helper finds the normal Windows install path:

```powershell
.\tools\setup_ollama_model.ps1 llama3.2
```

Manual setup:

```powershell
& "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" --version
& "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" pull llama3.2
```

Test AI:

```powershell
kick-bot-test-ai
kick-bot-speech
```

or:

```powershell
python -m kick_bot.test_ai_response
```

## 6. Enable AI Candidates

This keeps sending disabled, but turns on local AI response candidates:

```powershell
kick-bot-config --preset ai-dry-run --ai-trigger ngannou --ai-trigger netflix --ai-trigger "sold out" --personality hype --response-chance 0.35
kick-bot
```

Expected output when a trigger matches:

```text
[AI RESPONSE CANDIDATE] rampagejackson topic_ai/ngannou: ...
```

Personality options:

```text
casual
hype
analyst
```

## 7. Create A Kick Developer App

Go to:

```text
https://kick.com/settings/developer
```

Create an app with:

```text
Application Name: LocalKickBot
Description: Local testing chatbot for Kick chat
Redirect URL: http://localhost:8421/callback
```

Required scopes:

```text
Read user information
Write to Chat feed
Read channel information
```

Do not paste your client secret into chat or source files.

## 8. Run OAuth Login

PowerShell:

```powershell
cd D:\work\Kick_Bot
.\tools\login_kick_oauth.ps1
```

MobaXterm/Bash:

```bash
cd /drives/d/work/Kick_Bot
chmod +x ./tools/login_kick_oauth.sh
./tools/login_kick_oauth.sh
```

The token is saved locally:

```text
tokens\kick_user_token.json
```

## 9. Look Up Broadcaster User ID

After OAuth with `channel:read` scope:

```powershell
kick-bot-channel-lookup
```

Copy the returned `broadcaster_user_id` into the channel entry in:

```text
config\bot_config.json
```

## 10. One Confirmed Live Send Test

This enables one live send, with manual confirmation:

```powershell
kick-bot-config --channel rampagejackson --broadcaster-user-id 5633492 --preset one-send-live
kick-bot
```

When a trigger matches, the bot asks:

```text
Type 'send' to post to kick.com/rampagejackson: '...':
```

Only typing exactly:

```text
send
```

will post. After one successful send, further sends are blocked for that run.

## 11. Day-To-Day Commands

Run bot:

```powershell
kick-bot
```

Configure AI dry-run:

```powershell
kick-bot-config --preset ai-dry-run --ai-trigger ko --ai-trigger ngannou --personality hype --response-chance 0.25
```

Return to safe no-send mode:

```powershell
kick-bot-config --dry-run true --outbound-enabled false --send-enabled false
```

Test AI:

```powershell
kick-bot-test-ai
kick-bot-speech
```

## What About Webhooks?

You can ignore webhooks for the current bot.

This project currently uses the **Pusher websocket listener**:

```text
kick_bot.listener
```

That is what powers:

```powershell
kick-bot
python .\run_bot.py
```

The optional webhook file is:

```text
src\kick_bot\webhook_listener.py
```

Webhooks are a different official Kick flow where Kick sends events to a public HTTPS server that you control. That can be useful later for official event subscriptions, but it is not needed for the current local chat-reading and AI-response workflow.

## Safety Checklist

Live posting is off unless all of these are true:

- `dry_run` is `false`
- `outbound.enabled` is `true`
- channel `send_enabled` is `true`
- OAuth token exists
- send limit has not been reached
- confirmation prompt is accepted, when enabled

For speech-to-text mode, start with lower response chance and longer cooldown because transcription can be imperfect.

## More Notes

See:

- [docs/architecture.md](docs/architecture.md)
- [docs/commands.md](docs/commands.md)
- [docs/web-dashboard.md](docs/web-dashboard.md)
