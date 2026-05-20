import textwrap
from dataclasses import dataclass
from typing import Any

import requests


@dataclass(frozen=True)
class AIRequest:
    channel: str
    username: str
    content: str
    matched_phrase: str
    trigger_label: str
    personality_name: str
    personality_prompt: str
    instruction: str
    recent_chat: list[str]
    recent_speech: list[str] | None = None
    recent_vision: list[str] | None = None
    source: str = "chat"


@dataclass(frozen=True)
class AIResponse:
    ok: bool
    text: str
    error: str = ""


class OllamaResponder:
    def __init__(
        self,
        base_url: str,
        model: str,
        system_prompt: str,
        timeout_seconds: float = 30,
        max_response_chars: int = 220,
        temperature: float = 0.7,
        num_predict: int = 80,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.system_prompt = system_prompt
        self.timeout_seconds = timeout_seconds
        self.max_response_chars = max_response_chars
        self.temperature = temperature
        self.num_predict = num_predict

    def generate(self, request: AIRequest) -> AIResponse:
        prompt = self.build_prompt(request)

        try:
            response = requests.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model,
                    "stream": False,
                    "messages": [
                        {
                            "role": "system",
                            "content": self.system_prompt,
                        },
                        {
                            "role": "user",
                            "content": prompt,
                        },
                    ],
                    "options": {
                        "temperature": self.temperature,
                        "num_predict": self.num_predict,
                    },
                },
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            return AIResponse(ok=False, text="", error=str(exc))

        data = response.json()
        text = (
            data.get("message", {}).get("content")
            or data.get("response")
            or ""
        )
        text = self.clean_response(str(text))
        if not text:
            return AIResponse(ok=False, text="", error="empty AI response")

        return AIResponse(ok=True, text=text)

    def build_prompt(self, request: AIRequest) -> str:
        recent_chat = "\n".join((request.recent_chat or [])[-12:])
        recent_speech = "\n".join((request.recent_speech or [])[-6:])
        recent_vision = "\n".join((request.recent_vision or [])[-4:])

        speech_block = recent_speech or "(no recent speech transcript)"
        vision_block = recent_vision or "(no visual summaries yet)"

        return textwrap.dedent(
            f"""
            You are drafting one short Kick chat reply.

            Identity rules:
            - You are a viewer in chat, not the streamer.
            - Do not answer as the streamer.
            - Do not claim you personally know people unless that is explicitly in the chat.
            - Do not claim meetings, collabs, plans, DMs, streams, or relationships.
            - If someone asks the streamer a question, react as a viewer instead of answering for the streamer.

            Channel: {request.channel}
            Input source that triggered this reply: {request.source}
            Trigger label: {request.trigger_label}
            Trigger phrase found: {request.matched_phrase}
            Personality: {request.personality_name}
            Personality instructions:
            {request.personality_prompt}

            Trigger instruction:
            {request.instruction}

            Recent typed chat:
            {recent_chat}

            Recent stream speech transcript:
            {speech_block}

            Recent visual scene summaries:
            {vision_block}

            Message/transcript to answer:
            {request.username}: {request.content}

            Use typed chat, speech, and visual context together when available. If speech
            refers to something on screen, use the visual summaries to understand what it
            is about. Do not over-focus on the trigger word by itself; respond to the
            conversation and scene around it.

            Reply with only the chat message text. Keep it short, natural, and under {self.max_response_chars}
            characters. Do not mention that you are an AI.

            If you directly mention or reply to a specific username from chat, prefix the username with @.
            Correct: @Madnox01 that clip was wild
            Wrong: Madnox01, that clip was wild
            """
        ).strip()

    def clean_response(self, text: str) -> str:
        text = " ".join(text.strip().split())

        if (
            len(text) >= 2
            and text[0] == text[-1]
            and text[0] in {'"', "'"}
        ):
            text = text[1:-1].strip()

        if len(text) > self.max_response_chars:
            text = text[: self.max_response_chars].rstrip()

        return text
