"""Visual diagnostic for anonymous face tracking and active-speaker decisions."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, QUrl, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QStackedLayout,
    QVBoxLayout,
    QWidget,
)

from cortaflow.domain.tracking import FaceTrackPoint, SpeakerKeyframe


class FaceDiagnosticOverlay(QWidget):
    """Draw current face tracks over the video content area."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.points: list[FaceTrackPoint] = []
        self.speaker: SpeakerKeyframe | None = None
        self.source_width = 0
        self.source_height = 0
        self.position_ms = 0
        self.show_safe_area = True

    def set_data(
        self,
        points: list[FaceTrackPoint],
        speaker: SpeakerKeyframe | None,
        source_width: int,
        source_height: int,
        position_ms: int,
    ) -> None:
        self.points = list(points)
        self.speaker = speaker
        self.source_width = source_width
        self.source_height = source_height
        self.position_ms = position_ms
        self.update()

    def paintEvent(self, event: object) -> None:  # noqa: N802
        if not self.points or self.source_width <= 0 or self.source_height <= 0:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        content = self._content_rect()
        if content.width() <= 0 or content.height() <= 0:
            return

        if self.show_safe_area:
            target_ratio = 9 / 16
            if content.width() / content.height() >= target_ratio:
                safe_height = content.height()
                safe_width = safe_height * target_ratio
            else:
                safe_width = content.width()
                safe_height = safe_width / target_ratio
            safe = QRectF(
                content.left() + (content.width() - safe_width) / 2,
                content.top() + (content.height() - safe_height) / 2,
                safe_width,
                safe_height,
            )
            painter.setPen(QPen(QColor(120, 104, 233, 190), 2, Qt.PenStyle.DashLine))
            painter.drawRect(safe)
            painter.setPen(QColor(180, 173, 255))
            painter.drawText(int(safe.left() + 8), int(safe.top() + 20), "ÁREA 9:16")

        speaker_id = self.speaker.track_id if self.speaker else None
        for point in self.points:
            rect = self._face_rect(point, content)
            selected = speaker_id is not None and point.track_id == speaker_id
            color = QColor("#4ee39b") if selected else QColor("#ffbd66")
            painter.setPen(QPen(color, 3 if selected else 2))
            painter.drawRect(rect)
            confidence = self.speaker.confidence if selected and self.speaker else point.box.confidence
            state = "FALANTE" if selected else "ROSTO"
            if selected and self.speaker and self.speaker.uncertain:
                state = "INCERTO"
                color = QColor("#ffcf5a")
            label = f"{state} · ID {point.track_id} · {confidence:.0%}"
            painter.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
            text_rect = rect.adjusted(0, -24, 0, 0)
            painter.fillRect(text_rect, QColor(10, 12, 17, 220))
            painter.setPen(color)
            painter.drawText(text_rect.adjusted(6, 0, -4, 0), Qt.AlignmentFlag.AlignVCenter, label)

    def _content_rect(self) -> QRectF:
        if self.source_width <= 0 or self.source_height <= 0:
            return QRectF(self.rect())
        source_ratio = self.source_width / self.source_height
        widget_ratio = self.width() / max(1, self.height())
        if widget_ratio > source_ratio:
            height = self.height()
            width = height * source_ratio
            left = (self.width() - width) / 2
            return QRectF(left, 0, width, self.height())
        width = self.width()
        height = width / source_ratio
        top = (self.height() - height) / 2
        return QRectF(0, top, self.width(), height)

    @staticmethod
    def _face_rect(point: FaceTrackPoint, content: QRectF) -> QRectF:
        return QRectF(
            content.left() + point.box.x * content.width(),
            content.top() + point.box.y * content.height(),
            point.box.width * content.width(),
            point.box.height * content.height(),
        )


class FaceDiagnosticsDialog(QDialog):
    """Play a source video while exposing face and speaker decisions."""

    def __init__(
        self,
        source_path: Path,
        tracks: list[FaceTrackPoint],
        speaker_keyframes: list[SpeakerKeyframe] | None = None,
        source_width: int = 0,
        source_height: int = 0,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Diagnóstico facial · CortaFlow")
        self.resize(1100, 720)
        self.tracks = list(tracks)
        self.speaker_keyframes = list(speaker_keyframes or [])
        self.source_width = source_width
        self.source_height = source_height
        self._duration = 0

        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.video = QVideoWidget()
        self.player.setAudioOutput(self.audio)
        self.player.setVideoOutput(self.video)
        self.audio.setVolume(0.0)

        self.overlay = FaceDiagnosticOverlay()
        stack_host = QWidget()
        stack = QStackedLayout(stack_host)
        stack.setStackingMode(QStackedLayout.StackingMode.StackAll)
        stack.addWidget(self.video)
        stack.addWidget(self.overlay)

        self.status = QLabel("Carregando diagnóstico…")
        self.status.setWordWrap(True)
        self.play_button = QPushButton("Reproduzir")
        self.play_button.clicked.connect(self.toggle_playback)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 0)
        self.slider.sliderMoved.connect(self.player.setPosition)
        self.safe_area = QPushButton("Área 9:16")
        self.safe_area.setCheckable(True)
        self.safe_area.setChecked(True)
        self.safe_area.toggled.connect(self._safe_area_toggled)
        close_button = QPushButton("Fechar")
        close_button.clicked.connect(self.close)

        controls = QHBoxLayout()
        controls.addWidget(self.play_button)
        controls.addWidget(self.slider, 1)
        controls.addWidget(self.safe_area)
        controls.addWidget(close_button)

        layout = QVBoxLayout(self)
        layout.addWidget(stack_host, 1)
        layout.addLayout(controls)
        layout.addWidget(self.status)

        self.player.durationChanged.connect(self._duration_changed)
        self.player.positionChanged.connect(self._position_changed)
        self.player.playbackStateChanged.connect(self._playback_changed)
        self.player.setSource(QUrl.fromLocalFile(str(source_path.resolve())))

    def set_speaker_keyframes(self, keyframes: list[SpeakerKeyframe]) -> None:
        self.speaker_keyframes = list(keyframes)
        self._position_changed(self.player.position())

    def toggle_playback(self) -> None:
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def _duration_changed(self, duration: int) -> None:
        self._duration = max(0, duration)
        self.slider.setRange(0, self._duration)

    def _position_changed(self, position: int) -> None:
        self.slider.blockSignals(True)
        self.slider.setValue(position)
        self.slider.blockSignals(False)
        points = self._nearest_points(position)
        speaker = self._nearest_speaker(position)
        self.overlay.set_data(
            points,
            speaker,
            self.source_width,
            self.source_height,
            position,
        )
        if not points:
            self.status.setText(f"{_timestamp(position)} · nenhum rosto detectado nesta amostra.")
            return
        if speaker and speaker.track_id is not None:
            confidence = f"{speaker.confidence:.0%}"
            state = "incerto" if speaker.uncertain else "identificado"
            self.status.setText(
                f"{_timestamp(position)} · {len(points)} rosto(s) · "
                f"falante: ID {speaker.track_id} · confiança {confidence} · {state}"
            )
        else:
            self.status.setText(
                f"{_timestamp(position)} · {len(points)} rosto(s) · falante não determinado"
            )

    def _nearest_points(self, position: int) -> list[FaceTrackPoint]:
        if not self.tracks:
            return []
        closest = min(abs(point.timestamp_ms - position) for point in self.tracks)
        if closest > 500:
            return []
        timestamp = min(
            (point.timestamp_ms for point in self.tracks),
            key=lambda value: abs(value - position),
        )
        return [point for point in self.tracks if point.timestamp_ms == timestamp]

    def _nearest_speaker(self, position: int) -> SpeakerKeyframe | None:
        if not self.speaker_keyframes:
            return None
        item = min(self.speaker_keyframes, key=lambda value: abs(value.timestamp_ms - position))
        return item if abs(item.timestamp_ms - position) <= 500 else None

    def _safe_area_toggled(self, enabled: bool) -> None:
        self.overlay.show_safe_area = enabled
        self.overlay.update()

    def _playback_changed(self, state: QMediaPlayer.PlaybackState) -> None:
        self.play_button.setText(
            "Pausar" if state == QMediaPlayer.PlaybackState.PlayingState else "Reproduzir"
        )

    def closeEvent(self, event: object) -> None:  # noqa: N802
        self.player.stop()
        self.player.setSource(QUrl())
        super().closeEvent(event)


def _timestamp(milliseconds: int) -> str:
    total_seconds = max(0, milliseconds) // 1000
    return f"{total_seconds // 3600:02d}:{(total_seconds % 3600) // 60:02d}:{total_seconds % 60:02d}"


__all__ = ["FaceDiagnosticOverlay", "FaceDiagnosticsDialog"]
