import argparse
import json
from pathlib import Path
from typing import Any


CONFIG_PATH = Path("config/bot_config.json")


def load_config() -> dict[str, Any]:
    with CONFIG_PATH.open("r", encoding="utf-8") as config_file:
        return json.load(config_file)


def save_config(config: dict[str, Any]) -> None:
    with CONFIG_PATH.open("w", encoding="utf-8") as config_file:
        json.dump(config, config_file, indent=2)
        config_file.write("\n")


def find_channel(config: dict[str, Any], name: str) -> dict[str, Any]:
    for channel in config.get("channels", []):
        if channel.get("name", "").lower() == name.lower():
            return channel
    raise SystemExit(f"No channel named {name!r} found in bot_config.json")


def find_rule(config: dict[str, Any], name: str) -> dict[str, Any]:
    for rule in config.get("keywords", []):
        if rule.get("name") == name:
            return rule
    raise SystemExit(f"No rule named {name!r} found in bot_config.json")


def find_first_ai_rule(config: dict[str, Any]) -> dict[str, Any]:
    for rule in config.get("keywords", []):
        if rule.get("response_mode") == "ai":
            return rule
    return find_rule(config, "topic_ai")


def set_bool(value: str) -> bool:
    value = value.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise argparse.ArgumentTypeError("Expected true/false")


def main() -> None:
    parser = argparse.ArgumentParser(description="Update local Kick bot config safely.")
    parser.add_argument("--channel", default="rampagejackson")
    parser.add_argument("--broadcaster-user-id", type=int)
    parser.add_argument("--dry-run", type=set_bool)
    parser.add_argument("--outbound-enabled", type=set_bool)
    parser.add_argument("--send-enabled", type=set_bool)
    parser.add_argument("--outbound-type", choices=["bot", "user"])
    parser.add_argument("--ai-enabled", type=set_bool)
    parser.add_argument("--ai-rule-enabled", type=set_bool)
    parser.add_argument("--ai-rule")
    parser.add_argument(
        "--ai-trigger",
        action="append",
        help="Replace the AI trigger list. Can be passed more than once.",
    )
    parser.add_argument("--personality")
    parser.add_argument("--response-chance", type=float)
    parser.add_argument("--ai-model")
    parser.add_argument("--max-sends-per-run", type=int)
    parser.add_argument("--confirm-before-send", type=set_bool)
    parser.add_argument(
        "--preset",
        choices=["ai-dry-run", "one-send-live"],
        help="Apply a safe group of settings.",
    )
    args = parser.parse_args()

    config = load_config()
    channel = find_channel(config, args.channel)
    ai_rule = find_rule(config, args.ai_rule) if args.ai_rule else find_first_ai_rule(config)

    if args.preset == "ai-dry-run":
        config["dry_run"] = True
        config.setdefault("outbound", {})["enabled"] = False
        config.setdefault("ai", {})["enabled"] = True
        ai_rule["enabled"] = True
        channel["send_enabled"] = False

    if args.preset == "one-send-live":
        config["dry_run"] = False
        outbound = config.setdefault("outbound", {})
        outbound["enabled"] = True
        outbound["type"] = "user"
        outbound["max_sends_per_run"] = 1
        outbound["confirm_before_send"] = True
        channel["send_enabled"] = True
        channel["max_sends_per_run"] = 1

    if args.broadcaster_user_id is not None:
        channel["broadcaster_user_id"] = args.broadcaster_user_id
    elif isinstance(channel.get("broadcaster_user_id"), str):
        channel["broadcaster_user_id"] = int(channel["broadcaster_user_id"])
    if args.dry_run is not None:
        config["dry_run"] = args.dry_run
    if args.outbound_enabled is not None:
        config.setdefault("outbound", {})["enabled"] = args.outbound_enabled
    if args.send_enabled is not None:
        channel["send_enabled"] = args.send_enabled
    if args.outbound_type is not None:
        config.setdefault("outbound", {})["type"] = args.outbound_type
    if args.ai_enabled is not None:
        config.setdefault("ai", {})["enabled"] = args.ai_enabled
    if args.ai_rule_enabled is not None:
        ai_rule["enabled"] = args.ai_rule_enabled
    if args.ai_trigger is not None:
        ai_rule["match"] = args.ai_trigger
    if args.personality is not None:
        ai_rule["personality"] = args.personality
    if args.response_chance is not None:
        ai_rule["response_chance"] = args.response_chance
    if args.ai_model is not None:
        config.setdefault("ai", {})["model"] = args.ai_model
    if args.max_sends_per_run is not None:
        config.setdefault("outbound", {})["max_sends_per_run"] = args.max_sends_per_run
        channel["max_sends_per_run"] = args.max_sends_per_run
    if args.confirm_before_send is not None:
        config.setdefault("outbound", {})["confirm_before_send"] = args.confirm_before_send

    save_config(config)

    print("Updated bot_config.json")
    print(f"Channel: {channel['name']}")
    print(f"Broadcaster user id: {channel.get('broadcaster_user_id')}")
    print(f"Dry run: {config.get('dry_run')}")
    print(f"Outbound enabled: {config.get('outbound', {}).get('enabled')}")
    print(f"Outbound type: {config.get('outbound', {}).get('type')}")
    print(f"Channel send enabled: {channel.get('send_enabled')}")
    print(f"AI enabled: {config.get('ai', {}).get('enabled')}")
    print(f"AI rule enabled: {ai_rule.get('enabled')}")
    print(f"AI rule: {ai_rule.get('name')}")
    print(f"AI trigger: {ai_rule.get('match')}")
    print(f"AI personality: {ai_rule.get('personality')}")
    print(f"AI response chance: {ai_rule.get('response_chance')}")


if __name__ == "__main__":
    main()
