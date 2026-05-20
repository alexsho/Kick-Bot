from __future__ import annotations

from typing import Optional

from .ai_responder import AIRequest
from .listener_types import ChannelLike, ConfigLike, MessageLike, TriggerLike
from .stream_context import StreamContext


def build_coordinated_ai_request(
    *,
    config: ConfigLike,
    channel: ChannelLike,
    message: MessageLike,
    trigger: TriggerLike,
    recent_chat_fallback: list[str],
    stream_context: Optional[StreamContext] = None,
) -> AIRequest:
    """
    Build one AI request from typed chat, speech transcript, and visual summaries.

    This keeps the input listeners independent. Chat, speech, and future vision
    listeners write to StreamContext; this coordinator decides what context the
    model sees when a response is needed.
    """

    if stream_context is not None:
        context = stream_context.context_for_prompt(
            channel.name,
            chat_limit=config.ai.max_context_messages,
            speech_limit=max(3, config.ai.max_context_messages // 2),
            vision_limit=4,
        )
        recent_chat = context["recent_chat"]
        recent_speech = context["recent_speech"]
        recent_vision = context["recent_vision"]
    else:
        recent_chat = recent_chat_fallback[-config.ai.max_context_messages :]
        recent_speech = []
        recent_vision = []

    return AIRequest(
        channel=channel.name,
        username=message.username,
        content=message.content,
        matched_phrase=trigger.matched_phrase,
        trigger_label=trigger.trigger_label,
        personality_name=trigger.personality,
        personality_prompt=config.personalities[trigger.personality],
        instruction=trigger.ai_instruction,
        recent_chat=recent_chat,
        recent_speech=recent_speech,
        recent_vision=recent_vision,
        source=str(message.raw.get("source", "chat")) if hasattr(message, "raw") else "chat",
    )
