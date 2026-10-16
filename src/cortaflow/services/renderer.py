"""Professional FFmpeg rendering with encoder fallback and atomic output."""

import subprocess
from collections import deque
from collections.abc import Callable
from pathlib import Path
from queue import Empty, Queue
from threading import Event, Thread

from cortaflow.domain.clip import ClipRange, format_timestamp
from cortaflow.domain.editing import AudioSettings, LayerItem, ReframeSettings, TimelineClip
from cortaflow.domain.project import ExportSettings, WatermarkSettings
from cortaflow.domain.project import ReframeKeyframe
from cortaflow.domain.tracking import CropFrame
from cortaflow.infrastructure.ffmpeg import find_executable
from cortaflow.services.auto_reframe import apply_reframe_settings
from cortaflow.services.transcoder import ExportCancelled


def available_encoders() -> set[str]:
    result = subprocess.run([str(find_executable("ffmpeg")), "-hide_banner", "-encoders"], capture_output=True, text=True, encoding="utf-8", errors="replace", shell=False, check=False)
    return {name for name in ("h264_nvenc", "hevc_nvenc", "libx264", "libx265") if name in result.stdout}


def choose_video_encoder(settings: ExportSettings, encoders: set[str]) -> str:
    if settings.codec == "h265":
        return "hevc_nvenc" if settings.use_nvenc and "hevc_nvenc" in encoders else "libx265"
    return "h264_nvenc" if settings.use_nvenc and "h264_nvenc" in encoders else "libx264"


def build_render_command(
    source: Path,
    destination: Path,
    settings: ExportSettings,
    clip: ClipRange,
    crop: CropFrame | None = None,
    subtitle_path: Path | None = None,
    preview: bool = False,
    encoders: set[str] | None = None,
    crop_keyframes: list[ReframeKeyframe] | None = None,
    reframe_settings: ReframeSettings | None = None,
    audio_settings: AudioSettings | None = None,
    source_size: tuple[int, int] | None = None,
) -> list[str]:
    encoder = choose_video_encoder(settings, encoders if encoders is not None else available_encoders())
    width, height = output_dimensions(settings, reframe_settings, source_size, preview)
    filters: list[str] = []
    effective_keyframes = crop_keyframes or []
    if reframe_settings and source_size:
        effective_keyframes = apply_reframe_settings(
            effective_keyframes, reframe_settings, source_size[0], source_size[1]
        )
    motion_crop = build_motion_crop_filter(effective_keyframes, clip)
    if motion_crop:
        filters.append(motion_crop)
    elif crop:
        filters.append(f"crop={crop.width}:{crop.height}:{crop.x}:{crop.y}")
    filters.append(f"scale={width}:{height}:force_original_aspect_ratio=decrease")
    filters.append(f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black")
    escaped_subtitle = None
    if subtitle_path:
        escaped_subtitle = str(subtitle_path.resolve()).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
    watermark = settings.watermark if settings.watermark.enabled else None
    command = [
        str(find_executable("ffmpeg")), "-hide_banner", "-loglevel", "error",
        "-nostdin", "-y", "-ss", format_timestamp(clip.start_ms, True),
        "-i", str(source.resolve()),
    ]
    if watermark and watermark.image_path:
        command += ["-loop", "1", "-i", str(watermark.image_path.resolve())]
        watermark_width = max(2, round(width * watermark.width_percent / 100))
        overlay_x, overlay_y = watermark_overlay_position(watermark, width, height)
        graph = [f"[0:v]{','.join(filters)}[base]"]
        graph.append(
            f"[1:v]format=rgba,colorchannelmixer=aa={watermark.opacity:.3f},"
            f"scale={watermark_width}:-1[watermark]"
        )
        graph.append(
            f"[base][watermark]overlay=x='{overlay_x}':y='{overlay_y}':"
            "eof_action=repeat[marked]"
        )
        if escaped_subtitle:
            graph.append(
                f"[marked]subtitles=filename='{escaped_subtitle}',format=yuv420p[vout]"
            )
        else:
            graph.append("[marked]format=yuv420p[vout]")
        command += [
            "-t", format_timestamp(clip.duration_ms, True),
            "-filter_complex", ";".join(graph), "-map", "[vout]", "-map", "0:a?",
        ]
    else:
        if escaped_subtitle:
            filters.append(f"subtitles=filename='{escaped_subtitle}'")
        command += [
            "-t", format_timestamp(clip.duration_ms, True), "-vf", ",".join(filters),
            "-map", "0:v:0", "-map", "0:a?",
        ]
    command += ["-c:v", encoder]
    if encoder.endswith("_nvenc"): command += ["-cq", str(settings.quality), "-preset", "p5"]
    else: command += ["-crf", str(settings.quality), "-preset", "medium"]
    command += ["-r", str(settings.fps)]
    audio_filters: list[str] = []
    if audio_settings and audio_settings.volume != 1:
        audio_filters.append(f"volume={audio_settings.volume:.3f}")
    if settings.normalize_audio or (audio_settings and audio_settings.normalize):
        audio_filters.append("loudnorm=I=-16:TP=-1.5:LRA=11")
    if audio_filters:
        command += ["-af", ",".join(audio_filters)]
    command += ["-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-progress", "pipe:1", str(destination.resolve())]
    return command


def _escape_drawtext(value: str) -> str:
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", "\\'")
        .replace("%", "\\%")
        .replace("\n", "\\n")
    )


def _drawtext_font_option(font_name: str) -> str:
    candidate = Path(font_name).expanduser()
    if candidate.is_file():
        return f"fontfile='{_escape_drawtext(str(candidate.resolve()))}'"
    return f"font='{_escape_drawtext(font_name or 'Arial')}'"


def _layer_keyframe_expression(layer: LayerItem, attribute: str, default: float) -> str:
    """Build a compact FFmpeg expression for a layer property animated over time."""
    points = sorted(layer.keyframes, key=lambda item: item.timestamp_ms)
    if not points:
        return f"{default:.4f}"
    expression = f"{getattr(points[-1], attribute):.4f}"
    for current, following in reversed(list(zip(points, points[1:]))):
        start = current.timestamp_ms / 1000
        end = following.timestamp_ms / 1000
        start_value = float(getattr(current, attribute))
        end_value = float(getattr(following, attribute))
        duration = max(0.001, end - start)
        expression = (
            f"if(lt(t\\,{end:.3f})\\,{start_value:.4f}+"
            f"({end_value - start_value:.4f})*(t-{start:.3f})/{duration:.3f}\\,{expression})"
        )
    return expression


def output_dimensions(
    settings: ExportSettings,
    reframe: ReframeSettings | None = None,
    source_size: tuple[int, int] | None = None,
    preview: bool = False,
) -> tuple[int, int]:
    """Resolve final or preview dimensions from the persisted aspect ratio."""
    aspect = reframe.aspect_ratio if reframe else "9:16"
    if aspect == "1:1":
        width, height = settings.width, settings.width
    elif aspect == "4:5":
        width, height = settings.width, round(settings.width * 5 / 4)
    elif aspect == "original" and source_size and min(source_size) > 0:
        width, height = source_size
    else:
        width, height = settings.width, settings.height
    if preview:
        scale = min(1.0, 540 / width, 960 / height)
        width, height = round(width * scale), round(height * scale)
    return max(2, width // 2 * 2), max(2, height // 2 * 2)


def watermark_overlay_position(
    watermark: WatermarkSettings,
    output_width: int,
    output_height: int,
) -> tuple[str, str]:
    """Return bounded FFmpeg overlay expressions for preset or custom placement."""
    margin_x = round(output_width * watermark.margin_percent / 100)
    margin_y = round(output_height * watermark.margin_percent / 100)
    positions = {
        "top-left": (str(margin_x), str(margin_y)),
        "top": ("(W-w)/2", str(margin_y)),
        "top-right": (f"W-w-{margin_x}", str(margin_y)),
        "left": (str(margin_x), "(H-h)/2"),
        "center": ("(W-w)/2", "(H-h)/2"),
        "right": (f"W-w-{margin_x}", "(H-h)/2"),
        "bottom-left": (str(margin_x), f"H-h-{margin_y}"),
        "bottom": ("(W-w)/2", f"H-h-{margin_y}"),
        "bottom-right": (f"W-w-{margin_x}", f"H-h-{margin_y}"),
    }
    if watermark.position == "custom":
        return (
            f"(W-w)*{watermark.custom_x_percent / 100:.4f}",
            f"(H-h)*{watermark.custom_y_percent / 100:.4f}",
        )
    return positions[watermark.position]


def timeline_duration_ms(clips: list[TimelineClip]) -> int:
    return max((clip.timeline_end_ms for clip in clips), default=0)


def build_timeline_render_command(
    source: Path,
    destination: Path,
    settings: ExportSettings,
    clips: list[TimelineClip],
    subtitle_path: Path | None = None,
    preview: bool = False,
    encoders: set[str] | None = None,
    crop_keyframes: list[ReframeKeyframe] | None = None,
    reframe_settings: ReframeSettings | None = None,
    audio_settings: AudioSettings | None = None,
    source_size: tuple[int, int] | None = None,
    source_has_audio: bool = True,
    layers: list[LayerItem] | None = None,
) -> list[str]:
    """Build a filter graph that consumes the persisted video/audio timeline."""
    video_clips = sorted(
        (item for item in clips if item.track == "video"),
        key=lambda item: (item.timeline_start_ms, item.clip_id),
    )
    audio_clips = sorted(
        (item for item in clips if item.track == "audio"),
        key=lambda item: (item.timeline_start_ms, item.clip_id),
    )
    if not video_clips:
        raise ValueError("A linha do tempo não contém clipes de vídeo.")
    duration_ms = timeline_duration_ms(clips)
    if duration_ms <= 0:
        raise ValueError("A linha do tempo está vazia.")
    width, height = output_dimensions(settings, reframe_settings, source_size, preview)
    encoder = choose_video_encoder(settings, encoders if encoders is not None else available_encoders())
    filters: list[str] = [
        f"color=c=black:s={width}x{height}:r={settings.fps}:d={duration_ms / 1000:.3f}[base0]"
    ]

    video_inputs: list[str] = []
    if len(video_clips) == 1:
        video_inputs.append("0:v")
    else:
        labels = "".join(f"[vsrc{index}]" for index in range(len(video_clips)))
        filters.append(f"[0:v]split={len(video_clips)}{labels}")
        video_inputs.extend(f"vsrc{index}" for index in range(len(video_clips)))

    effective_keyframes = crop_keyframes or []
    if reframe_settings and source_size:
        effective_keyframes = apply_reframe_settings(
            effective_keyframes, reframe_settings, source_size[0], source_size[1]
        )
    for index, (clip_item, input_label) in enumerate(zip(video_clips, video_inputs)):
        source_clip = ClipRange(
            start_ms=clip_item.source_start_ms,
            end_ms=clip_item.source_end_ms,
        )
        chain = [
            f"trim=start={clip_item.source_start_ms / 1000:.3f}:end={clip_item.source_end_ms / 1000:.3f}",
            "setpts=PTS-STARTPTS",
        ]
        if clip_item.speed != 1:
            chain.append(f"setpts=PTS/{clip_item.speed:.6f}")
        motion_crop = build_motion_crop_filter(effective_keyframes, source_clip)
        if motion_crop:
            chain.append(motion_crop)
        chain.extend(
            (
                f"scale={width}:{height}:force_original_aspect_ratio=decrease",
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black",
                "setsar=1",
            )
        )
        fade_in = max(clip_item.fade_in_ms, clip_item.transition_ms) / 1000
        fade_out = clip_item.fade_out_ms / 1000
        if fade_in or fade_out:
            chain.append("format=yuva420p")
            if fade_in:
                chain.append(f"fade=t=in:st=0:d={min(fade_in, clip_item.duration_ms / 1000):.3f}:alpha=1")
            if fade_out:
                start = max(0.0, clip_item.duration_ms / 1000 - fade_out)
                chain.append(f"fade=t=out:st={start:.3f}:d={fade_out:.3f}:alpha=1")
        if clip_item.effect == "blur":
            chain.append("boxblur=2:1")
        elif clip_item.effect == "grayscale":
            chain.append("hue=s=0")
        elif clip_item.effect == "vintage":
            chain.append("eq=contrast=1.08:saturation=0.78:brightness=0.03")
        chain.append(f"setpts=PTS+{clip_item.timeline_start_ms / 1000:.3f}/TB")
        filters.append(f"[{input_label}]" + ",".join(chain) + f"[vclip{index}]")
        start = clip_item.timeline_start_ms / 1000
        end = clip_item.timeline_end_ms / 1000
        filters.append(
            f"[base{index}][vclip{index}]overlay=eof_action=pass:shortest=0:"
            f"enable='between(t,{start:.3f},{end:.3f})'[base{index + 1}]"
        )

    final_video = f"base{len(video_clips)}"
    watermark = settings.watermark if settings.watermark.enabled else None
    if watermark and watermark.image_path:
        watermark_width = max(2, round(width * watermark.width_percent / 100))
        overlay_x, overlay_y = watermark_overlay_position(watermark, width, height)
        filters.append(
            f"[1:v]format=rgba,colorchannelmixer=aa={watermark.opacity:.3f},"
            f"scale={watermark_width}:-1[watermark]"
        )
        filters.append(
            f"[{final_video}][watermark]overlay=x='{overlay_x}':y='{overlay_y}':"
            "eof_action=repeat[watermarked]"
        )
        final_video = "watermarked"
    image_layers = [
        layer for layer in (layers or [])
        if layer.kind == "image" and layer.visible and layer.source_path and Path(layer.source_path).is_file()
    ]
    image_input_start = 2 if watermark and watermark.image_path else 1
    for index, layer in enumerate(image_layers):
        width_px = max(2, round(width * layer.width_percent / 100))
        height_px = max(2, round(height * layer.height_percent / 100))
        opacity = _layer_keyframe_expression(layer, "opacity", layer.opacity)
        filters.append(
            f"[{image_input_start + index}:v]format=rgba,scale={width_px}:{height_px},"
            f"colorchannelmixer=aa='{opacity}'[layerimg{index}]"
        )
        x_value = _layer_keyframe_expression(layer, "x_percent", layer.x_percent)
        y_value = _layer_keyframe_expression(layer, "y_percent", layer.y_percent)
        x = f"(W-w)*({x_value})/100"
        y = f"(H-h)*({y_value})/100"
        start = layer.timeline_start_ms / 1000
        end = layer.timeline_end_ms / 1000
        filters.append(
            f"[{final_video}][layerimg{index}]overlay=x='{x}':y='{y}':"
            f"eof_action=pass:enable='between(t,{start:.3f},{end:.3f})'[layerout{index}]"
        )
        final_video = f"layerout{index}"

    text_layers = [
        layer for layer in (layers or [])
        if layer.kind == "text" and layer.visible and layer.text.strip()
    ]
    for index, layer in enumerate(text_layers):
        text = _escape_drawtext(layer.text)
        color = layer.color.lstrip("#") or "FFFFFF"
        x_value = _layer_keyframe_expression(layer, "x_percent", layer.x_percent)
        y_value = _layer_keyframe_expression(layer, "y_percent", layer.y_percent)
        opacity = _layer_keyframe_expression(layer, "opacity", layer.opacity)
        x = f"(w-text_w)*({x_value})/100"
        y = f"(h-text_h)*({y_value})/100"
        start = layer.timeline_start_ms / 1000
        end = layer.timeline_end_ms / 1000
        font_option = _drawtext_font_option(layer.font_name)
        background = ":box=1:boxcolor=black@0.45:boxborderw=14" if layer.background else ""
        filters.append(
            f"[{final_video}]drawtext={font_option}:text='{text}':"
            f"fontcolor=0x{color}@'{opacity}':fontsize={max(8, layer.font_size)}:"
            f"x='{x}':y='{y}':enable='between(t,{start:.3f},{end:.3f})'{background}[textout{index}]"
        )
        final_video = f"textout{index}"

    escaped_subtitle = None
    if subtitle_path:
        escaped_subtitle = str(subtitle_path.resolve()).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
        filters.append(f"[{final_video}]subtitles=filename='{escaped_subtitle}',format=yuv420p[vout]")
    else:
        filters.append(f"[{final_video}]format=yuv420p[vout]")

    include_audio = bool(audio_clips and source_has_audio)
    if include_audio:
        audio_inputs: list[str] = []
        if len(audio_clips) == 1:
            audio_inputs.append("0:a")
        else:
            labels = "".join(f"[asrc{index}]" for index in range(len(audio_clips)))
            filters.append(f"[0:a]asplit={len(audio_clips)}{labels}")
            audio_inputs.extend(f"asrc{index}" for index in range(len(audio_clips)))
        for index, (clip_item, input_label) in enumerate(zip(audio_clips, audio_inputs)):
            chain = [
                f"atrim=start={clip_item.source_start_ms / 1000:.3f}:end={clip_item.source_end_ms / 1000:.3f}",
                "asetpts=PTS-STARTPTS",
            ]
            if clip_item.speed != 1:
                chain.extend(_atempo_filters(clip_item.speed))
            fade_in = max(clip_item.fade_in_ms, clip_item.transition_ms) / 1000
            fade_out = clip_item.fade_out_ms / 1000
            if fade_in:
                chain.append(f"afade=t=in:st=0:d={min(fade_in, clip_item.duration_ms / 1000):.3f}")
            if fade_out:
                start = max(0.0, clip_item.duration_ms / 1000 - fade_out)
                chain.append(f"afade=t=out:st={start:.3f}:d={fade_out:.3f}")
            if clip_item.timeline_start_ms:
                chain.append(f"adelay={clip_item.timeline_start_ms}|{clip_item.timeline_start_ms}")
            filters.append(f"[{input_label}]" + ",".join(chain) + f"[aclip{index}]")
        audio_labels = "".join(f"[aclip{index}]" for index in range(len(audio_clips)))
        if len(audio_clips) == 1:
            filters.append("[aclip0]anull[amixed]")
        else:
            filters.append(
                f"{audio_labels}amix=inputs={len(audio_clips)}:duration=longest:dropout_transition=0[amixed]"
            )
        audio_chain: list[str] = []
        if audio_settings and audio_settings.volume != 1:
            audio_chain.append(f"volume={audio_settings.volume:.3f}")
        if settings.normalize_audio or (audio_settings and audio_settings.normalize):
            audio_chain.append("loudnorm=I=-16:TP=-1.5:LRA=11")
        audio_chain.append(f"atrim=end={duration_ms / 1000:.3f}")
        filters.append("[amixed]" + ",".join(audio_chain) + "[aout]")

    command = [
        str(find_executable("ffmpeg")), "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
        "-i", str(source.resolve()),
    ]
    if watermark and watermark.image_path:
        command += ["-loop", "1", "-i", str(watermark.image_path.resolve())]
    for layer in image_layers:
        command += ["-loop", "1", "-i", str(Path(layer.source_path).resolve())]
    command += ["-filter_complex", ";".join(filters), "-map", "[vout]"]
    if include_audio:
        command += ["-map", "[aout]"]
    command += ["-c:v", encoder]
    if encoder.endswith("_nvenc"):
        command += ["-cq", str(settings.quality), "-preset", "p5"]
    else:
        command += ["-crf", str(settings.quality), "-preset", "medium"]
    command += ["-r", str(settings.fps)]
    if include_audio:
        command += ["-c:a", "aac", "-b:a", "192k"]
    command += [
        "-t", f"{duration_ms / 1000:.3f}", "-movflags", "+faststart",
        "-progress", "pipe:1", str(destination.resolve()),
    ]
    return command


def _atempo_filters(speed: float) -> list[str]:
    """Represent any supported speed using FFmpeg's 0.5–2.0 atempo range."""
    remaining = speed
    filters: list[str] = []
    while remaining > 2:
        filters.append("atempo=2.0")
        remaining /= 2
    while remaining < 0.5:
        filters.append("atempo=0.5")
        remaining /= 0.5
    if abs(remaining - 1) > 0.001:
        filters.append(f"atempo={remaining:.6f}")
    return filters


def build_motion_crop_filter(
    keyframes: list[ReframeKeyframe],
    clip: ClipRange,
) -> str | None:
    """Build per-frame x/y interpolation expressions for FFmpeg's crop filter."""
    relevant = sorted(keyframes, key=lambda item: (item.timestamp_ms, item.manual))
    if not relevant:
        return None
    previous = [item for item in relevant if item.timestamp_ms <= clip.start_ms]
    points = ([previous[-1]] if previous else [relevant[0]]) + [
        item for item in relevant if clip.start_ms < item.timestamp_ms < clip.end_ms
    ]
    unique: dict[int, ReframeKeyframe] = {}
    for item in points:
        unique[max(0, item.timestamp_ms - clip.start_ms)] = item
    points = [unique[key] for key in sorted(unique)]
    points = _limit_motion_keyframes(points)
    unique = {max(0, item.timestamp_ms - clip.start_ms): item for item in points}
    times = sorted(unique)
    first = points[0].crop
    x_values = [(timestamp / 1000, unique[timestamp].crop.x) for timestamp in times]
    y_values = [(timestamp / 1000, unique[timestamp].crop.y) for timestamp in times]
    reset_times = {
        timestamp / 1000
        for timestamp in times
        if unique[timestamp].scene_reset
    }
    x_expression = _piecewise_expression(x_values, reset_times)
    y_expression = _piecewise_expression(y_values, reset_times)
    return f"crop={first.width}:{first.height}:x='{x_expression}':y='{y_expression}'"


def _limit_motion_keyframes(
    points: list[ReframeKeyframe],
    maximum_points: int = 60,
) -> list[ReframeKeyframe]:
    """Bound FFmpeg expression size while preserving endpoints and manual edits."""
    if len(points) <= maximum_points:
        return points
    preserved = sum(item.manual or item.scene_reset for item in points)
    automatic_slots = max(2, maximum_points - preserved)
    indexes = {
        round(index * (len(points) - 1) / (automatic_slots - 1))
        for index in range(automatic_slots)
    }
    indexes.update(
        index for index, item in enumerate(points) if item.manual or item.scene_reset
    )
    return [points[index] for index in sorted(indexes)]


def _piecewise_expression(
    points: list[tuple[float, int]],
    reset_times: set[float] | None = None,
) -> str:
    if len(points) == 1:
        return str(points[0][1])
    expression = str(points[-1][1])
    hard_cuts = reset_times or set()
    for (start_time, start_value), (end_time, end_value) in reversed(list(zip(points, points[1:]))):
        duration = max(0.001, end_time - start_time)
        interpolated = (
            str(start_value)
            if end_time in hard_cuts
            else f"{start_value}+({end_value - start_value})*(t-{start_time:.3f})/{duration:.3f}"
        )
        expression = f"if(lt(t\\,{end_time:.3f})\\,{interpolated}\\,{expression})"
    return expression


def render(
    source: Path,
    destination: Path,
    settings: ExportSettings,
    clip: ClipRange,
    crop: CropFrame | None = None,
    subtitle_path: Path | None = None,
    preview: bool = False,
    crop_keyframes: list[ReframeKeyframe] | None = None,
    progress: Callable[[dict[str, str]], None] | None = None,
    cancelled: Event | None = None,
    reframe_settings: ReframeSettings | None = None,
    audio_settings: AudioSettings | None = None,
    source_size: tuple[int, int] | None = None,
) -> Path:
    if destination.exists():
        raise FileExistsError("O destino já existe e não será sobrescrito.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.stem}.rendering{destination.suffix}")
    if temporary.exists():
        raise FileExistsError("Existe uma renderização parcial anterior; remova-a ou escolha outro destino.")
    encoders = available_encoders()
    encoder = choose_video_encoder(settings, encoders)
    attempts = [encoders]
    if encoder.endswith("_nvenc"):
        attempts.append({name for name in encoders if not name.endswith("_nvenc")})
    last_error = ""
    try:
        for attempt_index, attempt_encoders in enumerate(attempts):
            if attempt_index and progress:
                progress(
                    {
                        "progress": "fallback",
                        "encoder": choose_video_encoder(settings, attempt_encoders),
                        "message": "NVENC falhou; continuando com codificação por CPU.",
                    }
                )
            success, last_error = _render_attempt(
                source,
                temporary,
                settings,
                clip,
                crop,
                subtitle_path,
                preview,
                crop_keyframes or [],
                attempt_encoders,
                progress,
                cancelled,
                reframe_settings,
                audio_settings,
                source_size,
            )
            if success:
                temporary.replace(destination)
                return destination
            if temporary.exists():
                temporary.unlink()
        raise RuntimeError(f"FFmpeg falhou: {last_error[-800:]}")
    except Exception:
        if temporary.exists():
            temporary.unlink()
        raise


def render_timeline(
    source: Path,
    destination: Path,
    settings: ExportSettings,
    clips: list[TimelineClip],
    subtitle_path: Path | None = None,
    preview: bool = False,
    crop_keyframes: list[ReframeKeyframe] | None = None,
    reframe_settings: ReframeSettings | None = None,
    audio_settings: AudioSettings | None = None,
    source_size: tuple[int, int] | None = None,
    source_has_audio: bool = True,
    progress: Callable[[dict[str, str]], None] | None = None,
    cancelled: Event | None = None,
    layers: list[LayerItem] | None = None,
) -> Path:
    """Render the complete persisted timeline with atomic publication and fallback."""
    if destination.exists():
        raise FileExistsError("O destino já existe e não será sobrescrito.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.stem}.rendering{destination.suffix}")
    if temporary.exists():
        raise FileExistsError("Existe uma renderização parcial anterior; remova-a ou escolha outro destino.")
    encoders = available_encoders()
    attempts = [encoders]
    if choose_video_encoder(settings, encoders).endswith("_nvenc"):
        attempts.append({name for name in encoders if not name.endswith("_nvenc")})
    last_error = ""
    try:
        for attempt_index, attempt_encoders in enumerate(attempts):
            if attempt_index and progress:
                progress(
                    {
                        "progress": "fallback",
                        "encoder": choose_video_encoder(settings, attempt_encoders),
                        "message": "NVENC falhou; continuando com codificação por CPU.",
                    }
                )
            command = build_timeline_render_command(
                source, temporary, settings, clips, subtitle_path, preview, attempt_encoders,
                crop_keyframes, reframe_settings, audio_settings, source_size, source_has_audio, layers,
            )
            success, last_error = _run_render_process(
                command,
                choose_video_encoder(settings, attempt_encoders),
                progress,
                cancelled,
            )
            if success:
                temporary.replace(destination)
                return destination
            if temporary.exists():
                temporary.unlink()
        raise RuntimeError(f"FFmpeg falhou: {last_error[-800:]}")
    except Exception:
        if temporary.exists():
            temporary.unlink()
        raise


def _run_render_process(
    command: list[str],
    encoder: str,
    progress: Callable[[dict[str, str]], None] | None,
    cancelled: Event | None,
) -> tuple[bool, str]:
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        shell=False,
    )
    return _monitor_render_process(process, encoder, progress, cancelled)


def _render_attempt(
    source: Path,
    temporary: Path,
    settings: ExportSettings,
    clip: ClipRange,
    crop: CropFrame | None,
    subtitle_path: Path | None,
    preview: bool,
    crop_keyframes: list[ReframeKeyframe],
    encoders: set[str],
    progress: Callable[[dict[str, str]], None] | None,
    cancelled: Event | None,
    reframe_settings: ReframeSettings | None,
    audio_settings: AudioSettings | None,
    source_size: tuple[int, int] | None,
) -> tuple[bool, str]:
    encoder = choose_video_encoder(settings, encoders)
    process = subprocess.Popen(
        build_render_command(
            source,
            temporary,
            settings,
            clip,
            crop,
            subtitle_path,
            preview,
            encoders,
            crop_keyframes,
            reframe_settings,
            audio_settings,
            source_size,
        ),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        shell=False,
    )
    return _monitor_render_process(process, encoder, progress, cancelled)


def _monitor_render_process(
    process: subprocess.Popen[str],
    encoder: str,
    progress: Callable[[dict[str, str]], None] | None,
    cancelled: Event | None,
) -> tuple[bool, str]:
    """Drain FFmpeg stdout/stderr concurrently to prevent Windows pipe deadlocks."""
    assert process.stdout is not None
    assert process.stderr is not None
    stdout_queue: Queue[str] = Queue()
    stderr_lines: deque[str] = deque(maxlen=2_000)

    def read_stdout() -> None:
        for line in process.stdout:
            stdout_queue.put(line)

    def read_stderr() -> None:
        for line in process.stderr:
            stderr_lines.append(line)

    stdout_thread = Thread(target=read_stdout, daemon=True)
    stderr_thread = Thread(target=read_stderr, daemon=True)
    stdout_thread.start()
    stderr_thread.start()
    state: dict[str, str] = {}
    try:
        while process.poll() is None or stdout_thread.is_alive() or not stdout_queue.empty():
            if cancelled and cancelled.is_set():
                process.terminate()
                raise ExportCancelled("Renderização cancelada.")
            try:
                line = stdout_queue.get(timeout=0.1)
            except Empty:
                continue
            key, separator, value = line.strip().partition("=")
            if separator:
                state[key] = value
                if key == "progress" and progress:
                    state["encoder"] = encoder
                    progress(dict(state))
                    state.clear()
        process.wait()
        stdout_thread.join(timeout=2)
        stderr_thread.join(timeout=2)
        return process.returncode == 0, "".join(stderr_lines)
    except Exception:
        if process.poll() is None:
            process.kill()
            process.wait()
        stdout_thread.join(timeout=2)
        stderr_thread.join(timeout=2)
        raise
