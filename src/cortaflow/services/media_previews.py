"""Lightweight local media previews used by the editor timeline."""
from __future__ import annotations

import math
import struct
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from cortaflow.infrastructure.ffmpeg import find_executable, hidden_console_options


def build_media_preview_data(
    source: Path,
    duration_ms: int,
    progress=None,
    cancelled=None,
) -> dict[str, object]:
    """Generate small local thumbnails and normalized audio waveform samples."""
    if not source.is_file() or duration_ms <= 0:
        return {"thumbnails": [], "waveform": []}
    with TemporaryDirectory(prefix="cortaflow-preview-") as temporary:
        directory = Path(temporary)
        thumbnails: list[str] = []
        count = min(8, max(3, math.ceil(duration_ms / 10_000)))
        for index in range(count):
            if cancelled and cancelled.is_set():
                return {"thumbnails": [], "waveform": []}
            timestamp = duration_ms * index / max(1, count - 1) / 1000
            output = directory / f"thumb-{index}.jpg"
            command = [
                str(find_executable("ffmpeg")), "-hide_banner", "-loglevel", "error", "-y",
                "-ss", f"{timestamp:.3f}", "-i", str(source.resolve()),
                "-frames:v", "1", "-vf", "scale=240:-2", str(output),
            ]
            subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=False, **hidden_console_options())
            if output.is_file():
                # Copy bytes into a stable cache file owned by the caller's temp lifetime.
                stable = Path.cwd() / ".cortaflow-preview-cache"
                stable.mkdir(parents=True, exist_ok=True)
                destination = stable / f"{source.stem}-{index}-{duration_ms}.jpg"
                destination.write_bytes(output.read_bytes())
                thumbnails.append(str(destination))
        waveform = _extract_waveform(source, duration_ms)
        return {"thumbnails": thumbnails, "waveform": waveform}


def _extract_waveform(source: Path, duration_ms: int, samples: int = 240) -> list[float]:
    command = [
        str(find_executable("ffmpeg")), "-hide_banner", "-loglevel", "error",
        "-i", str(source.resolve()), "-vn", "-ac", "1", "-ar", "8000", "-f", "s16le", "pipe:1",
    ]
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, **hidden_console_options())
    raw = result.stdout
    if not raw:
        return []
    values = struct.unpack(f"<{len(raw) // 2}h", raw[: len(raw) // 2 * 2])
    bucket_size = max(1, len(values) // samples)
    waveform = []
    for start in range(0, len(values), bucket_size):
        bucket = values[start : start + bucket_size]
        waveform.append(min(1.0, sum(abs(value) for value in bucket) / max(1, len(bucket)) / 32768))
    return waveform[:samples]
