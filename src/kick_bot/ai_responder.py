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
        recent_chat = "\n".join(request.recent_chat[-12:])
        return textwrap.dedent(
            f"""
            You are drafting one short Kick chat reply.

            Channel: {request.channel}
            Trigger label: {request.trigger_label}
            Trigger phrase found in chat: {request.matched_phrase}
            Personality: {request.personality_name}
            Personality instructions:
            {request.personality_prompt}

            Trigger instruction: {request.instruction}

            Recent chat:
            {recent_chat}

            Message to answer:
            {request.username}: {request.content}

            Use the recent chat for context. Do not over-focus on the trigger word by
            itself; respond to the conversation around it. Reply with only the chat message text. Keep it short, natural, and under {self.max_response_chars}
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
