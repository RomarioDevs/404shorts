from pathlib import Path
import os
import pytest
from cortaflow.infrastructure.paths import ensure_safe_output_directory, sanitize_filename
from cortaflow.infrastructure.paths import extended_length_path


def test_extended_length_path_is_idempotent(tmp_path: Path) -> None:
    result = extended_length_path(tmp_path)
    assert extended_length_path(result) == result
    if os.name == "nt":
        assert str(result).startswith("\\\\?\\")
    else:
        assert result == tmp_path


@pytest.mark.skipif(os.name != "nt", reason="Windows UNC paths")
def test_extended_length_path_preserves_unc_share() -> None:
    assert extended_length_path(Path(r"\\server\share\models")) == Path(r"\\?\UNC\server\share\models")


@pytest.mark.parametrize(("value", "expected"), [("vídeo: teste?.mp4", "vídeo_ teste_.mp4"), ("CON", "_CON"), ("  ", "video")])
def test_sanitize_filename(value: str, expected: str) -> None:
    assert sanitize_filename(value) == expected


def test_rejects_drive_root() -> None:
    with pytest.raises(ValueError):
        ensure_safe_output_directory(Path(Path.cwd().anchor))

