import argparse
import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, Optional

from .vision_analyzer import VisionAnalyzer
from .listener import load_config
from .stream_context import StreamContext


def resolve_ffmpeg_executable() -> str:
    configured = os.getenv("FFMPEG_EXE", "").strip()
    if configured:
        return configured

    import shutil

    found = shutil.which("ffmpeg")
    if found:
        return found

    winget_link = Path.home() / "AppData" / "Local" / "Microsoft" / "WinGet" / "Links" / "ffmpeg.exe"
    if winget_link.exists():
        return str(winget_link)

    return "ffmpeg"


def get_stream_url(channel: str) -> str:
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


def capture_single_jpeg_frame(stream_url: str) -> bytes:
    """
    Capture exactly one clean JPEG frame.

    This replaces the older continuous MJPEG pipe approach. The continuous pipe
    can create bad/incomplete frames if parsing gets out of sync, which causes
    LLaVA/Ollama to return garbage symbols.
    """
    result = subprocess.run(
        [
            resolve_ffmpeg_executable(),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            stream_url,
            "-an",
            "-frames:v",
            "1",
            "-vf",
            "scale=640:-1",
            "-f",
            "image2pipe",
            "-vcodec",
            "mjpeg",
            "pipe:1",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    if result.returncode != 0:
        raise RuntimeError(
            "ffmpeg failed to capture a video frame:\n"
            f"{result.stderr.decode('utf-8', errors='replace')}"
        )

    frame = result.stdout

    if not frame:
        raise RuntimeError("ffmpeg returned an empty frame")

    if not (frame.startswith(b"\xff\xd8") and frame.endswith(b"\xff\xd9")):
        raise RuntimeError(
            f"ffmpeg returned invalid JPEG bytes: size={len(frame)}, "
            f"start={frame[:4]!r}, end={frame[-4:]!r}"
        )

    return frame


async def run_vision_listener(
    channel_name: str,
    frame_interval_seconds: int = 4,
    event_callback: Optional[Callable] = None,
    stop_event: Optional[asyncio.Event] = None,
    stream_context: Optional[StreamContext] = None,
) -> None:
    """
    Capture video frames from a Kick stream and analyze them with local Ollama/LLaVA.
    Adds visual summaries to stream_context so chat + speech + vision can be used together.
    """
    config = load_config()

    if not config.ai.enabled:
        print("[VISION] Vision analysis is disabled because ai.enabled=false")
        return

    if not config.vision.enabled:
        print("[VISION] Vision analysis is disabled because vision.enabled=false")
        return

    async def emit(event: dict) -> None:
        if event_callback:
            await event_callback(event)

    if stream_context is None:
        stream_context = StreamContext(config.ai.max_context_messages * 3)

    analyzer = VisionAnalyzer(
        base_url=config.ai.base_url,
        model=config.vision.model,
        timeout_seconds=config.ai.timeout_seconds,
    )

    await emit({
        "type": "status",
        "level": "info",
        "message": f"Vision listener resolving stream URL for kick.com/{channel_name}",
    })

    try:
        print(f"[VISION] Resolving stream URL for kick.com/{channel_name}")
        stream_url = await asyncio.to_thread(get_stream_url, channel_name)
    except RuntimeError as exc:
        message = f"Vision listener failed to resolve stream: {str(exc)}"
        print(f"[VISION] {message}")
        await emit({"type": "status", "level": "error", "message": message})
        return

    print("[VISION] Starting ffmpeg video capture")
    await emit({
        "type": "status",
        "level": "info",
        "message": f"Vision listener started for {channel_name}",
    })

    print(
        f"[VISION] Listening to stream video. "
        f"frame_interval_seconds={frame_interval_seconds}, dry_run={config.dry_run}"
    )

    if stop_event is None:
        stop_event = asyncio.Event()

    frame_count = 0

    while not stop_event.is_set():
        frame_count += 1

        try:
            print(f"[VISION] Analyzing frame #{frame_count}")

            frame_bytes = await asyncio.to_thread(capture_single_jpeg_frame, stream_url)
            result = await asyncio.to_thread(analyzer.analyze, frame_bytes, "image/jpeg")

            if result.ok:
                print(f"[VISION] Frame summary: {result.description}")

                if stream_context:
                    if hasattr(stream_context, "add_vision"):
                        stream_context.add_vision(channel_name, result.description)
                    elif hasattr(stream_context, "add_speech"):
                        stream_context.add_speech(
                            channel_name,
                            f"[vision] {result.description}",
                            username="StreamVision",
                        )

                await emit({
                    "type": "vision",
                    "timestamp": time.time(),
                    "channel": channel_name,
                    "username": "StreamVision",
                    "content": result.description,
                    "description": result.description,
                    "frame_number": frame_count,
                })
            else:
                print(f"[VISION] Analysis failed: {result.error}")
                await emit({
                    "type": "status",
                    "level": "warning",
                    "message": f"Vision analysis failed: {result.error}",
                })

        except Exception as exc:
            message = f"Vision listener error: {str(exc)}"
            print(f"[VISION] {message}")
            await emit({"type": "status", "level": "error", "message": message})

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=max(1, frame_interval_seconds))
        except asyncio.TimeoutError:
            pass

    print(f"[VISION] Vision listener stopped for {channel_name}")
    await emit({
        "type": "status",
        "level": "info",
        "message": f"Vision listener stopped for {channel_name}",
    })


def main() -> None:
    parser = argparse.ArgumentParser(description="Local Kick stream video vision listener.")
    parser.add_argument("--channel", default="larrywheels")
    parser.add_argument("--frame-interval", type=int, default=4, help="Seconds between frame analyses")
    args = parser.parse_args()

    asyncio.run(
        run_vision_listener(
            channel_name=args.channel,
            frame_interval_seconds=args.frame_interval,
        )
    )


if __name__ == "__main__":
    main()
