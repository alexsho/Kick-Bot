import asyncio
import argparse
import json
from collections import deque
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from .speech_listener import run_speech_listener
from .trigger_suggester import frequency_suggestions, ollama_suggestions, merge_trigger_lists

from .ai_responder import AIRequest, OllamaResponder
from .channel_resolver import resolve_channel
from .chat_sender import KickChatSender
from .env_loader import read_env, write_env
from .listener import BotRuntime, CONFIG_PATH, load_config


ROOT = Path.cwd()
WEB_DIR = Path(__file__).resolve().parent / "web"
RECENT_EVENTS: deque[dict[str, Any]] = deque(maxlen=500)

app = FastAPI(title="Kick Local Bot Dashboard")
clients: set[WebSocket] = set()
runtime_task: asyncio.Task[Any] | None = None
speech_task: asyncio.Task[Any] | None = None
speech_stop_event: asyncio.Event | None = None
runtime: BotRuntime | None = None


def config_file() -> Path:
    return CONFIG_PATH


def load_raw_config() -> dict[str, Any]:
    with config_file().open("r", encoding="utf-8") as handle:
        return json.load(handle)


def save_raw_config(config: dict[str, Any]) -> None:
    with config_file().open("w", encoding="utf-8") as handle:
        json.dump(config, handle, indent=2)
        handle.write("\n")

def recent_messages_for_channel(channel: str | None = None, max_messages: int = 300) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []

    for event in RECENT_EVENTS:
        event_type = event.get("type")
        if event_type not in {"chat", "speech"}:
            continue

        event_channel = str(event.get("channel", "")).lower()
        if channel and event_channel != channel.lower():
            continue

        content = str(event.get("content", "")).strip()
        if not content:
            continue

        messages.append(
            {
                "channel": event_channel,
                "username": str(event.get("username", "unknown")),
                "content": content,
            }
        )

    return messages[-max_messages:]

async def broadcast(event: dict[str, Any]) -> None:
    RECENT_EVENTS.append(event)
    stale: list[WebSocket] = []
    for websocket in list(clients):
        try:
            await websocket.send_json(event)
        except Exception:
            stale.append(websocket)
    for websocket in stale:
        clients.discard(websocket)


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    return HTMLResponse(html)


@app.get("/api/status")
async def status() -> dict[str, Any]:
    config = load_config()
    return {
        "running": runtime_task is not None and not runtime_task.done(),
        "speech_running": speech_task is not None and not speech_task.done(),
        "channels": [channel.name for channel in config.channels],
        "dry_run": config.dry_run,
        "outbound_enabled": config.outbound.enabled,
        "ai_enabled": config.ai.enabled,
        "ai_model": config.ai.model,
        "recent_events": len(RECENT_EVENTS),
    }


@app.post("/api/bot/start")
async def start_bot() -> JSONResponse:
    global runtime, runtime_task, speech_task, speech_stop_event

    if runtime_task and not runtime_task.done():
        return JSONResponse({"ok": True, "message": "Bot already running"})

    runtime = BotRuntime(event_callback=broadcast)
    runtime_task = asyncio.create_task(runtime.run_forever())

    config = load_config()
    enabled_channels = [channel for channel in config.channels if channel.enabled]

    if enabled_channels:
        speech_channel = enabled_channels[0].name
        speech_stop_event = asyncio.Event()
        speech_task = asyncio.create_task(
            run_speech_listener(
                channel_name=speech_channel,
                chunk_seconds=8,
                whisper_model="small",
                whisper_device="cpu",
                username="StreamAudio",
                event_callback=broadcast,
                stop_event=speech_stop_event,
            )
        )
        await broadcast({
            "type": "status",
            "level": "info",
            "message": f"Speech listener starting for {speech_channel}",
        })

    await broadcast({"type": "status", "level": "info", "message": "Bot started"})
    return JSONResponse({"ok": True})


@app.post("/api/bot/stop")
async def stop_bot() -> JSONResponse:
    global runtime, runtime_task, speech_task, speech_stop_event

    if runtime:
        runtime.request_stop()

    if speech_stop_event:
        speech_stop_event.set()

    if speech_task:
        speech_task.cancel()
        try:
            await speech_task
        except asyncio.CancelledError:
            pass

    if runtime_task:
        runtime_task.cancel()
        try:
            await runtime_task
        except asyncio.CancelledError:
            pass

    runtime = None
    runtime_task = None
    speech_task = None
    speech_stop_event = None

    await broadcast({"type": "status", "level": "info", "message": "Bot stopped"})
    return JSONResponse({"ok": True})


@app.get("/api/config")
async def get_config() -> dict[str, Any]:
    return load_raw_config()


@app.put("/api/config")
async def put_config(config: dict[str, Any]) -> JSONResponse:
    save_raw_config(config)
    await broadcast({"type": "status", "level": "info", "message": "Config saved"})
    return JSONResponse({"ok": True})


@app.post("/api/channel/resolve")
async def resolve_kick_channel(payload: dict[str, Any]) -> JSONResponse:
    channel_name = str(payload.get("channel", "")).strip()
    if not channel_name:
        return JSONResponse(
            {"ok": False, "error": "Channel name is required."},
            status_code=400,
        )

    token_warnings: list[str] = []
    access_token = None
    try:
        config = load_config()
        access_token = KickChatSender(config.outbound.token_path).get_access_token()
    except Exception as exc:
        token_warnings.append(f"OAuth token unavailable: {exc}")

    try:
        resolved = await asyncio.to_thread(resolve_channel, channel_name, access_token)
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=502)

    if resolved.broadcaster_user_id is None:
        resolved.warnings = token_warnings + resolved.warnings
    return JSONResponse({"ok": True, "channel": resolved.to_channel_config(), "details": resolved.to_dict()})


@app.get("/api/env")
async def get_env_status() -> dict[str, Any]:
    env = read_env()
    return {
        "KICK_CLIENT_ID": bool(env.get("KICK_CLIENT_ID")),
        "KICK_CLIENT_SECRET": bool(env.get("KICK_CLIENT_SECRET")),
        "KICK_REDIRECT_URI": env.get("KICK_REDIRECT_URI", ""),
        "KICK_OAUTH_SCOPES": env.get("KICK_OAUTH_SCOPES", ""),
    }


@app.put("/api/env")
async def put_env(values: dict[str, str]) -> JSONResponse:
    allowed = {
        "KICK_CLIENT_ID",
        "KICK_CLIENT_SECRET",
        "KICK_REDIRECT_URI",
        "KICK_OAUTH_SCOPES",
    }
    updates = {key: value for key, value in values.items() if key in allowed and value}
    write_env(updates)
    await broadcast({"type": "status", "level": "info", "message": ".env updated"})
    return JSONResponse({"ok": True})


@app.get("/api/events/recent")
async def recent_events() -> list[dict[str, Any]]:
    return list(RECENT_EVENTS)


@app.post("/api/test/ai")
async def test_ai(payload: dict[str, Any]) -> JSONResponse:
    config = load_config()
    responder = OllamaResponder(
        base_url=config.ai.base_url,
        model=config.ai.model,
        system_prompt=config.ai.system_prompt,
        timeout_seconds=config.ai.timeout_seconds,
        max_response_chars=config.ai.max_response_chars,
        temperature=config.ai.temperature,
        num_predict=config.ai.num_predict,
    )
    response = await asyncio.to_thread(
        responder.generate,
        AIRequest(
            channel=config.channels[0].name,
            username=payload.get("username", "TestUser"),
            content=payload.get("content", "ngannou just got a huge ko"),
            matched_phrase=payload.get("matched_phrase", "ngannou"),
            trigger_label="dashboard-test",
            personality_name=payload.get("personality", "hype"),
            personality_prompt=config.personalities.get(payload.get("personality", "hype"), ""),
            instruction="Draft one short Kick chat reply using the selected personality.",
            recent_chat=payload.get("recent_chat", []),
        ),
    )
    return JSONResponse({"ok": response.ok, "text": response.text, "error": response.error})


@app.websocket("/ws/events")
async def websocket_events(websocket: WebSocket) -> None:
    await websocket.accept()
    clients.add(websocket)
    try:
        for event in RECENT_EVENTS:
            await websocket.send_json(event)
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        clients.discard(websocket)

@app.post("/api/triggers/suggest")
async def suggest_triggers(payload: dict[str, Any]) -> JSONResponse:
    config = load_config()

    channel = str(payload.get("channel") or "").strip() or None
    max_messages = int(payload.get("max_messages") or 300)
    use_ai = bool(payload.get("use_ai", True))

    messages = recent_messages_for_channel(channel=channel, max_messages=max_messages)

    if not messages:
        return JSONResponse(
            {
                "ok": False,
                "error": "No recent chat or speech messages found for this channel yet.",
            },
            status_code=400,
        )

    frequency = frequency_suggestions(messages)

    ai_result = None
    ai_error = None

    if use_ai:
        try:
            ai_result = await asyncio.to_thread(
                ollama_suggestions,
                messages,
                frequency,
                channel,
                config.ai.model,
                config.ai.base_url,
            )
        except Exception as exc:
            ai_error = str(exc)

    merged = merge_trigger_lists(frequency, ai_result)

    return JSONResponse(
        {
            "ok": True,
            "channel": channel,
            "message_count": len(messages),
            "summary": ai_result.get("summary") if ai_result else "",
            "recommended_triggers": ai_result.get("recommended_triggers", []) if ai_result else [],
            "avoid_triggers": ai_result.get("avoid_triggers", []) if ai_result else [],
            "copy_paste_trigger_list": merged,
            "ai_error": ai_error,
            "frequency": {
                "words": frequency["words"],
                "phrases": frequency["phrases"],
            },
        }
    )

def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local Kick bot web dashboard.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()

    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
