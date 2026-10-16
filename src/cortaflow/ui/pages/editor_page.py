"""Basic, responsive player/editor page."""
import json
from uuid import uuid4

from pathlib import Path

from PySide6.QtCore import QThreadPool, QUrl, Qt, Signal
from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut, QUndoCommand, QUndoStack
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QInputDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSlider,
    QStackedLayout,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from cortaflow.domain.clip import ClipRange, format_timestamp
from cortaflow.domain.editing import LayerItem, SequenceDocument, TimelineClip, TransformKeyframe
from cortaflow.domain.project import ReframeKeyframe
from cortaflow.domain.tracking import CropFrame
from cortaflow.services.editor_operations import (
    move_clip,
    ripple_delete,
    set_transition,
    snap_position,
    split_at,
    trim_clip,
    update_clip_properties,
)
from cortaflow.services.media_previews import build_media_preview_data
from cortaflow.services.sequence_operations import create_image_layer, create_text_layer, update_layer
from cortaflow.services.transcoder import export_clip
from cortaflow.ui.widgets.timeline import TimelineWidget
from cortaflow.ui.widgets.reframe_overlay import ReframeOverlay
from cortaflow.ui.widgets.properties_panel import PropertiesPanel
from cortaflow.ui.widgets.layer_overlay import LayerOverlay
from cortaflow.ui.widgets.editor_chrome import EditorResourcePanel, EditorSectionHeader
from cortaflow.workers.base_worker import FunctionWorker


class TimelineStateCommand(QUndoCommand):
    def __init__(self, page: "EditorPage", before: list[TimelineClip], after: list[TimelineClip], text: str) -> None:
        super().__init__(text)
        self.page = page
        self.before = list(before)
        self.after = list(after)

    def undo(self) -> None:
        self.page._apply_timeline_clips(self.before)

    def redo(self) -> None:
        self.page._apply_timeline_clips(self.after)


class LayerStateCommand(QUndoCommand):
    def __init__(self, page: "EditorPage", before: list[LayerItem], after: list[LayerItem], text: str) -> None:
        super().__init__(text)
        self.page = page
        self.before = list(before)
        self.after = list(after)

    def undo(self) -> None:
        self.page._apply_layers(self.before)

    def redo(self) -> None:
        self.page._apply_layers(self.after)


class EditorPage(QWidget):
    timeline_changed = Signal(object)
    layers_changed = Signal(object)
    sequence_changed = Signal(object)
    sequence_export_requested = Signal()
    media_import_requested = Signal()
    settings_changed = Signal(object)
    reframe_keyframes_changed = Signal(object)
    automatic_requested = Signal()
    def __init__(self) -> None:
        super().__init__()
        self.source_path: Path | None = None
        self.in_ms: int | None = None
        self.out_ms: int | None = None
        self.fps = 25.0
        self.source_width = 0
        self.source_height = 0
        self.source_duration_ms = 0
        self.timeline_position_ms = 0
        self.active_video_clip_id: str | None = None
        self.user_playback_rate = 1.0
        self.timeline_clips: list[TimelineClip] = []
        self.layers: list[LayerItem] = []
        self.sequence: SequenceDocument | None = None
        self.selected_clip_id: str | None = None
        self.selected_clip_ids: set[str] = set()
        self.selected_layer_id: str | None = None
        self.reframe_keyframes: list[ReframeKeyframe] = []
        self.undo_stack = QUndoStack(self)
        self.export_worker: FunctionWorker | None = None
        self.preview_worker: FunctionWorker | None = None
        self.thread_pool = QThreadPool.globalInstance()

        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.video = QVideoWidget(self)
        self.player.setAudioOutput(self.audio)
        self.player.setVideoOutput(self.video)
        self.audio.setVolume(0.8)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(8, 8, 8, 8)
        root_layout.setSpacing(6)

        top_workspace = QWidget()
        top_layout = QHBoxLayout(top_workspace)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(6)
        root_layout.addWidget(top_workspace, 3)

        self.resources = EditorResourcePanel()
        self.resources.resource_requested.connect(self._handle_resource_request)
        self.resources.import_requested.connect(self.media_import_requested)
        top_layout.addWidget(self.resources)

        editor_body = QWidget()
        editor_body.setObjectName("editorWorkspace")
        layout = QVBoxLayout(editor_body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        top_layout.addWidget(editor_body, 1)

        header = QFrame()
        header.setObjectName("editorHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(14, 10, 14, 10)
        header_layout.setSpacing(8)
        header_layout.addWidget(EditorSectionHeader("Editor completo", "Workspace profissional · sequência não destrutiva"))
        header_layout.addStretch(1)
        self.sequence_badge = QLabel("RASCUNHO")
        self.sequence_badge.setObjectName("editorStatusBadge")
        header_layout.addWidget(self.sequence_badge)
        self.undo_button = self._control_button("↶", self.undo_stack.undo)
        self.undo_button.setObjectName("editorIconButton")
        self.undo_button.setToolTip("Desfazer (Ctrl+Z)")
        header_layout.addWidget(self.undo_button)
        self.redo_button = self._control_button("↷", self.undo_stack.redo)
        self.redo_button.setObjectName("editorIconButton")
        self.redo_button.setToolTip("Refazer (Ctrl+Shift+Z)")
        header_layout.addWidget(self.redo_button)
        # Keep the status widgets alive for state updates without spending canvas height.
        layout.addWidget(header)
        header.hide()

        # Contextual action strip: the main editor should expose the common
        # operations without forcing the user to hunt through the inspector.
        action_strip = QFrame()
        action_strip.setObjectName("editorActionStrip")
        action_layout = QHBoxLayout(action_strip)
        action_layout.setContentsMargins(8, 6, 8, 6)
        action_layout.setSpacing(5)
        action_layout.addWidget(QLabel("ADICIONAR"))
        self.quick_media_button = self._quick_action("Mídia", self.media_import_requested)
        self.quick_text_button = self._quick_action("Texto", self.add_text_layer)
        self.quick_image_button = self._quick_action("Imagem", self.add_image_layer)
        self.quick_split_button = self._quick_action("Dividir", self.split_at_cursor)
        self.quick_delete_button = self._quick_action("Excluir", self.delete_selected_clip)
        for button in (self.quick_media_button, self.quick_text_button, self.quick_image_button,
                       self.quick_split_button, self.quick_delete_button):
            action_layout.addWidget(button)
        action_layout.addSpacing(8)
        self.selection_label = QLabel("Nenhuma seleção")
        self.selection_label.setObjectName("editorSelectionLabel")
        action_layout.addWidget(self.selection_label)
        action_layout.addStretch(1)
        self.snap_button = QToolButton()
        self.snap_button.setText("↔ Encaixe")
        self.snap_button.setCheckable(True)
        self.snap_button.setChecked(True)
        self.snap_button.setToolTip("Atrair clipes para cortes e marcadores próximos")
        action_layout.addWidget(self.snap_button)
        layout.addWidget(action_strip)

        self.video_container = QWidget()
        self.video_container.setObjectName("previewSurface")
        video_stack = QStackedLayout(self.video_container)
        video_stack.setStackingMode(QStackedLayout.StackingMode.StackAll)
        video_stack.addWidget(self.video)
        self.reframe_overlay = ReframeOverlay()
        video_stack.addWidget(self.reframe_overlay)
        self.layer_overlay = LayerOverlay()
        self.layer_overlay.layer_selected.connect(self._select_layer)
        self.layer_overlay.layer_moved.connect(self._move_layer)
        video_stack.addWidget(self.layer_overlay)
        preview_header = QFrame()
        preview_header.setObjectName("previewHeader")
        preview_header_layout = QHBoxLayout(preview_header)
        preview_header_layout.setContentsMargins(12, 6, 12, 6)
        preview_header_layout.addWidget(QLabel("PREVIEW"))
        preview_header_layout.addStretch(1)
        self.preview_format_label = QLabel("Formato original")
        self.preview_format_label.setObjectName("previewMeta")
        preview_header_layout.addWidget(self.preview_format_label)
        self.preview_aspect = QComboBox()
        self.preview_aspect.addItems(["9:16", "16:9", "1:1", "4:5", "original"])
        self.preview_aspect.setToolTip("Formato do vídeo exportado")
        preview_header_layout.addWidget(QLabel("Formato"))
        preview_header_layout.addWidget(self.preview_aspect)
        layout.addWidget(preview_header)
        layout.addWidget(self.video_container, 1)

        transport_header = QFrame()
        transport_header.setObjectName("transportHeader")
        transport_header_layout = QHBoxLayout(transport_header)
        transport_header_layout.setContentsMargins(10, 4, 10, 4)
        transport_header_layout.addWidget(QLabel("CONTROLE DE REPRODUÇÃO"))
        transport_header_layout.addStretch(1)
        transport_header_layout.addWidget(QLabel("Espaço: reproduzir · I/O: entrada e saída · S: dividir"))
        layout.addWidget(transport_header)

        controls = QHBoxLayout()
        self.previous_frame_button = self._control_button("◀ Quadro", self._previous_frame)
        self.back_button = self._control_button("−5 s", lambda: self._jump(-5000))
        controls.addWidget(self.previous_frame_button)
        controls.addWidget(self.back_button)
        self.play_button = self._control_button("Reproduzir", self.toggle_playback)
        controls.addWidget(self.play_button)
        self.forward_button = self._control_button("+5 s", lambda: self._jump(5000))
        self.next_frame_button = self._control_button("Quadro ▶", self._next_frame)
        controls.addWidget(self.forward_button)
        controls.addWidget(self.next_frame_button)
        self.time_label = QLabel("00:00:00 / 00:00:00")
        controls.addWidget(self.time_label)

        self.rate = QComboBox()
        for label, value in (("0,5×", 0.5), ("1×", 1.0), ("1,5×", 1.5), ("2×", 2.0)):
            self.rate.addItem(label, value)
        self.rate.setCurrentIndex(1)
        self.rate.currentIndexChanged.connect(self._set_playback_rate)
        controls.addWidget(self.rate)

        self.mute_button = QPushButton("Mudo")
        self.mute_button.setCheckable(True)
        self.mute_button.toggled.connect(self.audio.setMuted)
        controls.addWidget(self.mute_button)
        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setValue(80)
        self.volume.setMaximumWidth(120)
        self.volume.valueChanged.connect(lambda value: self.audio.setVolume(value / 100))
        controls.addWidget(self.volume)
        self.fullscreen_button = self._control_button("Tela cheia", self.toggle_fullscreen)
        controls.addWidget(self.fullscreen_button)
        layout.addLayout(controls)

        marker_row = QHBoxLayout()
        self.mark_in_button = self._control_button("Entrada (I)", self.mark_in)
        self.mark_out_button = self._control_button("Saída (O)", self.mark_out)
        self.export_button = self._control_button("Exportar", self.export_selection)
        self.preview_button = self._control_button("Prévia vertical", self.sequence_export_requested.emit)
        self.preview_button.setToolTip("Abrir a prévia composta com legendas, camadas e reenquadramento")
        self.add_text_button = self._control_button("+ Texto", self.add_text_layer)
        self.add_image_button = self._control_button("+ Imagem", self.add_image_layer)
        self.delete_layer_button = self._control_button("Excluir", self.delete_selected_layer)
        self.delete_layer_button.setEnabled(False)
        self.duplicate_button = self._control_button("Duplicar", self.duplicate_selected_clips)
        self.cancel_export_button = self._control_button("Cancelar", self.cancel_export)
        self.cancel_export_button.setEnabled(False)
        marker_row.addWidget(self.mark_in_button)
        marker_row.addWidget(self.mark_out_button)
        marker_row.addWidget(self.export_button)
        marker_row.addWidget(self.preview_button)
        marker_row.addWidget(self.add_text_button)
        marker_row.addWidget(self.add_image_button)
        marker_row.addWidget(self.delete_layer_button)
        marker_row.addWidget(self.duplicate_button)
        marker_row.addWidget(self.cancel_export_button)
        marker_row.addStretch()
        layout.addLayout(marker_row)

        self.export_progress = QProgressBar()
        self.export_progress.setRange(0, 0)
        self.export_progress.hide()
        layout.addWidget(self.export_progress)
        self.status_label = QLabel("")
        layout.addWidget(self.status_label)
        timeline_header = QFrame()
        timeline_header.setObjectName("timelineHeader")
        timeline_header_layout = QHBoxLayout(timeline_header)
        timeline_header_layout.setContentsMargins(10, 6, 10, 6)
        timeline_header_layout.addWidget(QLabel("TIMELINE MULTIPISTA"))
        timeline_header_layout.addStretch(1)
        self.timeline_mode_label = QLabel("Vídeo · Áudio · Legendas · Cenas · IA")
        self.timeline_mode_label.setObjectName("previewMeta")
        timeline_header_layout.addWidget(self.timeline_mode_label)
        self.timeline = TimelineWidget()
        self.timeline.setObjectName("editorTimeline")
        self.timeline.seek_requested.connect(self._seek_timeline)
        self.timeline.clip_selected.connect(self._select_clip)
        self.timeline.layer_selected.connect(self._select_layer)
        self.timeline.selection_changed.connect(self._selection_changed)
        self.timeline.clip_move_requested.connect(self.move_selected_clip)
        self.timeline.clip_trim_requested.connect(self.trim_selected_clip)

        inspector_header = QFrame()
        inspector_header.setObjectName("inspectorHeader")
        inspector_header_layout = QVBoxLayout(inspector_header)
        inspector_header_layout.setContentsMargins(0, 12, 0, 4)
        inspector_header_layout.addWidget(QLabel("INSPECTOR"))
        inspector_hint = QLabel("Selecione um clipe ou camada para editar")
        inspector_hint.setObjectName("previewMeta")
        inspector_header_layout.addWidget(inspector_hint)

        self.properties = PropertiesPanel()
        self.properties.setObjectName("editorInspector")
        self.preview_aspect.currentTextChanged.connect(self.properties.aspect.setCurrentText)
        self.properties.aspect.currentTextChanged.connect(self.preview_aspect.setCurrentText)
        self.properties.settings_changed.connect(self._properties_changed)
        self.properties.clip_update_requested.connect(self._update_clip_properties)
        self.properties.manual_keyframe_requested.connect(self.add_manual_keyframe)
        self.properties.layer_keyframe_requested.connect(self.add_layer_keyframe)
        self.properties.layer_update_requested.connect(self._update_layer_properties)
        properties_column = QWidget()
        properties_column.setObjectName("propertiesColumn")
        properties_layout = QVBoxLayout(properties_column)
        properties_layout.setContentsMargins(0, 0, 0, 0)
        properties_layout.setSpacing(4)
        properties_layout.addWidget(inspector_header)
        properties_layout.addWidget(self.properties, 1)
        properties_column.setMinimumWidth(340)
        properties_column.setMaximumWidth(420)
        top_layout.addWidget(properties_column)

        timeline_workspace = QFrame()
        timeline_workspace.setObjectName("timelineWorkspace")
        timeline_layout = QVBoxLayout(timeline_workspace)
        timeline_layout.setContentsMargins(8, 6, 8, 6)
        timeline_layout.setSpacing(4)
        timeline_layout.addWidget(timeline_header)
        timeline_layout.addWidget(self.timeline, 1)
        root_layout.addWidget(timeline_workspace, 2)

        self.undo_stack.canUndoChanged.connect(self.undo_button.setEnabled)
        self.undo_stack.canRedoChanged.connect(self.redo_button.setEnabled)
        self.undo_button.setEnabled(False)
        self.redo_button.setEnabled(False)

        self.player.durationChanged.connect(self._duration_changed)
        self.player.positionChanged.connect(self._position_changed)
        self.player.playbackStateChanged.connect(self._playback_state_changed)
        self.player.errorOccurred.connect(self._playback_error)
        self.video.fullScreenChanged.connect(
            lambda active: self.fullscreen_button.setText("Sair da tela cheia" if active else "Tela cheia")
        )
        self._create_shortcuts()
        self.layer_overlay.raise_()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt virtual method
        """Release native multimedia objects before their video widget disappears."""
        if self.preview_worker is not None:
            self.preview_worker.cancel()
            self.preview_worker = None
        self.player.stop()
        self.player.setSource(QUrl())
        self.player.setVideoOutput(None)
        self.player.setAudioOutput(None)
        super().closeEvent(event)

    def _handle_resource_request(self, resource: str) -> None:
        """Route the professional resource browser to current editor capabilities."""
        handlers = {
            "text": self.add_text_layer,
            "image": self.add_image_layer,
            "ai": self.automatic_requested.emit,
        }
        handler = handlers.get(resource)
        if handler is not None:
            handler()
            return
        messages = {
            "media": "Mídia selecionada. Escolha o clipe na timeline para editar o corte no inspetor.",
            "audio": "Áudio selecionado: adicione música ou ajuste o áudio original no inspector.",
            "captions": "Legendas selecionadas: transcreva ou revise o texto na página Legendas.",
            "effects": "Efeitos selecionados: escolha uma categoria e aplique o efeito à camada na próxima etapa.",
            "transitions": "Transições selecionadas: arraste uma transição entre dois clipes na timeline.",
            "filters": "Filtros selecionados: os ajustes serão aplicados ao clipe selecionado.",
            "stickers": "Stickers selecionados: a biblioteca de elementos será integrada à sequência.",
            "templates": "Modelos selecionados: escolha um preset para iniciar uma sequência.",
            "ai": "IA selecionada: use Gerar cortes sugeridos para análise automática da mídia.",
        }
        self.status_label.setText(messages.get(resource, "Recurso selecionado."))

    def _properties_changed(self, settings: object) -> None:
        reframe, subtitle, audio, export = settings
        self.audio.setVolume(min(1.0, audio.volume / 2))
        self.reframe_overlay.set_settings(reframe)
        self._update_preview_format(reframe, export)
        self.settings_changed.emit((reframe, subtitle, audio, export))

    @staticmethod
    def _control_button(text: str, handler: object) -> QPushButton:
        button = QPushButton(text)
        button.clicked.connect(handler)
        return button

    @staticmethod
    def _quick_action(text: str, handler: object) -> QToolButton:
        button = QToolButton()
        button.setText(text)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(handler)
        button.setObjectName("editorQuickAction")
        return button

    def _create_shortcuts(self) -> None:
        bindings = (
            ("Space", self.toggle_playback),
            ("Left", self._previous_frame),
            ("Right", self._next_frame),
            ("Shift+Left", lambda: self._jump(-5000)),
            ("Shift+Right", lambda: self._jump(5000)),
            ("I", self.mark_in),
            ("O", self.mark_out),
            ("F11", self.toggle_fullscreen),
            ("S", self.split_at_cursor),
            ("Delete", self.delete_selected_clip),
            ("Ctrl+C", self.copy_selected_clips),
            ("Ctrl+V", self.paste_clips),
            ("Ctrl+D", self.duplicate_selected_clips),
            ("Ctrl+Z", self.undo_stack.undo),
            ("Ctrl+Shift+Z", self.undo_stack.redo),
        )
        self.shortcuts: list[QShortcut] = []
        for sequence, handler in bindings:
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(handler)
            self.shortcuts.append(shortcut)

    def load_media(
        self,
        path: Path,
        fps: float | None = None,
        width: int | None = None,
        height: int | None = None,
    ) -> None:
        self.source_path = path.resolve()
        self.resources.set_media(self.source_path)
        self.source_duration_ms = 0
        self.timeline_position_ms = 0
        self.active_video_clip_id = None
        self.in_ms = 0
        self.out_ms = None
        self.fps = fps if fps and fps > 0 else 25.0
        self.source_width = width or 0
        self.source_height = height or 0
        self.timeline.set_markers(self.in_ms, self.out_ms)
        self.reframe_overlay.set_source_size(width, height)
        self.status_label.setText(f"Mídia carregada · {self.fps:.3g} FPS")
        self.player.setSource(QUrl.fromLocalFile(str(self.source_path)))

    def set_selection(self, start_ms: int, end_ms: int) -> None:
        """Load an externally suggested range into the basic editor."""
        if end_ms <= start_ms:
            raise ValueError("O fim do corte deve ser posterior ao início.")
        self.in_ms = max(0, start_ms)
        self.out_ms = end_ms
        self._seek_timeline(self.in_ms)
        self._update_markers()

    def set_reframe_data(
        self,
        tracks,
        keyframes,
        selected_track_id: int | None,
        speaker_keyframes=None,
    ) -> None:
        self.reframe_keyframes = list(keyframes)
        self.reframe_overlay.set_data(
            tracks,
            keyframes,
            selected_track_id,
            speaker_keyframes,
        )
        self.timeline.canvas.track_items["reframe"] = list(keyframes)
        self.timeline.canvas.update()

    def set_project_editor_state(
        self,
        timeline_clips,
        transcript,
        scenes,
        suggestions,
        reframe_keyframes,
        reframe_settings,
        subtitle_style,
        audio_settings,
        export_settings,
        layers=None,
        sequence=None,
    ) -> None:
        self.timeline_clips = list(timeline_clips)
        selected_clip = next((item for item in self.timeline_clips if item.track == "video"), None)
        self.selected_clip_id = selected_clip.clip_id if selected_clip else None
        self.selected_clip_ids = {self.selected_clip_id} if self.selected_clip_id else set()
        self._update_selection_label()
        self.layers = list(layers or [])
        self.sequence = sequence
        self.selected_layer_id = None
        self.sequence_badge.setText("SEQUÊNCIA ATIVA" if sequence is not None else "RASCUNHO")
        self.reframe_keyframes = list(reframe_keyframes)
        cues = transcript.cues if transcript else []
        words = transcript.words if transcript else []
        self.layer_overlay.set_layers(self.layers)
        self.layer_overlay.set_position(self.timeline_position_ms)
        self.properties.set_selected_layer(None)
        self.properties.tabs.setCurrentIndex(0)
        self.delete_layer_button.setEnabled(False)
        self.timeline.set_track_data(
            self.timeline_clips,
            transcript=words,
            subtitles=cues,
            scenes=scenes,
            suggestions=suggestions,
            reframe=reframe_keyframes,
            layers=self.layers,
        )
        self.timeline.select_clips(sorted(self.selected_clip_ids))
        self.properties.set_selected_clip(selected_clip)
        self.properties.set_settings(
            reframe_settings,
            subtitle_style,
            audio_settings,
            export_settings,
        )
        self.reframe_overlay.set_settings(reframe_settings)
        self.preview_aspect.setCurrentText(reframe_settings.aspect_ratio)
        self._update_preview_format(reframe_settings, export_settings)
        self.timeline.select_layer(None)
        self._sync_timeline_duration()
        self._seek_timeline(min(self.timeline_position_ms, self.timeline.canvas.duration_ms))
        self.undo_stack.clear()

    def split_at_cursor(self) -> None:
        try:
            updated = split_at(self.timeline_clips, self.timeline_position_ms)
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self.undo_stack.push(TimelineStateCommand(self, self.timeline_clips, updated, "Dividir clipe"))

    def delete_selected_clip(self) -> None:
        clip_ids = set(self.selected_clip_ids)
        if not clip_ids and self.selected_clip_id:
            clip_ids.add(self.selected_clip_id)
        if not clip_ids:
            return
        linked_ranges = {
            (clip.timeline_start_ms, clip.timeline_end_ms)
            for clip in self.timeline_clips
            if clip.clip_id in clip_ids
        }
        clip_ids.update(
            clip.clip_id
            for clip in self.timeline_clips
            if (clip.timeline_start_ms, clip.timeline_end_ms) in linked_ranges
        )
        try:
            updated = ripple_delete(self.timeline_clips, clip_ids)
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self.undo_stack.push(TimelineStateCommand(self, self.timeline_clips, updated, "Excluir com ripple"))
        self.selected_clip_id = None
        self.selected_clip_ids.clear()
        self.properties.set_selected_clip(None)

    def _selected_clip_items(self) -> list[TimelineClip]:
        ids = set(self.selected_clip_ids)
        if not ids and self.selected_clip_id:
            ids.add(self.selected_clip_id)
        return [clip for clip in self.timeline_clips if clip.clip_id in ids]

    def copy_selected_clips(self) -> None:
        selected = self._selected_clip_items()
        if not selected:
            return
        anchor = min(item.timeline_start_ms for item in selected)
        payload = []
        for item in selected:
            data = item.model_dump(mode="json")
            data["timeline_start_ms"] = item.timeline_start_ms - anchor
            payload.append(data)
        QGuiApplication.clipboard().setText(json.dumps({"cortaflow_clips": payload}, ensure_ascii=False))
        self.status_label.setText(f"{len(selected)} clipe(s) copiado(s).")

    def paste_clips(self) -> None:
        try:
            payload = json.loads(QGuiApplication.clipboard().text())
            raw_clips = payload["cortaflow_clips"]
            pasted = []
            for raw in raw_clips:
                raw["clip_id"] = f"paste-{uuid4().hex[:12]}"
                raw["timeline_start_ms"] = self.timeline_position_ms + int(raw["timeline_start_ms"])
                pasted.append(TimelineClip.model_validate(raw))
        except (ValueError, TypeError, KeyError, json.JSONDecodeError):
            self.status_label.setText("A área de transferência não contém clipes do CortaFlow.")
            return
        updated = self.timeline_clips + pasted
        self.undo_stack.push(TimelineStateCommand(self, self.timeline_clips, updated, "Colar clipes"))
        self.selected_clip_ids = {item.clip_id for item in pasted}
        self.selected_clip_id = pasted[-1].clip_id

    def duplicate_selected_clips(self) -> None:
        selected = self._selected_clip_items()
        if not selected:
            return
        offset = max(item.timeline_end_ms for item in selected) - min(item.timeline_start_ms for item in selected) + 100
        anchor = min(item.timeline_start_ms for item in selected)
        duplicates = [
            item.model_copy(
                update={
                    "clip_id": f"copy-{uuid4().hex[:12]}",
                    "timeline_start_ms": item.timeline_start_ms + offset,
                }
            )
            for item in selected
        ]
        updated = self.timeline_clips + duplicates
        self.undo_stack.push(TimelineStateCommand(self, self.timeline_clips, updated, "Duplicar clipes"))
        self.selected_clip_ids = {item.clip_id for item in duplicates}
        self.selected_clip_id = duplicates[-1].clip_id

    def move_selected_clip(self, clip_id: str, timeline_start_ms: int) -> None:
        try:
            timeline_start_ms = snap_position(self.timeline_clips, clip_id, timeline_start_ms)
            updated = move_clip(self.timeline_clips, clip_id, timeline_start_ms)
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        if updated != self.timeline_clips:
            self.undo_stack.push(TimelineStateCommand(self, self.timeline_clips, updated, "Mover clipe"))

    def trim_selected_clip(self, clip_id: str, side: str, position_ms: int) -> None:
        target = next((clip for clip in self.timeline_clips if clip.clip_id == clip_id), None)
        if target is None:
            return
        group = [
            clip for clip in self.timeline_clips
            if clip.track in {"video", "audio"}
            and clip.timeline_start_ms == target.timeline_start_ms
            and clip.timeline_end_ms == target.timeline_end_ms
        ] or [target]
        updated = list(self.timeline_clips)
        try:
            for clip in group:
                if side == "left":
                    source_start = clip.source_start_ms + (position_ms - clip.timeline_start_ms)
                    if source_start >= clip.source_end_ms - 250:
                        raise ValueError("O clipe precisa manter pelo menos 250 ms.")
                    updated = trim_clip(updated, clip.clip_id, source_start, clip.source_end_ms)
                else:
                    source_end = clip.source_start_ms + (position_ms - clip.timeline_start_ms)
                    if source_end <= clip.source_start_ms + 250:
                        raise ValueError("O clipe precisa manter pelo menos 250 ms.")
                    updated = trim_clip(updated, clip.clip_id, clip.source_start_ms, source_end)
        except (ValueError, TypeError) as exc:
            self.status_label.setText(str(exc))
            return
        if updated != self.timeline_clips:
            self.undo_stack.push(TimelineStateCommand(self, self.timeline_clips, updated, "Ajustar duração"))

    def _update_clip_properties(self, payload: dict) -> None:
        try:
            updated = move_clip(self.timeline_clips, payload["clip_id"], payload["timeline_start_ms"])
            updated = trim_clip(
                updated,
                payload["clip_id"],
                payload["source_start_ms"],
                payload["source_end_ms"],
            )
            updated = set_transition(updated, payload["clip_id"], payload["transition_ms"])
            updated = update_clip_properties(
                updated,
                payload["clip_id"],
                speed=payload["speed"],
                fade_in_ms=payload["fade_in_ms"],
                fade_out_ms=payload["fade_out_ms"],
                effect=payload["effect"],
            )
        except ValueError as exc:
            QMessageBox.warning(self, "Edição inválida", str(exc))
            return
        self.undo_stack.push(TimelineStateCommand(self, self.timeline_clips, updated, "Ajustar clipe"))

    def _select_clip(self, clip_id: str) -> None:
        self.selected_layer_id = None
        self.layer_overlay.select_layer(None)
        self.timeline.select_layer(None)
        self.delete_layer_button.setEnabled(False)
        self.selected_clip_id = clip_id if clip_id in self.selected_clip_ids else next(iter(self.selected_clip_ids), None)
        self.timeline.select_clips(sorted(self.selected_clip_ids))
        self.properties.set_selected_clip(
            next((clip for clip in self.timeline_clips if clip.clip_id == self.selected_clip_id), None)
        )
        self.properties.tabs.setCurrentIndex(0)
        self._update_selection_label()

    def _selection_changed(self, clip_ids: object) -> None:
        self.selected_clip_ids = {str(item) for item in clip_ids}
        if self.selected_clip_id not in self.selected_clip_ids:
            self.selected_clip_id = next(iter(self.selected_clip_ids), None)
        self.properties.set_selected_clip(
            next((clip for clip in self.timeline_clips if clip.clip_id == self.selected_clip_id), None)
        )
        if self.selected_clip_id:
            self.selected_layer_id = None
            self.layer_overlay.select_layer(None)
            self.timeline.select_layer(None)
            self.properties.set_selected_layer(None)
            self.properties.tabs.setCurrentIndex(0)
        self._update_selection_label()

    def _update_selection_label(self) -> None:
        count = len(self.selected_clip_ids)
        if not count:
            self.selection_label.setText("Nenhuma seleção")
            return
        duration = sum(
            max(0, clip.timeline_end_ms - clip.timeline_start_ms)
            for clip in self.timeline_clips
            if clip.clip_id in self.selected_clip_ids
        )
        self.selection_label.setText(f"{count} clipe(s) selecionado(s) · {format_timestamp(duration)}")

    def _apply_timeline_clips(self, clips: list[TimelineClip]) -> None:
        self.timeline_clips = list(clips)
        self.selected_clip_ids.intersection_update(item.clip_id for item in clips)
        if self.selected_clip_id not in self.selected_clip_ids:
            self.selected_clip_id = next(iter(self.selected_clip_ids), None)
        self.timeline.canvas.clips = list(clips)
        self.timeline.canvas.track_items["video"] = [item for item in clips if item.track == "video"]
        self.timeline.canvas.track_items["audio"] = [item for item in clips if item.track == "audio"]
        self.timeline.select_clips(sorted(self.selected_clip_ids))
        self._sync_timeline_duration()
        self.timeline.canvas.update()
        self._update_selection_label()
        if self.selected_clip_id:
            self.properties.set_selected_clip(
                next((clip for clip in clips if clip.clip_id == self.selected_clip_id), None)
            )
        if self.sequence is not None:
            self.sequence = self.sequence.model_copy(update={"clips": list(clips), "dirty": True})
            self.sequence_changed.emit(self.sequence)
        self.timeline_changed.emit(list(clips))
        self._seek_timeline(self.timeline_position_ms)

    def _apply_layers(self, layers: list[LayerItem]) -> None:
        self.layers = list(layers)
        self.layer_overlay.set_layers(self.layers)
        self.timeline.canvas.track_items["layers"] = list(self.layers)
        self._sync_timeline_duration()
        self.timeline.select_layer(self.selected_layer_id)
        selected = next((layer for layer in self.layers if layer.item_id == self.selected_layer_id), None)
        self.properties.set_selected_layer(selected)
        if self.sequence is not None:
            self.sequence = self.sequence.model_copy(update={"layers": list(layers), "dirty": True})
            self.sequence_changed.emit(self.sequence)
        self.layers_changed.emit(list(layers))
        self.layer_overlay.set_position(self.timeline_position_ms)

    def add_text_layer(self) -> None:
        text, accepted = QInputDialog.getText(self, "Adicionar texto", "Texto da camada:")
        if not accepted:
            return
        sequence = self.sequence or SequenceDocument(
            sequence_id="editor-draft", name="Rascunho", clips=list(self.timeline_clips)
        )
        layer = create_text_layer(sequence, text, start_ms=self._layer_start_position())
        self.sequence = sequence
        self.sequence_badge.setText("SEQUÊNCIA ATIVA")
        self.selected_layer_id = layer.item_id
        self._apply_layers(sequence.layers)
        self._select_layer(layer.item_id)

    def add_image_layer(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Adicionar imagem", "", "Imagens (*.png *.jpg *.jpeg *.webp *.svg)"
        )
        if not path:
            return
        sequence = self.sequence or SequenceDocument(
            sequence_id="editor-draft", name="Rascunho", clips=list(self.timeline_clips)
        )
        layer = create_image_layer(sequence, path, start_ms=self._layer_start_position())
        self.sequence = sequence
        self.selected_layer_id = layer.item_id
        self._apply_layers(sequence.layers)
        self._select_layer(layer.item_id)

    def _select_layer(self, item_id: str | None) -> None:
        self.selected_layer_id = item_id
        self.delete_layer_button.setEnabled(bool(item_id))
        self.layer_overlay.select_layer(item_id)
        self.timeline.select_layer(item_id)
        self.properties.set_selected_layer(
            next((layer for layer in self.layers if layer.item_id == item_id), None)
        )
        self.properties.tabs.setCurrentIndex(1 if item_id else 0)

    def _layer_start_position(self) -> int:
        clips = self._video_clips()
        current = next(
            (clip for clip in clips if clip.timeline_start_ms <= self.timeline_position_ms < clip.timeline_end_ms),
            None,
        )
        if current is not None:
            return self.timeline_position_ms
        previous = next(
            (clip for clip in reversed(clips) if clip.timeline_end_ms <= self.timeline_position_ms),
            None,
        )
        if previous is not None:
            return max(previous.timeline_start_ms, previous.timeline_end_ms - min(1000, previous.duration_ms))
        next_clip = next((clip for clip in clips if clip.timeline_start_ms > self.timeline_position_ms), None)
        return next_clip.timeline_start_ms if next_clip else 0

    def delete_selected_layer(self) -> None:
        if not self.selected_layer_id:
            self.status_label.setText("Selecione uma camada para excluir.")
            return
        updated = [layer for layer in self.layers if layer.item_id != self.selected_layer_id]
        self.undo_stack.push(LayerStateCommand(self, self.layers, updated, "Excluir camada"))
        self.selected_layer_id = None
        self.delete_layer_button.setEnabled(False)
        self.layer_overlay.select_layer(None)
        self.properties.set_selected_layer(None)

    def _move_layer(self, item_id: str, x_percent: float, y_percent: float) -> None:
        try:
            updated = update_layer(self.sequence or SequenceDocument(
                sequence_id="editor-draft", name="Rascunho", clips=list(self.timeline_clips), layers=self.layers
            ), item_id, x_percent=x_percent, y_percent=y_percent)
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        before = list(self.layers)
        self.undo_stack.push(LayerStateCommand(self, before, updated.layers, "Mover camada"))

    def _update_layer_properties(self, payload: dict) -> None:
        try:
            sequence = self.sequence or SequenceDocument(
                sequence_id="editor-draft", name="Rascunho", clips=list(self.timeline_clips), layers=self.layers
            )
            updated = update_layer(sequence, payload.pop("item_id"), **payload)
            self.sequence = updated
        except (ValueError, TypeError) as exc:
            QMessageBox.warning(self, "Camada inválida", str(exc))
            return
        self.undo_stack.push(LayerStateCommand(self, self.layers, updated.layers, "Editar camada"))

    def add_layer_keyframe(self) -> None:
        if not self.selected_layer_id:
            self.status_label.setText("Selecione uma camada para adicionar um keyframe.")
            return
        layer = next((item for item in self.layers if item.item_id == self.selected_layer_id), None)
        if layer is None:
            return
        timestamp = self.timeline_position_ms
        keyframe = TransformKeyframe(
            timestamp_ms=timestamp,
            x_percent=self.properties.layer_x.value(),
            y_percent=self.properties.layer_y.value(),
            opacity=self.properties.layer_opacity.value(),
        )
        keyframes = [item for item in layer.keyframes if item.timestamp_ms != timestamp]
        keyframes.append(keyframe)
        keyframes.sort(key=lambda item: item.timestamp_ms)
        sequence = self.sequence or SequenceDocument(
            sequence_id="editor-draft", name="Rascunho", clips=list(self.timeline_clips), layers=self.layers
        )
        updated = update_layer(sequence, layer.item_id, keyframes=keyframes)
        self.undo_stack.push(LayerStateCommand(self, self.layers, updated.layers, "Adicionar keyframe"))

    def add_manual_keyframe(self) -> None:
        if not self.source_width or not self.source_height:
            return
        settings = self.properties
        ratios = {"9:16": (9, 16), "16:9": (16, 9), "1:1": (1, 1), "4:5": (4, 5)}
        if settings.aspect.currentText() == "original":
            width, height = self.source_width, self.source_height
        else:
            aspect_w, aspect_h = ratios[settings.aspect.currentText()]
            width = min(self.source_width, round(self.source_height * aspect_w / aspect_h))
            height = min(self.source_height, round(width * aspect_h / aspect_w))
        width = min(self.source_width, max(1, round(width / settings.zoom.value())))
        height = min(self.source_height, max(1, round(height / settings.zoom.value())))
        x = min(max(0, settings.crop_x.value()), max(0, self.source_width - width))
        y = min(max(0, settings.crop_y.value()), max(0, self.source_height - height))
        timestamp = self.player.position()
        keyframe = ReframeKeyframe(
            timestamp_ms=timestamp,
            crop=CropFrame(x=x, y=y, width=width, height=height),
            manual=True,
        )
        self.reframe_keyframes = [item for item in self.reframe_keyframes if item.timestamp_ms != timestamp]
        self.reframe_keyframes.append(keyframe)
        self.reframe_keyframes.sort(key=lambda item: item.timestamp_ms)
        self.reframe_overlay.keyframes = list(self.reframe_keyframes)
        self.timeline.canvas.track_items["reframe"] = list(self.reframe_keyframes)
        self.timeline.canvas.update()
        self.reframe_keyframes_changed.emit(list(self.reframe_keyframes))

    @property
    def frame_duration_ms(self) -> int:
        return max(1, round(1000 / self.fps))

    def _video_clips(self) -> list[TimelineClip]:
        return sorted(
            (clip for clip in self.timeline_clips if clip.track == "video"),
            key=lambda clip: (clip.timeline_start_ms, clip.clip_id),
        )

    def _sync_timeline_duration(self) -> None:
        clips_end = max(
            (clip.timeline_end_ms for clip in self.timeline_clips), default=0
        )
        layers_end = max((layer.timeline_end_ms for layer in self.layers), default=0)
        duration = max(clips_end, layers_end, self.source_duration_ms if not clips_end else 0)
        self.timeline.set_duration(max(0, duration))
        self.layer_overlay.set_duration(max(1, duration))
        self.time_label.setText(
            f"{format_timestamp(self.timeline_position_ms)} / {format_timestamp(duration)}"
        )

    def _update_preview_format(self, reframe, export) -> None:
        short_edge, long_edge = sorted((export.width, export.height))
        dimensions = {
            "9:16": (short_edge, long_edge),
            "16:9": (long_edge, short_edge),
            "1:1": (short_edge, short_edge),
            "4:5": (short_edge, round(short_edge * 5 / 4)),
            "original": (self.source_width, self.source_height),
        }
        width, height = dimensions[reframe.aspect_ratio]
        if width > 0 and height > 0:
            self.preview_format_label.setText(f"{width}×{height} · {export.fps:g} FPS")
        else:
            self.preview_format_label.setText(f"Formato {reframe.aspect_ratio} · {export.fps:g} FPS")

    def _seek_timeline(self, position_ms: int, resume: bool | None = None) -> None:
        was_playing = self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        keep_playing = was_playing if resume is None else resume
        clips = self._video_clips()
        if not clips:
            self.player.pause()
            self.active_video_clip_id = None
            self.timeline_position_ms = 0
            self.timeline.set_position(0)
            self.layer_overlay.set_position(0)
            self.time_label.setText(f"00:00:00 / {format_timestamp(self.timeline.canvas.duration_ms)}")
            return

        duration = max(clip.timeline_end_ms for clip in clips)
        target = max(0, min(position_ms, duration))
        clip = next(
            (item for item in clips if item.timeline_start_ms <= target < item.timeline_end_ms),
            None,
        )
        at_end = False
        if clip is None:
            clip = next((item for item in clips if item.timeline_start_ms > target), None)
            if clip is not None:
                target = clip.timeline_start_ms
            else:
                clip = next((item for item in reversed(clips) if item.timeline_end_ms <= target), None)
                if clip is None:
                    clip = clips[0]
                    target = clip.timeline_start_ms
                else:
                    target = clip.timeline_end_ms
                    at_end = True

        source_position = clip.source_end_ms - 1 if at_end else (
            clip.source_start_ms + round((target - clip.timeline_start_ms) * clip.speed)
        )
        source_position = max(clip.source_start_ms, min(source_position, clip.source_end_ms - 1))
        self.active_video_clip_id = clip.clip_id
        self.timeline_position_ms = target
        self.timeline.set_position(target)
        self.layer_overlay.set_position(target)
        self.reframe_overlay.set_timestamp(source_position)
        self.time_label.setText(
            f"{format_timestamp(target)} / {format_timestamp(self.timeline.canvas.duration_ms)}"
        )
        self.player.setPlaybackRate(self.user_playback_rate * clip.speed)
        self.player.setPosition(source_position)
        if keep_playing and not at_end:
            self.player.play()

    def toggle_playback(self) -> None:
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            clips = self._video_clips()
            if not clips:
                return
            target = self.timeline_position_ms
            if not any(item.timeline_start_ms <= target < item.timeline_end_ms for item in clips):
                next_clip = next((item for item in clips if item.timeline_start_ms > target), None)
                target = next_clip.timeline_start_ms if next_clip else clips[0].timeline_start_ms
            self._seek_timeline(target, resume=False)
            self.player.play()

    def toggle_fullscreen(self) -> None:
        self.video.setFullScreen(not self.video.isFullScreen())

    def _previous_frame(self) -> None:
        self.player.pause()
        self._jump(-self.frame_duration_ms)

    def _next_frame(self) -> None:
        self.player.pause()
        self._jump(self.frame_duration_ms)

    def _jump(self, delta_ms: int) -> None:
        self._seek_timeline(self.timeline_position_ms + delta_ms)

    def _set_playback_rate(self, index: int) -> None:
        value = self.rate.itemData(index)
        if value is not None:
            self.user_playback_rate = float(value)
            clip = next((item for item in self._video_clips() if item.clip_id == self.active_video_clip_id), None)
            self.player.setPlaybackRate(self.user_playback_rate * (clip.speed if clip else 1.0))

    def _position_changed(self, source_position: int) -> None:
        clip = next(
            (item for item in self._video_clips() if item.clip_id == self.active_video_clip_id),
            None,
        )
        if clip is None:
            timeline_position = min(source_position, self.timeline.canvas.duration_ms)
        elif source_position >= clip.source_end_ms - max(2, min(15, self.frame_duration_ms // 4)):
            next_clip = next(
                (item for item in self._video_clips() if item.timeline_start_ms >= clip.timeline_end_ms),
                None,
            )
            if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState and next_clip:
                self._seek_timeline(next_clip.timeline_start_ms, resume=True)
                return
            if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                self.player.pause()
            timeline_position = clip.timeline_end_ms
        else:
            source_offset = max(0, source_position - clip.source_start_ms)
            timeline_position = clip.timeline_start_ms + round(source_offset / clip.speed)
        self.timeline_position_ms = max(0, min(timeline_position, self.timeline.canvas.duration_ms))
        self.timeline.set_position(self.timeline_position_ms)
        self.layer_overlay.set_position(self.timeline_position_ms)
        self.reframe_overlay.set_timestamp(source_position)
        self.time_label.setText(
            f"{format_timestamp(self.timeline_position_ms)} / {format_timestamp(self.timeline.canvas.duration_ms)}"
        )

    def _duration_changed(self, duration: int) -> None:
        self.source_duration_ms = duration
        self._sync_timeline_duration()
        if self._video_clips():
            self._seek_timeline(
                self.timeline_position_ms,
                resume=self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState,
            )
        else:
            self._position_changed(self.player.position())
        if self.source_path and duration > 0 and self.preview_worker is None:
            worker = FunctionWorker(build_media_preview_data, self.source_path, duration)
            worker.signals.finished.connect(self._media_preview_finished)
            worker.signals.failed.connect(lambda message: self.status_label.setText(f"Preview da timeline indisponível: {message}"))
            self.preview_worker = worker
            self.thread_pool.start(worker)

    def _media_preview_finished(self, payload: object) -> None:
        self.preview_worker = None
        if isinstance(payload, dict):
            self.timeline.canvas.set_media_previews(
                list(payload.get("thumbnails", [])),
                list(payload.get("waveform", [])),
            )

    def _playback_state_changed(self, state: QMediaPlayer.PlaybackState) -> None:
        text = "Pausar" if state == QMediaPlayer.PlaybackState.PlayingState else "Reproduzir"
        self.play_button.setText(text)

    def _playback_error(self, error: QMediaPlayer.Error, message: str) -> None:
        if error != QMediaPlayer.Error.NoError:
            self.status_label.setText(f"Não foi possível reproduzir a mídia: {message}")

    def mark_in(self) -> None:
        self.in_ms = self.timeline_position_ms
        self._update_markers()

    def mark_out(self) -> None:
        self.out_ms = self.timeline_position_ms
        self._update_markers()

    def _update_markers(self) -> None:
        self.timeline.set_markers(self.in_ms, self.out_ms)

    def export_selection(self) -> None:
        if any(item.track == "video" for item in self.timeline_clips):
            self.sequence_export_requested.emit()
            return
        if self.export_worker is not None:
            return
        if not self.source_path or self.out_ms is None:
            QMessageBox.warning(self, "Corte incompleto", "Importe um vídeo e defina entrada e saída.")
            return
        try:
            clip = ClipRange(start_ms=self.in_ms or 0, end_ms=self.out_ms)
        except ValueError as exc:
            QMessageBox.warning(self, "Intervalo inválido", str(exc))
            return
        filename, _ = QFileDialog.getSaveFileName(
            self, "Exportar corte", "corte.mp4", "Vídeo MP4 (*.mp4)"
        )
        if not filename:
            return
        destination = Path(filename)
        if destination.exists():
            QMessageBox.warning(self, "Arquivo existente", "Escolha um novo nome para não sobrescrever um arquivo.")
            return

        worker = FunctionWorker(export_clip, self.source_path, destination, clip)
        worker.signals.progress.connect(self._export_progressed)
        worker.signals.finished.connect(self._export_finished)
        worker.signals.failed.connect(self._export_failed)
        self.export_worker = worker
        self.export_progress.show()
        self.export_button.setEnabled(False)
        self.cancel_export_button.setEnabled(True)
        self.status_label.setText("Exportando corte…")
        self.thread_pool.start(worker)

    def cancel_export(self) -> None:
        if self.export_worker is not None:
            self.export_worker.cancel()
            self.cancel_export_button.setEnabled(False)
            self.status_label.setText("Cancelando exportação…")

    def _export_progressed(self, status: object) -> None:
        self.status_label.setText("Exportando corte…")

    def _finish_export_state(self) -> None:
        self.export_worker = None
        self.export_progress.hide()
        self.export_button.setEnabled(True)
        self.cancel_export_button.setEnabled(False)

    def _export_finished(self, destination: Path) -> None:
        self._finish_export_state()
        self.status_label.setText(f"Exportação concluída: {destination}")
        QMessageBox.information(self, "Exportação concluída", f"Arquivo salvo em:\n{destination}")

    def _export_failed(self, message: str) -> None:
        self._finish_export_state()
        if "cancelad" in message.lower():
            self.status_label.setText("Exportação cancelada.")
            return
        self.status_label.setText("Exportação não concluída.")
        QMessageBox.critical(self, "Falha na exportação", message)
