import asyncio
import json
import os
import random
import re
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

import websockets
from websockets.exceptions import ConnectionClosed

from .ai_responder import AIRequest, OllamaResponder
from .chat_sender import KickChatSender
from .env_loader import load_env


load_env()
CONFIG_PATH = Path(os.getenv("KICK_BOT_CONFIG", "config/bot_config.json"))

DEFAULT_CONFIG = {
    "channels": [
        {
            "name": "rampagejackson",
            "chatroom_id": "5512091",
            "enabled": True,
            "send_enabled": False,
            "broadcaster_user_id": None,
            "max_sends_per_run": 1,
        }
    ],
    "pusher_app_key": "32cbd69e4b950bf97679",
    "pusher_cluster": "us2",
    "debug_raw_events": False,
    "dry_run": True,
    "ignored_usernames": ["KickBot"],
    "log_chat_jsonl": True,
    "chat_log_path": "logs/chat.jsonl",
    "trigger_log_path": "logs/triggers.jsonl",
    "outbound": {
        "enabled": False,
        "type": "bot",
        "token_path": "tokens/kick_user_token.json",
        "min_seconds_between_sends": 10,
        "max_sends_per_run": 1,
        "confirm_before_send": True,
    },
    "ai": {
        "enabled": False,
        "provider": "ollama",
        "base_url": "http://127.0.0.1:11434",
        "model": "llama3.1:8b",
        "timeout_seconds": 30,
        "max_context_messages": 12,
        "max_response_chars": 220,
        "temperature": 0.7,
        "num_predict": 80,
        "system_prompt": (
            "You are a friendly, concise Kick chat bot. Reply like a real chat "
            "participant: casual, helpful, and brief. Avoid insults, slurs, "
            "harassment, sexual content, and private personal information."
        ),
    },
    "personalities": {
        "casual": (
            "Sound like a relaxed regular in chat. Keep replies casual, brief, "
            "and lightly funny when it fits. Do not be corporate or overly helpful."
        ),
        "hype": (
            "Sound like an energetic fight-stream chatter. Keep replies short, "
            "confident, and hype, without spamming caps."
        ),
        "analyst": (
            "Sound like a calm analyst. Make concise observations from context "
            "without pretending to know facts not present in chat."
        ),
    },
    "default_cooldown_seconds": 30,
    "keywords": [
        {
            "name": "greeting",
            "enabled": True,
            "response_mode": "static",
            "match": ["hello", "hey chat"],
            "responses": ["Hey chat!", "What's up everyone?"],
            "cooldown_seconds": 30,
        },
        {
            "name": "giveaway",
            "enabled": True,
            "response_mode": "static",
            "match": ["giveaway"],
            "responses": ["I'm in!", "Count me in!", "Let's goooo"],
            "cooldown_seconds": 60,
        },
    ],
}

PLACEHOLDER_CHATROOM_IDS = {
    "the_chatroom_id",
    "your_chatroom_id",
    "your-chatroom-id",
    "chatroom_id",
}

FORBIDDEN_SELF_CLAIM_PATTERNS = [
    "i've met ",
    "i have met ",
    "i know him",
    "i know her",
    "i know them",
    "i'd be down for a collab",
    "i would be down for a collab",
    "we should collab",
    "let's collab",
    "i'll stream",
    "i will stream",
    "come on my stream",
    "i'll dm",
    "i will dm",
    "i'll hit him up",
    "i'll hit her up",
    "i'll ask him",
    "i'll ask her",
]

def blocks_false_identity_claim(response: str) -> bool:
    lower = response.lower()
    return any(pattern in lower for pattern in FORBIDDEN_SELF_CLAIM_PATTERNS)

@dataclass(frozen=True)
class ChatMessage:
    message_id: Optional[str]
    username: str
    content: str
    raw: dict[str, Any]


@dataclass(frozen=True)
class KeywordRule:
    name: str
    enabled: bool
    response_mode: str
    phrases: list[str]
    responses: list[str]
    cooldown_seconds: float
    ai_instruction: str
    personality: str
    trigger_label: str
    response_chance: float


@dataclass(frozen=True)
class ChannelConfig:
    name: str
    chatroom_id: str
    enabled: bool
    send_enabled: bool
    broadcaster_user_id: Optional[int]
    max_sends_per_run: Optional[int]

    @property
    def pusher_channel(self) -> str:
        return f"chatrooms.{self.chatroom_id}.v2"


@dataclass(frozen=True)
class OutboundConfig:
    enabled: bool
    message_type: str
    token_path: Path
    min_seconds_between_sends: float
    max_sends_per_run: Optional[int]
    confirm_before_send: bool


@dataclass(frozen=True)
class AIConfig:
    enabled: bool
    provider: str
    base_url: str
    model: str
    timeout_seconds: float
    max_context_messages: int
    max_response_chars: int
    temperature: float
    num_predict: int
    system_prompt: str


class SendLimiter:
    def __init__(self, max_sends_per_run: Optional[int]) -> None:
        self.max_sends_per_run = max_sends_per_run
        self.total_sent = 0
        self.sent_by_channel: dict[str, int] = {}

    def can_send(self, channel: ChannelConfig) -> tuple[bool, str]:
        if self.max_sends_per_run is not None and self.total_sent >= self.max_sends_per_run:
            return False, f"global max_sends_per_run reached ({self.max_sends_per_run})"

        channel_sent = self.sent_by_channel.get(channel.name, 0)
        if channel.max_sends_per_run is not None and channel_sent >= channel.max_sends_per_run:
            return False, (
                f"{channel.name} max_sends_per_run reached "
                f"({channel.max_sends_per_run})"
            )

        return True, ""

    def record_sent(self, channel: ChannelConfig) -> None:
        self.total_sent += 1
        self.sent_by_channel[channel.name] = self.sent_by_channel.get(channel.name, 0) + 1


@dataclass(frozen=True)
class BotConfig:
    channels: list[ChannelConfig]
    pusher_app_key: str
    pusher_cluster: str
    debug_raw_events: bool
    dry_run: bool
    ignored_usernames: set[str]
    log_chat_jsonl: bool
    chat_log_path: Path
    trigger_log_path: Path
    outbound: OutboundConfig
    ai: AIConfig
    personalities: dict[str, str]
    rules: list[KeywordRule]


@dataclass(frozen=True)
class TriggerCandidate:
    rule_name: str
    matched_phrase: str
    response_mode: str
    response: Optional[str]
    ai_instruction: str
    personality: str
    trigger_label: str


class ChatContext:
    def __init__(self, max_messages: int) -> None:
        self.max_messages = max_messages
        self.messages_by_channel: dict[str, deque[str]] = defaultdict(
            lambda: deque(maxlen=max_messages)
        )

    def add(self, channel: str, username: str, content: str) -> None:
        self.messages_by_channel[channel].append(f"{username}: {content}")

    def recent(self, channel: str) -> list[str]:
        return list(self.messages_by_channel[channel])


EventCallback = Callable[[dict[str, Any]], Awaitable[None]]


class BotRuntime:
    def __init__(self, event_callback: Optional[EventCallback] = None) -> None:
        self.event_callback = event_callback
        self.stop_event = asyncio.Event()
        self.config = load_config()
        self.keyword_engine = KeywordEngine(self.config.rules)
        self.sender = (
            KickChatSender(self.config.outbound.token_path)
            if self.config.outbound.enabled and not self.config.dry_run
            else None
        )
        self.send_limiter = SendLimiter(self.config.outbound.max_sends_per_run)
        self.ai_responder = (
            OllamaResponder(
                base_url=self.config.ai.base_url,
                model=self.config.ai.model,
                system_prompt=self.config.ai.system_prompt,
                timeout_seconds=self.config.ai.timeout_seconds,
                max_response_chars=self.config.ai.max_response_chars,
                temperature=self.config.ai.temperature,
                num_predict=self.config.ai.num_predict,
            )
            if self.config.ai.enabled
            else None
        )
        self.chat_context = ChatContext(self.config.ai.max_context_messages)

    async def emit(self, event: dict[str, Any]) -> None:
        if self.event_callback:
            await self.event_callback(event)

    def request_stop(self) -> None:
        self.stop_event.set()

    async def run_forever(self) -> None:
        backoff_seconds = 1.0

        while not self.stop_event.is_set():
            try:
                await listen_once(
                    self.config,
                    self.keyword_engine,
                    self.sender,
                    self.send_limiter,
                    self.ai_responder,
                    self.chat_context,
                    event_callback=self.emit,
                    stop_event=self.stop_event,
                )
                backoff_seconds = 1.0
            except ConnectionClosed as exc:
                message = f"Websocket closed: {exc}. Reconnecting in {backoff_seconds:.1f}s"
                print(message)
                await self.emit({"type": "status", "level": "warning", "message": message})
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                message = f"Listener error: {exc}. Reconnecting in {backoff_seconds:.1f}s"
                print(message)
                await self.emit({"type": "status", "level": "error", "message": message})

            try:
                await asyncio.wait_for(self.stop_event.wait(), timeout=backoff_seconds)
            except asyncio.TimeoutError:
                pass
            backoff_seconds = min(backoff_seconds * 2, 60.0)


class KeywordEngine:
    def __init__(self, rules: list[KeywordRule]) -> None:
        self.rules = rules
        self.last_triggered_at: dict[tuple[str, str], float] = {}

    def match(self, channel_name: str, message: str) -> Optional[TriggerCandidate]:
        now = time.monotonic()

        for rule in self.rules:
            if not rule.enabled:
                continue

            matched_phrase = next(
                (phrase for phrase in rule.phrases if phrase_matches(message, phrase)),
                None,
            )
            if not matched_phrase:
                continue

            cooldown_key = (channel_name, rule.name)
            last_triggered_at = self.last_triggered_at.get(cooldown_key, 0.0)
            if now - last_triggered_at < rule.cooldown_seconds:
                return None

            if random.random() > rule.response_chance:
                return None

            response = None
            if rule.response_mode == "static":
                if not rule.responses:
                    continue
                response = random.choice(rule.responses)

            self.last_triggered_at[cooldown_key] = now
            return TriggerCandidate(
                rule_name=rule.name,
                matched_phrase=matched_phrase,
                response_mode=rule.response_mode,
                response=response,
                ai_instruction=rule.ai_instruction,
                personality=rule.personality,
                trigger_label=rule.trigger_label,
            )

        return None


def phrase_matches(message: str, phrase: str) -> bool:
    phrase = phrase.strip()
    if not phrase:
        return False

    escaped_phrase = re.escape(phrase)
    pattern = rf"(?<![A-Za-z0-9_]){escaped_phrase}(?![A-Za-z0-9_])"
    return re.search(pattern, message, flags=re.IGNORECASE) is not None


def decode_json(value: Any, fallback: Any = None) -> Any:
    if fallback is None:
        fallback = {}

    if value is None:
        return fallback

    if isinstance(value, dict):
        return value

    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8", errors="replace")

    if isinstance(value, str):
        if not value:
            return fallback
        return json.loads(value)

    return fallback


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)

    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value

    return merged


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def optional_int(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    return int(value)


def resolve_path(path_value: str) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path
    config_parent = CONFIG_PATH.parent
    project_root = config_parent.parent if config_parent.name == "config" else config_parent
    return project_root / path


def load_config() -> BotConfig:
    file_config: dict[str, Any] = {}
    if CONFIG_PATH.exists():
        with CONFIG_PATH.open("r", encoding="utf-8") as config_file:
            file_config = json.load(config_file)

    raw_config = deep_merge(DEFAULT_CONFIG, file_config)

    if "channels" in file_config:
        raw_channels = raw_config["channels"]
    elif "channel" in file_config or "chatroom_id" in file_config:
        raw_channels = [
            {
                "name": raw_config.get("channel", "rampagejackson"),
                "chatroom_id": raw_config.get("chatroom_id", "5512091"),
                "enabled": True,
                "send_enabled": False,
                "broadcaster_user_id": None,
            }
        ]
    else:
        raw_channels = raw_config["channels"]

    channel_override = os.getenv("KICK_CHANNEL")
    chatroom_id_override = os.getenv("KICK_CHATROOM_ID")
    if channel_override or chatroom_id_override:
        channels = [
            ChannelConfig(
                name=(channel_override or raw_channels[0]["name"]).strip().lstrip("@"),
                chatroom_id=(chatroom_id_override or raw_channels[0]["chatroom_id"]).strip(),
                enabled=True,
                send_enabled=bool(raw_channels[0].get("send_enabled", False)),
                broadcaster_user_id=optional_int(raw_channels[0].get("broadcaster_user_id")),
                max_sends_per_run=optional_int(raw_channels[0].get("max_sends_per_run")),
            )
        ]
    else:
        channels = [
            ChannelConfig(
                name=str(channel["name"]).strip().lstrip("@"),
                chatroom_id=str(channel["chatroom_id"]).strip(),
                enabled=bool(channel.get("enabled", True)),
                send_enabled=bool(channel.get("send_enabled", False)),
                broadcaster_user_id=optional_int(channel.get("broadcaster_user_id")),
                max_sends_per_run=optional_int(channel.get("max_sends_per_run")),
            )
            for channel in raw_channels
        ]

    pusher_app_key = os.getenv("KICK_PUSHER_APP_KEY", raw_config["pusher_app_key"]).strip()
    pusher_cluster = os.getenv("KICK_PUSHER_CLUSTER", raw_config["pusher_cluster"]).strip()
    debug_raw_events = env_bool("KICK_DEBUG_RAW_EVENTS", bool(raw_config["debug_raw_events"]))
    dry_run = env_bool("KICK_DRY_RUN", bool(raw_config["dry_run"]))
    raw_outbound = raw_config.get("outbound", {})
    outbound = OutboundConfig(
        enabled=env_bool("KICK_OUTBOUND_ENABLED", bool(raw_outbound.get("enabled", False))),
        message_type=str(raw_outbound.get("type", "bot")),
        token_path=resolve_path(str(raw_outbound.get("token_path", "tokens/kick_user_token.json"))),
        min_seconds_between_sends=float(raw_outbound.get("min_seconds_between_sends", 10)),
        max_sends_per_run=optional_int(raw_outbound.get("max_sends_per_run")),
        confirm_before_send=bool(raw_outbound.get("confirm_before_send", True)),
    )
    raw_ai = raw_config.get("ai", {})
    ai = AIConfig(
        enabled=bool(raw_ai.get("enabled", False)),
        provider=str(raw_ai.get("provider", "ollama")),
        base_url=str(raw_ai.get("base_url", "http://127.0.0.1:11434")),
        model=str(raw_ai.get("model", "llama3.1:8b")),
        timeout_seconds=float(raw_ai.get("timeout_seconds", 30)),
        max_context_messages=int(raw_ai.get("max_context_messages", 12)),
        max_response_chars=int(raw_ai.get("max_response_chars", 220)),
        temperature=float(raw_ai.get("temperature", 0.7)),
        num_predict=int(raw_ai.get("num_predict", 80)),
        system_prompt=str(raw_ai.get("system_prompt", "")),
    )
    personalities = {
        str(name): str(prompt)
        for name, prompt in raw_config.get("personalities", {}).items()
    }

    default_cooldown = float(raw_config.get("default_cooldown_seconds", 30))
    rules = [
        KeywordRule(
            name=str(rule["name"]),
            enabled=bool(rule.get("enabled", True)),
            response_mode=str(rule.get("response_mode", "static")),
            phrases=[str(phrase) for phrase in rule.get("match", [])],
            responses=[str(response) for response in rule.get("responses", [])],
            cooldown_seconds=float(rule.get("cooldown_seconds", default_cooldown)),
            ai_instruction=str(rule.get("ai_instruction", "")),
            personality=str(rule.get("personality", "casual")),
            trigger_label=str(rule.get("trigger_label", rule["name"])),
            response_chance=float(rule.get("response_chance", 1.0)),
        )
        for rule in raw_config.get("keywords", [])
    ]

    return BotConfig(
        channels=[channel for channel in channels if channel.enabled],
        pusher_app_key=pusher_app_key,
        pusher_cluster=pusher_cluster,
        debug_raw_events=debug_raw_events,
        dry_run=dry_run,
        ignored_usernames={
            str(username).lower()
            for username in raw_config.get("ignored_usernames", [])
        },
        log_chat_jsonl=bool(raw_config.get("log_chat_jsonl", True)),
        chat_log_path=resolve_path(str(raw_config.get("chat_log_path", "logs/chat.jsonl"))),
        trigger_log_path=resolve_path(str(raw_config.get("trigger_log_path", "logs/triggers.jsonl"))),
        outbound=outbound,
        ai=ai,
        personalities=personalities,
        rules=rules,
    )


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as log_file:
        log_file.write(json.dumps(record, ensure_ascii=False) + "\n")


def extract_chat_message(pusher_event: dict[str, Any]) -> Optional[ChatMessage]:
    event_name = pusher_event.get("event", "")
    if not event_name.endswith("ChatMessageEvent"):
        return None

    payload = decode_json(pusher_event.get("data"))
    sender = payload.get("sender") or {}

    content = payload.get("content", "")
    username = sender.get("username") or sender.get("slug") or "Unknown"
    message_id = payload.get("id") or payload.get("message_id")

    if not content:
        return None

    return ChatMessage(
        message_id=message_id,
        username=username,
        content=content,
        raw=payload,
    )


def validate_channel(channel: ChannelConfig) -> None:
    if not channel.chatroom_id or channel.chatroom_id.lower() in PLACEHOLDER_CHATROOM_IDS:
        raise RuntimeError(
            f"Set a real numeric chatroom id for {channel.name!r}. "
            "Placeholder values will connect to Pusher, but they will not receive Kick chat."
        )

    if not channel.chatroom_id.isdigit():
        raise RuntimeError(
            f"Chatroom id for {channel.name!r} must be numeric, got {channel.chatroom_id!r}."
        )

    if channel.broadcaster_user_id is not None and not isinstance(channel.broadcaster_user_id, int):
        raise RuntimeError(
            f"broadcaster_user_id for {channel.name!r} must be a number or null."
        )


def validate_config(config: BotConfig) -> None:
    if not config.channels:
        raise RuntimeError("No enabled channels configured.")

    for channel in config.channels:
        validate_channel(channel)

    if not config.rules:
        raise RuntimeError("No keyword rules configured.")

    if config.outbound.message_type not in {"bot", "user"}:
        raise RuntimeError("outbound.type must be 'bot' or 'user'.")

    if (
        not config.dry_run
        and config.outbound.enabled
        and config.outbound.message_type == "user"
    ):
        missing_user_ids = [
            channel.name
            for channel in config.channels
            if channel.send_enabled and channel.broadcaster_user_id is None
        ]
        if missing_user_ids:
            raise RuntimeError(
                "outbound.type='user' requires broadcaster_user_id for send-enabled "
                f"channels: {', '.join(missing_user_ids)}"
            )

    if config.ai.provider != "ollama":
        raise RuntimeError("Only ai.provider='ollama' is supported right now.")

    for rule in config.rules:
        if rule.response_mode not in {"static", "ai"}:
            raise RuntimeError(
                f"Rule {rule.name!r} has invalid response_mode {rule.response_mode!r}."
            )
        if not 0 <= rule.response_chance <= 1:
            raise RuntimeError(
                f"Rule {rule.name!r} response_chance must be between 0 and 1."
            )
        if rule.response_mode == "ai" and rule.personality not in config.personalities:
            raise RuntimeError(
                f"Rule {rule.name!r} references missing personality {rule.personality!r}."
            )


async def subscribe_to_chat(websocket: Any, channel: ChannelConfig) -> None:
    subscribe_message = {
        "event": "pusher:subscribe",
        "data": {
            "auth": "",
            "channel": channel.pusher_channel,
        },
    }
    await websocket.send(json.dumps(subscribe_message))


async def maybe_send_response(
    config: BotConfig,
    sender: Optional[KickChatSender],
    send_limiter: SendLimiter,
    channel: ChannelConfig,
    response: str,
) -> None:
    if config.dry_run:
        return

    if not config.outbound.enabled:
        return

    if not channel.send_enabled:
        print(f"[SEND SKIPPED] {channel.name}: send_enabled is false")
        return

    if sender is None:
        raise RuntimeError("Outbound sender was not initialized.")

    can_send, reason = send_limiter.can_send(channel)
    if not can_send:
        print(f"[SEND SKIPPED] {reason}")
        return

    if config.outbound.confirm_before_send:
        prompt = f"Type 'send' to post to kick.com/{channel.name}: {response!r}: "
        confirmation = await asyncio.to_thread(input, prompt)
        if confirmation.strip().lower() != "send":
            print("[SEND SKIPPED] manual confirmation declined")
            return

    result = await asyncio.to_thread(
        sender.send_message,
        response,
        config.outbound.message_type,
        channel.broadcaster_user_id,
        None,
        config.outbound.min_seconds_between_sends,
    )

    if result.ok:
        send_limiter.record_sent(channel)
        print(f"[SENT] {channel.name}: {response}")
    else:
        print(f"[SEND FAILED] {result.status_code}: {result.data}")

def extract_recent_usernames(recent_chat: list[str], current_username: str) -> list[str]:
    usernames = {current_username}

    for line in recent_chat:
        if ":" not in line:
            continue

        username = line.split(":", 1)[0].strip()

        if username:
            usernames.add(username)

    return sorted(usernames, key=len, reverse=True)


def prefix_username_mentions(response: str, usernames: list[str]) -> str:
    fixed = response

    for username in usernames:
        username = username.strip()

        if not username:
            continue

        escaped = re.escape(username)

        # Match username when it appears as a standalone name and is not already @mentioned.
        pattern = rf"(?<![@A-Za-z0-9_]){escaped}(?![A-Za-z0-9_])"

        fixed = re.sub(
            pattern,
            f"@{username}",
            fixed,
            flags=re.IGNORECASE,
        )

    return fixed

async def build_response_text(
    config: BotConfig,
    ai_responder: Optional[OllamaResponder],
    chat_context: ChatContext,
    channel: ChannelConfig,
    chat_message: ChatMessage,
    trigger: TriggerCandidate,
) -> Optional[str]:
    if trigger.response_mode == "static":
        return trigger.response

    if trigger.response_mode != "ai":
        return None

    if not config.ai.enabled:
        print(f"[AI SKIPPED] Rule {trigger.rule_name} matched, but ai.enabled is false")
        return None

    if ai_responder is None:
        print("[AI SKIPPED] AI responder was not initialized")
        return None

    request = AIRequest(
        channel=channel.name,
        username=chat_message.username,
        content=chat_message.content,
        matched_phrase=trigger.matched_phrase,
        trigger_label=trigger.trigger_label,
        personality_name=trigger.personality,
        personality_prompt=config.personalities[trigger.personality],
        instruction=trigger.ai_instruction,
        recent_chat=chat_context.recent(channel.name),
    )
    response = await asyncio.to_thread(ai_responder.generate, request)

    if not response.ok:
        print(f"[AI FAILED] {response.error}")
        return None

    recent_chat = chat_context.recent(channel.name)
    usernames = extract_recent_usernames(recent_chat, chat_message.username)
    if blocks_false_identity_claim(response.text):
        print(f"[AI BLOCKED] false identity/streamer claim: {response.text}")
        return None
    return prefix_username_mentions(response.text, usernames)


async def listen_once(
    config: BotConfig,
    keyword_engine: KeywordEngine,
    sender: Optional[KickChatSender],
    send_limiter: SendLimiter,
    ai_responder: Optional[OllamaResponder],
    chat_context: ChatContext,
    event_callback: Optional[EventCallback] = None,
    stop_event: Optional[asyncio.Event] = None,
) -> None:
    validate_config(config)
    channels_by_pusher_name = {
        channel.pusher_channel: channel
        for channel in config.channels
    }

    websocket_url = (
        f"wss://ws-{config.pusher_cluster}.pusher.com/app/{config.pusher_app_key}"
        "?protocol=7&client=js&version=7.6.0&flash=false"
    )

    async with websockets.connect(
        websocket_url,
        ping_interval=20,
        ping_timeout=20,
        close_timeout=5,
        max_queue=1024,
    ) as websocket:
        hello = decode_json(await websocket.recv())
        hello_data = decode_json(hello.get("data"))
        socket_id = hello_data.get("socket_id", "unknown")
        print(f"Connected to Pusher socket {socket_id}")
        if event_callback:
            await event_callback(
                {
                    "type": "status",
                    "level": "info",
                    "message": f"Connected to Pusher socket {socket_id}",
                }
            )

        for channel in config.channels:
            await subscribe_to_chat(websocket, channel)
            print(f"Subscribed to {channel.pusher_channel} for kick.com/{channel.name}")
            if event_callback:
                await event_callback(
                    {
                        "type": "subscription",
                        "channel": channel.name,
                        "pusher_channel": channel.pusher_channel,
                    }
                )

        channel_names = ", ".join(channel.name for channel in config.channels)
        print(f"Listening to {channel_names}")
        print(f"Dry run: {config.dry_run}")
        print(f"Outbound enabled: {config.outbound.enabled}")
        print(f"AI enabled: {config.ai.enabled} ({config.ai.provider}/{config.ai.model})")
        ai_rules = [
            rule
            for rule in config.rules
            if rule.enabled and rule.response_mode == "ai"
        ]
        for rule in ai_rules:
            print(
                f"AI rule active: {rule.name} -> {', '.join(rule.phrases)} "
                f"(personality={rule.personality}, chance={rule.response_chance})"
            )
        if not config.dry_run and config.outbound.enabled:
            print(f"Manual send confirmation: {config.outbound.confirm_before_send}")
            print(f"Global send limit: {config.outbound.max_sends_per_run}")

        while not (stop_event and stop_event.is_set()):
            raw_message = await websocket.recv()
            if config.debug_raw_events:
                print(f"[RAW] {raw_message}")

            event = decode_json(raw_message)
            event_name = event.get("event", "")

            if event_name == "pusher_internal:subscription_succeeded":
                pusher_channel = event.get("channel", "")
                channel = channels_by_pusher_name.get(pusher_channel)
                if channel:
                    print(f"[SUBSCRIPTION OK] kick.com/{channel.name} ({pusher_channel})")
                else:
                    print(f"[SUBSCRIPTION OK] {pusher_channel}")
                continue

            if event_name == "pusher:pong":
                continue

            if event_name == "pusher:error":
                print(f"[PUSHER ERROR] {event.get('data')}")
                continue

            chat_message = extract_chat_message(event)
            if not chat_message:
                continue

            pusher_channel = event.get("channel", "")
            channel = channels_by_pusher_name.get(pusher_channel)
            if not channel and len(config.channels) == 1:
                channel = config.channels[0]
            if not channel:
                if config.debug_raw_events:
                    print(f"[UNKNOWN CHANNEL] {pusher_channel}: {event}")
                continue

            if chat_message.username.lower() in config.ignored_usernames:
                continue

            channel_prefix = f"[{channel.name}] " if len(config.channels) > 1 else ""
            print(f"{channel_prefix}{chat_message.username}: {chat_message.content}")
            chat_context.add(channel.name, chat_message.username, chat_message.content)
            if event_callback:
                await event_callback(
                    {
                        "type": "chat",
                        "timestamp": time.time(),
                        "channel": channel.name,
                        "chatroom_id": channel.chatroom_id,
                        "message_id": chat_message.message_id,
                        "username": chat_message.username,
                        "content": chat_message.content,
                    }
                )

            if config.log_chat_jsonl:
                append_jsonl(
                    config.chat_log_path,
                    {
                        "timestamp": time.time(),
                        "channel": channel.name,
                        "chatroom_id": channel.chatroom_id,
                        "message_id": chat_message.message_id,
                        "username": chat_message.username,
                        "content": chat_message.content,
                    },
                )

            trigger = keyword_engine.match(channel.name, chat_message.content)
            if trigger:
                response_text = await build_response_text(
                    config,
                    ai_responder,
                    chat_context,
                    channel,
                    chat_message,
                    trigger,
                )
                if not response_text:
                    continue

                append_jsonl(
                    config.trigger_log_path,
                    {
                        "timestamp": time.time(),
                        "channel": channel.name,
                        "chatroom_id": channel.chatroom_id,
                        "message_id": chat_message.message_id,
                        "username": chat_message.username,
                        "content": chat_message.content,
                        "rule_name": trigger.rule_name,
                        "matched_phrase": trigger.matched_phrase,
                        "response_mode": trigger.response_mode,
                        "trigger_label": trigger.trigger_label,
                        "personality": trigger.personality,
                        "response": response_text,
                        "dry_run": config.dry_run,
                    },
                )
                label = "AI RESPONSE CANDIDATE" if trigger.response_mode == "ai" else "BOT RESPONSE CANDIDATE"
                print(f"[{label}] {channel.name} {trigger.rule_name}/{trigger.matched_phrase}: {response_text}")
                if event_callback:
                    await event_callback(
                        {
                            "type": "trigger",
                            "timestamp": time.time(),
                            "channel": channel.name,
                            "chatroom_id": channel.chatroom_id,
                            "message_id": chat_message.message_id,
                            "username": chat_message.username,
                            "content": chat_message.content,
                            "rule_name": trigger.rule_name,
                            "matched_phrase": trigger.matched_phrase,
                            "response_mode": trigger.response_mode,
                            "response": response_text,
                            "dry_run": config.dry_run,
                        }
                    )
                await maybe_send_response(
                    config,
                    sender,
                    send_limiter,
                    channel,
                    response_text,
                )


async def run_forever() -> None:
    runtime = BotRuntime()
    await runtime.run_forever()


def main() -> None:
    try:
        asyncio.run(run_forever())
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
