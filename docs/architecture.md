# Architecture

## Runtime Flow

1. `kick_bot.listener` connects to Kick's Pusher websocket.
2. It subscribes to every enabled channel from `config/bot_config.json`.
3. Incoming chat is printed and logged to `logs/chat.jsonl`.
4. The keyword engine checks enabled trigger rules.
5. Static rules choose a configured response.
6. AI rules send recent chat context to local Ollama and produce a response candidate.
7. Outbound sending remains gated by `dry_run`, `outbound.enabled`, per-channel `send_enabled`, confirmation, and send limits.

## Important Paths

- `src/kick_bot/`: application source
- `config/bot_config.json`: local bot configuration
- `tokens/`: local OAuth tokens
- `logs/`: chat and trigger logs
- `tools/`: setup/login helper scripts
- `docs/`: project notes

## Current Safety Defaults

- AI can generate local candidates.
- Sending is disabled unless explicitly enabled.
- First live send mode still asks for confirmation and allows one send per run.
