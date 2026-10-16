"""Offline candidate generation and replaceable clip ranking."""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
import math
import re
from threading import Event
from typing import Any, Protocol

from cortaflow.domain.analysis import ClipSelectionSettings, ClipSuggestion, TimeRange
from cortaflow.domain.subtitle import Transcript
from cortaflow.domain.tracking import AudioEvidence, FaceTrackPoint
from cortaflow.services.editorial_validation import (
    assess_word_range,
    belongs_to_oversized_discourse,
    context_around,
)
from cortaflow.services.long_discourse import resolve_long_discourse
from cortaflow.services.topic_segmentation import segment_topics


ProgressCallback = Callable[[dict[str, Any]], None]

_HOOK_TERMS = {
    "atenção", "como", "descubra", "erro", "imagine", "ninguém", "por que",
    "segredo", "sabia", "você", "verdade", "what", "why", "how", "secret",
}
_VALUE_TERMS = {
    "aprenda", "causa", "como", "dica", "exemplo", "explica", "faça", "motivo",
    "passo", "porque", "problema", "resultado", "solução", "técnica", "use",
    "learn", "reason", "result", "solution", "step", "tip",
}
_EMOTION_TERMS = {
    "absurdo", "alegria", "emocionante", "incrível", "medo", "surpresa", "triste",
    "amazing", "fear", "happy", "incredible", "sad", "surprise",
}
_CONCLUSION_TERMS = {
    "assim", "conclusão", "enfim", "então", "finalmente", "portanto", "resultado",
    "conclusion", "finally", "result", "so", "therefore",
}
_TOPIC_STOP_TERMS = {
    "agora", "ainda", "aqui", "assim", "como", "conclusão", "coisa",
    "coisas", "depois", "essa", "esse", "esta", "explicação", "gente",
    "isso", "mais", "menos", "muito", "onde", "para", "pela", "pelo",
    "porque", "quando", "também", "traz", "tudo", "uma", "umas", "útil",
    "with", "this", "that", "from", "into", "about",
}


class ClipRanker(Protocol):
    """Replaceable ranking boundary used by heuristic and semantic rankers."""

    def rank(
        self,
        candidates: list[ClipSuggestion],
        max_results: int,
        *,
        progress: ProgressCallback | None = None,
        cancelled: Event | None = None,
    ) -> list[ClipSuggestion]: ...


class HeuristicClipRanker:
    """Deterministic fallback that preserves temporal and topical diversity."""

    def rank(
        self,
        candidates: list[ClipSuggestion],
        max_results: int,
        *,
        progress: ProgressCallback | None = None,
        cancelled: Event | None = None,
    ) -> list[ClipSuggestion]:
        ordered = sorted(candidates, key=lambda item: item.quality_score, reverse=True)
        selected: list[ClipSuggestion] = []
        for candidate in ordered:
            if cancelled and cancelled.is_set():
                break
            if all(
                _overlap_ratio(candidate, existing) == 0
                and _topic_similarity(candidate, existing) < 0.72
                for existing in selected
            ):
                selected.append(candidate)
            if len(selected) >= max_results:
                break
        if progress:
            progress(
                {
                    "status": "heuristic_ranking",
                    "message": f"Pré-filtro local selecionou {len(selected)} trechos.",
                }
            )
        return selected


def suggest_clips(
    transcript: Transcript,
    total_duration_ms: int,
    silences: list[TimeRange] | None = None,
    scenes: list[TimeRange] | None = None,
    max_results: int | None = None,
    settings: ClipSelectionSettings | None = None,
    audio_evidence: list[AudioEvidence] | None = None,
    face_tracks: list[FaceTrackPoint] | None = None,
    ranker: ClipRanker | None = None,
    progress: ProgressCallback | None = None,
    cancelled: Event | None = None,
) -> list[ClipSuggestion]:
    """Generate every valid natural-boundary candidate and rank a diverse subset."""
    if not transcript.words or total_duration_ms <= 0:
        return []
    configured = settings or ClipSelectionSettings()
    result_limit = max_results if max_results is not None else configured.max_results
    silences = silences or []
    scenes = scenes or []
    audio_evidence = audio_evidence or []
    face_tracks = face_tracks or []
    scene_boundary_set = {point for scene in scenes for point in (scene.start_ms, scene.end_ms)}
    # A scene change is useful visual evidence, but it is never evidence that a
    # person stopped speaking.  Only transcript/silence boundaries may create
    # speech cuts.
    speech_boundary_set = {
        point for silence in silences for point in (silence.start_ms, silence.end_ms)
    }
    scene_boundaries = tuple(sorted(scene_boundary_set))
    speech_boundaries = tuple(sorted(speech_boundary_set))
    energy_index = _EnergyIndex.build(audio_evidence)
    face_index = _FaceIndex.build(face_tracks)
    words = transcript.words
    minimum_ms = configured.min_seconds * 1000
    maximum_ms = configured.max_seconds * 1000
    topic_segments = segment_topics(words, minimum_ms=minimum_ms, maximum_ms=maximum_ms)
    topic_boundaries = tuple(
        sorted(
            {
                point
                for segment in topic_segments
                for point in (segment.start_ms, segment.end_ms)
            }
        )
    )
    start_indexes = {0}
    start_indexes.update(
        index + 1
        for index, word in enumerate(words[:-1])
        if _ends_sentence(word.text)
    )
    for boundary in speech_boundaries + topic_boundaries:
        nearest = min(range(len(words)), key=lambda index: abs(words[index].start_ms - boundary))
        if abs(words[nearest].start_ms - boundary) <= 1_500:
            start_indexes.add(nearest)

    if progress and len(topic_segments) > 1:
        progress(
            {
                "status": "topic_segmentation",
                "message": (
                    f"{len(topic_segments)} blocos temáticos identificados; "
                    "gerando candidatos dentro de cada assunto."
                ),
                "topic_segment_count": len(topic_segments),
                "topic_segments": [
                    {
                        "start_ms": item.start_ms,
                        "end_ms": item.end_ms,
                        "label": item.label,
                        "keywords": item.keywords,
                    }
                    for item in topic_segments
                ],
            }
        )

    candidates: list[ClipSuggestion] = []
    seen_ranges: set[tuple[int, int]] = set()
    natural_candidate_count = 0
    detailed_ranges: list[tuple[int, int]] = []
    for start_index in sorted(start_indexes):
        if cancelled and cancelled.is_set():
            break
        start_word = words[start_index]
        natural_ends: list[int] = []
        fallback_ends: list[int] = []
        for end_index in range(start_index, len(words)):
            word = words[end_index]
            duration = word.end_ms - start_word.start_ms
            if duration < minimum_ms:
                continue
            if duration > maximum_ms or word.end_ms > total_duration_ms:
                break
            fallback_ends.append(end_index)
            if (
                _ends_sentence(word.text)
                or                 _near_boundary(word.end_ms, speech_boundaries)
                or _near_boundary(word.end_ms, topic_boundaries)
                or _near_transcript_pause(words, end_index)

            ):
                natural_ends.append(end_index)
        # A fallback is only used when a range contains no sentence/pause ending.
        available = natural_ends or fallback_ends[-1:]
        natural_candidate_count += len(available)
        # Keep multiple duration profiles per start for the detailed multimodal score.
        # Every valid range is enumerated above; this light pass prevents tens of
        # thousands of Pydantic/text/audio evaluations on long recordings.
        ranked_ends = sorted(
            available,
            key=lambda index: _quick_range_score(words, start_index, index, configured),
            reverse=True,
        )
        detailed_ends = set(ranked_ends[:6])
        if available:
            detailed_ends.update((available[0], available[-1]))
        detailed_ranges.extend((start_index, end_index) for end_index in sorted(detailed_ends))

    resolved_subideas = resolve_long_discourse(
        words,
        minimum_ms=minimum_ms,
        maximum_ms=maximum_ms,
    )
    detailed_ranges.extend(
        (item.start_index, item.end_index)
        for item in resolved_subideas
    )
    if progress and resolved_subideas:
        progress(
            {
                "status": "long_discourse_resolved",
                "message": (
                    f"{len(resolved_subideas)} subideias recuperadas de discurso longo; "
                    "todas permanecem dentro do limite físico de 179 s."
                ),
                "resolved_subidea_count": len(resolved_subideas),
            }
        )

    for start_index, end_index in detailed_ranges:
        if cancelled and cancelled.is_set():
            break
        start_word = words[start_index]
        end_word = words[end_index]
        range_key = (start_word.start_ms, end_word.end_ms)
        if range_key in seen_ranges:
            continue
        seen_ranges.add(range_key)
        candidate = _score_candidate(
            words,
            start_index,
            end_index,
            configured,
            silences,
            scene_boundaries,
            speech_boundaries,
            topic_boundaries,
            energy_index,
            face_index,
        )
        if candidate is not None:
            candidates.append(candidate)

    if progress:
        progress(
            {
                "status": "candidate_generation",
                "message": (
                    f"{natural_candidate_count} limites naturais; "
                    f"{len(candidates)} passaram ao pré-filtro detalhado."
                ),
                "candidate_count": natural_candidate_count,
                "detailed_candidate_count": len(candidates),
            }
        )
    fallback = HeuristicClipRanker()
    prefilter_limit = max(result_limit, min(40, max(20, result_limit * 2)))
    prefiltered = (
        _semantic_prefilter(
            candidates,
            result_limit,
            prefilter_limit,
            fallback,
            progress=progress,
            cancelled=cancelled,
        )
        if ranker is not None
        else fallback.rank(
            candidates,
            prefilter_limit,
            progress=progress,
            cancelled=cancelled,
        )
    )
    selected = (ranker or fallback).rank(
        prefiltered,
        result_limit,
        progress=progress,
        cancelled=cancelled,
    )
    if configured.auto_accept_threshold is not None:
        selected = [
            item.model_copy(
                update={
                    "status": (
                        "accepted"
                        if (
                            item.quality_score >= configured.auto_accept_threshold
                            and item.editorial_status == "validated"
                        )
                        else item.status
                    )
                }
            )
            for item in selected
        ]
    return selected


def _semantic_prefilter(
    candidates: list[ClipSuggestion],
    result_limit: int,
    prefilter_limit: int,
    fallback: HeuristicClipRanker,
    *,
    progress: ProgressCallback | None,
    cancelled: Event | None,
) -> list[ClipSuggestion]:
    """Keep strong diverse clips plus safe boundary-expansion alternatives.

    The semantic reviewer must be able to repair a dependent opening or an
    unfinished ending. A diversity-only prefilter used to discard exactly
    those overlapping alternatives before the reviewer could see them.
    """
    primaries = fallback.rank(
        candidates,
        min(result_limit, prefilter_limit),
        progress=None,
        cancelled=cancelled,
    )
    selected: list[ClipSuggestion] = []
    seen: set[tuple[int, int]] = set()

    def add(candidate: ClipSuggestion) -> None:
        key = (candidate.start_ms, candidate.end_ms)
        if key not in seen and len(selected) < prefilter_limit:
            seen.add(key)
            selected.append(candidate)

    for primary in primaries:
        add(primary)
        expansions = sorted(
            (
                item
                for item in candidates
                if item.start_ms <= primary.start_ms
                and item.end_ms >= primary.end_ms
                and (item.start_ms, item.end_ms)
                != (primary.start_ms, primary.end_ms)
            ),
            key=lambda item: (
                item.duration_ms - primary.duration_ms,
                -item.quality_score,
            ),
        )
        for alternative in expansions[:2]:
            add(alternative)

    for candidate in sorted(candidates, key=lambda item: item.quality_score, reverse=True):
        if cancelled and cancelled.is_set():
            break
        add(candidate)
        if len(selected) >= prefilter_limit:
            break
    if progress:
        progress(
            {
                "status": "heuristic_ranking",
                "message": (
                    f"Pré-filtro local manteve {len(selected)} trechos, incluindo "
                    "alternativas seguras para corrigir começo e fim."
                ),
            }
        )
    return selected


def _score_candidate(
    words: list,
    start_index: int,
    end_index: int,
    settings: ClipSelectionSettings,
    silences: list[TimeRange],
    scene_boundaries: tuple[int, ...],
    speech_boundaries: tuple[int, ...],
    topic_boundaries: tuple[int, ...],
    energy_index: _EnergyIndex,
    face_index: _FaceIndex,
) -> ClipSuggestion | None:
    editorial = assess_word_range(words, start_index, end_index, silences)
    start_word = words[start_index]
    end_word = words[end_index]
    recoverable_editorial_issue = (
        not editorial.passes
        and editorial.end_complete
        and any(
            (
                not editorial.start_safe,
                not editorial.start_independent,
                not editorial.end_safe,
                not editorial.end_complete,
            )
        )
    )
    # Keep a complete natural ending when the issue is repairable by the
    # semantic reviewer. Mid-speech fallback ranges without a sentence ending
    # remain rejected, so visual scenes can never authorize an unsafe cut.
    if not editorial.passes and not recoverable_editorial_issue:
        return None
    duration = end_word.end_ms - start_word.start_ms
    excerpt_words = [word.text for word in words[start_index : end_index + 1]]
    excerpt = " ".join(excerpt_words)
    silence_overlap = sum(
        max(0, min(end_word.end_ms, silence.end_ms) - max(start_word.start_ms, silence.start_ms))
        for silence in silences
    )
    speech_ratio = max(0.0, 1 - silence_overlap / max(1, duration))
    if speech_ratio < 0.55:
        return None
    density = min(1.0, len(excerpt_words) / max(1.0, duration / 650))
    preferred_ms = settings.preferred_seconds * 1000
    duration_fit = max(0.0, 1 - abs(duration - preferred_ms) / max(5_000, preferred_ms))
    natural_start = start_index == 0 or _ends_sentence(words[start_index - 1].text)
    aligned_start = editorial.start_safe and (
        natural_start or _near_boundary(start_word.start_ms, speech_boundaries)
    )
    aligned_end = editorial.end_safe and (
        _ends_sentence(end_word.text)
        or _near_boundary(end_word.end_ms, topic_boundaries)
    )
    boundary_quality = editorial.score
    topic_alignment = (
        int(_near_boundary(start_word.start_ms, topic_boundaries))
        + int(_near_boundary(end_word.end_ms, topic_boundaries))
    ) / 2
    topic_focus = _topic_prompt_score(
        excerpt,
        settings.topic_prompt,
        settings.vocabulary,
    )
    scene_alignment = (
        int(_near_boundary(start_word.start_ms, scene_boundaries))
        + int(_near_boundary(end_word.end_ms, scene_boundaries))
    ) / 2
    hook = _hook_score(excerpt_words, excerpt, duration)
    flow = _flow_score(excerpt_words, aligned_start, aligned_end)
    value = _keyword_score(excerpt, _VALUE_TERMS)
    emotion = min(1.0, _keyword_score(excerpt, _EMOTION_TERMS) + 0.25 * excerpt.count("!"))
    energy = energy_index.score(start_word.start_ms, end_word.end_ms)
    face = face_index.continuity(start_word.start_ms, end_word.end_ms)
    face_switches = face_index.switches(start_word.start_ms, end_word.end_ms)
    resegmented = belongs_to_oversized_discourse(
        words,
        start_index,
        end_index,
        179_000,
    )
    before, after = context_around(words, start_index, end_index)
    question_ending = end_word.text.strip().endswith("?")
    components = {
        "fala": speech_ratio,
        "fala_segura": float(editorial.start_safe and editorial.end_safe),
        "validade_editorial": editorial.score,
        "densidade": density,
        "duração": duration_fit,
        "limites": boundary_quality,
        "hook": hook,
        "fluxo": flow,
        "valor": value,
        "emoção": emotion,
        "energia": energy,
        "cena": scene_alignment,
        "rosto": face,
        "estabilidade_rosto": max(0.0, 1.0 - min(1.0, face_switches / 3)),
        "qualidade_audiovisual": round(0.55 * face + 0.45 * energy, 3),
        "subideia_resolvida": float(resegmented),
        "tópico": topic_focus,
        "mudança_tema": topic_alignment,
    }
    weights = {
        "fala": 0.08,
        "fala_segura": 0.12,
        "validade_editorial": 0.12,
        "densidade": 0.05,
        "duração": 0.03,
        "limites": 0.10,
        "hook": 0.14,
        "fluxo": 0.14,
        "valor": 0.10,
        "emoção": 0.04,
        "energia": 0.03,
        "cena": 0.02,
        "rosto": 0.03,
        "estabilidade_rosto": 0.03,
        "tópico": 0.06,
        "mudança_tema": 0.04,
    }
    score = sum(components[name] * weight for name, weight in weights.items())
    reasons = ["ideia com início e fim naturais", "boa densidade de fala"]
    if hook >= 0.55:
        reasons.append("abertura com hook")
    if value >= 0.5:
        reasons.append("conteúdo informativo")
    if emotion >= 0.5:
        reasons.append("sinal de emoção")
    if scene_alignment:
        reasons.append("alinhado a mudança de cena")
    if face >= 0.65:
        reasons.append("rosto contínuo")
    if face_switches:
        reasons.append(f"{face_switches} troca(s) de rosto; revisar enquadramento")
    if resegmented:
        reasons.append("subideia extraída de discussão acima de 179 s")
    if topic_alignment or topic_focus > 0.5:
        reasons.append("bloco temático identificável")
    if question_ending:
        reasons.append("pergunta final exige validação da resposta")
    return ClipSuggestion(
        start_ms=start_word.start_ms,
        end_ms=end_word.end_ms,
        title=_title(excerpt_words),
        transcript_excerpt=excerpt,
        quality_score=round(min(1.0, score), 3),
        reason=", ".join(reasons).capitalize() + ".",
        score_components={name: round(value, 3) for name, value in components.items()},
        editorial_status=(
            "needs_review"
            if resegmented or question_ending or not editorial.passes
            else "validated"
        ),
        editorial_score=round(editorial.score, 3),
        relevance_score=round(min(1.0, 0.55 * value + 0.45 * flow), 3),
        confidence_score=round(min(1.0, 0.65 * editorial.score + 0.35 * speech_ratio), 3),
        potential_score=round(min(1.0, score), 3),
        production_quality_score=round(0.55 * face + 0.45 * energy, 3),
        opening_dependency=("repairable" if not editorial.start_independent else "none"),
        ending_state=("complete" if editorial.end_complete else "repairable"),
        repair_history=[editorial.reason] if not editorial.passes else [],
        context_before=before,
        context_after=after,
        resegmented_from_long_unit=resegmented,
        selection_goal=settings.selection_goal,
        topic_prompt=settings.topic_prompt,
        audience=settings.audience,
        vocabulary=list(settings.vocabulary),
    )


def _quick_range_score(words: list, start_index: int, end_index: int, settings: ClipSelectionSettings) -> float:
    duration = words[end_index].end_ms - words[start_index].start_ms
    preferred_ms = settings.preferred_seconds * 1000
    duration_fit = max(0.0, 1 - abs(duration - preferred_ms) / max(5_000, preferred_ms))
    natural_start = start_index == 0 or _ends_sentence(words[start_index - 1].text)
    natural_end = _ends_sentence(words[end_index].text)
    impact = any(mark in words[end_index].text for mark in ("?", "!"))
    # Duration is a preference, never the main editorial decision.  Complete
    # beginnings/endings are kept ahead of clips merely close to the target.
    return 0.2 * duration_fit + 0.3 * natural_start + 0.4 * natural_end + 0.1 * impact


def _hook_score(words: list[str], excerpt: str, duration_ms: int) -> float:
    hook_word_count = max(1, round(len(words) * min(0.3, 8_000 / max(1, duration_ms))))
    opening = " ".join(words[:hook_word_count]).lower()
    keyword = max((_phrase_present(opening, term) for term in _HOOK_TERMS), default=False)
    question = "?" in opening
    exclamation = "!" in opening
    number = bool(re.search(r"\d", opening))
    direct = opening.startswith(("se ", "quando ", "pare ", "veja ", "imagine "))
    return min(1.0, 0.42 * keyword + 0.28 * question + 0.12 * exclamation + 0.1 * number + 0.08 * direct)


def _flow_score(words: list[str], aligned_start: bool, aligned_end: bool) -> float:
    ending = " ".join(words[-12:]).lower()
    conclusion = any(_phrase_present(ending, term) for term in _CONCLUSION_TERMS)
    sentence_end = _ends_sentence(words[-1])
    return min(1.0, 0.35 * aligned_start + 0.35 * aligned_end + 0.2 * sentence_end + 0.1 * conclusion)


def _topic_prompt_score(text: str, prompt: str, vocabulary: list[str] | None = None) -> float:
    """Score overlap with the user-provided subject without requiring an LLM."""
    prompt_terms = _content_terms(prompt)
    prompt_terms |= _content_terms(" ".join(vocabulary or []))
    if not prompt_terms:
        return 0.5
    excerpt_terms = _content_terms(text)
    return min(1.0, len(prompt_terms & excerpt_terms) / max(1, min(6, len(prompt_terms))))


def _keyword_score(text: str, terms: set[str]) -> float:
    lowered = text.lower()
    hits = sum(_phrase_present(lowered, term) for term in terms)
    number_bonus = 0.2 if re.search(r"\d", lowered) else 0.0
    return min(1.0, hits / 3 + number_bonus)


def _phrase_present(text: str, phrase: str) -> bool:
    return bool(re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", text, re.IGNORECASE))


@dataclass(frozen=True)
class _EnergyIndex:
    timestamps: tuple[int, ...]
    prefix_sum: tuple[float, ...]
    prefix_square_sum: tuple[float, ...]

    @classmethod
    def build(cls, evidence: list[AudioEvidence]) -> "_EnergyIndex":
        ordered = sorted(evidence, key=lambda item: item.timestamp_ms)
        sums = [0.0]
        squares = [0.0]
        for item in ordered:
            sums.append(sums[-1] + item.energy)
            squares.append(squares[-1] + item.energy * item.energy)
        return cls(
            tuple(item.timestamp_ms for item in ordered),
            tuple(sums),
            tuple(squares),
        )

    def score(self, start_ms: int, end_ms: int) -> float:
        left = bisect_left(self.timestamps, start_ms)
        right = bisect_right(self.timestamps, end_ms)
        count = right - left
        if count <= 0:
            return 0.5
        total = self.prefix_sum[right] - self.prefix_sum[left]
        square_total = self.prefix_square_sum[right] - self.prefix_square_sum[left]
        average = total / count
        variance = max(0.0, square_total / count - average * average)
        expression = min(1.0, math.sqrt(variance) * 3)
        return min(1.0, 0.7 * average + 0.3 * expression)


@dataclass(frozen=True)
class _FaceIndex:
    timestamps: tuple[int, ...]
    points: tuple[FaceTrackPoint, ...]

    @classmethod
    def build(cls, tracks: list[FaceTrackPoint]) -> "_FaceIndex":
        ordered = sorted(tracks, key=lambda item: item.timestamp_ms)
        return cls(tuple(item.timestamp_ms for item in ordered), tuple(ordered))

    def continuity(self, start_ms: int, end_ms: int) -> float:
        left = bisect_left(self.timestamps, start_ms)
        right = bisect_right(self.timestamps, end_ms)
        relevant = self.points[left:right]
        if not relevant:
            return 0.5
        counts = Counter(point.track_id for point in relevant)
        dominant_share = max(counts.values()) / len(relevant)
        timestamps = sorted({point.timestamp_ms for point in relevant})
        covered = (
            (timestamps[-1] - timestamps[0]) / max(1, end_ms - start_ms)
            if len(timestamps) > 1
            else 0
        )
        return min(1.0, 0.7 * dominant_share + 0.3 * covered)

    def switches(self, start_ms: int, end_ms: int) -> int:
        """Count focus changes in chronological samples for editorial review."""
        left = bisect_left(self.timestamps, start_ms)
        right = bisect_right(self.timestamps, end_ms)
        relevant = self.points[left:right]
        by_timestamp: dict[int, set[int]] = {}
        for point in relevant:
            by_timestamp.setdefault(point.timestamp_ms, set()).add(point.track_id)
        previous: int | None = None
        changes = 0
        for timestamp in sorted(by_timestamp):
            current = min(by_timestamp[timestamp])
            if previous is not None and current != previous:
                changes += 1
            previous = current
        return changes


def _ends_sentence(text: str) -> bool:
    return text.rstrip().endswith((".", "!", "?", ":", ";"))


def _near_transcript_pause(words: list, end_index: int, minimum_gap_ms: int = 450) -> bool:
    """Treat a reliable inter-word pause as a reviewable natural boundary."""
    if end_index + 1 >= len(words):
        return True
    return words[end_index + 1].start_ms - words[end_index].end_ms >= minimum_gap_ms


def _near_boundary(
    timestamp_ms: int,
    boundaries: tuple[int, ...],
    tolerance_ms: int = 1_500,
) -> bool:
    if not boundaries:
        return False
    position = bisect_left(boundaries, timestamp_ms)
    return any(
        abs(timestamp_ms - boundaries[index]) <= tolerance_ms
        for index in (position - 1, position)
        if 0 <= index < len(boundaries)
    )


def _title(words: list[str]) -> str:
    title = " ".join(words[:8]).strip(" .,!?;:")
    return title[:70] or "Trecho sugerido"


def _overlap_ratio(left: ClipSuggestion, right: ClipSuggestion) -> float:
    overlap = max(0, min(left.end_ms, right.end_ms) - max(left.start_ms, right.start_ms))
    return overlap / max(1, min(left.duration_ms, right.duration_ms))


def _topic_similarity(left: ClipSuggestion, right: ClipSuggestion) -> float:
    left_terms = _content_terms(left.transcript_excerpt)
    right_terms = _content_terms(right.transcript_excerpt)
    if not left_terms or not right_terms:
        return 0.0
    return len(left_terms & right_terms) / len(left_terms | right_terms)


def _content_terms(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[\wÀ-ÿ]+", text.lower())
        if len(token) >= 4 and token not in _TOPIC_STOP_TERMS
    }
