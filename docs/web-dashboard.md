# Web Dashboard

The local dashboard runs at:

```text
http://127.0.0.1:8080
```

Start it with:

```powershell
kick-bot-web
```

or:

```powershell
python .\web_dashboard.py
```

## Current Features

- Start and stop the bot listener
- View live chat in the browser
- View AI/static trigger candidates
- See every configured channel as a card
- Click a channel to edit its friendly fields and selected-channel JSON
- Add additional channels for multi-channel listening
- Use `Lookup & Add` to resolve `chatroom_id` and `broadcaster_user_id` from a channel name
- Apply unsaved dashboard changes before starting or restarting the bot
- Edit the full `config/bot_config.json` from Advanced JSON
- Save Kick OAuth app settings into `.env`
- Test local Ollama responses

When the bot starts, it subscribes to every channel in `config/bot_config.json`
where `enabled` is true. If you add or change channels while the bot is running,
use Restart so the listener reloads the saved config.

The lookup uses:

```text
https://kick.com/api/v2/channels/CHANNEL_NAME/chatroom
```

for `chatroom_id`, and the official Kick API for `broadcaster_user_id`.
If the chatroom endpoint gets blocked with `403`, install:

```powershell
python -m pip install tls-client
```

## Secrets

Secrets are saved in:

```text
.env
```

The `.env` file is ignored by git. Keep it local.

## Notes

This first dashboard runs on local HTTP. That is fine for local-only use on `127.0.0.1`.
Do not expose it to the public internet without adding authentication and HTTPS.
