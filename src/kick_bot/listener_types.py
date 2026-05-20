from __future__ import annotations

from pathlib import Path
from typing import Optional, Protocol, Any


class AIConfigLike(Protocol):
    max_context_messages: int


class ConfigLike(Protocol):
    ai: AIConfigLike
    personalities: dict[str, str]


class ChannelLike(Protocol):
    name: str


class MessageLike(Protocol):
    username: str
    content: str
    raw: dict[str, Any]


class TriggerLike(Protocol):
    matched_phrase: str
    trigger_label: str
    personality: str
    ai_instruction: str
