"""Preview approval and sequential professional export queue."""

from collections import deque
from dataclasses import dataclass
import logging
from pathlib import Path
import sqlite3
from time import monotonic
from uuid import uuid4

from PySide6.QtCore import Qt, QThreadPool, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QImageReader
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QStackedLayout,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cortaflow.config import AppConfig
from cortaflow.domain.analysis import ClipSuggestion
from cortaflow.domain.clip import ClipRange, format_timestamp
from cortaflow.domain.editing import AudioSettings, LayerItem, ReframeSettings, SubtitleStyle, TimelineClip
from cortaflow.domain.project import ExportSettings, ReframeKeyframe, WatermarkSettings
from cortaflow.domain.subtitle import SubtitleCue, TranscriptWord
from cortaflow.infrastructure.database import enqueue_task, initialize_database, update_task_status
from cortaflow.services.export_service import render_project_export
from cortaflow.services.renderer import output_dimensions
from cortaflow.ui.widgets.watermark_overlay import WatermarkOverlay
from cortaflow.workers.base_worker import FunctionWorker


LOGGER = logging.getLogger(__name__)


def _progress_microseconds(state: dict) -> int:
    """Read FFmpeg progress safely; some codecs report ``N/A`` before the first frame."""
    for key in ("out_time_us", "out_time_ms"):
        raw_value = state.get(key)
        if raw_value in (None, "", "N/A"):
            continue
        try:
            return max(0, int(float(raw_value)))
        except (TypeError, ValueError, OverflowError):
            continue
    return 0


@dataclass
class ExportJob:
    job_id: str
    destination: Path
    clip: ClipRange
    settings: ExportSettings
    preview: bool = False
    use_timeline: bool = False
    status: str = "pending"
    database_id: int | None = None
    suggestion: ClipSuggestion | None = None


class ExportPage(QWidget):
    settings_changed = Signal(object)
    cues_changed = Signal(object)
    reframe_edit_requested = Signal(object)
    suggestion_saved = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.source_path: Path | None = None
        self.duration_ms = 0
        self.cues: list[SubtitleCue] = []
        self.words: list[TranscriptWord] = []
        self.subtitle_style = SubtitleStyle()
        self.keyframes: list[ReframeKeyframe] = []
        self.timeline_clips: list[TimelineClip] = []
        self.layers: list[LayerItem] = []
        self.reframe_settings = ReframeSettings()
        self.audio_settings = AudioSettings()
        self.source_size: tuple[int, int] | None = None
        self.suggestions: list[ClipSuggestion] = []
        self.settings = ExportSettings()
        self.queue: deque[ExportJob] = deque()
        self.jobs: list[ExportJob] = []
        self.current_job: ExportJob | None = None
        self.current_worker: FunctionWorker | None = None
        self.preview_path: Path | None = None
        self.preview_approved = False
        self.review_suggestion: ClipSuggestion | None = None
        self.review_reference_preview: Path | None = None
        self.sequence_export_mode = False
        self.review_cue_indexes: list[int] = []
        self._editing_cues = False
        self.review_start_ms = 0
        self.review_end_ms: int | None = None
        self._pending_review_seek_ms: int | None = None
        self.job_started_at = 0.0
        self.thread_pool = QThreadPool.globalInstance()

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.resolution = QComboBox()
        self.resolution.addItem("1080 × 1920 · máxima", (1080, 1920))
        self.resolution.addItem("720 × 1280", (720, 1280))
        self.codec = QComboBox()
        self.codec.addItem("H.264", "h264")
        self.codec.addItem("H.265", "h265")
        self.fps = QDoubleSpinBox()
        self.fps.setRange(12, 120)
        self.fps.setValue(30)
        self.quality = QSpinBox()
        self.quality.setRange(0, 51)
        self.quality.setValue(20)
        self.quality.setToolTip("Valor menor preserva mais qualidade. 18–20 é alta qualidade; 0 gera arquivos muito grandes.")
        self.nvenc = QCheckBox("Usar NVIDIA NVENC quando disponível")
        self.nvenc.setChecked(True)
        self.normalize = QCheckBox("Normalizar áudio para -16 LUFS")
        self.timeline_mode = QCheckBox("Usar linha do tempo editada")
        self.start_seconds = QDoubleSpinBox()
        self.start_seconds.setDecimals(3)
        self.end_seconds = QDoubleSpinBox()
        self.end_seconds.setDecimals(3)
        self.watermark_enabled = QCheckBox("Aplicar imagem no vídeo")
        self.watermark_enabled.setEnabled(False)
        self.watermark_path = QLineEdit()
        self.watermark_path.setReadOnly(True)
        self.watermark_path.setPlaceholderText("Nenhuma imagem escolhida")
        self.watermark_select = QPushButton("Escolher imagem…")
        self.watermark_select.clicked.connect(self.choose_watermark)
        self.watermark_remove = QPushButton("Remover")
        self.watermark_remove.clicked.connect(self.remove_watermark)
        watermark_file_row = QHBoxLayout()
        watermark_file_row.addWidget(self.watermark_path, 1)
        watermark_file_row.addWidget(self.watermark_select)
        watermark_file_row.addWidget(self.watermark_remove)
        self.watermark_position = QComboBox()
        for label, value in (
            ("Superior esquerdo", "top-left"), ("Superior", "top"),
            ("Superior direito", "top-right"), ("Esquerda", "left"),
            ("Centro", "center"), ("Direita", "right"),
            ("Inferior esquerdo", "bottom-left"), ("Inferior", "bottom"),
            ("Inferior direito", "bottom-right"), ("Personalizada", "custom"),
        ):
            self.watermark_position.addItem(label, value)
        self.watermark_width = QSpinBox()
        self.watermark_width.setRange(2, 80)
        self.watermark_width.setSuffix("% da largura")
        self.watermark_opacity = QDoubleSpinBox()
        self.watermark_opacity.setRange(0.05, 1)
        self.watermark_opacity.setSingleStep(0.05)
        self.watermark_opacity.setDecimals(2)
        self.watermark_margin = QDoubleSpinBox()
        self.watermark_margin.setRange(0, 25)
        self.watermark_margin.setSuffix("%")
        self.watermark_x = QDoubleSpinBox()
        self.watermark_x.setRange(0, 100)
        self.watermark_x.setSuffix("%")
        self.watermark_y = QDoubleSpinBox()
        self.watermark_y.setRange(0, 100)
        self.watermark_y.setSuffix("%")
        for label, widget in (
            ("Resolução", self.resolution), ("Codec", self.codec), ("FPS", self.fps),
            ("Qualidade", self.quality), ("GPU", self.nvenc), ("Áudio", self.normalize),
            ("Montagem", self.timeline_mode),
            ("Início (s)", self.start_seconds), ("Fim (s)", self.end_seconds),
        ):
            form.addRow(label, widget)
        form.addRow("Imagem da marca-d'água", watermark_file_row)
        form.addRow("Marca-d'água", self.watermark_enabled)
        form.addRow("Posição", self.watermark_position)
        form.addRow("Tamanho", self.watermark_width)
        form.addRow("Transparência", self.watermark_opacity)
        form.addRow("Margem", self.watermark_margin)
        form.addRow("Posição X", self.watermark_x)
        form.addRow("Posição Y", self.watermark_y)
        layout.addWidget(QLabel("Editor do corte sugerido"))
        editor_row = QHBoxLayout()
        review_column = QVBoxLayout()
        self.review_player = QMediaPlayer(self)
        self.review_audio = QAudioOutput(self)
        self.review_video = QVideoWidget(self)
        self.review_player.setAudioOutput(self.review_audio)
        self.review_player.setVideoOutput(self.review_video)
        self.review_audio.setVolume(0.8)
        self.review_canvas = QWidget(self)
        self.review_canvas.setMinimumHeight(280)
        self.preview_stack = QStackedLayout(self.review_canvas)
        self.preview_stack.setContentsMargins(0, 0, 0, 0)
        self.preview_stack.setStackingMode(QStackedLayout.StackingMode.StackAll)
        self.preview_stack.addWidget(self.review_video)
        self.watermark_overlay = WatermarkOverlay(self.review_canvas)
        self.preview_stack.addWidget(self.watermark_overlay)
        self.watermark_overlay.raise_()
        review_column.addWidget(self.review_canvas, 2)
        self.review_help = QLabel(
            "Confira o corte, o rosto e as legendas. Com uma imagem escolhida, arraste a "
            "marca-d'água sobre o vídeo e use o quadrado no canto para redimensionar."
        )
        self.review_help.setWordWrap(True)
        review_column.addWidget(self.review_help)
        review_actions = QHBoxLayout()
        self.play_review_button = QPushButton("Reproduzir corte")
        self.play_review_button.clicked.connect(self.toggle_review_playback)
        self.reframe_button = QPushButton("Ajustar enquadramento no Editor")
        self.reframe_button.clicked.connect(self.request_reframe_edit)
        review_actions.addWidget(self.play_review_button)
        review_actions.addWidget(self.reframe_button)
        review_actions.addStretch()
        review_column.addLayout(review_actions)
        review_column.addWidget(QLabel("Legendas deste corte (edite o texto antes de gerar a prévia)"))
        self.review_subtitles = QTableWidget(0, 3)
        self.review_subtitles.setHorizontalHeaderLabels(["Início", "Fim", "Texto"])
        self.review_subtitles.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.review_subtitles.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.review_subtitles.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.review_subtitles.setMaximumHeight(180)
        self.review_subtitles.itemChanged.connect(self._review_subtitle_edited)
        review_column.addWidget(self.review_subtitles, 1)
        editor_row.addLayout(review_column, 2)
        editor_row.addLayout(form, 1)
        layout.addLayout(editor_row, 3)

        actions = QHBoxLayout()
        self.preview_button = QPushButton("Atualizar prévia após ajustes")
        self.preview_button.clicked.connect(self.generate_preview)
        self.open_preview_button = QPushButton("Abrir prévia")
        self.open_preview_button.setEnabled(False)
        self.open_preview_button.clicked.connect(self.open_preview)
        self.approve_button = QPushButton("Validar prévia")
        self.approve_button.setEnabled(False)
        self.approve_button.clicked.connect(self.approve_preview)
        self.batch_button = QPushButton("Salvar cortes aprovados")
        self.batch_button.setEnabled(False)
        self.batch_button.hide()
        self.batch_button.clicked.connect(self.enqueue_accepted)
        self.cancel_button = QPushButton("Cancelar tarefa atual")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_current)
        for button in (
            self.preview_button, self.open_preview_button, self.approve_button,
            self.batch_button, self.cancel_button,
        ):
            actions.addWidget(button)
        actions.addStretch()
        layout.addLayout(actions)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        layout.addWidget(self.progress)
        self.status = QLabel("Importe uma mídia para exportar.")
        layout.addWidget(self.status)
        self.queue_table = QTableWidget(0, 5)
        self.queue_table.setHorizontalHeaderLabels(["Destino", "Intervalo", "Tipo", "Status", "Progresso"])
        layout.addWidget(self.queue_table, 1)
        for widget in (self.resolution, self.codec, self.fps, self.quality, self.nvenc, self.normalize):
            signal = (
                widget.currentIndexChanged if isinstance(widget, QComboBox)
                else widget.toggled if isinstance(widget, QCheckBox)
                else widget.valueChanged
            )
            signal.connect(self._settings_edited)
        for widget in (
            self.watermark_enabled, self.watermark_position, self.watermark_width,
            self.watermark_opacity, self.watermark_margin, self.watermark_x,
            self.watermark_y,
        ):
            signal = (
                widget.currentIndexChanged if isinstance(widget, QComboBox)
                else widget.toggled if isinstance(widget, QCheckBox)
                else widget.valueChanged
            )
            signal.connect(self._watermark_edited)
        self.timeline_mode.toggled.connect(self._timeline_mode_changed)
        self.start_seconds.valueChanged.connect(self._range_edited)
        self.end_seconds.valueChanged.connect(self._range_edited)
        self.review_player.positionChanged.connect(self._review_position_changed)
        self.review_player.mediaStatusChanged.connect(self._review_media_status_changed)
        self.review_player.playbackStateChanged.connect(self._review_playback_changed)
        self.watermark_overlay.placement_changed.connect(self._watermark_dragged)
        self._load_settings(self.settings)

    def set_context(
        self,
        source_path: Path | None,
        duration_ms: int,
        settings: ExportSettings,
        cues: list[SubtitleCue],
        subtitle_style: SubtitleStyle,
        keyframes: list[ReframeKeyframe],
        suggestions: list[ClipSuggestion],
        words: list[TranscriptWord] | None = None,
        timeline_clips: list[TimelineClip] | None = None,
        reframe_settings: ReframeSettings | None = None,
        audio_settings: AudioSettings | None = None,
        source_size: tuple[int, int] | None = None,
        layers: list[LayerItem] | None = None,
    ) -> None:
        resolved_source = source_path.resolve() if source_path else None
        if resolved_source != self.source_path:
            self.review_suggestion = None
            self.review_reference_preview = None
        self.source_path = resolved_source
        self.duration_ms = max(0, duration_ms)
        self.cues = list(cues)
        self.words = list(words or [])
        self.subtitle_style = subtitle_style
        self.keyframes = list(keyframes)
        self.suggestions = list(suggestions)
        if self.review_suggestion:
            self.review_suggestion = next(
                (
                    item for item in self.suggestions
                    if item.start_ms == self.review_suggestion.start_ms
                    and item.end_ms == self.review_suggestion.end_ms
                    and item.title == self.review_suggestion.title
                ),
                self.review_suggestion,
            )
        self.timeline_clips = list(timeline_clips or [])
        self.layers = list(layers or [])
        self.reframe_settings = reframe_settings or ReframeSettings()
        self.audio_settings = audio_settings or AudioSettings()
        self.source_size = source_size
        self.settings = settings
        self.start_seconds.blockSignals(True)
        self.end_seconds.blockSignals(True)
        self.start_seconds.setRange(0, self.duration_ms / 1000)
        self.end_seconds.setRange(0, self.duration_ms / 1000)
        if self.review_suggestion:
            self.start_seconds.setValue(self.review_suggestion.start_ms / 1000)
            self.end_seconds.setValue(self.review_suggestion.end_ms / 1000)
        else:
            self.start_seconds.setValue(0)
            self.end_seconds.setValue(self.duration_ms / 1000)
        self.start_seconds.blockSignals(False)
        self.end_seconds.blockSignals(False)
        self._load_settings(settings)
        has_video_timeline = any(item.track == "video" for item in self.timeline_clips)
        use_video_timeline = has_video_timeline and self.review_suggestion is None
        self.timeline_mode.blockSignals(True)
        self.timeline_mode.setEnabled(use_video_timeline)
        self.timeline_mode.setChecked(use_video_timeline)
        self.timeline_mode.blockSignals(False)
        editable_review_range = self.review_suggestion is not None or not has_video_timeline
        self.start_seconds.setEnabled(editable_review_range)
        self.end_seconds.setEnabled(editable_review_range)
        self._refresh_review_subtitles()
        self._invalidate_preview()
        self.preview_button.setEnabled(self.source_path is not None and self.duration_ms > 0)
        if self.review_suggestion and self.source_path:
            self.approve_button.setEnabled(True)
        self.batch_button.setEnabled(
            self.preview_approved and any(item.status == "accepted" for item in suggestions)
        )
        self.status.setText(
            "Revise este corte, ajuste o necessário e gere a prévia final."
            if source_path and self.review_suggestion
            else "Configure o intervalo e gere uma prévia."
            if source_path
            else "Importe uma mídia para exportar."
        )

    def generate_preview(self) -> None:
        clip = self._selected_clip()
        if not clip or not self.source_path:
            return
        config = AppConfig()
        preview_dir = config.preview_dir
        preview_dir.mkdir(parents=True, exist_ok=True)
        destination = preview_dir / f"preview-{uuid4().hex}.mp4"
        self._invalidate_preview()
        self._enqueue(
            ExportJob(
                uuid4().hex,
                destination,
                clip,
                self.settings.model_copy(),
                preview=True,
                use_timeline=self.timeline_mode.isChecked(),
            ),
            front=True,
        )

    def approve_preview(self) -> None:
        if self.sequence_export_mode:
            self.save_sequence()
            return
        if self.review_suggestion:
            self.save_current_suggestion()
            return
        if not self.preview_path or not self.preview_path.is_file():
            return
        self.preview_approved = True
        self.batch_button.setEnabled(any(item.status == "accepted" for item in self.suggestions))
        self.status.setText("Prévia validada. Agora escolha a pasta para salvar os cortes aceitos.")

    def prepare_sequence_export(self) -> bool:
        """Open the active non-destructive timeline for preview and final save."""
        if not self.source_path or not self.source_path.is_file():
            QMessageBox.warning(self, "Mídia ausente", "Importe uma mídia antes de exportar a sequência.")
            return False
        if not any(item.track == "video" for item in self.timeline_clips):
            QMessageBox.warning(self, "Sequência vazia", "A sequência não contém clipes de vídeo.")
            return False
        self.sequence_export_mode = True
        self.review_suggestion = None
        self.review_reference_preview = None
        duration_ms = max(item.timeline_end_ms for item in self.timeline_clips)
        self.timeline_mode.blockSignals(True)
        self.timeline_mode.setEnabled(True)
        self.timeline_mode.setChecked(True)
        self.timeline_mode.blockSignals(False)
        self.start_seconds.blockSignals(True)
        self.end_seconds.blockSignals(True)
        self.start_seconds.setValue(0)
        self.end_seconds.setValue(duration_ms / 1000)
        self.start_seconds.blockSignals(False)
        self.end_seconds.blockSignals(False)
        self.start_seconds.setEnabled(False)
        self.end_seconds.setEnabled(False)
        self.approve_button.setText("Salvar sequência")
        self.approve_button.setEnabled(False)
        self.batch_button.setVisible(False)
        self._refresh_review_subtitles()
        self._invalidate_preview()
        self.status.setText("Sequência editada carregada. Gere a prévia para revisar antes de salvar.")
        return True

    def save_sequence(self) -> bool:
        """Save the edited timeline, layers and subtitles as one final video."""
        if not self.sequence_export_mode or not self.source_path:
            return False
        filename, _ = QFileDialog.getSaveFileName(
            self, "Salvar sequência editada", "corta-flow-sequencia.mp4", "Vídeo MP4 (*.mp4)"
        )
        if not filename:
            return False
        destination = self._available_destination(Path(filename))
        duration_ms = max((item.timeline_end_ms for item in self.timeline_clips), default=0)
        if duration_ms <= 0:
            return False
        queued = self._enqueue_final_job(
            destination,
            ClipRange(start_ms=0, end_ms=duration_ms),
            use_timeline=True,
        )
        if queued:
            self.approve_button.setEnabled(False)
            self.status.setText(f"Salvando a sequência editada em {destination.name}…")
        return queued

    def save_current_suggestion(self) -> bool:
        """Save the cut open in the individual editor without batch acceptance."""
        if not self.source_path or not self.review_suggestion:
            return False
        self.sequence_export_mode = False
        folder = QFileDialog.getExistingDirectory(self, "Pasta para salvar este corte")
        if not folder:
            return False
        safe_title = self._safe_title(self.review_suggestion.title)
        destination = self._available_destination(Path(folder) / f"{safe_title}.mp4")
        queued = self._enqueue_final_job(
            destination,
            ClipRange(
                start_ms=self.review_suggestion.start_ms,
                end_ms=self.review_suggestion.end_ms,
            ),
            use_timeline=False,
            suggestion=self.review_suggestion,
        )
        if queued:
            self.approve_button.setEnabled(False)
            watermark_note = " com marca-d'água" if self.settings.watermark.enabled else ""
            self.status.setText(
                f"Salvando o corte aberto{watermark_note} na pasta escolhida…"
            )
        return queued

    def open_preview(self) -> None:
        if self.preview_path and self.preview_path.is_file():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.preview_path)))

    def enqueue_accepted(self) -> None:
        if not self.preview_approved:
            return
        accepted = [item for item in self.suggestions if item.status == "accepted"]
        if not accepted:
            return
        folder = QFileDialog.getExistingDirectory(self, "Pasta dos cortes exportados")
        if not folder:
            return
        for index, item in enumerate(accepted, start=1):
            safe_title = "".join(character if character.isalnum() or character in " -_" else "_" for character in item.title).strip()
            destination = Path(folder) / f"{index:02d}-{safe_title or 'corte'}.mp4"
            self._enqueue_final_job(
                destination,
                ClipRange(start_ms=item.start_ms, end_ms=item.end_ms),
                use_timeline=False,
            )

    def prepare_accepted(self) -> bool:
        """Prepare the first accepted cut for the mandatory final preview."""
        accepted = [item for item in self.suggestions if item.status == "accepted"]
        if not self.source_path or not accepted:
            QMessageBox.warning(
                self,
                "Cortes aprovados ausentes",
                "Aceite pelo menos um corte antes de preparar a exportação final.",
            )
            return False
        self.review_suggestion = None
        self.review_reference_preview = None
        self.approve_button.setText("Validar prévia do lote")
        self.batch_button.setVisible(True)
        first = accepted[0]
        self.timeline_mode.setChecked(False)
        self.start_seconds.setValue(first.start_ms / 1000)
        self.end_seconds.setValue(first.end_ms / 1000)
        self._invalidate_preview()
        self.preview_button.setEnabled(True)
        self.status.setText(
            "Configure qualidade e marca-d'água; gere e aprove a prévia antes de salvar."
        )
        return True

    def prepare_suggestion(
        self,
        suggestion: ClipSuggestion,
        rendered_preview: Path | None = None,
    ) -> bool:
        """Open one suggestion in the final review editor before saving it."""
        if not self.source_path or not self.source_path.is_file():
            QMessageBox.warning(
                self,
                "Mídia ausente",
                "A mídia original não está disponível para revisar este corte.",
            )
            return False
        self.sequence_export_mode = False
        self.review_suggestion = suggestion
        self.review_reference_preview = (
            rendered_preview.resolve()
            if rendered_preview and rendered_preview.is_file()
            else None
        )
        self.timeline_mode.setChecked(False)
        self.start_seconds.blockSignals(True)
        self.end_seconds.blockSignals(True)
        self.start_seconds.setValue(suggestion.start_ms / 1000)
        self.end_seconds.setValue(suggestion.end_ms / 1000)
        self.start_seconds.blockSignals(False)
        self.end_seconds.blockSignals(False)
        self.start_seconds.setEnabled(True)
        self.end_seconds.setEnabled(True)
        self.approve_button.setText("Salvar este corte")
        self.approve_button.setEnabled(True)
        self.batch_button.setVisible(False)
        self._refresh_review_subtitles()
        self._invalidate_preview()
        self.approve_button.setEnabled(True)
        if self.review_reference_preview:
            self._load_review_media(self.review_reference_preview, 0, None, baked=False)
        self.preview_button.setEnabled(True)
        self.status.setText(
            "Ajuste início, fim, enquadramento, legendas e marca-d'água. "
            "Gere a prévia e salve o intervalo revisado."
        )
        return True

    def choose_watermark(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Escolher imagem da marca-d'água",
            "",
            "Imagens (*.png *.webp *.jpg *.jpeg *.bmp)",
        )
        if not filename:
            return
        reader = QImageReader(filename)
        if not reader.canRead():
            QMessageBox.warning(
                self,
                "Imagem inválida",
                "Escolha uma imagem PNG, WebP, JPG ou BMP válida.",
            )
            return
        self.watermark_path.setText(str(Path(filename).resolve()))
        self.watermark_enabled.setEnabled(True)
        self.watermark_enabled.setChecked(True)
        self.watermark_overlay.set_image(Path(filename).resolve())
        self._sync_watermark_overlay()
        self._settings_edited()
        self.status.setText(
            "Marca-d'água ativada e visível sobre a área do vídeo. "
            "Clique em Atualizar prévia após ajustes para gravá-la no MP4."
        )

    def remove_watermark(self) -> None:
        self.watermark_enabled.setChecked(False)
        self.watermark_path.clear()
        self.watermark_enabled.setEnabled(False)
        self.watermark_overlay.set_image(None)
        self._settings_edited()

    def _watermark_edited(self) -> None:
        active = self.watermark_enabled.isChecked() and bool(self.watermark_path.text())
        custom = active and self.watermark_position.currentData() == "custom"
        for widget in (
            self.watermark_position, self.watermark_width,
            self.watermark_opacity, self.watermark_margin,
        ):
            widget.setEnabled(active)
        self.watermark_x.setEnabled(custom)
        self.watermark_y.setEnabled(custom)
        self._sync_watermark_overlay()
        self._settings_edited()

    def _watermark_dragged(self, x_percent: float, y_percent: float, width_percent: float) -> None:
        widgets = (self.watermark_position, self.watermark_x, self.watermark_y, self.watermark_width)
        for widget in widgets:
            widget.blockSignals(True)
        self.watermark_position.setCurrentIndex(self.watermark_position.findData("custom"))
        self.watermark_x.setValue(x_percent)
        self.watermark_y.setValue(y_percent)
        self.watermark_width.setValue(round(width_percent))
        for widget in widgets:
            widget.blockSignals(False)
        self.watermark_x.setEnabled(True)
        self.watermark_y.setEnabled(True)
        self._settings_edited()

    def _sync_watermark_overlay(self) -> None:
        path = Path(self.watermark_path.text()) if self.watermark_path.text() else None
        active = self.watermark_enabled.isChecked() and bool(path)
        output_width, output_height = output_dimensions(
            self.settings,
            self.reframe_settings,
            self.source_size,
            preview=True,
        )
        self.watermark_overlay.set_content_aspect_ratio(output_width, output_height)
        if active and path and self.watermark_overlay.set_image(path):
            position = self.watermark_position.currentData()
            horizontal = {
                "top-left": 0, "left": 0, "bottom-left": 0,
                "top": 50, "center": 50, "bottom": 50,
                "top-right": 100, "right": 100, "bottom-right": 100,
            }
            vertical = {
                "top-left": 0, "top": 0, "top-right": 0,
                "left": 50, "center": 50, "right": 50,
                "bottom-left": 100, "bottom": 100, "bottom-right": 100,
            }
            x_percent = self.watermark_x.value() if position == "custom" else horizontal[position]
            y_percent = self.watermark_y.value() if position == "custom" else vertical[position]
            self.watermark_overlay.set_placement(
                x_percent,
                y_percent,
                self.watermark_width.value(),
                self.watermark_opacity.value(),
            )
            # In StackAll mode the current widget owns the top layer. Merely calling
            # raise_() is not stable while QVideoWidget keeps repainting on Windows.
            self.preview_stack.setCurrentWidget(self.watermark_overlay)
            self.watermark_overlay.show()
            self.watermark_overlay.raise_()
        else:
            self.watermark_overlay.hide()

    def _enqueue_final_job(
        self,
        destination: Path,
        clip: ClipRange,
        use_timeline: bool | None = None,
        suggestion: ClipSuggestion | None = None,
    ) -> bool:
        if destination.exists():
            QMessageBox.warning(self, "Arquivo existente", f"O arquivo não será sobrescrito:\n{destination}")
            return False
        self._enqueue(
            ExportJob(
                uuid4().hex,
                destination,
                clip,
                self.settings.model_copy(),
                use_timeline=self.timeline_mode.isChecked() if use_timeline is None else use_timeline,
                suggestion=suggestion,
            )
        )
        return True

    def _enqueue(self, job: ExportJob, front: bool = False) -> None:
        job.database_id = self._persist_job(job)
        self.jobs.append(job)
        if front:
            self.queue.appendleft(job)
        else:
            self.queue.append(job)
        self._refresh_queue_table()
        self._start_next()

    def _start_next(self) -> None:
        if self.current_worker is not None or not self.queue or not self.source_path:
            return
        job = self.queue.popleft()
        job.status = "running"
        self._persist_status(job)
        worker_args = (
            self.source_path,
            job.destination,
            job.settings,
            job.clip,
            list(self.cues),
            self.subtitle_style,
            list(self.keyframes),
            job.preview,
            list(self.words),
            self.reframe_settings,
            self.audio_settings,
            self.source_size,
            list(self.timeline_clips) if job.use_timeline else [],
        )
        worker_kwargs = (
            {"layers": list(self.layers)}
            if job.use_timeline and self.layers
            else {}
        )
        worker = FunctionWorker(render_project_export, *worker_args, **worker_kwargs)
        worker.signals.progress.connect(self._render_progress)
        worker.signals.finished.connect(self._render_finished)
        worker.signals.failed.connect(self._render_failed)
        self.current_job = job
        self.current_worker = worker
        self.job_started_at = monotonic()
        self.cancel_button.setEnabled(True)
        self.progress.setValue(0)
        self.status.setText("Renderizando prévia…" if job.preview else "Exportando item da fila…")
        self._refresh_queue_table()
        self.thread_pool.start(worker)

    def _render_progress(self, state: dict) -> None:
        if not self.current_job:
            return
        if state.get("progress") == "fallback":
            self.status.setText(str(state.get("message")))
            return
        out_time_us = _progress_microseconds(state)
        processed_ms = out_time_us / 1000
        percentage = min(100, round(processed_ms * 100 / self.current_job.clip.duration_ms))
        self.progress.setValue(percentage)
        elapsed = monotonic() - self.job_started_at
        eta = elapsed * (100 - percentage) / percentage if percentage else 0
        encoder = state.get("encoder", "—")
        fps = state.get("fps", "—")
        speed = state.get("speed", "—")
        self.status.setText(
            f"{encoder} · {percentage}% · {fps} FPS · {speed} · decorrido {elapsed:.0f}s · ETA {eta:.0f}s"
        )
        self._refresh_queue_table(percentage)

    def _render_finished(self, destination: Path) -> None:
        assert self.current_job is not None
        completed_job = self.current_job
        completed_job.status = "completed"
        self._persist_status(completed_job)
        if completed_job.preview:
            self.preview_path = destination
            self.open_preview_button.setEnabled(True)
            self.approve_button.setEnabled(True)
            if self.sequence_export_mode:
                self.approve_button.setText("Salvar sequência")
            self._load_review_media(destination, 0, None, baked=True)
            watermark_note = (
                " Marca-d'água gravada no MP4."
                if completed_job.settings.watermark.enabled
                else ""
            )
            self.status.setText(
                (
                    "Prévia concluída. Revise e clique em Salvar este corte."
                    if self.review_suggestion
                    else "Prévia concluída. Revise e clique em Aprovar prévia."
                )
                + watermark_note
            )
        else:
            self.status.setText(f"Exportação concluída: {destination}")
            if completed_job.suggestion:
                self.suggestion_saved.emit(completed_job.suggestion)
        self._finish_current()

    def _render_failed(self, message: str) -> None:
        assert self.current_job is not None
        self.current_job.status = "cancelled" if "cancelad" in message.lower() else "failed"
        self._persist_status(self.current_job)
        self.status.setText("Tarefa cancelada." if self.current_job.status == "cancelled" else f"Falha: {message}")
        self._finish_current()

    def _finish_current(self) -> None:
        self.current_worker = None
        self.current_job = None
        self.cancel_button.setEnabled(False)
        self._refresh_queue_table()
        QTimer.singleShot(0, self._start_next)

    def cancel_current(self) -> None:
        if self.current_worker:
            self.current_worker.cancel()
            self.cancel_button.setEnabled(False)
            self.status.setText("Cancelando renderização…")

    def _settings_edited(self) -> None:
        width, height = self.resolution.currentData()
        self.settings = ExportSettings(
            width=width, height=height, fps=self.fps.value(), codec=self.codec.currentData(),
            quality=self.quality.value(), use_nvenc=self.nvenc.isChecked(),
            normalize_audio=self.normalize.isChecked(),
            watermark=WatermarkSettings(
                enabled=self.watermark_enabled.isChecked() and bool(self.watermark_path.text()),
                image_path=Path(self.watermark_path.text()) if self.watermark_path.text() else None,
                position=self.watermark_position.currentData(),
                width_percent=self.watermark_width.value(),
                opacity=self.watermark_opacity.value(),
                margin_percent=self.watermark_margin.value(),
                custom_x_percent=self.watermark_x.value(),
                custom_y_percent=self.watermark_y.value(),
            ),
        )
        self.settings_changed.emit(self.settings)
        self._invalidate_preview()

    def _load_settings(self, settings: ExportSettings) -> None:
        widgets = (
            self.resolution, self.codec, self.fps, self.quality, self.nvenc, self.normalize,
            self.watermark_enabled, self.watermark_position, self.watermark_width,
            self.watermark_opacity, self.watermark_margin, self.watermark_x, self.watermark_y,
        )
        for widget in widgets:
            widget.blockSignals(True)
        self.resolution.setCurrentIndex(max(0, self.resolution.findData((settings.width, settings.height))))
        self.codec.setCurrentIndex(max(0, self.codec.findData(settings.codec)))
        self.fps.setValue(settings.fps)
        self.quality.setValue(settings.quality)
        self.nvenc.setChecked(settings.use_nvenc)
        self.normalize.setChecked(settings.normalize_audio)
        watermark = settings.watermark
        self.watermark_path.setText(str(watermark.image_path) if watermark.image_path else "")
        self.watermark_enabled.setEnabled(watermark.image_path is not None)
        self.watermark_enabled.setChecked(watermark.enabled and watermark.image_path is not None)
        self.watermark_position.setCurrentIndex(
            max(0, self.watermark_position.findData(watermark.position))
        )
        self.watermark_width.setValue(round(watermark.width_percent))
        self.watermark_opacity.setValue(watermark.opacity)
        self.watermark_margin.setValue(watermark.margin_percent)
        self.watermark_x.setValue(watermark.custom_x_percent)
        self.watermark_y.setValue(watermark.custom_y_percent)
        for widget in widgets:
            widget.blockSignals(False)
        active = self.watermark_enabled.isChecked()
        for widget in (
            self.watermark_position, self.watermark_width,
            self.watermark_opacity, self.watermark_margin,
        ):
            widget.setEnabled(active)
        custom = active and watermark.position == "custom"
        self.watermark_x.setEnabled(custom)
        self.watermark_y.setEnabled(custom)
        self._sync_watermark_overlay()

    def _refresh_review_subtitles(self) -> None:
        start_ms = round(self.start_seconds.value() * 1000)
        end_ms = round(self.end_seconds.value() * 1000)
        self.review_cue_indexes = [
            index
            for index, cue in enumerate(self.cues)
            if cue.end_ms > start_ms and cue.start_ms < end_ms
        ]
        self._editing_cues = True
        self.review_subtitles.setRowCount(len(self.review_cue_indexes))
        for row, cue_index in enumerate(self.review_cue_indexes):
            cue = self.cues[cue_index]
            for column, value in enumerate(
                (
                    format_timestamp(cue.start_ms, include_millis=True),
                    format_timestamp(cue.end_ms, include_millis=True),
                    cue.text,
                )
            ):
                item = QTableWidgetItem(value)
                if column != 2:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.review_subtitles.setItem(row, column, item)
        self._editing_cues = False

    def _review_subtitle_edited(self, item: QTableWidgetItem) -> None:
        if self._editing_cues or item.column() != 2:
            return
        row = item.row()
        if not 0 <= row < len(self.review_cue_indexes):
            return
        cue_index = self.review_cue_indexes[row]
        self.cues[cue_index] = self.cues[cue_index].model_copy(
            update={"text": item.text().strip(), "manually_edited": True}
        )
        self.cues_changed.emit(list(self.cues))
        self._invalidate_preview()
        self.status.setText("Legenda alterada. Gere uma nova prévia para validar a correção.")

    def toggle_review_playback(self) -> None:
        if not self.review_player.source().isLocalFile():
            return
        if self.review_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.review_player.pause()
            return
        if self.review_end_ms is not None and self.review_player.position() >= self.review_end_ms:
            self.review_player.setPosition(self.review_start_ms)
        self.review_player.play()

    def request_reframe_edit(self) -> None:
        clip = self._selected_clip()
        if clip:
            self.reframe_edit_requested.emit(clip)

    def _load_review_media(
        self,
        path: Path | None,
        start_ms: int,
        end_ms: int | None,
        *,
        baked: bool,
    ) -> None:
        self.review_start_ms = start_ms
        self.review_end_ms = end_ms
        self._pending_review_seek_ms = start_ms
        if not path or not path.is_file():
            self.review_player.stop()
            self.review_player.setSource(QUrl())
            self.play_review_button.setEnabled(False)
            self.watermark_overlay.hide()
            return
        current = (
            Path(self.review_player.source().toLocalFile())
            if self.review_player.source().isLocalFile()
            else None
        )
        resolved = path.resolve()
        if current != resolved:
            self.review_player.stop()
            self.review_player.setSource(QUrl.fromLocalFile(str(resolved)))
        else:
            self.review_player.setPosition(start_ms)
        self.play_review_button.setEnabled(True)
        if baked:
            self.watermark_overlay.hide()
        else:
            self._sync_watermark_overlay()

    def _review_media_status_changed(self, status: QMediaPlayer.MediaStatus) -> None:
        if status not in (
            QMediaPlayer.MediaStatus.LoadedMedia,
            QMediaPlayer.MediaStatus.BufferedMedia,
        ):
            return
        if self._pending_review_seek_ms is not None:
            self.review_player.setPosition(self._pending_review_seek_ms)
            self._pending_review_seek_ms = None

    def _review_position_changed(self, position: int) -> None:
        if self.review_end_ms is not None and position >= self.review_end_ms:
            self.review_player.pause()
            self.review_player.setPosition(self.review_start_ms)

    def _review_playback_changed(self, state: QMediaPlayer.PlaybackState) -> None:
        self.play_review_button.setText(
            "Pausar corte"
            if state == QMediaPlayer.PlaybackState.PlayingState
            else "Reproduzir corte"
        )

    def _range_edited(self) -> None:
        self._refresh_review_subtitles()
        self._invalidate_preview()

    @staticmethod
    def _safe_title(title: str) -> str:
        safe = "".join(
            character if character.isalnum() or character in " -_" else "_"
            for character in title
        ).strip()
        return safe or "corte"

    @staticmethod
    def _available_destination(destination: Path) -> Path:
        if not destination.exists():
            return destination
        for suffix in range(2, 10_000):
            candidate = destination.with_name(f"{destination.stem} ({suffix}){destination.suffix}")
            if not candidate.exists():
                return candidate
        raise RuntimeError("Não foi possível criar um nome livre para o corte.")

    def _selected_clip(self) -> ClipRange | None:
        try:
            if self.timeline_mode.isChecked() and self.timeline_clips:
                duration_ms = max(item.timeline_end_ms for item in self.timeline_clips)
                return ClipRange(start_ms=0, end_ms=duration_ms)
            return ClipRange(
                start_ms=round(self.start_seconds.value() * 1000),
                end_ms=round(self.end_seconds.value() * 1000),
            )
        except ValueError as exc:
            QMessageBox.warning(self, "Intervalo inválido", str(exc))
            return None

    def _timeline_mode_changed(self) -> None:
        active = self.timeline_mode.isChecked()
        self.start_seconds.setEnabled(not active)
        self.end_seconds.setEnabled(not active)
        self._invalidate_preview()

    def _invalidate_preview(self) -> None:
        self.preview_approved = False
        self.preview_path = None
        self.open_preview_button.setEnabled(False)
        self.approve_button.setEnabled(
            bool(self.review_suggestion and self.source_path)
        )
        self.batch_button.setEnabled(False)
        clip = self._selected_clip()
        if self.review_suggestion and self.review_reference_preview:
            self._load_review_media(self.review_reference_preview, 0, None, baked=False)
        else:
            self._load_review_media(
                self.source_path,
                clip.start_ms if clip else 0,
                clip.end_ms if clip else None,
                baked=False,
            )

    def _refresh_queue_table(self, current_percentage: int = 0) -> None:
        self.queue_table.setRowCount(len(self.jobs))
        for row, job in enumerate(self.jobs):
            values = (
                str(job.destination),
                f"{job.clip.start_ms / 1000:.1f}s–{job.clip.end_ms / 1000:.1f}s",
                "Prévia" if job.preview else "Final",
                job.status,
                f"{current_percentage}%" if job is self.current_job else ("100%" if job.status == "completed" else "—"),
            )
            for column, value in enumerate(values):
                self.queue_table.setItem(row, column, QTableWidgetItem(value))

    def _persist_job(self, job: ExportJob) -> int | None:
        config = AppConfig()
        try:
            connection = initialize_database(config.data_dir / "cortaflow.db")
            try:
                return enqueue_task(
                    connection,
                    "export_preview" if job.preview else "export_final",
                    {
                        "source": str(self.source_path) if self.source_path else None,
                        "destination": str(job.destination.resolve()),
                        "clip": job.clip.model_dump(mode="json"),
                        "settings": job.settings.model_dump(mode="json"),
                        "use_timeline": job.use_timeline,
                    },
                )
            finally:
                connection.close()
        except (OSError, sqlite3.Error, ValueError) as exc:
            LOGGER.warning("Não foi possível registrar a tarefa local: %s", type(exc).__name__)
            return None

    @staticmethod
    def _persist_status(job: ExportJob) -> None:
        if job.database_id is None:
            return
        config = AppConfig()
        try:
            connection = initialize_database(config.data_dir / "cortaflow.db")
            try:
                update_task_status(connection, job.database_id, job.status)
            finally:
                connection.close()
        except (OSError, sqlite3.Error, ValueError) as exc:
            LOGGER.warning("Não foi possível atualizar a tarefa local: %s", type(exc).__name__)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt virtual method
        self.review_player.stop()
        self.review_player.setSource(QUrl())
        self.review_player.setVideoOutput(None)
        self.review_player.setAudioOutput(None)
        super().closeEvent(event)
