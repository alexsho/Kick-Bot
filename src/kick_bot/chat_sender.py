import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import requests
from .env_loader import load_env


load_env()
KICK_CHAT_URL = "https://api.kick.com/public/v1/chat"
KICK_TOKEN_URL = "https://id.kick.com/oauth/token"


@dataclass(frozen=True)
class SendResult:
    ok: bool
    status_code: int
    data: dict[str, Any]


class KickChatSender:
    def __init__(
        self,
        token_path: Path,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
    ) -> None:
        self.token_path = token_path
        self.client_id = client_id or os.getenv("KICK_CLIENT_ID", "")
        self.client_secret = client_secret or os.getenv("KICK_CLIENT_SECRET", "")
        self._token: Optional[dict[str, Any]] = None
        self._last_sent_at = 0.0

    def load_token(self) -> dict[str, Any]:
        if self._token is not None:
            return self._token

        with self.token_path.open("r", encoding="utf-8") as token_file:
            self._token = json.load(token_file)

        return self._token

    def save_token(self, token: dict[str, Any]) -> None:
        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        with self.token_path.open("w", encoding="utf-8") as token_file:
            json.dump(token, token_file, indent=2)
        self._token = token

    def get_access_token(self) -> str:
        token = self.load_token()
        expires_at = float(token.get("expires_at", 0))

        if expires_at and time.time() < expires_at - 60:
            return str(token["access_token"])

        refresh_token = token.get("refresh_token")
        if not refresh_token:
            raise RuntimeError("Token is expired and no refresh_token is available.")

        return self.refresh_access_token(str(refresh_token))

    def refresh_access_token(self, refresh_token: str) -> str:
        if not self.client_id or not self.client_secret:
            raise RuntimeError(
                "KICK_CLIENT_ID and KICK_CLIENT_SECRET are required to refresh tokens."
            )

        response = requests.post(
            KICK_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
            timeout=20,
        )
        response.raise_for_status()
        token = response.json()
        token["expires_at"] = time.time() + int(token.get("expires_in", 0))
        self.save_token(token)
        return str(token["access_token"])

    def send_message(
        self,
        content: str,
        message_type: str = "bot",
        broadcaster_user_id: Optional[int] = None,
        reply_to_message_id: Optional[str] = None,
        min_seconds_between_sends: float = 10.0,
    ) -> SendResult:
        now = time.monotonic()
        if now - self._last_sent_at < min_seconds_between_sends:
            return SendResult(
                ok=False,
                status_code=429,
                data={"error": "local sender cooldown active"},
            )

        content = content.strip()
        if not content:
            raise ValueError("Cannot send an empty chat message.")

        payload: dict[str, Any] = {
            "content": content,
            "type": message_type,
        }

        if message_type == "user":
            if broadcaster_user_id is None:
                raise RuntimeError(
                    "broadcaster_user_id is required when sending as type='user'."
                )
            payload["broadcaster_user_id"] = broadcaster_user_id
        elif message_type != "bot":
            raise ValueError("message_type must be 'bot' or 'user'.")

        if reply_to_message_id:
            payload["reply_to_message_id"] = reply_to_message_id

        response = requests.post(
            KICK_CHAT_URL,
            json=payload,
            headers={
                "Authorization": f"Bearer {self.get_access_token()}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            timeout=20,
        )

        try:
            data = response.json()
        except ValueError:
            data = {"text": response.text}

        if response.ok:
            self._last_sent_at = now

        if not response.ok:
            data = {
                "kick_response": data,
                "request_payload": payload,
            }

        return SendResult(
            ok=response.ok,
            status_code=response.status_code,
            data=data,
        )
