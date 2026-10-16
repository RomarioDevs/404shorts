"""Safe FFmpeg command generation and basic clip export."""

import subprocess
from collections.abc import Callable
from pathlib import Path
from threading import Event

from cortaflow.domain.clip import ClipRange, format_timestamp
from cortaflow.infrastructure.ffmpeg import find_executable, hidden_console_options


class ExportCancelled(RuntimeError):
    pass


def build_clip_command(source: Path, destination: Path, clip: ClipRange) -> list[str]:
    """Build a frame-accurate, broadly compatible H.264/AAC export command."""
    return [
        str(find_executable("ffmpeg")), "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
        "-ss", format_timestamp(clip.start_ms, True), "-i", str(source.resolve()),
        "-t", format_timestamp(clip.duration_ms, True), "-map", "0:v:0", "-map", "0:a?",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
        str(destination.resolve()),
    ]


def export_clip(source: Path, destination: Path, clip: ClipRange, progress: Callable[[dict], None] | None = None, cancelled: Event | None = None) -> Path:
    """Export via a temporary file and atomically publish the completed result."""
    if not source.is_file():
        raise FileNotFoundError(source)
    if destination.exists():
        raise FileExistsError("O arquivo de destino já existe.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.stem}.partial{destination.suffix}")
    command = build_clip_command(source, temporary, clip)
    process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", shell=False, **hidden_console_options())
    try:
        while process.poll() is None:
            if cancelled and cancelled.is_set():
                raise ExportCancelled("Exportação cancelada.")
            if progress:
                progress({"status": "processing"})
            try:
                process.wait(timeout=0.1)
            except subprocess.TimeoutExpired:
                continue
    except Exception:
        _stop_process(process)
        if temporary.exists():
            temporary.unlink()
        raise
    return _finish_process(process, temporary, destination)


def _stop_process(process: subprocess.Popen) -> None:
    """Stop and reap FFmpeg so cancellation never leaves a child process behind."""
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)
    # Drain pipes and reap the child even when termination was requested after exit.
    process.communicate()


def _finish_process(process: subprocess.Popen, temporary: Path, destination: Path) -> Path:
    try:
        _, stderr = process.communicate(timeout=300)
    except subprocess.TimeoutExpired:
        process.kill()
        _, stderr = process.communicate()
    if process.returncode != 0:
        if temporary.exists():
            temporary.unlink()
        raise RuntimeError(f"FFmpeg falhou ao exportar o corte: {stderr[-500:]}")
    temporary.replace(destination)
    return destination
