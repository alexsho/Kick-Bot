from ai_responder import AIRequest, OllamaResponder
from kick_pusher_listener import load_config


def main() -> None:
    config = load_config()

    responder = OllamaResponder(
        base_url=config.ai.base_url,
        model=config.ai.model,
        system_prompt=config.ai.system_prompt,
        timeout_seconds=config.ai.timeout_seconds,
        max_response_chars=config.ai.max_response_chars,
        temperature=config.ai.temperature,
        num_predict=config.ai.num_predict,
    )

    response = responder.generate(
        AIRequest(
            channel=config.channels[0].name,
            username="TestUser",
            content="pineapple what should we talk about?",
            matched_phrase="pineapple",
            trigger_label="topic-watch",
            personality_name="casual",
            personality_prompt=config.personalities["casual"],
            instruction="Respond to the nearby chat context using the selected personality.",
            recent_chat=[
                "ViewerOne: stream has been chill today",
                "ViewerTwo: anyone watching the fight later?",
                "TestUser: pineapple what should we talk about?",
            ],
        )
    )

    if response.ok:
        print(response.text)
    else:
        raise SystemExit(f"AI test failed: {response.error}")


if __name__ == "__main__":
    main()
