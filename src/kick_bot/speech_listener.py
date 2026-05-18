import argparse
import asyncio
import subprocess
import sys
import time
from typing import Optional

from faster_whisper import WhisperModel

from .listener import (
    ChatContext,
    ChatMessage,
    KeywordEngine,
    SendLimiter,
    build_response_text,
    load_config,
    maybe_send_response,
)
from .ai_responder import OllamaResponder
from .chat_sender import KickChatSender


SAMPLE_RATE = 16000
BYTES_PER_SAMPLE = 2


def get_stream_url(channel: str) -> str:
    """
    Uses yt-dlp to resolve kick.com/<channel> into a playable stream URL.
    """
    page_url = f"https://kick.com/{channel}"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "yt_dlp",
            "-g",
            "--impersonate",
            "Chrome-110:Windows-10",
            page_url,
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        raise RuntimeError(
            "yt-dlp failed to resolve stream URL:\n"
            f"STDOUT:\n{result.stdout}\n\nSTDERR:\n{result.stderr}"
        )

    urls = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if not urls:
        raise RuntimeError("yt-dlp returned no stream URL.")

    return urls[0]


def start_ffmpeg_audio(stream_url: str) -> subprocess.Popen:
    """
    Starts ffmpeg and outputs raw 16 kHz mono PCM audio to stdout.
    """
    return subprocess.Popen(
        [
            r"C:\Users\Alexander\AppData\Local\Microsoft\WinGet\Links\ffmpeg.exe",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            stream_url,
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(SAMPLE_RATE),
            "-f",
            "s16le",
            "pipe:1",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def pcm_to_float32(pcm_bytes: bytes):
    """
    Converts signed 16-bit PCM bytes to float32 numpy array for faster-whisper.
    """
    import numpy as np

    audio = np.frombuffer(pcm_bytes, dtype=np.int16).astype("float32")
    audio /= 32768.0
    return audio


def transcribe_chunk(model: WhisperModel, pcm_bytes: bytes) -> str:
    audio = pcm_to_float32(pcm_bytes)

    segments, info = model.transcribe(
        audio,
        language="en",
        beam_size=1,
        vad_filter=True,
        condition_on_previous_text=False,
    )

    text_parts = []
    for segment in segments:
        text = segment.text.strip()
        if text:
            text_parts.append(text)

    return " ".join(text_parts).strip()


async def process_transcript(
    transcript: str,
    channel_name: str,
    username: str,
    config,
    keyword_engine: KeywordEngine,
    sender: Optional[KickChatSender],
    send_limiter: SendLimiter,
    ai_responder: Optional[OllamaResponder],
    chat_context: ChatContext,
) -> None:
    if not transcript:
        return

    if not config.channels:
        print("[SPEECH] No enabled channel configured.")
        return

    channel = next(
        (item for item in config.channels if item.name.lower() == channel_name.lower()),
        config.channels[0],
    )

    print(f"[speech/{channel.name}] {username}: {transcript}")

    chat_context.add(channel.name, username, transcript)

    chat_message = ChatMessage(
        message_id=None,
        username=username,
        content=transcript,
        raw={
            "source": "speech_to_text",
            "timestamp": time.time(),
        },
    )

    trigger = keyword_engine.match(channel.name, transcript)
    if not trigger:
        return

    response_text = await build_response_text(
        config=config,
        ai_responder=ai_responder,
        chat_context=chat_context,
        channel=channel,
        chat_message=chat_message,
        trigger=trigger,
    )

    if not response_text:
        return

    print(
        f"[SPEECH AI CANDIDATE] {channel.name} "
        f"{trigger.rule_name}/{trigger.matched_phrase}: {response_text}"
    )

    await maybe_send_response(
        config=config,
        sender=sender,
        send_limiter=send_limiter,
        channel=channel,
        response=response_text,
    )


async def run_speech_listener(
    channel_name: str,
    chunk_seconds: int = 8,
    whisper_model: str = "small",
    whisper_device: str = "cpu",
    username: str = "StreamAudio",
    event_callback=None,
    stop_event: Optional[asyncio.Event] = None,
) -> None:
    config = load_config()

    keyword_engine = KeywordEngine(config.rules)
    send_limiter = SendLimiter(config.outbound.max_sends_per_run)

    sender = (
        KickChatSender(config.outbound.token_path)
        if config.outbound.enabled and not config.dry_run
        else None
    )

    ai_responder = (
        OllamaResponder(
            base_url=config.ai.base_url,
            model=config.ai.model,
            system_prompt=config.ai.system_prompt,
            timeout_seconds=config.ai.timeout_seconds,
            max_response_chars=config.ai.max_response_chars,
            temperature=config.ai.temperature,
            num_predict=config.ai.num_predict,
        )
        if config.ai.enabled
        else None
    )

    chat_context = ChatContext(config.ai.max_context_messages)

    async def emit(event: dict) -> None:
        if event_callback:
            await event_callback(event)

    await emit({
        "type": "status",
        "level": "info",
        "message": f"Speech listener loading Whisper model {whisper_model} on {whisper_device}",
    })

    print(f"[SPEECH] Loading Whisper model: {whisper_model} on {whisper_device}")
    model = WhisperModel(
        whisper_model,
        device=whisper_device,
        compute_type="int8" if whisper_device == "cpu" else "float16",
    )

    await emit({
        "type": "status",
        "level": "info",
        "message": f"Speech listener resolving stream URL for kick.com/{channel_name}",
    })

    print(f"[SPEECH] Resolving stream URL for kick.com/{channel_name}")
    stream_url = get_stream_url(channel_name)

    print("[SPEECH] Starting ffmpeg audio pipe")
    process = start_ffmpeg_audio(stream_url)

    if process.stdout is None:
        raise RuntimeError("ffmpeg stdout pipe was not created.")

    bytes_per_chunk = SAMPLE_RATE * BYTES_PER_SAMPLE * chunk_seconds

    await emit({
        "type": "status",
        "level": "info",
        "message": f"Speech listener started for {channel_name}",
    })

    print(
        f"[SPEECH] Listening to stream audio. "
        f"chunk_seconds={chunk_seconds}, dry_run={config.dry_run}"
    )

    if stop_event is None:
        stop_event = asyncio.Event()

    try:
        while not stop_event.is_set():
            pcm_bytes = await asyncio.to_thread(process.stdout.read, bytes_per_chunk)

            if not pcm_bytes:
                raise RuntimeError("ffmpeg audio stream ended.")

            transcript = await asyncio.to_thread(transcribe_chunk, model, pcm_bytes)

            if not transcript:
                continue

            channel = next(
                (item for item in config.channels if item.name.lower() == channel_name.lower()),
                config.channels[0],
            )

            print(f"[speech/{channel.name}] {username}: {transcript}")

            await emit({
                "type": "speech",
                "timestamp": time.time(),
                "channel": channel.name,
                "username": username,
                "content": transcript,
            })

            chat_context.add(channel.name, username, transcript)

            chat_message = ChatMessage(
                message_id=None,
                username=username,
                content=transcript,
                raw={
                    "source": "speech_to_text",
                    "timestamp": time.time(),
                },
            )

            trigger = keyword_engine.match(channel.name, transcript)

            if not trigger:
                continue

            await emit({
                "type": "status",
                "level": "info",
                "message": f"Speech trigger matched: {trigger.rule_name} / {trigger.matched_phrase}",
            })

            response_text = await build_response_text(
                config=config,
                ai_responder=ai_responder,
                chat_context=chat_context,
                channel=channel,
                chat_message=chat_message,
                trigger=trigger,
            )

            if not response_text:
                continue

            print(
                f"[SPEECH AI CANDIDATE] {channel.name} "
                f"{trigger.rule_name}/{trigger.matched_phrase}: {response_text}"
            )

            await emit({
                "type": "speech_trigger",
                "timestamp": time.time(),
                "channel": channel.name,
                "username": username,
                "content": transcript,
                "rule_name": trigger.rule_name,
                "matched_phrase": trigger.matched_phrase,
                "response_mode": trigger.response_mode,
                "response": response_text,
                "dry_run": config.dry_run,
            })

            await maybe_send_response(
                config=config,
                sender=sender,
                send_limiter=send_limiter,
                channel=channel,
                response=response_text,
            )

    finally:
        await emit({
            "type": "status",
            "level": "info",
            "message": f"Speech listener stopped for {channel_name}",
        })
        process.kill()


def main() -> None:
    parser = argparse.ArgumentParser(description="Local Kick stream speech-to-text listener.")
    parser.add_argument("--channel", default="larrywheels")
    parser.add_argument("--chunk-seconds", type=int, default=8)
    parser.add_argument("--model", default="base")
    parser.add_argument("--device", choices=["cpu", "cuda"], default="cpu")
    parser.add_argument("--username", default="StreamAudio")
    args = parser.parse_args()

    asyncio.run(
        run_speech_listener(
            channel_name=args.channel,
            chunk_seconds=args.chunk_seconds,
            whisper_model=args.model,
            whisper_device=args.device,
            username=args.username,
        )
    )


if __name__ == "__main__":
    main()