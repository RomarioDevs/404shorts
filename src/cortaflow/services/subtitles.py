"""Readable subtitle grouping and export."""

import json
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path
from threading import Event
from typing import Any

import pysubs2

from cortaflow.domain.subtitle import SubtitleCue, Transcript, TranscriptWord
from cortaflow.domain.clip import ClipRange
from cortaflow.domain.editing import SubtitleStyle
from cortaflow.infrastructure.ffmpeg import find_executable, hidden_console_options
from cortaflow.services.transcoder import ExportCancelled


def group_words(
    words: list[TranscriptWord],
    min_words: int = 2,
    max_words: int = 7,
    max_chars: int = 42,
    preset: str = "dynamic",
) -> list[SubtitleCue]:
    """Group words using punctuation, pauses, duration and a readability preset."""
    if not words:
        return []
    preset_limits = {
        "clean": (max_words, max_chars, 3_200, 900),
        "dynamic": (min(max_words, 6), min(max_chars, 38), 2_400, 650),
        "viral": (min(max_words, 4), min(max_chars, 28), 1_800, 450),
    }
    effective_max_words, effective_max_chars, max_duration_ms, pause_ms = preset_limits.get(
        preset, preset_limits["dynamic"]
    )
    cues: list[SubtitleCue] = []
    current: list[TranscriptWord] = []
    for word in words:
        previous = current[-1] if current else None
        if previous and word.start_ms - previous.end_ms >= pause_ms and len(current) >= min_words:
            cues.append(_cue_from_words(current))
            current = []
        current.append(word)
        text = " ".join(item.text.strip() for item in current).strip()
        punctuated = word.text.rstrip().endswith((".", "!", "?", ":", ";"))
        duration = word.end_ms - current[0].start_ms
        should_break = (
            len(current) >= effective_max_words
            or len(text) >= effective_max_chars
            or duration >= max_duration_ms
            or (punctuated and len(current) >= min_words)
        )
        if should_break:
            cues.append(_cue_from_words(current))
            current = []
    if current:
        if len(current) == 1 and cues and len(cues[-1].text.split()) < effective_max_words:
            previous = cues[-1]
            cues[-1] = SubtitleCue(
                start_ms=previous.start_ms,
                end_ms=current[-1].end_ms,
                text=f"{previous.text} {current[0].text}".strip(),
            )
        else:
            cues.append(_cue_from_words(current))
    return cues


def _cue_from_words(words: list[TranscriptWord]) -> SubtitleCue:
    return SubtitleCue(
        start_ms=words[0].start_ms,
        end_ms=words[-1].end_ms,
        text=" ".join(item.text.strip() for item in words).strip(),
    )


def save_transcript(transcript: Transcript, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(transcript.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_transcript(path: Path) -> Transcript:
    """Load and validate a previously saved transcript JSON file."""
    return Transcript.model_validate_json(path.read_text(encoding="utf-8"))


def export_subtitles(
    cues: list[SubtitleCue],
    path: Path,
    animated: bool = False,
    style: SubtitleStyle | None = None,
    words: list[TranscriptWord] | None = None,
    resolution: tuple[int, int] = (1080, 1920),
) -> Path:
    subs = pysubs2.SSAFile()
    if animated:
        configured = style or SubtitleStyle()
        width, height = resolution
        if min(width, height) <= 0:
            raise ValueError("A resolução lógica da legenda deve ser positiva.")
        subs.info["PlayResX"] = str(width)
        subs.info["PlayResY"] = str(height)
        subs.info["WrapStyle"] = "0"
        subs.info["ScaledBorderAndShadow"] = "yes"
        style_scale = width / 1080
        alignment = {
            "top": pysubs2.Alignment.TOP_CENTER,
            "center": pysubs2.Alignment.MIDDLE_CENTER,
            "bottom": pysubs2.Alignment.BOTTOM_CENTER,
        }[configured.position]
        ass_style = pysubs2.SSAStyle(
            fontname=configured.font_name,
            fontsize=max(8, round(configured.font_size * style_scale)),
            bold=True,
            primarycolor=_parse_color(configured.primary_color),
            secondarycolor=_parse_color(configured.highlight_color),
            outlinecolor=_parse_color(configured.outline_color),
            outline=round(configured.outline_width * style_scale, 1),
            shadow=round(configured.shadow * style_scale, 1),
            alignment=alignment,
            marginl=max(24, round(width * 0.08)),
            marginr=max(24, round(width * 0.08)),
            marginv=max(24, round(height * 0.08)),
            borderstyle=3 if configured.background else 1,
        )
        subs.styles["CortaFlow"] = ass_style
    for cue in cues:
        text = _wrap_two_lines(cue.text)
        if animated:
            cue_words = [
                word
                for word in (words or [])
                if word.end_ms > cue.start_ms and word.start_ms < cue.end_ms
            ]
            text = _karaoke_text(cue, text, cue_words)
        subs.events.append(pysubs2.SSAEvent(start=cue.start_ms, end=cue.end_ms, text=text, style="CortaFlow" if animated else "Default"))
    path.parent.mkdir(parents=True, exist_ok=True)
    subs.save(str(path), format_="ass" if path.suffix.lower() == ".ass" else "srt")
    return path


def export_vtt(cues: list[SubtitleCue], path: Path) -> Path:
    """Write standards-compliant WebVTT cues with deterministic timestamps."""
    lines = ["WEBVTT", ""]
    for index, cue in enumerate(cues, start=1):
        lines.extend(
            [
                str(index),
                f"{_vtt_timestamp(cue.start_ms)} --> {_vtt_timestamp(cue.end_ms)}",
                _vtt_text(cue.text),
                "",
            ]
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _vtt_text(text: str) -> str:
    return _wrap_two_lines(text).replace(chr(92) + "N", chr(10))


def _vtt_timestamp(milliseconds: int) -> str:
    milliseconds = max(0, milliseconds)
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1_000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{millis:03d}"


def clip_subtitle_track(
    cues: list[SubtitleCue],
    words: list[TranscriptWord],
    clip: ClipRange,
    max_words: int = 7,
    preset: str = "dynamic",
) -> tuple[list[SubtitleCue], list[TranscriptWord]]:
    """Clip source timestamps and shift the subtitle track to output time zero."""
    clipped_words = [
        TranscriptWord(
            text=word.text,
            start_ms=max(word.start_ms, clip.start_ms) - clip.start_ms,
            end_ms=min(word.end_ms, clip.end_ms) - clip.start_ms,
            probability=word.probability,
        )
        for word in words
        if word.end_ms > clip.start_ms and word.start_ms < clip.end_ms
    ]
    clipped_words = [word for word in clipped_words if word.end_ms > word.start_ms]
    if clipped_words:
        generated = group_words(clipped_words, max_words=max_words, preset=preset)
        manual = [
            SubtitleCue(
                start_ms=max(cue.start_ms, clip.start_ms) - clip.start_ms,
                end_ms=min(cue.end_ms, clip.end_ms) - clip.start_ms,
                text=cue.text,
                manually_edited=True,
            )
            for cue in cues
            if cue.manually_edited
            and cue.end_ms > clip.start_ms
            and cue.start_ms < clip.end_ms
        ]
        return merge_manual_corrections(manual, generated), clipped_words
    clipped_cues = [
        SubtitleCue(
            start_ms=max(cue.start_ms, clip.start_ms) - clip.start_ms,
            end_ms=min(cue.end_ms, clip.end_ms) - clip.start_ms,
            text=cue.text,
            manually_edited=cue.manually_edited,
        )
        for cue in cues
        if cue.end_ms > clip.start_ms and cue.start_ms < clip.end_ms
    ]
    return [cue for cue in clipped_cues if cue.end_ms > cue.start_ms], []


def _wrap_two_lines(text: str) -> str:
    words = text.replace("\\N", " ").split()
    plain = " ".join(words)
    if len(words) < 2 or len(plain) <= 28:
        return plain
    best_split = min(
        range(1, len(words)),
        key=lambda index: abs(len(" ".join(words[:index])) - len(" ".join(words[index:]))),
    )
    left, right = " ".join(words[:best_split]), " ".join(words[best_split:])
    return f"{left}\\N{right}"


def _karaoke_text(
    cue: SubtitleCue,
    wrapped_text: str,
    timed_words: list[TranscriptWord],
) -> str:
    plain_words = cue.text.split()
    if timed_words and len(timed_words) == len(plain_words):
        cursor = cue.start_ms
        result: list[str] = []
        line_break_after = len(wrapped_text.split("\\N", maxsplit=1)[0].split()) if "\\N" in wrapped_text else -1
        for index, (text, word) in enumerate(zip(plain_words, timed_words), start=1):
            duration_cs = max(1, round((min(cue.end_ms, word.end_ms) - cursor) / 10))
            result.append(f"{{\\kf{duration_cs}}}{text}")
            cursor = min(cue.end_ms, word.end_ms)
            result.append("\\N" if index == line_break_after else " ")
        return "".join(result).rstrip()
    duration_cs = max(1, (cue.end_ms - cue.start_ms) // 10)
    each = max(1, duration_cs // max(1, len(plain_words)))
    pieces = [f"{{\\kf{each}}}{word}" for word in plain_words]
    if "\\N" in wrapped_text:
        split = len(wrapped_text.split("\\N", maxsplit=1)[0].split())
        return " ".join(pieces[:split]) + "\\N" + " ".join(pieces[split:])
    return " ".join(pieces)


def merge_manual_corrections(old: list[SubtitleCue], generated: list[SubtitleCue]) -> list[SubtitleCue]:
    """Preserve manually edited cues with matching time overlap."""
    result = list(generated)
    for manual in (cue for cue in old if cue.manually_edited):
        match = next((index for index, cue in enumerate(result) if min(cue.end_ms, manual.end_ms) > max(cue.start_ms, manual.start_ms)), None)
        if match is None:
            result.append(manual)
        else:
            result[match] = manual
    return sorted(result, key=lambda cue: cue.start_ms)


def _parse_color(value: str) -> pysubs2.Color:
    cleaned = value.strip().lstrip("#")
    if len(cleaned) != 6:
        return pysubs2.Color(255, 255, 255)
    try:
        return pysubs2.Color(*(int(cleaned[index:index + 2], 16) for index in (0, 2, 4)))
    except ValueError:
        return pysubs2.Color(255, 255, 255)


def escape_subtitle_filter_path(path: Path) -> str:
    """Escape a local path for FFmpeg's subtitles filter parser."""
    value = path.resolve().as_posix()
    return value.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def build_burn_subtitles_command(source: Path, subtitle_path: Path, destination: Path) -> list[str]:
    """Build a compatible H.264/AAC command that burns ASS/SRT subtitles."""
    subtitle_filter = f"subtitles=filename='{escape_subtitle_filter_path(subtitle_path)}'"
    return [
        str(find_executable("ffmpeg")),
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-y",
        "-i",
        str(source.resolve()),
        "-vf",
        subtitle_filter,
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "20",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        "-progress",
        "pipe:1",
        str(destination.resolve()),
    ]


def burn_subtitles(
    source: Path,
    destination: Path,
    cues: list[SubtitleCue],
    style: SubtitleStyle | None = None,
    progress: Callable[[dict[str, Any]], None] | None = None,
    cancelled: Event | None = None,
) -> Path:
    """Burn animated ASS subtitles and atomically publish the completed video."""
    source = source.resolve()
    destination = destination.resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    if not cues:
        raise ValueError("Não há legendas para aplicar.")
    if destination.exists():
        raise FileExistsError("O destino já existe e não será sobrescrito.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_video = destination.with_name(f".{destination.stem}.legendando{destination.suffix}")

    with tempfile.TemporaryDirectory(prefix="cortaflow-legendas-", dir=destination.parent) as temp_dir:
        from cortaflow.services.media_probe import probe_media

        metadata = probe_media(source)
        subtitle_path = export_subtitles(
            cues,
            Path(temp_dir) / "legendas.ass",
            animated=True,
            style=style,
            resolution=(metadata.width or 1080, metadata.height or 1920),
        )
        process = subprocess.Popen(
            build_burn_subtitles_command(source, subtitle_path, temporary_video),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
            **hidden_console_options(),
        )
        state: dict[str, str] = {}
        try:
            assert process.stdout is not None
            for line in process.stdout:
                if cancelled and cancelled.is_set():
                    process.terminate()
                    raise ExportCancelled("Aplicação de legendas cancelada.")
                key, separator, value = line.strip().partition("=")
                if separator:
                    state[key] = value
                    if key == "progress" and progress:
                        progress(dict(state))
                        state.clear()
            _, stderr = process.communicate()
            if process.returncode != 0:
                raise RuntimeError(f"FFmpeg falhou ao aplicar as legendas: {stderr[-800:]}")
            temporary_video.replace(destination)
            return destination
        except Exception:
            if process.poll() is None:
                process.kill()
                process.wait()
            if temporary_video.exists():
                temporary_video.unlink()
            raise
