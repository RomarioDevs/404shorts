"""Crop guide overlay for vertical framing and anonymous face tracks."""

from PySide6.QtCore import QLineF, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from cortaflow.domain.editing import ReframeSettings
from cortaflow.domain.project import ReframeKeyframe, resolve_reframe_at
from cortaflow.domain.tracking import CropFrame, FaceTrackPoint, SpeakerKeyframe
from cortaflow.services.auto_reframe import apply_reframe_settings


class ReframeOverlay(QWidget):
    crop_changed = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.source_width = 0
        self.source_height = 0
        self.tracks: list[FaceTrackPoint] = []
        self.keyframes: list[ReframeKeyframe] = []
        self.selected_track_id: int | None = None
        self.speaker_keyframes: list[SpeakerKeyframe] = []
        self.timestamp_ms = 0
        self.settings = ReframeSettings()
        self.effective_keyframes: list[ReframeKeyframe] = []
        self._drag_origin: QPointF | None = None
        self._drag_start_crop: CropFrame | None = None
        self._drag_crop: CropFrame | None = None
        self._refresh_keyframes()

    def set_settings(self, settings: ReframeSettings) -> None:
        self.settings = settings
        self._drag_crop = None
        self._refresh_keyframes()
        self.update()

    def set_source_size(self, width: int | None, height: int | None) -> None:
        self.source_width = max(0, width or 0)
        self.source_height = max(0, height or 0)
        self._refresh_keyframes()
        self.update()

    def set_data(
        self,
        tracks: list[FaceTrackPoint],
        keyframes: list[ReframeKeyframe],
        selected_track_id: int | None,
        speaker_keyframes: list[SpeakerKeyframe] | None = None,
    ) -> None:
        self.tracks = list(tracks)
        self.keyframes = list(keyframes)
        self.selected_track_id = selected_track_id
        self.speaker_keyframes = list(speaker_keyframes or [])
        self._refresh_keyframes()
        self.update()

    def _refresh_keyframes(self) -> None:
        if self.source_width and self.source_height:
            self.effective_keyframes = apply_reframe_settings(
                self.keyframes, self.settings, self.source_width, self.source_height
            )
        else:
            self.effective_keyframes = list(self.keyframes)

    def set_timestamp(self, timestamp_ms: int) -> None:
        self.timestamp_ms = max(0, timestamp_ms)
        self.update()

    def begin_drag(self, point: QPointF) -> bool:
        """Start moving the crop box when the pointer is inside it."""
        if not self.source_width or not self.source_height:
            return False
        video_rect = self._video_rect()
        crop = self._crop_at_timestamp()
        crop_rect = self._source_rect(crop.x, crop.y, crop.width, crop.height, video_rect)
        if not video_rect.contains(point) or not crop_rect.contains(point):
            return False
        self._drag_origin = QPointF(point)
        self._drag_start_crop = crop
        self._drag_crop = crop
        return True

    def move_drag(self, point: QPointF) -> None:
        if self._drag_origin is None or self._drag_start_crop is None:
            return
        video_rect = self._video_rect()
        scale_x = video_rect.width() / self.source_width
        scale_y = video_rect.height() / self.source_height
        start = self._drag_start_crop
        x = start.x + round((point.x() - self._drag_origin.x()) / max(scale_x, 1e-9))
        y = start.y + round((point.y() - self._drag_origin.y()) / max(scale_y, 1e-9))
        self._drag_crop = start.model_copy(update={
            "x": max(0, min(self.source_width - start.width, x)),
            "y": max(0, min(self.source_height - start.height, y)),
        })
        self.update()

    def end_drag(self) -> None:
        if self._drag_crop is not None and self._drag_crop != self._drag_start_crop:
            self.crop_changed.emit(self._drag_crop)
        self._drag_origin = None
        self._drag_start_crop = None
        self._drag_crop = None
        self.update()

    def paintEvent(self, event: object) -> None:  # noqa: N802 - Qt API
        if not self.source_width or not self.source_height:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        video_rect = self._video_rect()
        crop = self._drag_crop or self._crop_at_timestamp()
        crop_rect = self._source_rect(crop.x, crop.y, crop.width, crop.height, video_rect)
        shade = QColor(0, 0, 0, 135)
        painter.fillRect(QRectF(video_rect.left(), video_rect.top(), crop_rect.left() - video_rect.left(), video_rect.height()), shade)
        painter.fillRect(QRectF(crop_rect.right(), video_rect.top(), video_rect.right() - crop_rect.right(), video_rect.height()), shade)
        painter.fillRect(QRectF(crop_rect.left(), video_rect.top(), crop_rect.width(), crop_rect.top() - video_rect.top()), shade)
        painter.fillRect(QRectF(crop_rect.left(), crop_rect.bottom(), crop_rect.width(), video_rect.bottom() - crop_rect.bottom()), shade)

        painter.setPen(QPen(QColor("#7f75eb"), 2))
        painter.drawRect(crop_rect)
        grip = QRectF(crop_rect.center().x() - 12, crop_rect.center().y() - 12, 24, 24)
        painter.setPen(QPen(QColor("#7f75eb"), 1))
        painter.setBrush(QColor(25, 27, 36, 220))
        painter.drawRoundedRect(grip, 5, 5)
        painter.setPen(QPen(QColor("#ffffff"), 1.5))
        painter.drawLine(QLineF(grip.left() + 7, grip.center().y(), grip.right() - 7, grip.center().y()))
        painter.drawLine(QLineF(grip.center().x(), grip.top() + 7, grip.center().x(), grip.bottom() - 7))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(255, 255, 255, 90), 1, Qt.PenStyle.DashLine))
        painter.drawLine(QLineF(crop_rect.center().x(), crop_rect.top(), crop_rect.center().x(), crop_rect.bottom()))
        safe_y = crop_rect.bottom() - crop_rect.height() * 0.22
        painter.drawLine(QLineF(crop_rect.left(), safe_y, crop_rect.right(), safe_y))

        for point in self._visible_faces():
            face_rect = self._source_rect(
                point.box.x * self.source_width,
                point.box.y * self.source_height,
                point.box.width * self.source_width,
                point.box.height * self.source_height,
                video_rect,
            )
            selected = point.track_id == self._active_track_id()
            color = QColor("#55d6a8") if selected else QColor("#ffb65c")
            painter.setPen(QPen(color, 3 if selected else 2))
            painter.drawRect(face_rect)
            painter.drawText(face_rect.topLeft() + self._label_offset(), f"Rosto {point.track_id}")

    def _crop_at_timestamp(self) -> CropFrame:
        crop = resolve_reframe_at(self.effective_keyframes, self.timestamp_ms)
        if crop is None:
            ratios = {
                "9:16": (9, 16),
                "16:9": (16, 9),
                "1:1": (1, 1),
                "4:5": (4, 5),
                "original": (self.source_width, self.source_height),
            }
            ratio_width, ratio_height = ratios[self.settings.aspect_ratio]
            ratio = ratio_width / ratio_height
            crop_width, crop_height = self.source_width, self.source_height
            if crop_width / crop_height > ratio:
                crop_width = round(crop_height * ratio)
            else:
                crop_height = round(crop_width / ratio)
            crop = CropFrame(
                x=max(0, min(self.source_width - crop_width, round((self.source_width - crop_width) / 2 + self.settings.x))),
                y=max(0, min(self.source_height - crop_height, round((self.source_height - crop_height) / 2 + self.settings.y))),
                width=crop_width,
                height=crop_height,
            )
        return crop

    def _visible_faces(self) -> list[FaceTrackPoint]:
        if not self.tracks:
            return []
        nearest_timestamp = min(
            {point.timestamp_ms for point in self.tracks},
            key=lambda value: abs(value - self.timestamp_ms),
        )
        if abs(nearest_timestamp - self.timestamp_ms) > 800:
            return []
        return [point for point in self.tracks if point.timestamp_ms == nearest_timestamp]

    def _active_track_id(self) -> int | None:
        eligible = [item for item in self.speaker_keyframes if item.timestamp_ms <= self.timestamp_ms]
        if eligible:
            return max(eligible, key=lambda item: (item.timestamp_ms, item.manual)).track_id
        return self.selected_track_id

    def _video_rect(self) -> QRectF:
        scale = min(self.width() / self.source_width, self.height() / self.source_height)
        width, height = self.source_width * scale, self.source_height * scale
        return QRectF((self.width() - width) / 2, (self.height() - height) / 2, width, height)

    def _source_rect(self, x: float, y: float, width: float, height: float, video: QRectF) -> QRectF:
        scale_x, scale_y = video.width() / self.source_width, video.height() / self.source_height
        return QRectF(video.left() + x * scale_x, video.top() + y * scale_y, width * scale_x, height * scale_y)

    @staticmethod
    def _label_offset():
        return QPointF(3, 15)
