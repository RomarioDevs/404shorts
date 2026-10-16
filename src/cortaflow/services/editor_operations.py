"""Pure timeline editing operations used by undoable UI commands."""

from uuid import uuid4

from cortaflow.domain.editing import TimelineClip


def create_initial_clips(duration_ms: int, label: str = "Mídia original") -> list[TimelineClip]:
    if duration_ms <= 0:
        return []
    group = uuid4().hex
    return [
        TimelineClip(
            clip_id=f"{group}-video",
            track="video",
            source_start_ms=0,
            source_end_ms=duration_ms,
            timeline_start_ms=0,
            label=label,
        ),
        TimelineClip(
            clip_id=f"{group}-audio",
            track="audio",
            source_start_ms=0,
            source_end_ms=duration_ms,
            timeline_start_ms=0,
            label=label,
        ),
    ]


def split_at(clips: list[TimelineClip], position_ms: int) -> list[TimelineClip]:
    """Split every audio/video clip crossed by the playhead."""
    changed = False
    result: list[TimelineClip] = []
    for clip in clips:
        if not clip.timeline_start_ms < position_ms < clip.timeline_end_ms:
            result.append(clip)
            continue
        changed = True
        offset = position_ms - clip.timeline_start_ms
        split_source = clip.source_start_ms + round(offset * clip.speed)
        result.extend(
            (
                _updated(clip, source_end_ms=split_source),
                _updated(
                    clip,
                    clip_id=f"{uuid4().hex}-{clip.track}",
                    source_start_ms=split_source,
                    timeline_start_ms=position_ms,
                ),
            )
        )
    if not changed:
        raise ValueError("O cursor deve estar dentro de um clipe para dividir.")
    return sorted(result, key=lambda item: (item.track, item.timeline_start_ms))


def delete_clip(clips: list[TimelineClip], clip_id: str) -> list[TimelineClip]:
    result = [clip for clip in clips if clip.clip_id != clip_id]
    if len(result) == len(clips):
        raise ValueError("Selecione um clipe válido para excluir.")
    return result


def snap_position(
    clips: list[TimelineClip],
    clip_id: str,
    timeline_start_ms: int,
    threshold_ms: int = 120,
) -> int:
    """Snap a dragged clip to nearby clip edges, like a magnetic timeline."""
    target = next((clip for clip in clips if clip.clip_id == clip_id), None)
    if target is None:
        raise ValueError("Clipe não encontrado.")
    proposed_end = timeline_start_ms + target.duration_ms
    candidates = {0}
    for clip in clips:
        if clip.clip_id != clip_id:
            candidates.update((clip.timeline_start_ms, clip.timeline_end_ms))
    anchors = (timeline_start_ms, proposed_end)
    best: tuple[int, int] | None = None
    for edge in anchors:
        for candidate in candidates:
            distance = abs(edge - candidate)
            if distance > threshold_ms:
                continue
            snapped = candidate if edge == timeline_start_ms else candidate - target.duration_ms
            choice = (distance, max(0, snapped))
            if best is None or choice < best:
                best = choice
    return best[1] if best is not None else max(0, timeline_start_ms)


def ripple_delete(clips: list[TimelineClip], clip_ids: set[str]) -> list[TimelineClip]:
    """Delete selected clips and close the resulting gaps across all tracks."""
    selected = [clip for clip in clips if clip.clip_id in clip_ids]
    if not selected:
        raise ValueError("Selecione pelo menos um clipe válido para excluir.")
    intervals = sorted({(clip.timeline_start_ms, clip.timeline_end_ms) for clip in selected})
    merged_intervals: list[tuple[int, int]] = []
    for start, end in intervals:
        if merged_intervals and start <= merged_intervals[-1][1]:
            previous_start, previous_end = merged_intervals[-1]
            merged_intervals[-1] = (previous_start, max(previous_end, end))
        else:
            merged_intervals.append((start, end))
    result: list[TimelineClip] = []
    for clip in clips:
        if clip.clip_id in clip_ids:
            continue
        shift = sum(
            end - start
            for start, end in merged_intervals
            if end <= clip.timeline_start_ms
        )
        result.append(_updated(clip, timeline_start_ms=max(0, clip.timeline_start_ms - shift)))
    return result


def move_clip(clips: list[TimelineClip], clip_id: str, timeline_start_ms: int) -> list[TimelineClip]:
    if timeline_start_ms < 0:
        raise ValueError("A posição do clipe não pode ser negativa.")
    found = False
    result = []
    for clip in clips:
        if clip.clip_id == clip_id:
            found = True
            result.append(_updated(clip, timeline_start_ms=timeline_start_ms))
        else:
            result.append(clip)
    if not found:
        raise ValueError("Clipe não encontrado.")
    return result


def trim_clip(
    clips: list[TimelineClip],
    clip_id: str,
    source_start_ms: int,
    source_end_ms: int,
) -> list[TimelineClip]:
    found = False
    result = []
    for clip in clips:
        if clip.clip_id == clip_id:
            found = True
            result.append(_updated(clip, source_start_ms=source_start_ms, source_end_ms=source_end_ms))
        else:
            result.append(clip)
    if not found:
        raise ValueError("Clipe não encontrado.")
    return result


def set_transition(clips: list[TimelineClip], clip_id: str, duration_ms: int) -> list[TimelineClip]:
    found = False
    result = []
    for clip in clips:
        if clip.clip_id == clip_id:
            found = True
            result.append(_updated(clip, transition_ms=duration_ms))
        else:
            result.append(clip)
    if not found:
        raise ValueError("Clipe não encontrado.")
    return result


def update_clip_properties(clips: list[TimelineClip], clip_id: str, **updates: object) -> list[TimelineClip]:
    """Update speed, fades, effect and other persisted clip properties atomically."""
    if not any(clip.clip_id == clip_id for clip in clips):
        raise ValueError("Clipe não encontrado.")
    return [
        _updated(clip, **updates) if clip.clip_id == clip_id else clip
        for clip in clips
    ]


def _updated(clip: TimelineClip, **changes: object) -> TimelineClip:
    payload = clip.model_dump()
    payload.update(changes)
    return TimelineClip.model_validate(payload)
