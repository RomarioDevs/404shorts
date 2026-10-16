"""One-click local pipeline from imported media to reviewable previews."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import TYPE_CHECKING, Any

from cortaflow.domain.analysis import AnalysisResult, ClipSelectionSettings, ClipSuggestion
from cortaflow.domain.clip import ClipRange
from cortaflow.domain.editing import AudioSettings, ReframeSettings, SubtitleStyle
from cortaflow.domain.media import MediaMetadata
from cortaflow.domain.project import ExportSettings, ReframeKeyframe
from cortaflow.domain.subtitle import Transcript
from cortaflow.domain.tracking import FaceTrackPoint, FramingValidation, SpeakerKeyframe
from cortaflow.services.audio_analysis import extract_audio_evidence
from cortaflow.services.clip_scoring import ClipRanker, suggest_clips
from cortaflow.services.export_service import render_project_export
from cortaflow.services.face_analysis import analyze_faces
from cortaflow.services.media_probe import probe_media
from cortaflow.services.reframe_validation import ensure_safe_reframe, validate_suggestion_reframe
from cortaflow.services.rendered_framing import validate_rendered_preview
from cortaflow.services.scene_detection import detect_scenes, detect_silences
from cortaflow.services.speaker_analysis import analyze_active_speaker

if TYPE_CHECKING:
    from cortaflow.services.transcription import FasterWhisperTranscriber


ProgressCallback = Callable[[dict[str, Any]], None]


class AutomaticPipelineCancelled(RuntimeError):
    """Raised when the complete automatic pipeline is cancelled."""


@dataclass(frozen=True)
class AutomaticPreview:
    suggestion_index: int
    path: Path
    subtitles_applied: bool = False
    reframe_applied: bool = False
    framing_status: str = "needs_review"
    framing_score: float = 0
    framing_message: str = "O enquadramento do arquivo pronto ainda não foi conferido."


@dataclass(frozen=True)
class AutomaticPipelineResult:
    metadata: MediaMetadata
    transcript: Transcript
    analysis: AnalysisResult
    face_tracks: list[FaceTrackPoint]
    speaker_keyframes: list[SpeakerKeyframe]
    reframe_keyframes: list[ReframeKeyframe]
    previews: list[AutomaticPreview]
    preview_directory: Path


def create_automatic_cuts(
    media_path: Path,
    transcript: Transcript | None,
    selection_settings: ClipSelectionSettings,
    ranker: ClipRanker | None,
    transcriber: FasterWhisperTranscriber | None,
    face_model_path: Path | None,
    preview_directory: Path,
    export_settings: ExportSettings,
    subtitle_style: SubtitleStyle,
    reframe_settings: ReframeSettings,
    audio_settings: AudioSettings,
    preview_limit: int = 3,
    progress: ProgressCallback | None = None,
    cancelled: Event | None = None,
) -> AutomaticPipelineResult:
    """Run the approved local stages and save only review copies in the app cache."""
    media_path = media_path.resolve()
    preview_directory = preview_directory.resolve()
    if preview_limit < 0:
        raise ValueError("A quantidade de prévias não pode ser negativa.")
    preview_directory.mkdir(parents=True, exist_ok=True)
    _check_cancelled(cancelled)
    _update(progress, "media", "1/7 · Validando a mídia local…")
    metadata = probe_media(media_path)

    generated_transcript = transcript
    if generated_transcript is None:
        if transcriber is None:
            raise RuntimeError(
                "O modelo de transcrição não está disponível localmente e nenhum download foi autorizado."
            )
        _update(progress, "transcription", "2/7 · Transcrevendo o áudio localmente…")
        generated_transcript = transcriber.transcribe(
            media_path,
            progress=progress,
            cancelled=cancelled,
        )
    else:
        _update(progress, "transcription", "2/7 · Reutilizando a transcrição do projeto.")
    _check_cancelled(cancelled)

    _update(progress, "analysis", "3/7 · Detectando cenas, pausas e atividade de voz…")
    scenes = detect_scenes(media_path, progress=progress, cancelled=cancelled)
    _check_cancelled(cancelled)
    silences = detect_silences(media_path, progress=progress, cancelled=cancelled)
    _check_cancelled(cancelled)
    audio_evidence = extract_audio_evidence(
        media_path,
        generated_transcript,
        silences,
        progress=progress,
        cancelled=cancelled,
    )
    _check_cancelled(cancelled)

    face_tracks: list[FaceTrackPoint] = []
    speaker_keyframes: list[SpeakerKeyframe] = []
    keyframes: list[ReframeKeyframe] = []
    face_detector_available = bool(face_model_path and face_model_path.is_file())
    if face_detector_available:
        _update(progress, "reframe", "4/7 · Detectando rostos e preparando 9:16…")
        face_tracks, keyframes = analyze_faces(
            media_path,
            face_model_path,
            scenes,
            sample_interval_ms=250,
            progress=progress,
            cancelled=cancelled,
        )
        # A entrevista pode alternar entre câmeras: nesse caso nunca há dois
        # rostos no mesmo quadro, mas ainda existem vários participantes ao
        # longo do vídeo. A análise de falante precisa rodar nos dois casos.
        if _has_multiple_visible_faces(face_tracks) or _has_multiple_tracked_faces(face_tracks):
            _update(
                progress,
                "speaker",
                "4/7 · Mais de uma pessoa detectada; identificando o falante ativo…",
            )
            speaker_keyframes, speaker_crops = analyze_active_speaker(
                media_path,
                face_tracks,
                metadata.width or 0,
                metadata.height or 0,
                generated_transcript,
                silences,
                scenes,
                [],
                progress,
                cancelled,
                audio_evidence=audio_evidence,
            )
            if speaker_crops:
                keyframes = speaker_crops
    else:
        _update(
            progress,
            "reframe_skipped",
            "4/7 · Modelo facial local ausente; usando enquadramento vertical central.",
        )
    _check_cancelled(cancelled)

    _update(progress, "suggestions", "5/7 · Pontuando trechos com texto, áudio e rostos…")
    try:
        suggestions = suggest_clips(
            generated_transcript,
            round(metadata.duration_seconds * 1000),
            silences=silences,
            scenes=scenes,
            settings=selection_settings,
            audio_evidence=audio_evidence,
            face_tracks=face_tracks,
            ranker=ranker,
            progress=progress,
            cancelled=cancelled,
        )
        keyframes = ensure_safe_reframe(
            face_tracks,
            speaker_keyframes,
            keyframes,
            metadata.width or 0,
            metadata.height or 0,
        )
        _update(
            progress,
            "framing_validation",
            "5/7 · Validando rosto e enquadramento em cada corte sugerido…",
        )
        validated_suggestions: list[ClipSuggestion] = []
        for suggestion in suggestions:
            framing = (
                validate_suggestion_reframe(
                    suggestion,
                    face_tracks,
                    speaker_keyframes,
                    keyframes,
                    reframe_settings,
                    metadata.width or 0,
                    metadata.height or 0,
                )
                if face_detector_available
                else _unavailable_framing_validation()
            )
            components = dict(suggestion.score_components)
            components["enquadramento"] = framing.score
            validated_suggestions.append(
                suggestion.model_copy(
                    update={
                        "score_components": components,
                        "framing_status": framing.status,
                        "framing_score": framing.score,
                        "visible_faces": framing.max_visible_faces,
                        "speaker_changes": framing.speaker_changes,
                    }
                )
            )
        analysis = AnalysisResult(
            scenes=scenes,
            silences=silences,
            suggestions=validated_suggestions,
        )
    finally:
        release = getattr(ranker, "release", None)
        if callable(release):
            release()
    _check_cancelled(cancelled)
    suggestions_message = (
        f"{len(analysis.suggestions)} cortes encontrados e validados; preparando versões verticais…"
        if analysis.suggestions
        else (
            "A análise terminou, mas nenhum limite editorial foi aprovado. "
            "A transcrição pode estar sem pausas/pontuação suficientes; revise a transcrição "
            "ou reduza a duração mínima para testar novamente."
        )
    )
    _update(
        progress,
        "suggestions_ready",
        suggestions_message,
        suggestions=list(analysis.suggestions),
    )

    _update(progress, "subtitles", "6/7 · Preparando legendas sincronizadas por corte…")
    run_directory = _create_run_directory(preview_directory, media_path.stem)
    previews: list[AutomaticPreview] = []
    ordered = sorted(analysis.suggestions, key=lambda item: item.quality_score, reverse=True)
    for index, suggestion in enumerate(ordered[:preview_limit]):
        _check_cancelled(cancelled)
        _update(
            progress,
            "preview",
            f"7/7 · Preparando versão vertical {index + 1} de {min(preview_limit, len(ordered))}…",
            preview=index + 1,
            preview_count=min(preview_limit, len(ordered)),
        )
        destination = run_directory / f"{index + 1:02d}-{_safe_name(suggestion)}.mp4"
        render_project_export(
            media_path,
            destination,
            export_settings,
            ClipRange(start_ms=suggestion.start_ms, end_ms=suggestion.end_ms),
            generated_transcript.cues,
            subtitle_style,
            keyframes,
            True,
            generated_transcript.words,
            reframe_settings,
            audio_settings,
            (metadata.width, metadata.height) if metadata.width and metadata.height else None,
            [],
            progress,
            cancelled,
        )
        suggestion_index = analysis.suggestions.index(suggestion)
        expected_face = any(
            suggestion.start_ms <= point.timestamp_ms < suggestion.end_ms
            for point in face_tracks
        )
        if face_detector_available and face_model_path:
            _update(
                progress,
                "rendered_framing_validation",
                f"7/7 · Conferindo o rosto no MP4 pronto {index + 1} de "
                f"{min(preview_limit, len(ordered))}…",
            )
            rendered_framing = validate_rendered_preview(
                destination,
                face_model_path,
                expected_face=expected_face,
                cancelled=cancelled,
            )
        else:
            rendered_framing = _unavailable_framing_validation()
        current = analysis.suggestions[suggestion_index]
        analysis.suggestions[suggestion_index] = current.model_copy(
            update={
                "framing_status": rendered_framing.status,
                "framing_score": rendered_framing.score,
                "visible_faces": max(
                    current.visible_faces,
                    rendered_framing.max_visible_faces,
                ),
            }
        )
        previews.append(
            AutomaticPreview(
                suggestion_index,
                destination,
                subtitles_applied=any(
                    cue.end_ms > suggestion.start_ms and cue.start_ms < suggestion.end_ms
                    for cue in generated_transcript.cues
                ),
                reframe_applied=bool(keyframes),
                framing_status=rendered_framing.status,
                framing_score=rendered_framing.score,
                framing_message=rendered_framing.message,
            )
        )
        _update(
            progress,
            "preview_ready",
            (
                f"Versão vertical {index + 1} de {min(preview_limit, len(ordered))} "
                "com rosto conferido no MP4 pronto."
                if rendered_framing.status != "needs_review"
                else (
                    f"Versão vertical {index + 1} precisa de revisão: "
                    f"{rendered_framing.message}"
                )
            ),
            previews=list(previews),
            suggestions=list(analysis.suggestions),
        )
    _update(
        progress,
        "complete",
        (
            f"Fluxo automático concluído · {len(analysis.suggestions)} cortes · {len(previews)} versões."
            if analysis.suggestions
            else (
                "Fluxo concluído sem cortes: nenhum intervalo com início independente e "
                "fim seguro foi encontrado."
            )
        ),
    )
    return AutomaticPipelineResult(
        metadata=metadata,
        transcript=generated_transcript,
        analysis=analysis,
        face_tracks=face_tracks,
        speaker_keyframes=speaker_keyframes,
        reframe_keyframes=keyframes,
        previews=previews,
        preview_directory=run_directory,
    )


def _has_multiple_visible_faces(tracks: list[FaceTrackPoint]) -> bool:
    """Return whether any sampled frame contains at least two distinct tracked faces."""
    visible_by_timestamp: dict[int, set[int]] = {}
    for point in tracks:
        visible_by_timestamp.setdefault(point.timestamp_ms, set()).add(point.track_id)
    return any(len(track_ids) > 1 for track_ids in visible_by_timestamp.values())


def _has_multiple_tracked_faces(tracks: list[FaceTrackPoint]) -> bool:
    """Return whether more than one temporary face ID appears in the recording."""
    return len({point.track_id for point in tracks}) > 1


def _unavailable_framing_validation() -> FramingValidation:
    """Never call a central fallback 'no face' when no detector actually ran."""
    return FramingValidation(
        status="needs_review",
        score=0,
        face_samples=0,
        safe_samples=0,
        unsafe_samples=0,
        max_visible_faces=0,
        speaker_changes=0,
        uncertain_speaker_samples=0,
        message=(
            "O detector facial local não estava disponível; o programa não pode afirmar "
            "que o rosto está enquadrado."
        ),
    )


def _check_cancelled(cancelled: Event | None) -> None:
    if cancelled and cancelled.is_set():
        raise AutomaticPipelineCancelled("Criação automática cancelada.")


def _update(progress: ProgressCallback | None, status: str, message: str, **extra: Any) -> None:
    if progress:
        progress({"status": status, "message": message, **extra})


def _safe_name(suggestion: ClipSuggestion) -> str:
    value = "".join(
        character if character.isalnum() or character in "-_ " else "_"
        for character in suggestion.title
    ).strip()
    return (value[:60] or "corte").replace(" ", "-")


def _create_run_directory(parent: Path, media_stem: str) -> Path:
    """Reserve a readable, collision-free subfolder without overwriting old cuts."""
    safe_stem = "".join(
        character if character.isalnum() or character in "-_ " else "_"
        for character in media_stem
    ).strip()
    base_name = f"Cortes automáticos - {safe_stem[:70] or 'vídeo'}"
    for index in range(1, 10_000):
        suffix = "" if index == 1 else f" ({index})"
        candidate = parent / f"{base_name}{suffix}"
        try:
            candidate.mkdir(exist_ok=False)
        except FileExistsError:
            continue
        return candidate
    raise RuntimeError("Não foi possível reservar uma nova pasta para os cortes automáticos.")
