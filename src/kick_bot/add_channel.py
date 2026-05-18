import argparse
import json
from pathlib import Path
from typing import Any, Optional

from .channel_resolver import ResolvedChannel, resolve_channel
from .chat_sender import KickChatSender
from .listener import CONFIG_PATH, load_config


def load_raw_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as config_file:
        return json.load(config_file)


def save_raw_config(path: Path, config: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as config_file:
        json.dump(config, config_file, indent=2)
        config_file.write("\n")


def get_access_token() -> tuple[Optional[str], list[str]]:
    try:
        config = load_config()
        sender = KickChatSender(config.outbound.token_path)
        return sender.get_access_token(), []
    except Exception as exc:
        return None, [f"OAuth token unavailable: {exc}"]


def upsert_channel(
    config: dict[str, Any],
    resolved: ResolvedChannel,
    send_enabled: bool = False,
    enabled: bool = True,
    max_sends_per_run: int = 1,
) -> tuple[dict[str, Any], bool]:
    channels = config.setdefault("channels", [])
    lookup_name = (resolved.slug or resolved.name).lower()

    existing = next(
        (
            channel
            for channel in channels
            if str(channel.get("name", "")).lower() == lookup_name
        ),
        None,
    )
    created = existing is None

    if existing is None:
        existing = {
            "name": resolved.slug or resolved.name,
            "enabled": enabled,
            "send_enabled": send_enabled,
            "max_sends_per_run": max_sends_per_run,
        }
        channels.append(existing)

    existing["name"] = resolved.slug or resolved.name
    existing["chatroom_id"] = resolved.chatroom_id or existing.get("chatroom_id", "")
    existing["enabled"] = bool(existing.get("enabled", enabled))
    existing["send_enabled"] = bool(existing.get("send_enabled", send_enabled))
    existing["max_sends_per_run"] = existing.get("max_sends_per_run", max_sends_per_run)
    existing["broadcaster_user_id"] = (
        resolved.broadcaster_user_id
        if resolved.broadcaster_user_id is not None
        else existing.get("broadcaster_user_id")
    )

    return existing, created


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Resolve a Kick channel name and add/update it in config/bot_config.json."
    )
    parser.add_argument("channel", help="Kick channel name, @name, or kick.com/name URL.")
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--print-only", action="store_true", help="Lookup only; do not edit config.")
    parser.add_argument("--send-enabled", action="store_true", help="Allow this channel to send replies.")
    parser.add_argument("--disabled", action="store_true", help="Add the channel disabled.")
    parser.add_argument("--max-sends-per-run", type=int, default=1)
    args = parser.parse_args()

    access_token, token_warnings = get_access_token()
    resolved = resolve_channel(args.channel, access_token=access_token)
    if resolved.broadcaster_user_id is None:
        resolved.warnings = token_warnings + resolved.warnings

    print(json.dumps(resolved.to_dict(), indent=2))

    if args.print_only:
        return

    config = load_raw_config(args.config)
    channel, created = upsert_channel(
        config,
        resolved,
        send_enabled=args.send_enabled,
        enabled=not args.disabled,
        max_sends_per_run=args.max_sends_per_run,
    )
    save_raw_config(args.config, config)

    action = "Added" if created else "Updated"
    print()
    print(f"{action} {channel['name']} in {args.config}")
    print(f"chatroom_id: {channel.get('chatroom_id')}")
    print(f"broadcaster_user_id: {channel.get('broadcaster_user_id')}")
    print(f"enabled: {channel.get('enabled')}")
    print(f"send_enabled: {channel.get('send_enabled')}")
    if resolved.warnings:
        print("\nWarnings:")
        for warning in resolved.warnings:
            print(f"- {warning}")


if __name__ == "__main__":
    main()
