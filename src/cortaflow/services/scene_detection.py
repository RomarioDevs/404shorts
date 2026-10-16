"""Scene and silence detection with cooperative cancellation."""

import re
import subprocess
from collections.abc import Callable
from pathlib import Path
from threading import Event, Thread
from typing import Any

from scenedetect import AdaptiveDetector, SceneManager, open_video

from cortaflow.domain.analysis import TimeRange
from cortaflow.infrastructure.ffmpeg import find_executable, hidden_console_options


class AnalysisCancelled(RuntimeError):
    """Raised when media analysis is cooperatively cancelled."""


def detect_scenes(
    media_path: Path,
    progress: Callable[[dict[str, Any]], None] | None = None,
    cancelled: Event | None = None,
) -> list[TimeRange]:
    """Detect adaptive scene boundaries without blocking the UI thread."""
    media_path = media_path.resolve()
    if not media_path.is_file():
        raise FileNotFoundError(media_path)
    video = open_video(str(media_path))
    manager = SceneManager()
    manager.add_detector(AdaptiveDetector())
    error: list[Exception] = []

    def operation() -> None:
        try:
            manager.detect_scenes(video=video, show_progress=False)
        except Exception as exc:
            error.append(exc)

    if progress:
        progress({"status": "scenes", "message": "Detectando mudanças de cena…"})
    thread = Thread(target=operation, name="cortaflow-scene-detection", daemon=True)
    thread.start()
    while thread.is_alive():
        if cancelled and cancelled.wait(0.05):
            manager.stop()
            thread.join()
            raise AnalysisCancelled("Análise cancelada.")
        thread.join(0.05)
    if error:
        raise error[0]
    return [
        TimeRange(
            start_ms=round(start.get_seconds() * 1000),
            end_ms=round(end.get_seconds() * 1000),
        )
        for start, end in manager.get_scene_list()
        if end.get_seconds() > start.get_seconds()
    ]


def parse_silencedetect_output(output: str) -> list[TimeRange]:
    """Pair the ordered silence start/end events emitted by FFmpeg."""
    events = re.findall(r"silence_(start|end):\s*(-?[0-9.]+)", output)
    ranges: list[TimeRange] = []
    active_start: float | None = None
    for event, value in events:
        timestamp = max(0.0, float(value))
        if event == "start":
            active_start = timestamp
        elif active_start is not None and timestamp > active_start:
            ranges.append(
                TimeRange(start_ms=round(active_start * 1000), end_ms=round(timestamp * 1000))
            )
            active_start = None
    return ranges


def detect_silences(
    media_path: Path,
    noise_db: int = -35,
    minimum_seconds: float = 0.7,
    progress: Callable[[dict[str, Any]], None] | None = None,
    cancelled: Event | None = None,
) -> list[TimeRange]:
    """Run FFmpeg silencedetect safely and allow cancellation."""
    media_path = media_path.resolve()
    if not media_path.is_file():
        raise FileNotFoundError(media_path)
    if not -100 <= noise_db <= 0:
        raise ValueError("O limiar de silêncio deve estar entre -100 e 0 dB.")
    if minimum_seconds <= 0:
        raise ValueError("A duração mínima de silêncio deve ser positiva.")
    if progress:
        progress({"status": "silences", "message": "Detectando silêncios…"})
    command = [
        str(find_executable("ffmpeg")), "-hide_banner", "-nostdin", "-i", str(media_path),
        "-af", f"silencedetect=noise={noise_db}dB:d={minimum_seconds}", "-f", "null", "-",
    ]
    process = subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        shell=False,
        **hidden_console_options(),
    )
    communication: list[tuple[str, str]] = []

    def collect_output() -> None:
        communication.append(process.communicate())

    reader = Thread(target=collect_output, name="cortaflow-silence-output", daemon=True)
    reader.start()
    while reader.is_alive():
        if cancelled and cancelled.wait(0.05):
            process.terminate()
            reader.join(timeout=5)
            if reader.is_alive():
                process.kill()
                reader.join()
            raise AnalysisCancelled("Análise cancelada.")
        reader.join(0.05)
    _, stderr = communication[0]
    if process.returncode != 0:
        raise RuntimeError(f"FFmpeg falhou ao detectar silêncios: {stderr[-500:]}")
    return parse_silencedetect_output(stderr)
