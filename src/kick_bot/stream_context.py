from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Literal


ContextSource = Literal["chat", "speech", "vision"]


@dataclass(frozen=True)
class ContextItem:
    source: ContextSource
    channel: str
    content: str
    username: str = ""
    timestamp: float = 0.0

    def format_for_prompt(self) -> str:
        if self.source == "chat" and self.username:
            return f"{self.username}: {self.content}"
        if self.source == "speech":
            return f"StreamAudio: {self.content}"
        if self.source == "vision":
            return f"Vision: {self.content}"
        return self.content


class StreamContext:
    """
    Shared context buffer for all inputs that describe the livestream.

    Typed chat, speech-to-text, and future vision summaries all write here.
    The response generator can then build one prompt from the same channel's
    recent chat + audio transcript + visual summaries.
    """

    def __init__(self, max_items_per_source: int = 30) -> None:
        self.max_items_per_source = max_items_per_source
        self._items: dict[str, dict[ContextSource, deque[ContextItem]]] = defaultdict(
            lambda: {
                "chat": deque(maxlen=max_items_per_source),
                "speech": deque(maxlen=max_items_per_source),
                "vision": deque(maxlen=max_items_per_source),
            }
        )

    def add_chat(self, channel: str, username: str, content: str) -> None:
        self.add("chat", channel, content, username=username)

    def add_speech(self, channel: str, transcript: str, username: str = "StreamAudio") -> None:
        self.add("speech", channel, transcript, username=username)

    def add_vision(self, channel: str, summary: str, username: str = "Vision") -> None:
        self.add("vision", channel, summary, username=username)

    def add(
        self,
        source: ContextSource,
        channel: str,
        content: str,
        username: str = "",
    ) -> None:
        content = content.strip()
        if not content:
            return

        item = ContextItem(
            source=source,
            channel=channel,
            username=username,
            content=content,
            timestamp=time.time(),
        )
        self._items[channel][source].append(item)

    def recent_items(
        self,
        channel: str,
        source: ContextSource,
        limit: int | None = None,
    ) -> list[ContextItem]:
        items = list(self._items[channel][source])
        if limit is not None:
            return items[-limit:]
        return items

    def recent_chat(self, channel: str, limit: int | None = None) -> list[str]:
        return [
            item.format_for_prompt()
            for item in self.recent_items(channel, "chat", limit)
        ]

    def recent_speech(self, channel: str, limit: int | None = None) -> list[str]:
        return [
            item.content
            for item in self.recent_items(channel, "speech", limit)
        ]

    def recent_vision(self, channel: str, limit: int | None = None) -> list[str]:
        return [
            item.content
            for item in self.recent_items(channel, "vision", limit)
        ]

    def context_for_prompt(
        self,
        channel: str,
        chat_limit: int = 12,
        speech_limit: int = 6,
        vision_limit: int = 4,
    ) -> dict[str, list[str]]:
        return {
            "recent_chat": self.recent_chat(channel, chat_limit),
            "recent_speech": self.recent_speech(channel, speech_limit),
            "recent_vision": self.recent_vision(channel, vision_limit),
        }
