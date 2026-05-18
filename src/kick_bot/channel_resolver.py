from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional
from urllib.parse import urlparse

import requests


KICK_CHATROOM_URL = "https://kick.com/api/v2/channels/{slug}/chatroom"
KICK_WEB_CHANNEL_URL = "https://kick.com/api/v2/channels/{slug}"
KICK_OFFICIAL_CHANNELS_URL = "https://api.kick.com/public/v1/channels"


@dataclass
class ResolvedChannel:
    name: str
    chatroom_id: Optional[str] = None
    broadcaster_user_id: Optional[int] = None
    slug: Optional[str] = None
    stream_title: Optional[str] = None
    chatroom_data: dict[str, Any] = field(default_factory=dict)
    channel_data: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "chatroom_id": self.chatroom_id,
            "broadcaster_user_id": self.broadcaster_user_id,
            "slug": self.slug,
            "stream_title": self.stream_title,
            "chatroom_data": self.chatroom_data,
            "channel_data": summarize_channel_data(self.channel_data),
            "warnings": self.warnings,
        }

    def to_channel_config(self) -> dict[str, Any]:
        return {
            "name": self.slug or self.name,
            "chatroom_id": self.chatroom_id or "",
            "enabled": True,
            "send_enabled": False,
            "broadcaster_user_id": self.broadcaster_user_id,
            "max_sends_per_run": 1,
        }


def normalize_channel_name(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("Channel name is required.")

    parsed = urlparse(value)
    if parsed.netloc:
        path_parts = [part for part in parsed.path.split("/") if part]
        if path_parts:
            value = path_parts[0]

    return value.strip().lstrip("@").lower()


def browser_headers() -> dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://kick.com/",
        "Origin": "https://kick.com",
    }


def summarize_channel_data(data: dict[str, Any]) -> dict[str, Any]:
    if not data:
        return {}

    user = data.get("user") or {}
    livestream = data.get("livestream") or {}
    return {
        "id": data.get("id"),
        "user_id": data.get("user_id"),
        "slug": data.get("slug"),
        "verified": data.get("verified"),
        "followers_count": data.get("followers_count"),
        "user": {
            "id": user.get("id"),
            "username": user.get("username"),
        },
        "livestream": {
            "id": livestream.get("id"),
            "is_live": livestream.get("is_live"),
            "session_title": livestream.get("session_title"),
            "viewer_count": livestream.get("viewer_count"),
            "language": livestream.get("language"),
        } if livestream else None,
    }


def response_json(response: Any) -> dict[str, Any]:
    try:
        data = response.json()
    except ValueError:
        data = {"text": response.text}

    if isinstance(data, dict):
        return data
    return {"data": data}


def fetch_json_with_browser_tls(url: str) -> tuple[int, dict[str, Any], str]:
    headers = browser_headers()

    try:
        import tls_client  # type: ignore[import-not-found]
    except ImportError:
        response = requests.get(url, headers=headers, timeout=20)
        return response.status_code, response_json(response), "requests"

    session = tls_client.Session(
        client_identifier="chrome_124",
        random_tls_extension_order=True,
    )
    response = session.get(url, headers=headers, timeout_seconds=20)
    return response.status_code, response_json(response), "tls-client"


def fetch_chatroom_data(slug: str) -> dict[str, Any]:
    url = KICK_CHATROOM_URL.format(slug=slug)
    status_code, data, client_name = fetch_json_with_browser_tls(url)
    if status_code != 200:
        hint = ""
        if client_name == "requests" and status_code == 403:
            hint = " Install tls-client for browser-like TLS: python -m pip install tls-client"
        raise RuntimeError(
            f"Kick chatroom lookup failed with {client_name}: {status_code} {data}.{hint}"
        )
    return data


def fetch_web_channel_data(slug: str) -> dict[str, Any]:
    url = KICK_WEB_CHANNEL_URL.format(slug=slug)
    status_code, data, client_name = fetch_json_with_browser_tls(url)
    if status_code != 200:
        hint = ""
        if client_name == "requests" and status_code == 403:
            hint = " Install tls-client for browser-like TLS: python -m pip install tls-client"
        raise RuntimeError(
            f"Kick web channel lookup failed with {client_name}: {status_code} {data}.{hint}"
        )
    return data


def fetch_official_channel(access_token: str, slug: str) -> dict[str, Any]:
    response = requests.get(
        KICK_OFFICIAL_CHANNELS_URL,
        params=[("slug", slug)],
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        },
        timeout=20,
    )
    data = response_json(response)

    if not response.ok:
        raise RuntimeError(f"Kick official channel lookup failed: {response.status_code} {data}")

    channels = data.get("data") or []
    if not channels:
        raise RuntimeError(f"No official Kick channel found for slug {slug!r}: {data}")

    return channels[0]


def resolve_channel(channel_name: str, access_token: Optional[str] = None) -> ResolvedChannel:
    slug = normalize_channel_name(channel_name)
    resolved = ResolvedChannel(name=slug, slug=slug)

    chatroom_data = fetch_chatroom_data(slug)
    chatroom_id = chatroom_data.get("id") or (chatroom_data.get("data") or {}).get("id")
    if chatroom_id is None:
        raise RuntimeError(f"Chatroom response did not include an id: {chatroom_data}")

    resolved.chatroom_id = str(chatroom_id)
    resolved.chatroom_data = chatroom_data

    try:
        web_channel_data = fetch_web_channel_data(slug)
        resolved.channel_data = web_channel_data
        resolved.slug = web_channel_data.get("slug") or slug

        user = web_channel_data.get("user") or {}
        broadcaster_user_id = (
            web_channel_data.get("broadcaster_user_id")
            or web_channel_data.get("user_id")
            or user.get("id")
        )
        if broadcaster_user_id is not None:
            resolved.broadcaster_user_id = int(broadcaster_user_id)

        livestream = web_channel_data.get("livestream") or {}
        resolved.stream_title = (
            livestream.get("session_title")
            or livestream.get("title")
            or web_channel_data.get("stream_title")
        )
    except Exception as exc:
        resolved.warnings.append(f"Kick web channel details lookup failed: {exc}")

    if not access_token:
        if resolved.broadcaster_user_id is None:
            resolved.warnings.append(
                "Broadcaster user ID was not fetched because no Kick OAuth token is available."
            )
        return resolved

    try:
        channel_data = fetch_official_channel(access_token, slug)
    except Exception as exc:
        if resolved.broadcaster_user_id is None:
            resolved.warnings.append(f"Broadcaster user ID lookup failed: {exc}")
        else:
            resolved.warnings.append(
                f"Official broadcaster user ID lookup failed; using web endpoint value: {exc}"
            )
        return resolved

    broadcaster_user_id = channel_data.get("broadcaster_user_id")
    if broadcaster_user_id is not None:
        resolved.broadcaster_user_id = int(broadcaster_user_id)
    else:
        resolved.warnings.append("Official channel response did not include broadcaster_user_id.")

    resolved.slug = channel_data.get("slug") or slug
    resolved.stream_title = channel_data.get("stream_title")
    resolved.channel_data = channel_data
    return resolved
