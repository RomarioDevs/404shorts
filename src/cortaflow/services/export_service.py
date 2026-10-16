"""Prepare project assets and invoke the professional renderer."""

import tempfile
from collections.abc import Callable
from pathlib import Path
from threading import Event
from typing import Any

from cortaflow.config import AppConfig

from cortaflow.domain.clip import ClipRange
from cortaflow.domain.editing import AudioSettings, LayerItem, ReframeSettings, SubtitleStyle, TimelineClip
from cortaflow.domain.project import ExportSettings, ReframeKeyframe
from cortaflow.domain.subtitle import SubtitleCue, TranscriptWord
from cortaflow.infrastructure.ffmpeg import run_ffprobe_json
from cortaflow.services.renderer import output_dimensions, render, render_timeline
from cortaflow.services.subtitles import clip_subtitle_track, export_subtitles


def render_project_export(
    source: Path,
    destination: Path,
    settings: ExportSettings,
    clip: ClipRange,
    cues: list[SubtitleCue],
    subtitle_style: SubtitleStyle,
    keyframes: list[ReframeKeyframe],
    preview: bool,
    words: list[TranscriptWord] | None = None,
    reframe_settings: ReframeSettings | None = None,
    audio_settings: AudioSettings | None = None,
    source_size: tuple[int, int] | None = None,
    timeline_clips: list[TimelineClip] | None = None,
    progress: Callable[[dict[str, Any]], None] | None = None,
    cancelled: Event | None = None,
    layers: list[LayerItem] | None = None,
) -> Path:
    """Render with temporary ASS assets that are always cleaned up."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    watermark = settings.watermark
    if watermark.enabled:
        if watermark.image_path is None:
            raise ValueError("Ative a marca-d'água somente depois de escolher uma imagem.")
        watermark_path = watermark.image_path.resolve()
        if not watermark_path.is_file():
            raise FileNotFoundError(
                f"A imagem da marca-d'água não foi encontrada: {watermark_path}"
            )
        watermark_payload = run_ffprobe_json(watermark_path)
        if not any(
            item.get("codec_type") == "video"
            for item in watermark_payload.get("streams", [])
        ):
            raise ValueError("O arquivo escolhido não contém uma imagem válida.")
    payload = run_ffprobe_json(source)
    video_stream = next(
        (item for item in payload.get("streams", []) if item.get("codec_type") == "video"),
        {},
    )
    probed_size = (
        int(video_stream.get("width") or 0),
        int(video_stream.get("height") or 0),
    )
    if min(probed_size) > 0:
        source_size = probed_size
    elif not source_size:
        source_size = (settings.width, settings.height)
    effective_reframe = reframe_settings or ReframeSettings()
    effective_audio = audio_settings or AudioSettings(normalize=settings.normalize_audio)
    resolution = output_dimensions(settings, effective_reframe, source_size, preview)

    temp_root = AppConfig().render_temp_dir
    temp_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="export-", dir=temp_root) as temp_dir:
        subtitle_path = None
        if timeline_clips:
            output_cues, output_words = _timeline_subtitle_track(
                cues, words or [], timeline_clips, subtitle_style.max_words, subtitle_style.preset
            )
        else:
            output_cues, output_words = clip_subtitle_track(
                cues, words or [], clip, subtitle_style.max_words, subtitle_style.preset
            )
        if output_cues:
            subtitle_path = export_subtitles(
                output_cues,
                Path(temp_dir) / "legendas.ass",
                animated=subtitle_style.animated,
                style=subtitle_style,
                words=output_words,
                resolution=resolution,
            )
        if timeline_clips:
            source_has_audio = any(
                item.get("codec_type") == "audio" for item in payload.get("streams", [])
            )
            return render_timeline(
                source,
                destination,
                settings,
                timeline_clips,
                subtitle_path=subtitle_path,
                preview=preview,
                crop_keyframes=keyframes,
                reframe_settings=effective_reframe,
                audio_settings=effective_audio,
                source_size=source_size,
                source_has_audio=source_has_audio,
                progress=progress,
                cancelled=cancelled,
                layers=layers,
            )
        return render(
            source,
            destination,
            settings,
            clip,
            subtitle_path=subtitle_path,
            preview=preview,
            crop_keyframes=keyframes,
            progress=progress,
            cancelled=cancelled,
            reframe_settings=effective_reframe,
            audio_settings=effective_audio,
            source_size=source_size,
        )


def _timeline_subtitle_track(
    cues: list[SubtitleCue],
    words: list[TranscriptWord],
    clips: list[TimelineClip],
    max_words: int,
    preset: str = "dynamic",
) -> tuple[list[SubtitleCue], list[TranscriptWord]]:
    """Map source subtitle timestamps into each edited video timeline segment."""
    output_cues: list[SubtitleCue] = []
    output_words: list[TranscriptWord] = []
    for item in sorted(
        (clip for clip in clips if clip.track == "video"),
        key=lambda clip: (clip.timeline_start_ms, clip.clip_id),
    ):
        source_clip = ClipRange(start_ms=item.source_start_ms, end_ms=item.source_end_ms)
        segment_cues, segment_words = clip_subtitle_track(
            cues, words, source_clip, max_words, preset
        )
        for cue in segment_cues:
            start_ms, end_ms = _map_segment_times(
                cue.start_ms, cue.end_ms, item
            )
            output_cues.append(
                cue.model_copy(update={"start_ms": start_ms, "end_ms": end_ms})
            )
        for word in segment_words:
            start_ms, end_ms = _map_segment_times(
                word.start_ms, word.end_ms, item
            )
            output_words.append(
                word.model_copy(update={"start_ms": start_ms, "end_ms": end_ms})
            )
    return sorted(output_cues, key=lambda cue: cue.start_ms), sorted(
        output_words, key=lambda word: word.start_ms
    )


def _map_segment_times(
    start_ms: int,
    end_ms: int,
    clip: TimelineClip,
) -> tuple[int, int]:
    """Map source-relative timestamps through clip speed onto the timeline."""
    timeline_start = clip.timeline_start_ms + round(start_ms / clip.speed)
    timeline_end = clip.timeline_start_ms + round(end_ms / clip.speed)
    timeline_start = min(clip.timeline_end_ms - 1, max(clip.timeline_start_ms, timeline_start))
    timeline_end = min(
        clip.timeline_end_ms,
        max(timeline_start + 1, timeline_end),
    )
    return timeline_start, timeline_end
