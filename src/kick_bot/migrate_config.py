import json
from pathlib import Path
from typing import Any


CONFIG_PATH = Path("config/bot_config.json")

DEFAULT_PERSONALITIES = {
    "casual": (
        "Sound like a relaxed regular in chat. Keep replies casual, brief, "
        "and lightly funny when it fits. Do not be corporate or overly helpful."
    ),
    "hype": (
        "Sound like an energetic fight-stream chatter. Keep replies short, "
        "confident, and hype, without spamming caps."
    ),
    "analyst": (
        "Sound like a calm analyst. Make concise observations from context "
        "without pretending to know facts not present in chat."
    ),
}


def main() -> None:
    with CONFIG_PATH.open("r", encoding="utf-8") as config_file:
        config: dict[str, Any] = json.load(config_file)

    config.setdefault("personalities", DEFAULT_PERSONALITIES)
    for name, prompt in DEFAULT_PERSONALITIES.items():
        config["personalities"].setdefault(name, prompt)

    ignored_usernames = config.setdefault("ignored_usernames", [])
    if not any(str(username).lower() == "kickbot" for username in ignored_usernames):
        ignored_usernames.append("KickBot")

    for rule in config.get("keywords", []):
        if rule.get("response_mode") != "ai":
            continue

        if rule.get("name") == "ai_mention":
            rule["name"] = "topic_ai"

        rule.setdefault("personality", "casual")
        rule.setdefault("trigger_label", "topic-watch")
        rule.setdefault("response_chance", 1.0)
        rule["ai_instruction"] = (
            "Respond to the nearby chat context using the selected personality."
        )

    with CONFIG_PATH.open("w", encoding="utf-8") as config_file:
        json.dump(config, config_file, indent=2)
        config_file.write("\n")

    print("Migrated bot_config.json")


if __name__ == "__main__":
    main()
