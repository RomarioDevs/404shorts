"""Persistent editor timeline and property settings."""

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class TransformKeyframe(BaseModel):
    """Transformação visual interpolável de uma camada em um instante."""

    timestamp_ms: int = Field(ge=0)
    x_percent: float = Field(default=50, ge=0, le=100)
    y_percent: float = Field(default=50, ge=0, le=100)
    scale: float = Field(default=1, ge=0.05, le=10)
    rotation: float = Field(default=0, ge=-360, le=360)
    opacity: float = Field(default=1, ge=0, le=1)


class LayerItem(BaseModel):
    """Objeto visual não destrutivo posicionado sobre a sequência."""

    item_id: str = Field(min_length=1)
    kind: Literal["text", "image", "video"] = "text"
    timeline_start_ms: int = Field(default=0, ge=0)
    timeline_end_ms: int = Field(default=1000, gt=0)
    source_path: str | None = None
    text: str = "Texto"
    font_name: str = "Arial"
    font_size: int = Field(default=56, ge=8, le=240)
    color: str = "#FFFFFF"
    background: str | None = None
    x_percent: float = Field(default=50, ge=0, le=100)
    y_percent: float = Field(default=78, ge=0, le=100)
    width_percent: float = Field(default=80, ge=1, le=100)
    height_percent: float = Field(default=18, ge=1, le=100)
    rotation: float = Field(default=0, ge=-360, le=360)
    opacity: float = Field(default=1, ge=0, le=1)
    visible: bool = True
    keyframes: list[TransformKeyframe] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_duration(self) -> "LayerItem":
        if self.timeline_end_ms <= self.timeline_start_ms:
            raise ValueError("O fim da camada deve ser posterior ao início.")
        if self.kind in {"image", "video"} and not self.source_path:
            raise ValueError("Uma camada de mídia precisa de um arquivo de origem.")
        return self

    @property
    def duration_ms(self) -> int:
        return self.timeline_end_ms - self.timeline_start_ms


def layer_transform_at(layer: LayerItem, timestamp_ms: int) -> TransformKeyframe:
    """Return the interpolated layer transform used by the editor preview."""
    points = sorted(layer.keyframes, key=lambda item: item.timestamp_ms)
    if not points:
        return TransformKeyframe(
            timestamp_ms=max(0, timestamp_ms),
            x_percent=layer.x_percent,
            y_percent=layer.y_percent,
            scale=1,
            rotation=layer.rotation,
            opacity=layer.opacity,
        )
    if len(points) == 1:
        return points[0]
    for start, end in zip(points, points[1:]):
        if timestamp_ms < end.timestamp_ms:
            fraction = max(
                0.0,
                min(
                    1.0,
                    (timestamp_ms - start.timestamp_ms)
                    / max(1, end.timestamp_ms - start.timestamp_ms),
                ),
            )
            return TransformKeyframe(
                timestamp_ms=max(0, timestamp_ms),
                x_percent=start.x_percent + (end.x_percent - start.x_percent) * fraction,
                y_percent=start.y_percent + (end.y_percent - start.y_percent) * fraction,
                scale=start.scale + (end.scale - start.scale) * fraction,
                rotation=start.rotation + (end.rotation - start.rotation) * fraction,
                opacity=start.opacity + (end.opacity - start.opacity) * fraction,
            )
    return points[-1]


class SequenceDocument(BaseModel):
    """Sequência editável derivada de uma sugestão, sem alterar a mídia original."""

    sequence_id: str = Field(min_length=1)
    name: str = "Rascunho de corte"
    suggested_start_ms: int | None = Field(default=None, ge=0)
    suggested_end_ms: int | None = Field(default=None, gt=0)
    clips: list["TimelineClip"] = Field(default_factory=list)
    layers: list[LayerItem] = Field(default_factory=list)
    dirty: bool = False

    @property
    def duration_ms(self) -> int:
        return max(
            max((item.timeline_end_ms for item in self.clips), default=0),
            max((item.timeline_end_ms for item in self.layers), default=0),
        )


class TimelineClip(BaseModel):
    clip_id: str = Field(min_length=1)
    track: Literal["video", "audio"]
    source_start_ms: int = Field(ge=0)
    source_end_ms: int = Field(gt=0)
    timeline_start_ms: int = Field(ge=0)
    label: str = "Clipe"
    transition_ms: int = Field(default=0, ge=0, le=5000)
    speed: float = Field(default=1.0, ge=0.25, le=4.0)
    fade_in_ms: int = Field(default=0, ge=0, le=5000)
    fade_out_ms: int = Field(default=0, ge=0, le=5000)
    effect: Literal["none", "blur", "grayscale", "vintage"] = "none"

    @model_validator(mode="after")
    def validate_range(self) -> "TimelineClip":
        if self.source_end_ms <= self.source_start_ms:
            raise ValueError("O fim do clipe deve ser posterior ao início.")
        if self.transition_ms > self.duration_ms:
            raise ValueError("A transição não pode exceder a duração do clipe.")
        if self.fade_in_ms + self.fade_out_ms > self.duration_ms:
            raise ValueError("Os fades não podem exceder a duração do clipe.")
        return self

    @property
    def duration_ms(self) -> int:
        return max(1, round((self.source_end_ms - self.source_start_ms) / self.speed))

    @property
    def timeline_end_ms(self) -> int:
        return self.timeline_start_ms + self.duration_ms


class SubtitleStyle(BaseModel):
    font_name: str = "Arial"
    font_size: int = Field(default=62, ge=12, le=160)
    primary_color: str = "#FFFFFF"
    highlight_color: str = "#FFD54F"
    outline_color: str = "#000000"
    outline_width: int = Field(default=4, ge=0, le=12)
    shadow: int = Field(default=2, ge=0, le=12)
    background: bool = False
    position: Literal["top", "center", "bottom"] = "bottom"
    max_words: int = Field(default=7, ge=2, le=7)
    preset: Literal["clean", "dynamic", "viral"] = "dynamic"
    animated: bool = True


class AudioSettings(BaseModel):
    volume: float = Field(default=1.0, ge=0, le=2)
    normalize: bool = False


class ReframeSettings(BaseModel):
    aspect_ratio: Literal["9:16", "16:9", "1:1", "4:5", "original"] = "9:16"
    x: int = Field(default=0, ge=0)
    y: int = Field(default=0, ge=0)
    zoom: float = Field(default=1.0, ge=0.25, le=4)
    smoothing: float = Field(default=0.2, ge=0, le=1)
    max_speed_px: int = Field(default=80, ge=1, le=1000)
    automatic: bool = True


# TimelineClip é declarado depois de SequenceDocument para manter os modelos agrupados;
# a reconstrução resolve a referência forward antes do primeiro uso.
SequenceDocument.model_rebuild()
