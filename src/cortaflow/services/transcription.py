"""Replaceable local Faster-Whisper transcription service."""

from collections.abc import Callable
import ctypes
from dataclasses import dataclass
import importlib
import os
from pathlib import Path
from threading import Event
from typing import Any, Literal

from cortaflow.domain.subtitle import Transcript, TranscriptWord
from cortaflow.infrastructure.certificates import configure_system_certificates
from cortaflow.infrastructure.paths import extended_length_path
from cortaflow.services.subtitles import group_words

ProgressCallback = Callable[[dict[str, Any]], None]
SUPPORTED_MODELS = {"small", "medium", "turbo"}
ctranslate2: Any | None = None
WhisperModel: Any | None = None


class TranscriptionCancelled(RuntimeError):
    """Raised when a transcription is cooperatively cancelled."""


@dataclass(frozen=True)
class ComputeDeviceStatus:
    device: Literal["cuda", "cpu"]
    compute_type: str
    detail: str
    missing_libraries: tuple[str, ...] = ()


_WINDOWS_CUDA_LIBRARIES = {
    "cublas64_12.dll": "cuBLAS 12",
    "cublasLt64_12.dll": "cuBLASLt 12",
    "cudnn64_9.dll": "cuDNN 9",
}
_CUDA_DLL_HANDLES: list[object] = []


def _missing_cuda_libraries() -> tuple[str, ...]:
    if os.name != "nt":
        return ()
    missing: list[str] = []
    for filename, label in _WINDOWS_CUDA_LIBRARIES.items():
        try:
            handle = ctypes.WinDLL(filename)  # type: ignore[attr-defined]
            # Keep loaded CUDA dependencies alive for the lifetime of the process.
            # Unloading cuDNN while another native module still references it can
            # terminate the Windows process with an access violation.
            _CUDA_DLL_HANDLES.append(handle)
        except OSError:
            missing.append(label)
    return tuple(missing)


def diagnose_compute_device() -> ComputeDeviceStatus:
    """Report a usable compute mode, including Windows CUDA runtime readiness."""
    try:
        runtime = _ctranslate_runtime()
        if runtime.get_cuda_device_count() <= 0:
            return ComputeDeviceStatus("cpu", "int8", "CUDA não detectada")
        missing = _missing_cuda_libraries()
        if missing:
            detail = f"CUDA incompleta: {', '.join(missing)} ausente(s)"
            return ComputeDeviceStatus("cpu", "int8", detail, missing)
        supported = runtime.get_supported_compute_types("cuda")
        if "float16" in supported:
            return ComputeDeviceStatus("cuda", "float16", "CUDA pronta")
        if "int8_float16" in supported:
            return ComputeDeviceStatus("cuda", "int8_float16", "CUDA pronta")
        return ComputeDeviceStatus("cpu", "int8", "CUDA sem modo de cálculo compatível")
    except (RuntimeError, ValueError, OSError) as exc:
        return ComputeDeviceStatus("cpu", "int8", f"CUDA indisponível: {exc}")


def detect_compute_device() -> tuple[Literal["cuda", "cpu"], str]:
    """Choose a supported CUDA mode, falling back safely to CPU INT8."""
    status = diagnose_compute_device()
    return status.device, status.compute_type


def _is_cuda_runtime_error(error: Exception) -> bool:
    message = str(error).lower()
    return any(token in message for token in ("cuda", "cudnn", "cublas", "gpu"))


class FasterWhisperTranscriber:
    """Transcribe local media behind a replaceable service boundary."""

    def __init__(
        self,
        model_size: str = "small",
        model_cache: Path | None = None,
        certificate_cache: Path | None = None,
        allow_download: bool = False,
    ) -> None:
        if model_size not in SUPPORTED_MODELS:
            raise ValueError("Modelo não suportado.")
        self.model_size = model_size
        self.model_cache = model_cache
        self.certificate_cache = certificate_cache
        self.allow_download = allow_download

    def transcribe(
        self,
        media_path: Path,
        language: str | None = None,
        progress: ProgressCallback | None = None,
        cancelled: Event | None = None,
    ) -> Transcript:
        """Generate word timestamps with VAD and automatic CUDA fallback."""
        media_path = media_path.resolve()
        if not media_path.is_file():
            raise FileNotFoundError(media_path)
        if language not in (None, "pt"):
            raise ValueError("Idioma manual ainda não suportado.")
        if cancelled and cancelled.is_set():
            raise TranscriptionCancelled("Transcrição cancelada.")

        if self.certificate_cache:
            configure_system_certificates(self.certificate_cache)

        device, compute_type = detect_compute_device()
        try:
            return self._transcribe_once(
                media_path, language, device, compute_type, progress, cancelled
            )
        except (RuntimeError, OSError) as exc:
            if device != "cuda" or not _is_cuda_runtime_error(exc):
                raise
            if progress:
                progress(
                    {
                        "status": "fallback",
                        "device": "cpu",
                        "message": "CUDA indisponível em tempo de execução; continuando pela CPU.",
                    }
                )
            return self._transcribe_once(
                media_path, language, "cpu", "int8", progress, cancelled
            )

    def _transcribe_once(
        self,
        media_path: Path,
        language: str | None,
        device: str,
        compute_type: str,
        progress: ProgressCallback | None,
        cancelled: Event | None,
    ) -> Transcript:
        if progress:
            progress({"status": "loading_model", "device": device, "model": self.model_size})
        model_class = _whisper_model_class()
        model = model_class(
            self.model_size,
            device=device,
            compute_type=compute_type,
            download_root=str(self.model_cache) if self.model_cache else None,
            local_files_only=not self.allow_download,
        )
        segments, info = model.transcribe(
            str(media_path),
            language=language,
            word_timestamps=True,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500},
        )
        words: list[TranscriptWord] = []
        segment_count = 0
        for segment in segments:
            if cancelled and cancelled.is_set():
                raise TranscriptionCancelled("Transcrição cancelada.")
            segment_count += 1
            for word in segment.words or []:
                if word.start is None or word.end is None or not word.word.strip():
                    continue
                words.append(
                    TranscriptWord(
                        text=word.word.strip(),
                        start_ms=round(word.start * 1000),
                        end_ms=round(word.end * 1000),
                        probability=word.probability,
                    )
                )
            if progress:
                progress(
                    {
                        "status": "transcribing",
                        "device": device,
                        "segments": segment_count,
                        "position_ms": round(segment.end * 1000),
                    }
                )
        return Transcript(
            language=info.language,
            language_probability=info.language_probability,
            words=words,
            cues=group_words(words),
        )


def whisper_model_is_cached(model_cache: Path, model_size: str) -> bool:
    """Return true only for a complete local Faster-Whisper snapshot."""
    if model_size not in SUPPORTED_MODELS:
        return False
    repository = extended_length_path(model_cache) / f"models--Systran--faster-whisper-{model_size}" / "snapshots"
    if not repository.is_dir():
        return False
    required = {"config.json", "model.bin", "tokenizer.json"}
    return any(
        required <= {item.name for item in snapshot.iterdir() if item.is_file()}
        for snapshot in repository.iterdir()
        if snapshot.is_dir()
    )


def _ctranslate_runtime() -> Any:
    global ctranslate2
    if ctranslate2 is None:
        ctranslate2 = importlib.import_module("ctranslate2")
    return ctranslate2


def _whisper_model_class() -> Any:
    global WhisperModel
    if WhisperModel is None:
        WhisperModel = importlib.import_module("faster_whisper").WhisperModel
    return WhisperModel
