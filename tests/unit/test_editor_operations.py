import pytest

from cortaflow.services.editor_operations import (
    create_initial_clips,
    move_clip,
    ripple_delete,
    set_transition,
    snap_position,
    split_at,
    trim_clip,
)


def test_split_move_trim_transition_and_delete() -> None:
    initial = create_initial_clips(10_000, "Fonte")
    assert {clip.track for clip in initial} == {"video", "audio"}
    split = split_at(initial, 4_000)
    assert len(split) == 4
    assert sorted(clip.duration_ms for clip in split) == [4000, 4000, 6000, 6000]

    selected = next(clip for clip in split if clip.track == "video" and clip.timeline_start_ms == 4000)
    moved = move_clip(split, selected.clip_id, 5_000)
    assert next(clip for clip in moved if clip.clip_id == selected.clip_id).timeline_start_ms == 5_000
    trimmed = trim_clip(moved, selected.clip_id, 5_000, 9_000)
    transitioned = set_transition(trimmed, selected.clip_id, 500)
    edited = next(clip for clip in transitioned if clip.clip_id == selected.clip_id)
    assert edited.duration_ms == 4_000
    assert edited.transition_ms == 500


def test_snap_position_uses_nearby_clip_edges() -> None:
    clips = create_initial_clips(10_000)
    first = next(clip for clip in clips if clip.track == "video")
    moved = move_clip(clips, first.clip_id, 2_000)
    second = next(clip for clip in moved if clip.clip_id != first.clip_id and clip.track == "audio")
    assert snap_position(moved, first.clip_id, second.timeline_end_ms - first.duration_ms + 80) == second.timeline_end_ms - first.duration_ms


def test_ripple_delete_closes_gap_for_all_tracks() -> None:
    clips = create_initial_clips(10_000)
    split = split_at(clips, 4_000)
    split = split_at(split, 7_000)
    middle = next(clip for clip in split if clip.track == "video" and clip.timeline_start_ms == 4_000)
    middle_audio = next(clip for clip in split if clip.track == "audio" and clip.timeline_start_ms == 4_000)
    result = ripple_delete(split, {middle.clip_id, middle_audio.clip_id})
    remaining = next(clip for clip in result if clip.track == "video" and clip.source_start_ms == 7_000)
    assert remaining.timeline_start_ms == 4_000
    assert next(clip for clip in result if clip.track == "audio" and clip.source_start_ms == 7_000).timeline_start_ms == 4_000


def test_invalid_trim_and_transition_are_rejected() -> None:
    clip = create_initial_clips(1000)[0]
    with pytest.raises(ValueError):
        trim_clip([clip], clip.clip_id, 900, 100)
    with pytest.raises(ValueError):
        set_transition([clip], clip.clip_id, 2000)
