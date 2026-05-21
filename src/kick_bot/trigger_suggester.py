import argparse
import json
import re
import urllib.request
import urllib.error
from collections import Counter
from pathlib import Path
from typing import Any


DEFAULT_STOPWORDS = {
    "the", "and", "you", "that", "this", "with", "for", "are", "was", "were",
    "have", "has", "had", "not", "but", "what", "when", "where", "why", "how",
    "from", "they", "them", "your", "just", "like", "about", "into", "out",
    "its", "it's", "dont", "don't", "does", "did", "then", "than", "can",
    "cant", "can't", "will", "would", "could", "should", "there", "their",
    "here", "bro", "lol", "lmao", "lmfao", "kekw", "kekleo", "lulw",
    "true", "real", "yeah", "yes", "nope", "nah", "oh", "ah", "ha",
    "emote", "emoji", "chat", "stream", "thing", "things", "people",
    "someone", "something", "really", "actually", "still", "even",
}

SPAM_PATTERNS = [
    r"\[emote:\d+:[^\]]+\]",
    r"https?://\S+",
    r"@\w+",
]

JUNK_TRIGGER_PATTERNS = [
    r"^\d+$",
    r"^[a-z]$",
    r"^(lol|lmao|lmfao|kekw|lulw|true|real|yeah|nope|nah)$",
]


def clean_text(text: str) -> str:
    text = text.lower()

    for pattern in SPAM_PATTERNS:
        text = re.sub(pattern, " ", text)

    text = re.sub(r"[^a-z0-9\s'\-]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def is_junk_trigger(text: str) -> bool:
    text = text.strip().lower()

    if not text:
        return True

    for pattern in JUNK_TRIGGER_PATTERNS:
        if re.match(pattern, text):
            return True

    if len(text) < 3:
        return True

    return False


def load_messages(path: Path, channel: str | None = None, max_messages: int = 500) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []

    if not path.exists():
        raise FileNotFoundError(f"Could not find {path}")

    if path.suffix.lower() == ".jsonl":
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue

                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue

                item_channel = str(item.get("channel", "")).lower()
                if channel and item_channel != channel.lower():
                    continue

                username = str(item.get("username") or item.get("user") or "unknown")
                content = str(item.get("content") or item.get("message") or item.get("text") or "")

                if content:
                    messages.append({
                        "channel": item_channel,
                        "username": username,
                        "content": content,
                    })
    else:
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.strip():
                messages.append({
                    "channel": channel or "unknown",
                    "username": "unknown",
                    "content": line.strip(),
                })

    return messages[-max_messages:]


def make_ngrams(words: list[str], n: int) -> list[str]:
    return [" ".join(words[i:i + n]) for i in range(len(words) - n + 1)]


def frequency_suggestions(messages: list[dict[str, str]], top_words: int = 40, top_phrases: int = 40) -> dict[str, list[tuple[str, int]]]:
    word_counter = Counter()
    phrase_counter = Counter()

    for message in messages:
        cleaned = clean_text(message["content"])

        words = [
            word for word in cleaned.split()
            if len(word) >= 4
            and word not in DEFAULT_STOPWORDS
            and not word.isdigit()
        ]

        word_counter.update(words)

        for n in (2, 3):
            for phrase in make_ngrams(words, n):
                if not is_junk_trigger(phrase):
                    phrase_counter[phrase] += 1

    common_words = [
        item for item in word_counter.most_common(top_words)
        if item[1] >= 2 and not is_junk_trigger(item[0])
    ]

    common_phrases = [
        item for item in phrase_counter.most_common(top_phrases)
        if item[1] >= 2 and not is_junk_trigger(item[0])
    ]

    return {
        "words": common_words,
        "phrases": common_phrases,
    }


def call_ollama(
    prompt: str,
    model: str = "llama3.2",
    base_url: str = "http://127.0.0.1:11434",
    timeout_seconds: int = 60,
) -> str:
    url = f"{base_url.rstrip('/')}/api/generate"

    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.2,
            "num_predict": 700,
        },
    }

    data = json.dumps(payload).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            body = response.read().decode("utf-8")
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Ollama request failed: {exc}") from exc

    parsed = json.loads(body)
    return str(parsed.get("response", "")).strip()


def extract_json_object(text: str) -> dict[str, Any]:
    """
    Handles models that wrap JSON with explanation text.
    """
    text = text.strip()

    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text, flags=re.IGNORECASE).strip()
        text = re.sub(r"```$", "", text).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")

    if start == -1 or end == -1 or end <= start:
        raise ValueError("Could not find JSON object in Ollama response.")

    return json.loads(text[start:end + 1])


def build_ollama_prompt(
    messages: list[dict[str, str]],
    frequency: dict[str, list[tuple[str, int]]],
    channel: str | None,
) -> str:
    recent_lines = []
    for item in messages[-120:]:
        content = item["content"].replace("\n", " ").strip()
        username = item["username"]
        recent_lines.append(f"{username}: {content}")

    freq_words = ", ".join(word for word, _ in frequency["words"][:30])
    freq_phrases = ", ".join(phrase for phrase, _ in frequency["phrases"][:30])

    channel_name = channel or "mixed channels"

    return f"""
You are helping configure a local livestream chat bot trigger system.

Channel/context: {channel_name}

Goal:
Generate useful trigger words and phrases that would cause a bot to respond naturally to the current stream topic.

Rules:
- Return ONLY valid JSON.
- Do not include markdown.
- Do not include explanations outside JSON.
- Prefer specific topics over generic words.
- Avoid pure emotes like KEKW, LULW, emoji names, "lol", "true", "real".
- Avoid usernames unless the username is a public figure/topic being discussed.
- Include both chat-trigger topics and speech-to-text-trigger topics.
- Avoid hateful slurs or explicit insults as triggers.
- Avoid triggers that are too broad unless they are central to the stream.
- Good triggers are 1 to 4 words.
- Include "confidence" from 0.0 to 1.0.
- Include a short reason for each trigger.
- Group suggestions by category.

Frequency candidates from logs:
Single words: {freq_words}

Repeated phrases: {freq_phrases}

Recent chat/transcript sample:
{chr(10).join(recent_lines)}

Return this exact JSON shape:
{{
  "channel": "{channel_name}",
  "summary": "one sentence summary of current stream topics",
  "recommended_triggers": [
    {{
      "trigger": "example",
      "category": "topic/person/event/game/reaction/speech",
      "confidence": 0.9,
      "reason": "short reason"
    }}
  ],
  "avoid_triggers": [
    {{
      "trigger": "example",
      "reason": "why it is too broad/spammy/risky"
    }}
  ],
  "copy_paste_trigger_list": [
    "trigger one",
    "trigger two"
  ]
}}
""".strip()


def ollama_suggestions(
    messages: list[dict[str, str]],
    frequency: dict[str, list[tuple[str, int]]],
    channel: str | None,
    model: str,
    base_url: str,
) -> dict[str, Any]:
    prompt = build_ollama_prompt(messages, frequency, channel)
    response = call_ollama(prompt=prompt, model=model, base_url=base_url)
    return extract_json_object(response)


def merge_trigger_lists(
    frequency: dict[str, list[tuple[str, int]]],
    ai_result: dict[str, Any] | None,
    max_items: int = 40,
) -> list[str]:
    triggers: list[str] = []

    if ai_result:
        for item in ai_result.get("copy_paste_trigger_list", []):
            trigger = str(item).strip().lower()
            if trigger and not is_junk_trigger(trigger) and trigger not in triggers:
                triggers.append(trigger)

        for item in ai_result.get("recommended_triggers", []):
            trigger = str(item.get("trigger", "")).strip().lower()
            if trigger and not is_junk_trigger(trigger) and trigger not in triggers:
                triggers.append(trigger)

    for word, _ in frequency["words"]:
        if word not in triggers and not is_junk_trigger(word):
            triggers.append(word)

    for phrase, _ in frequency["phrases"]:
        if phrase not in triggers and not is_junk_trigger(phrase):
            triggers.append(phrase)

    return triggers[:max_items]


def print_frequency_results(frequency: dict[str, list[tuple[str, int]]]) -> None:
    print("\n=== Frequency candidates: single words ===\n")
    for word, count in frequency["words"]:
        print(f"{word}  ({count})")

    print("\n=== Frequency candidates: phrases ===\n")
    for phrase, count in frequency["phrases"]:
        print(f"{phrase}  ({count})")


def print_ai_results(ai_result: dict[str, Any]) -> None:
    print("\n=== AI topic summary ===\n")
    print(ai_result.get("summary", ""))

    print("\n=== AI recommended triggers ===\n")
    for item in ai_result.get("recommended_triggers", []):
        trigger = item.get("trigger")
        category = item.get("category", "topic")
        confidence = item.get("confidence", "")
        reason = item.get("reason", "")
        print(f"{trigger}  [{category}, confidence={confidence}] - {reason}")

    print("\n=== Avoid these triggers ===\n")
    for item in ai_result.get("avoid_triggers", []):
        trigger = item.get("trigger")
        reason = item.get("reason", "")
        print(f"{trigger} - {reason}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Suggest smart trigger words from Kick bot logs.")
    parser.add_argument("--path", default="logs/chat.jsonl")
    parser.add_argument("--channel", default=None)
    parser.add_argument("--max-messages", type=int, default=500)
    parser.add_argument("--top-words", type=int, default=40)
    parser.add_argument("--top-phrases", type=int, default=40)
    parser.add_argument("--model", default="llama3.2")
    parser.add_argument("--base-url", default="http://127.0.0.1:11434")
    parser.add_argument("--no-ai", action="store_true")
    parser.add_argument("--json-out", default=None, help="Optional path to write full suggestion JSON.")

    args = parser.parse_args()

    messages = load_messages(
        Path(args.path),
        channel=args.channel,
        max_messages=args.max_messages,
    )

    if not messages:
        print("No messages found.")
        return

    frequency = frequency_suggestions(
        messages,
        top_words=args.top_words,
        top_phrases=args.top_phrases,
    )

    print_frequency_results(frequency)

    ai_result = None

    if not args.no_ai:
        try:
            ai_result = ollama_suggestions(
                messages=messages,
                frequency=frequency,
                channel=args.channel,
                model=args.model,
                base_url=args.base_url,
            )
            print_ai_results(ai_result)
        except Exception as exc:
            print("\nAI suggestion failed. Falling back to frequency-only suggestions.")
            print(f"Reason: {exc}")

    merged = merge_trigger_lists(frequency, ai_result)

    output = {
        "channel": args.channel,
        "message_count": len(messages),
        "frequency": {
            "words": frequency["words"],
            "phrases": frequency["phrases"],
        },
        "ai": ai_result,
        "copy_paste_trigger_list": merged,
    }

    print("\n=== Copy/paste trigger list ===\n")
    for item in merged:
        print(item)

    if args.json_out:
        out_path = Path(args.json_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(output, indent=2), encoding="utf-8")
        print(f"\nWrote suggestion JSON to: {out_path}")


if __name__ == "__main__":
    main()


# ---------------------------------------------------------------------------
# Smart trigger filtering
# ---------------------------------------------------------------------------
# This wrapper layer keeps trigger suggestions from filling topic_ai with weak
# single-word triggers like "good", "more", "right", "dude", "going", etc.
# It also protects direct mention behavior by blocking alexsho/@alexsho from
# general topic suggestions.

SMART_TRIGGER_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "been", "being", "but", "by",
    "can", "cant", "can't", "could", "did", "do", "does", "doing", "done",
    "for", "from", "get", "gets", "getting", "go", "goes", "going", "gone",
    "good", "got", "gonna", "had", "has", "have", "having", "he", "her",
    "here", "him", "his", "how", "i", "im", "i'm", "in", "is", "it", "its",
    "it's", "just", "know", "like", "lol", "lmao", "lmfao", "more", "much",
    "my", "need", "no", "not", "now", "of", "on", "or", "our", "out",
    "right", "say", "says", "see", "seeing", "seen", "she", "shit", "so",
    "some", "someone", "something", "still", "that", "the", "them", "then",
    "there", "they", "thing", "things", "this", "to", "too", "up", "want",
    "wants", "was", "we", "well", "were", "what", "when", "where", "who",
    "why", "with", "yeah", "yes", "you", "your", "youre", "you're", "dude",
    "bro", "chat", "stream", "time", "back", "look", "looks", "wait",
    "take", "takes", "make", "makes", "start", "started", "over", "under",
    "really", "actually", "basically", "literally", "okay", "ok",
}

SMART_TRIGGER_BLOCKED = {
    "alexsho", "@alexsho",
    "adin", "adinross",
    "larry", "larrywheels",
    "asmongold", "asmongold247",
    "clavicular",
    "stevewilldoit",
    "fugglet",
}

def _smart_words(trigger: str) -> list[str]:
    cleaned = re.sub(r"[^a-zA-Z0-9\s'\-@]", " ", str(trigger).lower())
    return [part.strip(".,!?;:'\"()[]{}") for part in cleaned.split() if part.strip()]

def is_smart_trigger_candidate(trigger: str) -> bool:
    normalized = " ".join(str(trigger).strip().split())
    lowered = normalized.lower()

    if not lowered:
        return False

    if lowered in SMART_TRIGGER_BLOCKED:
        return False

    if lowered.startswith("[emote:") or "http://" in lowered or "https://" in lowered:
        return False

    if re.fullmatch(r"\d+", lowered):
        return False

    words = _smart_words(lowered)

    if not words:
        return False

    if any(word in SMART_TRIGGER_BLOCKED for word in words):
        return False

    # Reject weak single-word triggers.
    if len(words) == 1:
        word = words[0]
        if word in SMART_TRIGGER_STOPWORDS:
            return False
        if len(word) < 5:
            return False

    # Reject phrases that are mostly filler.
    filler = sum(1 for word in words if word in SMART_TRIGGER_STOPWORDS)
    if len(words) >= 2 and filler / len(words) > 0.5:
        return False

    # Reject overly long phrase triggers.
    if len(words) > 4:
        return False

    return True

def smart_filter_triggers(triggers: list[str], max_items: int = 40) -> list[str]:
    seen: set[str] = set()
    accepted: list[str] = []

    # Prefer meaningful phrases first, then distinctive single words.
    ordered = sorted(
        [str(item).strip() for item in triggers if str(item).strip()],
        key=lambda item: (
            len(item.split()) < 2,
            -len(item.split()),
            len(item),
        ),
    )

    for trigger in ordered:
        normalized = " ".join(trigger.split())
        key = normalized.lower()

        if key in seen:
            continue

        if not is_smart_trigger_candidate(normalized):
            continue

        seen.add(key)
        accepted.append(normalized)

        if len(accepted) >= max_items:
            break

    return accepted

def _smart_filter_frequency_items(items: list[tuple[str, int]], max_items: int) -> list[tuple[str, int]]:
    filtered: list[tuple[str, int]] = []
    seen: set[str] = set()

    for trigger, count in items:
        key = trigger.lower().strip()
        if key in seen:
            continue
        if not is_smart_trigger_candidate(trigger):
            continue
        seen.add(key)
        filtered.append((trigger, count))
        if len(filtered) >= max_items:
            break

    return filtered

_original_frequency_suggestions = frequency_suggestions

def frequency_suggestions(messages: list[dict[str, str]], top_words: int = 40, top_phrases: int = 40) -> dict[str, list[tuple[str, int]]]:
    raw = _original_frequency_suggestions(messages, top_words=top_words, top_phrases=top_phrases)
    return {
        "words": _smart_filter_frequency_items(raw.get("words", []), top_words),
        "phrases": _smart_filter_frequency_items(raw.get("phrases", []), top_phrases),
    }

_original_merge_trigger_lists = merge_trigger_lists

def merge_trigger_lists(frequency: dict[str, list[tuple[str, int]]], ai_result: dict[str, Any] | None = None) -> list[str]:
    merged = _original_merge_trigger_lists(frequency, ai_result)
    return smart_filter_triggers(merged)

