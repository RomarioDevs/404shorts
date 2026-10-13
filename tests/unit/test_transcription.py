from pathlib import Path
import os
from types import SimpleNamespace

import pytest

from cortaflow.services import transcription
from cortaflow.services.transcription import (
    FasterWhisperTranscriber,
    detect_compute_device,
    whisper_model_is_cached,
)


def test_compute_device_always_has_safe_mode() -> None:
    device, compute = detect_compute_device()
    assert (device, compute) in {
        ("cuda", "float16"),
        ("cuda", "int8_float16"),
        ("cpu", "int8"),
    }


def test_compute_device_falls_back_when_cuda_probe_fails(monkeypatch) -> None:
    monkeypatch.setattr(
        transcription,
        "ctranslate2",
        SimpleNamespace(
            get_cuda_device_count=lambda: 1,
            get_supported_compute_types=lambda _device: (_ for _ in ()).throw(
                RuntimeError("CUDA indisponível")
            ),
        ),
    )
    assert detect_compute_device() == ("cpu", "int8")


def test_compute_device_requires_windows_cuda_libraries(monkeypatch) -> None:
    monkeypatch.setattr(
        transcription,
        "ctranslate2",
        SimpleNamespace(
            get_cuda_device_count=lambda: 1,
            get_supported_compute_types=lambda _device: {"float16"},
        ),
    )
    monkeypatch.setattr(transcription, "_missing_cuda_libraries", lambda: ("cuDNN 9",))

    status = transcription.diagnose_compute_device()

    assert (status.device, status.compute_type) == ("cpu", "int8")
    assert status.missing_libraries == ("cuDNN 9",)
    assert "cuDNN 9" in status.detail


def test_compute_device_reports_cuda_only_when_runtime_is_ready(monkeypatch) -> None:
    monkeypatch.setattr(
        transcription,
        "ctranslate2",
        SimpleNamespace(
            get_cuda_device_count=lambda: 1,
            get_supported_compute_types=lambda _device: {"float16", "int8_float16"},
        ),
    )
    monkeypatch.setattr(transcription, "_missing_cuda_libraries", lambda: ())

    assert detect_compute_device() == ("cuda", "float16")


def test_transcriber_uses_words_vad_and_manual_portuguese(monkeypatch, tmp_path: Path) -> None:
    media = tmp_path / "áudio teste.mp4"
    media.write_bytes(b"fixture")
    captured: dict = {}

    class FakeModel:
        def __init__(self, model_size, **kwargs):
            captured["model_size"] = model_size
            captured["device"] = kwargs["device"]
            captured["local_files_only"] = kwargs["local_files_only"]

        def transcribe(self, path, **kwargs):
            captured["path"] = path
            captured["options"] = kwargs
            word = SimpleNamespace(word=" Olá", start=0.1, end=0.5, probability=0.98)
            segment = SimpleNamespace(words=[word], end=0.5)
            info = SimpleNamespace(language="pt", language_probability=0.99)
            return iter([segment]), info

    monkeypatch.setattr(transcription, "WhisperModel", FakeModel)
    monkeypatch.setattr(transcription, "detect_compute_device", lambda: ("cpu", "int8"))
    updates: list[dict] = []
    result = FasterWhisperTranscriber("small").transcribe(media, "pt", updates.append)

    assert captured["options"]["word_timestamps"] is True
    assert captured["options"]["vad_filter"] is True
    assert captured["options"]["language"] == "pt"
    assert captured["local_files_only"] is True
    assert result.words[0].text == "Olá"
    assert result.words[0].start_ms == 100
    assert result.cues[0].text == "Olá"
    assert updates[-1]["position_ms"] == 500


def test_transcriber_retries_on_cuda_runtime_failure(monkeypatch, tmp_path: Path) -> None:
    media = tmp_path / "source.mp4"
    media.write_bytes(b"fixture")
    devices: list[str] = []

    class FakeModel:
        def __init__(self, _model_size, **kwargs):
            devices.append(kwargs["device"])
            if kwargs["device"] == "cuda":
                raise RuntimeError("Could not load cuDNN CUDA library")

        def transcribe(self, _path, **_kwargs):
            return iter([]), SimpleNamespace(language="pt", language_probability=0.8)

    monkeypatch.setattr(transcription, "WhisperModel", FakeModel)
    monkeypatch.setattr(transcription, "detect_compute_device", lambda: ("cuda", "float16"))
    updates: list[dict] = []
    result = FasterWhisperTranscriber().transcribe(media, progress=updates.append)

    assert devices == ["cuda", "cpu"]
    assert result.language == "pt"
    assert any(update["status"] == "fallback" for update in updates)


def test_rejects_unsupported_model() -> None:
    with pytest.raises(ValueError, match="Modelo"):
        FasterWhisperTranscriber("gigante")


def test_cached_model_requires_complete_snapshot(tmp_path: Path) -> None:
    snapshot = (
        tmp_path
        / "models--Systran--faster-whisper-small"
        / "snapshots"
        / "revision"
    )
    snapshot.mkdir(parents=True)
    for name in ("config.json", "model.bin", "tokenizer.json"):
        (snapshot / name).write_bytes(b"fixture")
    assert whisper_model_is_cached(tmp_path, "small")
    (snapshot / "model.bin").unlink()
    assert not whisper_model_is_cached(tmp_path, "small")


@pytest.mark.skipif(os.name != "nt", reason="Windows extended-length paths")
def test_cache_lookup_supports_long_paths(monkeypatch, tmp_path: Path) -> None:
    media = tmp_path / "source.mp4"
    media.write_bytes(b"fixture")
    cache = tmp_path / ("a" * 80) / ("b" * 80) / "faster-whisper"

    class FakeModel:
        def __init__(self, _model_size, **kwargs):
            root = transcription.extended_length_path(Path(kwargs["download_root"]))
            assert str(root).startswith("\\\\?\\")
            assert kwargs["local_files_only"] is False
            repository = root / "models--Systran--faster-whisper-small"
            blob = repository / "blobs" / ("e" * 40 + ".5a1baf5d.incomplete")
            assert len(str(blob)) > 260
            blob.parent.mkdir(parents=True, exist_ok=True)
            blob.write_bytes(b"fixture")
            snapshot = repository / "snapshots" / ("f" * 40)
            snapshot.mkdir(parents=True)
            blob.replace(snapshot / "model.bin")
            for name in ("config.json", "tokenizer.json"):
                (snapshot / name).write_bytes(b"fixture")

        def transcribe(self, _path, **_kwargs):
            return iter([]), SimpleNamespace(language="pt", language_probability=0.8)

    monkeypatch.setattr(transcription, "WhisperModel", FakeModel)
    monkeypatch.setattr(transcription, "detect_compute_device", lambda: ("cpu", "int8"))
    FasterWhisperTranscriber(model_cache=cache, allow_download=True).transcribe(media)
    assert whisper_model_is_cached(cache, "small")
