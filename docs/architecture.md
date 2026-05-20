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


## Shared Stream Context

The bot now has a shared `StreamContext` buffer used by typed chat, speech-to-text, and future vision summaries.

```text
Typed chat listener  ─┐
Speech listener      ├─ StreamContext ── Response coordinator ── Ollama ── KickChatSender
Vision listener      ┘
```

This keeps input listeners independent while allowing the AI prompt to include:

- recent typed chat
- recent stream speech transcript
- recent visual scene summaries, when available
- the current trigger and message/transcript that caused the response

Speech and vision are primarily treated as context. A trigger can still come from typed chat or speech, but the generated response can use all available context for that channel.

The vision listener is not required for the shared context to work. When a future `vision_listener.py` adds summaries with `StreamContext.add_vision(...)`, those summaries will automatically become available to coordinated AI prompts.
