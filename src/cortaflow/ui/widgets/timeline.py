"""Scrollable multi-track timeline for the full editor."""

import math
from typing import Any

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QLabel, QPushButton, QRubberBand, QScrollArea, QSlider, QVBoxLayout, QWidget

from cortaflow.domain.clip import format_timestamp
from cortaflow.domain.editing import TimelineClip

TRACKS = (
    ("video", "VÍDEO", QColor("#38445d")),
    ("audio", "ÁUDIO", QColor("#28354b")),
    ("transcript", "TRANSCRIÇÃO", QColor("#3d344f")),
    ("subtitles", "LEGENDAS", QColor("#4b3b35")),
    ("scenes", "CENAS", QColor("#2f4540")),
    ("suggestions", "SUGESTÕES", QColor("#49364b")),
    ("reframe", "ENQUADRAM.", QColor("#343f48")),
)


class TimelineCanvas(QWidget):
    seek_requested = Signal(int)
    clip_selected = Signal(str)
    selection_changed = Signal(object)
    clip_move_requested = Signal(str, int)
    clip_trim_requested = Signal(str, str, int)
    track_left = 104
    ruler_height = 30
    track_height = 34

    def __init__(self) -> None:
        super().__init__()
        self.duration_ms = 0
        self.position_ms = 0
        self.in_ms: int | None = 0
        self.out_ms: int | None = None
        self.pixels_per_second = 60
        self.clips: list[TimelineClip] = []
        self.track_items: dict[str, list[Any]] = {name: [] for name, _, _ in TRACKS}
        self.selected_clip_id: str | None = None
        self.selected_clip_ids: set[str] = set()
        self.thumbnail_paths: list[str] = []
        self.waveform: list[float] = []
        self.track_order = [name for name, _, _ in TRACKS]
        self.track_visible = {name: True for name, _, _ in TRACKS}
        self.track_locked = {name: False for name, _, _ in TRACKS}
        self._drag_clip_id: str | None = None
        self._drag_offset_ms = 0
        self._trim_side: str | None = None
        self._selection_origin: QPoint | None = None
        self._rubber_band = QRubberBand(QRubberBand.Shape.Rectangle, self)
        self.setMinimumHeight(self.ruler_height + len(TRACKS) * self.track_height + 8)
        self._update_width()

    def set_duration(self, duration_ms: int) -> None:
        self.duration_ms = max(0, duration_ms)
        self.position_ms = min(self.position_ms, self.duration_ms)
        self._update_width()
        self.update()

    def set_position(self, position_ms: int) -> None:
        self.position_ms = max(0, min(position_ms, self.duration_ms))
        self.update()

    def set_markers(self, in_ms: int | None, out_ms: int | None) -> None:
        self.in_ms, self.out_ms = in_ms, out_ms
        self.update()

    def set_zoom(self, pixels_per_second: int) -> None:
        self.pixels_per_second = max(20, pixels_per_second)
        self._update_width()
        self.update()

    def set_track_data(
        self,
        clips: list[TimelineClip],
        transcript: list[Any] | None = None,
        subtitles: list[Any] | None = None,
        scenes: list[Any] | None = None,
        suggestions: list[Any] | None = None,
        reframe: list[Any] | None = None,
    ) -> None:
        self.clips = list(clips)
        self.track_items["video"] = [clip for clip in clips if clip.track == "video"]
        self.track_items["audio"] = [clip for clip in clips if clip.track == "audio"]
        self.track_items["transcript"] = list(transcript or [])
        self.track_items["subtitles"] = list(subtitles or [])
        self.track_items["scenes"] = list(scenes or [])
        self.track_items["suggestions"] = list(suggestions or [])
        self.track_items["reframe"] = list(reframe or [])
        self.update()

    def set_media_previews(self, thumbnails: list[str], waveform: list[float]) -> None:
        self.thumbnail_paths = list(thumbnails)
        self.waveform = list(waveform)
        self.update()

    def set_track_visible(self, track: str, visible: bool) -> None:
        if track in self.track_visible:
            self.track_visible[track] = visible
            self.update()

    def set_track_locked(self, track: str, locked: bool) -> None:
        if track in self.track_locked:
            self.track_locked[track] = locked

    def move_track(self, track: str, direction: int) -> None:
        if track not in self.track_order:
            return
        index = self.track_order.index(track)
        destination = max(0, min(len(self.track_order) - 1, index + direction))
        self.track_order.insert(destination, self.track_order.pop(index))
        self.update()

    def select_clip(self, clip_id: str | None) -> None:
        self.selected_clip_id = clip_id
        self.selected_clip_ids = {clip_id} if clip_id else set()
        self.update()

    def position_to_x(self, position_ms: int) -> float:
        return self.track_left + max(0, position_ms) * self.pixels_per_second / 1000

    def x_to_position(self, x: float) -> int:
        value = round((x - self.track_left) * 1000 / self.pixels_per_second)
        return max(0, min(value, self.duration_ms))

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        position = self.x_to_position(event.position().x())
        clip = self._clip_at(event.position().x(), event.position().y())
        if clip:
            additive = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
            if additive and clip.clip_id in self.selected_clip_ids:
                self.selected_clip_ids.remove(clip.clip_id)
            elif additive:
                self.selected_clip_ids.add(clip.clip_id)
            else:
                self.selected_clip_ids = {clip.clip_id}
            self.selected_clip_id = clip.clip_id
            self.selection_changed.emit(sorted(self.selected_clip_ids))
            left_x = self.position_to_x(clip.timeline_start_ms)
            right_x = self.position_to_x(clip.timeline_end_ms)
            if abs(event.position().x() - left_x) <= 9:
                self._trim_side = "left"
                self._drag_clip_id = clip.clip_id
            elif abs(event.position().x() - right_x) <= 9:
                self._trim_side = "right"
                self._drag_clip_id = clip.clip_id
            else:
                self._trim_side = None
                self._drag_clip_id = clip.clip_id
                self._drag_offset_ms = position - clip.timeline_start_ms
            self.clip_selected.emit(clip.clip_id)
            self.update()
        elif not (event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self.selected_clip_id = None
            self.selected_clip_ids.clear()
            self.selection_changed.emit([])
            self._selection_origin = event.position().toPoint()
            self._rubber_band.setGeometry(QRect(self._selection_origin, self._selection_origin))
            self._rubber_band.show()
        self.seek_requested.emit(position)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.buttons() & Qt.MouseButton.LeftButton:
            if self._selection_origin is not None:
                self._rubber_band.setGeometry(QRect(self._selection_origin, event.position().toPoint()).normalized())
            self.seek_requested.emit(self.x_to_position(event.position().x()))

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._selection_origin is not None:
            area = self._rubber_band.geometry()
            self._rubber_band.hide()
            self._selection_origin = None
            if area.width() > 6 or area.height() > 6:
                selected: set[str] = set()
                for clip in self.clips:
                    if clip.track not in {"video", "audio"}:
                        continue
                    top = self.ruler_height + [name for name in self.track_order if self.track_visible[name]].index(clip.track) * self.track_height
                    clip_rect = QRectF(
                        self.position_to_x(clip.timeline_start_ms), top + 5,
                        max(3, self.position_to_x(clip.timeline_end_ms) - self.position_to_x(clip.timeline_start_ms)),
                        self.track_height - 10,
                    )
                    if area.intersects(clip_rect.toRect()):
                        selected.add(clip.clip_id)
                self.selected_clip_ids = selected
                self.selected_clip_id = next(iter(selected), None)
                self.selection_changed.emit(sorted(selected))
                self.update()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._drag_clip_id:
            position = self.x_to_position(event.position().x())
            if self._trim_side:
                self.clip_trim_requested.emit(self._drag_clip_id, self._trim_side, position)
            else:
                self.clip_move_requested.emit(self._drag_clip_id, max(0, position - self._drag_offset_ms))
        self._drag_clip_id = None
        self._trim_side = None

    def paintEvent(self, event: object) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#15171d"))
        track_width = max(1, self.width() - self.track_left - 12)
        painter.setPen(QColor("#aeb4c2"))
        painter.drawText(10, 21, "TEMPO")

        seconds = max(0, math.ceil(self.duration_ms / 1000))
        major_step = 1 if self.pixels_per_second >= 80 else 5
        painter.setPen(QPen(QColor("#656c7a"), 1))
        for second in range(0, seconds + 1, major_step):
            x = self.position_to_x(second * 1000)
            painter.drawLine(QPointF(x, 20), QPointF(x, 29))
            painter.drawText(QPointF(x + 3, 16), format_timestamp(second * 1000))

        colors = {name: (label, color) for name, label, color in TRACKS}
        visible_tracks = [name for name in self.track_order if self.track_visible[name]]
        for index, name in enumerate(visible_tracks):
            label, color = colors[name]
            top = self.ruler_height + index * self.track_height
            painter.setPen(QColor("#aeb4c2"))
            painter.drawText(8, top + 22, label)
            background = QRectF(self.track_left, top + 2, track_width, self.track_height - 4)
            painter.fillRect(background, QColor("#20232b"))
            self._draw_track_items(painter, name, top, color)

        self._draw_marker(painter, self.in_ms, QColor("#55d6a8"))
        self._draw_marker(painter, self.out_ms, QColor("#ffb65c"))
        cursor_x = self.position_to_x(self.position_ms)
        painter.setPen(QPen(QColor("#f5f7ff"), 2))
        painter.drawLine(QPointF(cursor_x, 28), QPointF(cursor_x, self.height() - 3))

    def _draw_track_items(self, painter: QPainter, name: str, top: int, color: QColor) -> None:
        items = self.track_items[name]
        if name == "audio" and not items:
            return
        for item in items:
            start, end, label = self._item_values(name, item)
            if end <= start:
                continue
            rect = QRectF(
                self.position_to_x(start),
                top + 5,
                max(3, self.position_to_x(end) - self.position_to_x(start)),
                self.track_height - 10,
            )
            selected = isinstance(item, TimelineClip) and item.clip_id in self.selected_clip_ids
            painter.fillRect(rect, color.lighter(125) if selected else color)
            if name == "video" and self.thumbnail_paths:
                index = int(start / max(1, self.duration_ms) * len(self.thumbnail_paths)) % len(self.thumbnail_paths)
                image = QImage(self.thumbnail_paths[index])
                if not image.isNull():
                    painter.save()
                    painter.setOpacity(0.42)
                    painter.drawImage(rect, image)
                    painter.restore()
            if name == "audio" and self.waveform:
                painter.save()
                painter.setPen(QPen(QColor("#9a8cff"), 1))
                for index, value in enumerate(self.waveform):
                    x = rect.left() + rect.width() * index / max(1, len(self.waveform) - 1)
                    amplitude = max(1.0, value * rect.height() * 0.42)
                    painter.drawLine(QPointF(x, rect.center().y() - amplitude), QPointF(x, rect.center().y() + amplitude))
                painter.restore()
            painter.setPen(QPen(QColor("#f5f7ff") if selected else QColor("#c5cad5"), 2 if selected else 1))
            painter.drawRect(rect)
            painter.drawText(rect.adjusted(4, 2, -3, -2), Qt.AlignmentFlag.AlignVCenter, label)
            if isinstance(item, TimelineClip) and item.transition_ms:
                transition_width = item.transition_ms * self.pixels_per_second / 1000
                painter.fillRect(QRectF(rect.left(), rect.top(), transition_width, rect.height()), QColor(127, 117, 235, 100))
        if name == "audio" and items and not self.waveform:
            painter.setPen(QPen(QColor("#7f75eb"), 1))
            y = top + self.track_height / 2
            for x in range(self.track_left, self.width() - 12, 5):
                amplitude = 3 + 7 * abs(math.sin(x * .09))
                painter.drawLine(QPointF(x, y - amplitude), QPointF(x, y + amplitude))

    @staticmethod
    def _item_values(name: str, item: Any) -> tuple[int, int, str]:
        if isinstance(item, TimelineClip):
            return item.timeline_start_ms, item.timeline_end_ms, item.label
        start = int(getattr(item, "start_ms", getattr(item, "timestamp_ms", 0)))
        end = int(getattr(item, "end_ms", start + 120))
        if name == "reframe":
            end = start + 120
        label = str(getattr(item, "text", getattr(item, "title", "◆")))
        return start, end, label[:50]

    def _clip_at(self, x: float, y: float) -> TimelineClip | None:
        position = self.x_to_position(x)
        visible_tracks = [name for name in self.track_order if self.track_visible[name]]
        for track in ("video", "audio"):
            if not self.track_visible[track] or self.track_locked[track]:
                continue
            top = self.ruler_height + visible_tracks.index(track) * self.track_height
            if top <= y <= top + self.track_height:
                return next(
                    (
                        clip
                        for clip in self.clips
                        if clip.track == track and clip.timeline_start_ms <= position <= clip.timeline_end_ms
                    ),
                    None,
                )
        return None

    def _draw_marker(self, painter: QPainter, position_ms: int | None, color: QColor) -> None:
        if position_ms is None:
            return
        x = self.position_to_x(position_ms)
        painter.setPen(QPen(color, 2))
        painter.drawLine(QPointF(x, 28), QPointF(x, self.height() - 3))

    def _update_width(self) -> None:
        content_width = self.track_left + round(self.duration_ms * self.pixels_per_second / 1000) + 24
        self.setMinimumWidth(max(760, content_width))


class TimelineWidget(QWidget):
    seek_requested = Signal(int)
    clip_selected = Signal(str)
    selection_changed = Signal(object)
    clip_move_requested = Signal(str, int)
    clip_trim_requested = Signal(str, str, int)

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        toolbar = QHBoxLayout()
        self.markers = QLabel("Entrada: 00:00:00    Saída: —")
        toolbar.addWidget(self.markers)
        toolbar.addStretch()
        toolbar.addWidget(QLabel("Faixas"))
        self.track_checks: dict[str, QCheckBox] = {}
        for track, label in (("video", "Vídeo"), ("audio", "Áudio"), ("subtitles", "Legendas")):
            check = QCheckBox(label)
            check.setChecked(True)
            check.toggled.connect(lambda visible, name=track: self.canvas.set_track_visible(name, visible))
            self.track_checks[track] = check
            toolbar.addWidget(check)
        self.track_locks: dict[str, QCheckBox] = {}
        for track, label in (("video", "Travar vídeo"), ("audio", "Travar áudio")):
            lock = QCheckBox(label)
            lock.toggled.connect(lambda locked, name=track: self.canvas.set_track_locked(name, locked))
            self.track_locks[track] = lock
            toolbar.addWidget(lock)
        self.track_selector = QComboBox()
        self.track_selector.addItems([label for _, label, _ in TRACKS])
        toolbar.addWidget(self.track_selector)
        up_button = QPushButton("↑")
        down_button = QPushButton("↓")
        up_button.setMaximumWidth(28)
        down_button.setMaximumWidth(28)
        up_button.clicked.connect(lambda: self.canvas.move_track(TRACKS[self.track_selector.currentIndex()][0], -1))
        down_button.clicked.connect(lambda: self.canvas.move_track(TRACKS[self.track_selector.currentIndex()][0], 1))
        toolbar.addWidget(up_button)
        toolbar.addWidget(down_button)
        clear_button = QPushButton("Limpar seleção")
        clear_button.setToolTip("Desmarcar todos os clipes")
        clear_button.clicked.connect(self._clear_selection)
        toolbar.addWidget(clear_button)
        toolbar.addWidget(QLabel("Zoom"))
        self.zoom = QSlider(Qt.Orientation.Horizontal)
        self.zoom.setRange(20, 200)
        self.zoom.setValue(60)
        self.zoom.setMaximumWidth(160)
        toolbar.addWidget(self.zoom)
        self.zoom_label = QLabel("60 px/s")
        self.zoom_label.setMinimumWidth(48)
        toolbar.addWidget(self.zoom_label)
        layout.addLayout(toolbar)
        self.canvas = TimelineCanvas()
        self.canvas.seek_requested.connect(self.seek_requested)
        self.canvas.clip_selected.connect(self.clip_selected)
        self.canvas.selection_changed.connect(self.selection_changed)
        self.canvas.clip_move_requested.connect(self.clip_move_requested)
        self.canvas.clip_trim_requested.connect(self.clip_trim_requested)
        self.zoom.valueChanged.connect(self.canvas.set_zoom)
        self.zoom.valueChanged.connect(lambda value: self.zoom_label.setText(f"{value} px/s"))
        self.scroll = QScrollArea()
        self.scroll.setWidget(self.canvas)
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setMinimumHeight(240)
        layout.addWidget(self.scroll)

    def set_duration(self, duration_ms: int) -> None:
        self.canvas.set_duration(duration_ms)

    def set_position(self, position_ms: int) -> None:
        self.canvas.set_position(position_ms)

    def set_markers(self, in_ms: int | None, out_ms: int | None) -> None:
        self.canvas.set_markers(in_ms, out_ms)
        entrance = format_timestamp(in_ms or 0)
        exit_text = format_timestamp(out_ms) if out_ms is not None else "—"
        self.markers.setText(f"Entrada: {entrance}    Saída: {exit_text}")

    def set_track_data(self, *args: Any, **kwargs: Any) -> None:
        self.canvas.set_track_data(*args, **kwargs)

    def set_media_previews(self, thumbnails: list[str], waveform: list[float]) -> None:
        self.canvas.set_media_previews(thumbnails, waveform)

    def select_clip(self, clip_id: str | None) -> None:
        self.canvas.select_clip(clip_id)

    def select_clips(self, clip_ids: list[str]) -> None:
        self.canvas.selected_clip_ids = set(clip_ids)
        self.canvas.selected_clip_id = clip_ids[-1] if clip_ids else None
        self.canvas.update()

    def _clear_selection(self) -> None:
        self.canvas.selected_clip_ids.clear()
        self.canvas.selected_clip_id = None
        self.canvas.selection_changed.emit([])
        self.canvas.update()
