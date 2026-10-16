"""Discovery and controlled execution of FFmpeg tools."""

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any


class FFmpegNotFoundError(RuntimeError):
    pass


def hidden_console_options() -> dict[str, int]:
    """Prevent FFmpeg console windows from flashing when the desktop app runs on Windows."""
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


def find_executable(name: str) -> Path:
    located = shutil.which(name)
    if located:
        return Path(located).resolve()
    root = Path.home() / "AppData/Local/Microsoft/WinGet/Packages"
    matches = list(root.glob(f"Gyan.FFmpeg.Essentials_*/**/{name}.exe"))
    if matches:
        return matches[0].resolve()
    raise FFmpegNotFoundError(f"{name} não foi encontrado.")


def run_ffprobe_json(media_path: Path) -> dict[str, Any]:
    if not media_path.is_file():
        raise FileNotFoundError(media_path)
    command = [str(find_executable("ffprobe")), "-v", "error", "-show_format", "-show_streams", "-of", "json", str(media_path.resolve())]
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", shell=False, check=False, **hidden_console_options())
    if result.returncode != 0:
        raise RuntimeError("Não foi possível ler os metadados do arquivo.")
    return json.loads(result.stdout)

