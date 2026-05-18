import json
from pathlib import Path
from typing import Any

import requests

from kick_chat_sender import KickChatSender
from kick_pusher_listener import load_config


KICK_CHANNELS_URL = "https://api.kick.com/public/v1/channels"


def fetch_channel(access_token: str, slug: str) -> dict[str, Any]:
    response = requests.get(
        KICK_CHANNELS_URL,
        params=[("slug", slug)],
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        },
        timeout=20,
    )

    try:
        data = response.json()
    except ValueError:
        data = {"text": response.text}

    if not response.ok:
        raise RuntimeError(f"Kick channel lookup failed: {response.status_code} {data}")

    channels = data.get("data") or []
    if not channels:
        raise RuntimeError(f"No channel found for slug {slug!r}: {data}")

    return channels[0]


def main() -> None:
    config = load_config()
    sender = KickChatSender(config.outbound.token_path)
    access_token = sender.get_access_token()

    for channel in config.channels:
        channel_data = fetch_channel(access_token, channel.name)
        print(json.dumps(
            {
                "name": channel.name,
                "slug": channel_data.get("slug"),
                "broadcaster_user_id": channel_data.get("broadcaster_user_id"),
                "stream_title": channel_data.get("stream_title"),
            },
            indent=2,
        ))

    print("\nFor outbound.type = \"user\", copy broadcaster_user_id into bot_config.json.")


if __name__ == "__main__":
    main()
