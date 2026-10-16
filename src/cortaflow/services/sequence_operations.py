"""Operações não destrutivas da sequência editável."""

from __future__ import annotations

from uuid import uuid4

from cortaflow.domain.analysis import ClipSuggestion
from cortaflow.domain.editing import LayerItem, SequenceDocument, TimelineClip


def create_sequence_from_suggestion(
    suggestion: ClipSuggestion,
    *,
    title: str | None = None,
) -> SequenceDocument:
    """Cria um rascunho A/V a partir da sugestão, sem alterar o arquivo original."""
    duration = suggestion.end_ms - suggestion.start_ms
    if duration <= 0:
        raise ValueError("A sugestão precisa ter duração positiva.")
    sequence_id = f"seq-{uuid4().hex[:12]}"
    clips = [
        TimelineClip(
            clip_id=f"{sequence_id}-video",
            track="video",
            source_start_ms=suggestion.start_ms,
            source_end_ms=suggestion.end_ms,
            timeline_start_ms=0,
            label=suggestion.title or "Vídeo sugerido",
        ),
        TimelineClip(
            clip_id=f"{sequence_id}-audio",
            track="audio",
            source_start_ms=suggestion.start_ms,
            source_end_ms=suggestion.end_ms,
            timeline_start_ms=0,
            label="Áudio original",
        ),
    ]
    return SequenceDocument(
        sequence_id=sequence_id,
        name=title or suggestion.title or "Rascunho de corte",
        suggested_start_ms=suggestion.start_ms,
        suggested_end_ms=suggestion.end_ms,
        clips=clips,
    )


def create_text_layer(
    sequence: SequenceDocument,
    text: str,
    *,
    start_ms: int = 0,
    end_ms: int | None = None,
) -> LayerItem:
    """Adiciona texto livre alinhado ao início da sequência."""
    duration = end_ms if end_ms is not None else max(start_ms + 1000, sequence.duration_ms)
    layer = LayerItem(
        item_id=f"text-{uuid4().hex[:12]}",
        kind="text",
        timeline_start_ms=start_ms,
        timeline_end_ms=max(start_ms + 250, duration),
        text=text.strip() or "Texto",
    )
    sequence.layers.append(layer)
    sequence.dirty = True
    return layer


def create_image_layer(
    sequence: SequenceDocument,
    source_path: str,
    *,
    start_ms: int = 0,
    end_ms: int | None = None,
) -> LayerItem:
    """Adiciona uma imagem como overlay editável."""
    duration = end_ms if end_ms is not None else max(start_ms + 1000, sequence.duration_ms)
    layer = LayerItem(
        item_id=f"image-{uuid4().hex[:12]}",
        kind="image",
        timeline_start_ms=start_ms,
        timeline_end_ms=max(start_ms + 250, duration),
        source_path=source_path,
        text="",
        width_percent=28,
        height_percent=22,
        x_percent=82,
        y_percent=18,
    )
    sequence.layers.append(layer)
    sequence.dirty = True
    return layer


def update_layer(sequence: SequenceDocument, item_id: str, **updates: object) -> SequenceDocument:
    """Atualiza uma camada com validação de intervalo e retorna cópia independente."""
    items = []
    found = False
    for item in sequence.layers:
        if item.item_id == item_id:
            values = item.model_dump()
            values.update(updates)
            items.append(LayerItem.model_validate(values))
            found = True
        else:
            items.append(item)
    if not found:
        raise ValueError("Camada não encontrada.")
    return sequence.model_copy(update={"layers": items, "dirty": True})


def delete_layer(sequence: SequenceDocument, item_id: str) -> SequenceDocument:
    items = [item for item in sequence.layers if item.item_id != item_id]
    if len(items) == len(sequence.layers):
        raise ValueError("Camada não encontrada.")
    return sequence.model_copy(update={"layers": items, "dirty": True})


def ripple_delete(clips: list[TimelineClip], clip_id: str) -> list[TimelineClip]:
    """Exclui um clipe e fecha o espaço em todas as faixas."""
    target = next((clip for clip in clips if clip.clip_id == clip_id), None)
    if target is None:
        raise ValueError("Clipe não encontrado.")
    shift = target.duration_ms
    updated: list[TimelineClip] = []
    for clip in clips:
        if clip.clip_id == clip_id:
            continue
        start = clip.timeline_start_ms
        if start >= target.timeline_end_ms:
            start -= shift
        updated.append(clip.model_copy(update={"timeline_start_ms": max(0, start)}))
    return updated


def trim_clip_side(
    clips: list[TimelineClip],
    clip_id: str,
    *,
    side: str,
    timeline_position_ms: int,
) -> list[TimelineClip]:
    """Trim visual de uma alça, preservando sincronismo entre origem e timeline."""
    target = next((clip for clip in clips if clip.clip_id == clip_id), None)
    if target is None:
        raise ValueError("Clipe não encontrado.")
    if side == "left":
        delta = timeline_position_ms - target.timeline_start_ms
        new_source = target.source_start_ms + delta
        if new_source >= target.source_end_ms - 100:
            raise ValueError("O clipe ficaria curto demais.")
        return [
            clip.model_copy(
                update={
                    "source_start_ms": new_source,
                    "timeline_start_ms": timeline_position_ms,
                }
            )
            if clip.clip_id == clip_id
            else clip
            for clip in clips
        ]
    if side == "right":
        delta = timeline_position_ms - target.timeline_start_ms
        new_source = target.source_start_ms + delta
        if new_source <= target.source_start_ms + 100 or new_source > target.source_end_ms:
            raise ValueError("A nova saída precisa ficar dentro do clipe.")
        return [
            clip.model_copy(update={"source_end_ms": new_source})
            if clip.clip_id == clip_id
            else clip
            for clip in clips
        ]
    raise ValueError("A alça precisa ser left ou right.")
