from pathlib import Path
from threading import Event

import pytest

from cortaflow.domain.clip import ClipRange
from cortaflow.services import transcoder
from cortaflow.services.transcoder import ExportCancelled, build_clip_command


def test_command_is_argument_list_and_supports_optional_audio(tmp_path: Path) -> None:
    command = build_clip_command(Path("C:/Vídeos/vídeo com espaço.mp4"), tmp_path / "saída.mp4", ClipRange(start_ms=1250, end_ms=3250))
    assert Path(command[0]).name.lower() in {"ffmpeg", "ffmpeg.exe"}
    assert "00:00:01.250" in command
    assert "00:00:02.000" in command
    assert "0:a?" in command
    assert isinstance(command, list)


class FakeProcess:
    def __init__(self, wait_raises_timeout: bool = False) -> None:
        self.returncode = None
        self.terminated = False
        self.killed = False
        self.communicated = False
        self.wait_raises_timeout = wait_raises_timeout

    def poll(self):
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9

    def wait(self, timeout=None) -> None:
        if self.wait_raises_timeout and not self.killed:
            raise transcoder.subprocess.TimeoutExpired("ffmpeg", timeout)
        self.returncode = -15 if self.terminated else 0

    def communicate(self, timeout=None):
        self.communicated = True
        return "", ""


def test_cancelled_export_terminates_and_reaps_ffmpeg(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    process = FakeProcess()
    monkeypatch.setattr(transcoder, "build_clip_command", lambda *args: ["ffmpeg"])
    monkeypatch.setattr(transcoder.subprocess, "Popen", lambda *args, **kwargs: process)
    cancelled = Event()
    cancelled.set()

    with pytest.raises(ExportCancelled):
        transcoder.export_clip(
            source,
            tmp_path / "output.mp4",
            ClipRange(start_ms=0, end_ms=1000),
            cancelled=cancelled,
        )

    assert process.terminated
    assert process.communicated


def test_stop_process_kills_ffmpeg_when_graceful_shutdown_times_out() -> None:
    process = FakeProcess(wait_raises_timeout=True)

    transcoder._stop_process(process)

    assert process.terminated
    assert process.killed
    assert process.communicated
