"""Lightweight local media previews used by the editor timeline."""
from __future__ import annotations

import math
import shutil
import subprocess
from threading import Lock
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np

from cortaflow.infrastructure.ffmpeg import find_executable, hidden_console_options


_preview_cache_lock = Lock()
_preview_cache_shutting_down = False


def _remove_media_preview_cache() -> None:
    cache = Path.cwd() / ".cortaflow-preview-cache"
    try:
        if cache.is_symlink() or cache.is_file():
            cache.unlink(missing_ok=True)
        elif cache.exists():
            shutil.rmtree(cache)
    except OSError:
        # Cache files are disposable; a locked file should not prevent app startup.
        pass


def clear_media_preview_cache() -> None:
    """Remove generated timeline thumbnails from the current workspace."""
    global _preview_cache_shutting_down
    with _preview_cache_lock:
        _preview_cache_shutting_down = False
        _remove_media_preview_cache()


def stop_and_clear_media_preview_cache() -> None:
    """Block new preview-cache writes and remove the cache during shutdown."""
    global _preview_cache_shutting_down
    with _preview_cache_lock:
        _preview_cache_shutting_down = True
        _remove_media_preview_cache()


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
                stable = Path.cwd() / ".cortaflow-preview-cache"
                destination = stable / f"{source.stem}-{index}-{duration_ms}.jpg"
                with _preview_cache_lock:
                    if not _preview_cache_shutting_down and not (cancelled and cancelled.is_set()):
                        stable.mkdir(parents=True, exist_ok=True)
                        destination.write_bytes(output.read_bytes())
                        thumbnails.append(str(destination))
        if cancelled and cancelled.is_set():
            return {"thumbnails": [], "waveform": []}
        waveform = _extract_waveform(source, duration_ms, cancelled=cancelled)
        return {"thumbnails": thumbnails, "waveform": waveform}


def _extract_waveform(
    source: Path,
    duration_ms: int,
    samples: int = 240,
    cancelled=None,
) -> list[float]:
    """Read bounded PCM buckets so waveform memory stays constant for long media."""
    if duration_ms <= 0 or samples <= 0:
        return []
    command = [
        str(find_executable("ffmpeg")), "-hide_banner", "-loglevel", "error",
        "-i", str(source.resolve()), "-vn", "-ac", "1", "-ar", "8000", "-f", "s16le", "pipe:1",
    ]
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        shell=False,
        **hidden_console_options(),
    )
    waveform: list[float] = []
    bucket_samples = max(1, math.ceil(duration_ms * 8 / samples))
    try:
        assert process.stdout is not None
        exhausted = False
        for _ in range(samples):
            remaining = bucket_samples
            total_amplitude = 0
            count = 0
            while remaining > 0:
                if cancelled and cancelled.is_set():
                    process.terminate()
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                    return []
                read_samples = min(32_768, remaining)
                raw = process.stdout.read(read_samples * 2)
                if len(raw) % 2:
                    raw += process.stdout.read(1)
                if len(raw) % 2:
                    raw = raw[:-1]
                if not raw:
                    exhausted = True
                    break
                values = np.frombuffer(raw, dtype="<i2").astype(np.int32)
                if not values.size:
                    exhausted = True
                    break
                total_amplitude += int(np.abs(values).sum(dtype=np.int64))
                count += int(values.size)
                remaining -= int(values.size)
            if count:
                waveform.append(min(1.0, total_amplitude / count / 32768))
            if exhausted or count < bucket_samples:
                break
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        if process.poll() is None:
            process.wait()
        return waveform
    except Exception:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        raise
    finally:
        if process.stdout is not None and not process.stdout.closed:
            process.stdout.close()
