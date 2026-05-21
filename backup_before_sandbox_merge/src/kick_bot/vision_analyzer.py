import base64
import re
from dataclasses import dataclass

import requests


@dataclass(frozen=True)
class VisionAnalysisResult:
    ok: bool
    description: str = ""
    error: str = ""


def _clean_model_text(text: str) -> str:
    """
    Remove control characters and reject obvious token-garbage output.
    """
    text = text.replace("\x00", "")
    text = re.sub(r"[\x01-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    text = re.sub(r"\s+", " ", text).strip()

    # Ollama/LLaVA can occasionally return raw-looking special tokens.
    text = text.replace("<s>", "").replace("</s>", "").replace("<unk>", "").strip()

    return text


def _looks_like_garbage(text: str) -> bool:
    if not text:
        return True

    # Count normal readable characters versus symbol junk.
    readable = sum(ch.isalnum() or ch.isspace() or ch in ".,!?;:'\"()-/[]" for ch in text)
    ratio = readable / max(1, len(text))

    if ratio < 0.65:
        return True

    # If there are almost no letters, it is probably not a useful description.
    letters = sum(ch.isalpha() for ch in text)
    if letters < 5:
        return True

    return False


class VisionAnalyzer:
    """
    Analyzes stream screenshots using a local Ollama vision model such as llava.
    """

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:11434",
        model: str = "llava",
        timeout_seconds: float = 60,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds

    def analyze(self, image_bytes: bytes, media_type: str = "image/jpeg") -> VisionAnalysisResult:
        if not image_bytes:
            return VisionAnalysisResult(ok=False, error="image_bytes is empty")

        if media_type == "image/jpeg" and not (
            image_bytes.startswith(b"\xff\xd8") and image_bytes.endswith(b"\xff\xd9")
        ):
            return VisionAnalysisResult(ok=False, error="image_bytes is not a complete JPEG")

        image_base64 = base64.b64encode(image_bytes).decode("ascii")

        try:
            response = requests.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": (
                        "You are looking at one livestream screenshot. "
                        "Describe only what is visible in one short plain-English sentence. "
                        "Do not invent names, backstory, drama, or events outside the image."
                    ),
                    "images": [image_base64],
                    "stream": False,
                    "options": {
                        "temperature": 0.1,
                        "num_predict": 60,
                    },
                },
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            return VisionAnalysisResult(
                ok=False,
                error=(
                    f"Ollama request failed: {str(exc)}. "
                    f"Is Ollama running and is '{self.model}' installed?"
                ),
            )

        try:
            data = response.json()
        except Exception as exc:
            return VisionAnalysisResult(ok=False, error=f"Failed to parse Ollama JSON: {str(exc)}")

        description = _clean_model_text(str(data.get("response", "")))

        if _looks_like_garbage(description):
            return VisionAnalysisResult(
                ok=False,
                error=f"Ollama returned unreadable vision output: {description[:80]!r}",
            )

        return VisionAnalysisResult(ok=True, description=description)
