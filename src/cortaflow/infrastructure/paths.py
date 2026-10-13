"""Safe filename and path utilities."""

import os
import re
import unicodedata
from pathlib import Path

_INVALID_WINDOWS_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


def extended_length_path(path: Path) -> Path:
    """Allow Windows cache descendants to exceed the legacy MAX_PATH limit."""
    if os.name != "nt":
        return path
    absolute = str(path.expanduser().resolve())
    if absolute.startswith("\\\\?\\"):
        return Path(absolute)
    if absolute.startswith("\\\\"):
        return Path("\\\\?\\UNC\\" + absolute[2:])
    return Path("\\\\?\\" + absolute)


def sanitize_filename(value: str, fallback: str = "video") -> str:
    normalized = unicodedata.normalize("NFC", value).strip().rstrip(". ")
    safe = re.sub(r"\s+", " ", _INVALID_WINDOWS_CHARS.sub("_", normalized)).strip().rstrip(". ")
    safe = safe or fallback
    if Path(safe).stem.upper() in _RESERVED_NAMES:
        safe = f"_{safe}"
    return safe[:180]


def ensure_safe_output_directory(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    if resolved == Path(resolved.anchor):
        raise ValueError("A raiz do disco não pode ser usada como pasta de saída.")
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved

