"""Aspect-safe crop calculation, interpolation and motion smoothing."""

from cortaflow.domain.project import ReframeKeyframe
from cortaflow.domain.editing import ReframeSettings
from cortaflow.domain.tracking import CropFrame, FaceBox, FaceTrackPoint, SpeakerKeyframe


def calculate_crop(
    source_width: int,
    source_height: int,
    aspect_width: int = 9,
    aspect_height: int = 16,
    focus: FaceBox | None = None,
) -> CropFrame:
    if min(source_width, source_height, aspect_width, aspect_height) <= 0:
        raise ValueError("As dimensões do enquadramento devem ser positivas.")
    target_ratio = aspect_width / aspect_height
    if source_width / source_height > target_ratio:
        height = source_height
        width = round(height * target_ratio)
    else:
        width = source_width
        height = round(width / target_ratio)
    center_x = (focus.x + focus.width / 2) * source_width if focus else source_width / 2
    desired_eye_y = (focus.y + focus.height * 0.35) * source_height if focus else source_height / 3
    x = round(center_x - width / 2)
    y = round(desired_eye_y - height / 3)
    return CropFrame(
        x=max(0, min(source_width - width, x)),
        y=max(0, min(source_height - height, y)),
        width=width,
        height=height,
    )


def smooth_crop(
    previous: CropFrame,
    target: CropFrame,
    alpha: float = 0.2,
    dead_zone_px: int = 8,
    max_step_px: int = 80,
) -> CropFrame:
    def move(old: int, new: int) -> int:
        delta = new - old
        if abs(delta) <= dead_zone_px:
            return old
        return max(0, round(old + max(-max_step_px, min(max_step_px, delta * alpha))))

    return CropFrame(
        x=move(previous.x, target.x),
        y=move(previous.y, target.y),
        width=move(previous.width, target.width),
        height=move(previous.height, target.height),
    )


def keep_face_in_safe_area(
    crop: CropFrame,
    focus: FaceBox | None,
    source_width: int,
    source_height: int,
    horizontal_margin: float = 0.16,
) -> CropFrame:
    """Move a crop just enough to keep the complete face away from side borders."""
    if focus is None:
        return crop
    face_left = focus.x * source_width
    face_right = (focus.x + focus.width) * source_width
    safe_left = crop.x + crop.width * horizontal_margin
    safe_right = crop.x + crop.width * (1 - horizontal_margin)
    x = float(crop.x)
    if face_left < safe_left:
        x = face_left - crop.width * horizontal_margin
    if face_right > safe_right:
        x = face_right - crop.width * (1 - horizontal_margin)
    return crop.model_copy(
        update={"x": max(0, min(source_width - crop.width, round(x)))}
    )


def interpolate_crop(start: CropFrame, end: CropFrame, progress: float) -> CropFrame:
    """Linearly interpolate crop values between two tracked observations."""
    amount = max(0.0, min(1.0, progress))
    blend = lambda left, right: round(left + (right - left) * amount)
    return CropFrame(
        x=blend(start.x, end.x),
        y=blend(start.y, end.y),
        width=blend(start.width, end.width),
        height=blend(start.height, end.height),
    )


def apply_reframe_settings(
    keyframes: list[ReframeKeyframe],
    settings: ReframeSettings,
    source_width: int,
    source_height: int,
) -> list[ReframeKeyframe]:
    """Apply the persisted aspect, zoom and motion limits to render keyframes."""
    if min(source_width, source_height) <= 0:
        return list(keyframes)
    aspect = {
        "9:16": (9, 16),
        "16:9": (16, 9),
        "1:1": (1, 1),
        "4:5": (4, 5),
        "original": (source_width, source_height),
    }[settings.aspect_ratio]
    base = calculate_crop(source_width, source_height, *aspect)
    target_width = min(source_width, max(2, round(base.width / settings.zoom)))
    target_height = min(source_height, max(2, round(base.height / settings.zoom)))

    def positioned(center_x: float, center_y: float) -> CropFrame:
        x = round(center_x - target_width / 2)
        y = round(center_y - target_height / 2)
        return CropFrame(
            x=max(0, min(source_width - target_width, x)),
            y=max(0, min(source_height - target_height, y)),
            width=target_width,
            height=target_height,
        )

    if not settings.automatic:
        return [
            ReframeKeyframe(
                timestamp_ms=0,
                crop=CropFrame(
                    x=min(settings.x, source_width - target_width),
                    y=min(settings.y, source_height - target_height),
                    width=target_width,
                    height=target_height,
                ),
                manual=True,
            )
        ]
    if not keyframes:
        return [
            ReframeKeyframe(
                timestamp_ms=0,
                crop=positioned(source_width / 2 + settings.x, source_height / 2 + settings.y),
            )
        ]

    result: list[ReframeKeyframe] = []
    previous: CropFrame | None = None
    for keyframe in sorted(keyframes, key=lambda item: item.timestamp_ms):
        source_crop = keyframe.crop
        target = positioned(
            source_crop.x + source_crop.width / 2 + settings.x,
            source_crop.y + source_crop.height / 2 + settings.y,
        )
        # Face-safe automatic keyframes have already been smoothed against the detected
        # face. Smoothing them twice makes the crop lag and can cut a moving face.
        if (
            previous is not None
            and not keyframe.manual
            and not keyframe.scene_reset
            and not keyframe.face_safe
            and settings.smoothing > 0
        ):
            target = smooth_crop(
                previous,
                target,
                alpha=settings.smoothing,
                max_step_px=settings.max_speed_px,
            )
        result.append(
            ReframeKeyframe(
                timestamp_ms=keyframe.timestamp_ms,
                crop=target,
                manual=keyframe.manual,
                scene_reset=keyframe.scene_reset,
                face_safe=keyframe.face_safe,
            )
        )
        previous = target
    return result


def generate_reframe_keyframes(
    tracks: list[FaceTrackPoint],
    source_width: int,
    source_height: int,
    selected_track_id: int | None = None,
    scene_boundaries_ms: list[int] | None = None,
) -> list[ReframeKeyframe]:
    """Create smoothed automatic keyframes; selected temporary ID has priority."""
    if not tracks:
        return []
    scene_boundaries = sorted(scene_boundaries_ms or [])
    grouped: dict[int, list[FaceTrackPoint]] = {}
    for point in tracks:
        grouped.setdefault(point.timestamp_ms, []).append(point)
    keyframes: list[ReframeKeyframe] = []
    previous: CropFrame | None = None
    previous_timestamp = -1
    for timestamp in sorted(grouped):
        faces = grouped[timestamp]
        focus = next(
            (point for point in faces if point.track_id == selected_track_id),
            max(faces, key=lambda point: point.box.width * point.box.height),
        )
        target = calculate_crop(source_width, source_height, focus=focus.box)
        scene_reset = any(previous_timestamp < boundary <= timestamp for boundary in scene_boundaries)
        crop = target if previous is None or scene_reset else smooth_crop(previous, target)
        crop = keep_face_in_safe_area(crop, focus.box, source_width, source_height)
        keyframes.append(
            ReframeKeyframe(
                timestamp_ms=timestamp,
                crop=crop,
                manual=False,
                scene_reset=scene_reset,
            )
        )
        previous, previous_timestamp = crop, timestamp
    return keyframes


def generate_speaker_reframe_keyframes(
    tracks: list[FaceTrackPoint],
    speakers: list[SpeakerKeyframe],
    source_width: int,
    source_height: int,
    scene_boundaries_ms: list[int] | None = None,
) -> list[ReframeKeyframe]:
    """Follow speaker decisions; uncertain decisions use a group-friendly crop."""
    tracks_by_timestamp: dict[int, list[FaceTrackPoint]] = {}
    for point in tracks:
        tracks_by_timestamp.setdefault(point.timestamp_ms, []).append(point)
    decisions = {item.timestamp_ms: item for item in speakers}
    previous: CropFrame | None = None
    previous_timestamp = -1
    boundaries = sorted(scene_boundaries_ms or [])
    result: list[ReframeKeyframe] = []
    for timestamp in sorted(tracks_by_timestamp):
        faces = tracks_by_timestamp[timestamp]
        decision = decisions.get(timestamp)
        focus_point = next(
            (point for point in faces if decision and point.track_id == decision.track_id),
            None,
        )
        focus = focus_point.box if focus_point else _combined_face_box([point.box for point in faces])
        target = calculate_crop(source_width, source_height, focus=focus)
        scene_reset = any(previous_timestamp < boundary <= timestamp for boundary in boundaries)
        manual = bool(decision and decision.manual)
        crop = target if previous is None or scene_reset or manual else smooth_crop(previous, target)
        crop = keep_face_in_safe_area(crop, focus, source_width, source_height)
        result.append(
            ReframeKeyframe(
                timestamp_ms=timestamp,
                crop=crop,
                manual=manual,
                scene_reset=scene_reset,
            )
        )
        previous, previous_timestamp = crop, timestamp
    return result


def _combined_face_box(boxes: list[FaceBox]) -> FaceBox | None:
    if not boxes:
        return None
    left = min(box.x for box in boxes)
    top = min(box.y for box in boxes)
    right = max(box.x + box.width for box in boxes)
    bottom = max(box.y + box.height for box in boxes)
    return FaceBox(x=left, y=top, width=right - left, height=bottom - top)
