"""Orchestrate local audio evidence and active-speaker reframing."""

from collections.abc import Callable
from pathlib import Path
from threading import Event
from typing import Any

from cortaflow.domain.analysis import TimeRange
from cortaflow.domain.project import ReframeKeyframe
from cortaflow.domain.subtitle import Transcript
from cortaflow.domain.tracking import (
    AudioEvidence,
    FaceTrackPoint,
    SpeakerKeyframe,
    SpeakerOverride,
)
from cortaflow.services.active_speaker import EvidenceActiveSpeakerDetector
from cortaflow.services.audio_analysis import AudioAnalysisCancelled, extract_audio_evidence
from cortaflow.services.auto_reframe import generate_speaker_reframe_keyframes


def analyze_active_speaker(
    media_path: Path,
    tracks: list[FaceTrackPoint],
    source_width: int,
    source_height: int,
    transcript: Transcript | None = None,
    silences: list[TimeRange] | None = None,
    scenes: list[TimeRange] | None = None,
    overrides: list[SpeakerOverride] | None = None,
    progress: Callable[[dict[str, Any]], None] | None = None,
    cancelled: Event | None = None,
    *,
    audio_evidence: list[AudioEvidence] | None = None,
) -> tuple[list[SpeakerKeyframe], list[ReframeKeyframe]]:
    """Cross mouth motion with VAD/audio energy and generate smooth camera focus."""
    if min(source_width, source_height) <= 0:
        raise ValueError("As dimensões da mídia são necessárias para o reenquadramento.")
    if not tracks:
        return [], []
    evidence = audio_evidence
    if evidence is None:
        evidence = extract_audio_evidence(
            media_path,
            transcript=transcript,
            silences=silences,
            progress=progress,
            cancelled=cancelled,
        )
    if not evidence:
        evidence = [
            AudioEvidence(timestamp_ms=point.timestamp_ms, energy=0, voice_active=False)
            for point in tracks
        ]
    grouped: dict[int, list[FaceTrackPoint]] = {}
    for point in tracks:
        grouped.setdefault(point.timestamp_ms, []).append(point)
    scene_boundaries = sorted(scene.start_ms for scene in (scenes or []) if scene.start_ms > 0)
    boundary_index = 0
    detector = EvidenceActiveSpeakerDetector()
    decisions: list[SpeakerKeyframe] = []
    previous_timestamp = -1
    for timestamp in sorted(grouped):
        if cancelled and cancelled.is_set():
            raise AudioAnalysisCancelled("Análise de falante cancelada.")
        while boundary_index < len(scene_boundaries) and scene_boundaries[boundary_index] <= timestamp:
            if scene_boundaries[boundary_index] > previous_timestamp:
                detector.reset()
            boundary_index += 1
        sample = _closest_audio_evidence(evidence, timestamp)
        decision = detector.update(timestamp, grouped[timestamp], sample.voice_active, sample.energy)
        decisions.append(
            SpeakerKeyframe(
                timestamp_ms=timestamp,
                track_id=decision.track_id,
                confidence=decision.confidence,
                uncertain=decision.uncertain,
            )
        )
        previous_timestamp = timestamp
        if progress:
            progress(
                {
                    "status": "speaker",
                    "position_ms": timestamp,
                    "track_id": decision.track_id,
                    "confidence": decision.confidence,
                }
            )
    decisions = apply_speaker_overrides(decisions, overrides or [])
    crops = generate_speaker_reframe_keyframes(
        tracks,
        decisions,
        source_width,
        source_height,
        scene_boundaries_ms=scene_boundaries,
    )
    return decisions, crops


def _closest_audio_evidence(evidence: list[AudioEvidence], timestamp_ms: int) -> AudioEvidence:
    """Use nearby audio evidence, avoiding stale samples after A/V drift.

    Audio is bucketed at roughly 200 ms. If a face sample falls far outside
    the available audio range, treating it as silence is safer than assigning
    speech from another part of the recording to the wrong face.
    """
    closest = min(evidence, key=lambda item: abs(item.timestamp_ms - timestamp_ms))
    if abs(closest.timestamp_ms - timestamp_ms) <= 450:
        return closest
    return AudioEvidence(timestamp_ms=timestamp_ms, energy=0, voice_active=False)


def apply_speaker_overrides(
    decisions: list[SpeakerKeyframe],
    overrides: list[SpeakerOverride],
) -> list[SpeakerKeyframe]:
    """Apply saved manual intervals after inference so human corrections always win."""
    result: list[SpeakerKeyframe] = []
    for decision in decisions:
        manual = next(
            (
                item
                for item in reversed(overrides)
                if item.start_ms <= decision.timestamp_ms < item.end_ms
            ),
            None,
        )
        if manual:
            result.append(
                SpeakerKeyframe(
                    timestamp_ms=decision.timestamp_ms,
                    track_id=manual.track_id,
                    confidence=1.0,
                    uncertain=False,
                    manual=True,
                )
            )
        else:
            result.append(decision)
    return result
