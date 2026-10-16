"""Replaceable active-speaker inference based on local evidence."""

from abc import ABC, abstractmethod
from collections import defaultdict, deque
from dataclasses import dataclass
from cortaflow.domain.tracking import FaceTrackPoint


@dataclass(frozen=True)
class SpeakerDecision:
    track_id: int | None
    confidence: float
    uncertain: bool


class ActiveSpeakerDetector(ABC):
    @abstractmethod
    def update(self, timestamp_ms: int, faces: list[FaceTrackPoint], voice_active: bool, audio_energy: float) -> SpeakerDecision:
        """Update evidence and select a temporary face track if sufficiently certain."""

    @abstractmethod
    def reset(self) -> None:
        """Reset temporal evidence at a strong scene boundary."""


class EvidenceActiveSpeakerDetector(ActiveSpeakerDetector):
    def __init__(self, switch_margin: float = 0.15, persistence_ms: int = 700, history_size: int = 12) -> None:
        self.switch_margin = switch_margin; self.persistence_ms = persistence_ms
        self.history: dict[int, deque[tuple[int, float]]] = defaultdict(lambda: deque(maxlen=history_size))
        self.current_id: int | None = None; self.candidate_id: int | None = None; self.candidate_since = 0
        self.previous_mouth: dict[int, float] = {}

    def reset(self) -> None:
        self.history.clear()
        self.previous_mouth.clear()
        self.current_id = None
        self.candidate_id = None
        self.candidate_since = 0

    def update(self, timestamp_ms: int, faces: list[FaceTrackPoint], voice_active: bool, audio_energy: float) -> SpeakerDecision:
        visible_ids = {face.track_id for face in faces}
        if self.current_id not in visible_ids:
            self.current_id = None
        for face in faces:
            mouth = max(0.0, min(1.0, face.mouth_openness or 0.0))
            previous = self.previous_mouth.get(face.track_id, mouth)
            motion = min(1.0, abs(mouth - previous) * 3)
            self.previous_mouth[face.track_id] = mouth
            area = min(1.0, face.box.width * face.box.height * 8)
            energy = max(0, min(1, audio_energy))
            mouth_signal = 0.7 * mouth + 0.3 * motion
            voice_match = mouth_signal * energy * (1.0 if voice_active else 0.05)
            # During speech, mouth/audio synchrony dominates size: a large
            # silent face must not win merely because it occupies more pixels.
            score = 0.68 * voice_match + 0.14 * mouth_signal + 0.10 * area + 0.08 * face.box.confidence
            self.history[face.track_id].append((timestamp_ms, score))
        scores = {track_id: sum(value for _, value in values) / len(values) for track_id, values in self.history.items() if track_id in visible_ids and values}
        if not scores or not voice_active:
            return SpeakerDecision(self.current_id if self.current_id in visible_ids else None, 0, True)
        best_id, best_score = max(scores.items(), key=lambda item: item[1])
        current_score = scores.get(self.current_id, 0)
        if self.current_id is None:
            self.current_id = best_id
        elif best_id != self.current_id and best_score >= current_score + self.switch_margin:
            if self.candidate_id != best_id:
                self.candidate_id, self.candidate_since = best_id, timestamp_ms
            elif timestamp_ms - self.candidate_since >= self.persistence_ms:
                self.current_id, self.candidate_id = best_id, None
        else:
            self.candidate_id = None
        confidence = scores.get(self.current_id, 0)
        ordered = sorted(scores.values(), reverse=True)
        gap = ordered[0] - ordered[1] if len(ordered) > 1 else ordered[0]
        uncertain = confidence < 0.25 or gap < 0.05
        # A short-lived candidate should not be reported as a confident switch.
        if self.candidate_id is not None:
            uncertain = True
        return SpeakerDecision(self.current_id, round(confidence, 3), uncertain)
