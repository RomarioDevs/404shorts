"""Main application shell."""

from pathlib import Path
from PySide6.QtCore import QThreadPool, QTimer
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QInputDialog,
    QPushButton,
    QStackedWidget,
    QStatusBar,
    QToolBar,
    QWidget,
    QFileDialog,
)
from cortaflow.ui.pages.import_page import ImportPage
from cortaflow.ui.pages.analysis_page import AnalysisPage
from cortaflow.ui.pages.editor_page import EditorPage
from cortaflow.ui.pages.subtitles_page import SubtitlesPage
from cortaflow.ui.pages.suggestions_page import SuggestionsPage
from cortaflow.ui.pages.export_page import ExportPage
from cortaflow.ui.pages.history_page import HistoryPage
from cortaflow.domain.project import ProjectDocument
from cortaflow.services.project_service import (
    autosave_path,
    load_project,
    recovery_available,
    save_autosave,
    save_project,
)
from cortaflow.services.editor_operations import create_initial_clips
from cortaflow.services.sequence_operations import create_sequence_from_suggestion
from cortaflow.services.automatic_pipeline import create_automatic_cuts
from cortaflow.services.face_detection import find_local_face_landmarker
from cortaflow.services.transcription import (
    FasterWhisperTranscriber,
    diagnose_compute_device,
    whisper_model_is_cached,
)
from cortaflow.workers.base_worker import FunctionWorker
from cortaflow.config import AppConfig
from cortaflow.infrastructure.database import (
    get_setting,
    initialize_database,
    record_project_history,
    set_setting,
)


class MainWindow(QMainWindow):
    """Top-level window and navigation shell."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("mainWindow")
        self.setWindowTitle("CortaFlow AI")
        self.resize(1400, 850)
        self.setMinimumSize(1000, 650)
        self.project = ProjectDocument()
        self.project_path: Path | None = None
        self.automatic_worker: FunctionWorker | None = None
        self._create_actions()
        self._create_central_area()
        self._create_toolbar()
        self._create_status_bar()
        self._apply_theme()
        self.navigation.currentRowChanged.connect(self._update_editor_chrome)
        self._update_editor_chrome(self.navigation.currentRow())
        self.autosave_timer = QTimer(self)
        self.autosave_timer.setInterval(30_000)
        self.autosave_timer.timeout.connect(self._autosave)
        self.autosave_timer.start()

    def _create_actions(self) -> None:
        self.save_action = QAction("Salvar", self)
        self.save_action.setShortcut(QKeySequence.StandardKey.Save)
        self.save_action.triggered.connect(self._save_project)
        self.export_action = QAction("Salvar cortes", self)
        self.export_action.setShortcut(QKeySequence("Ctrl+E"))
        self.export_action.triggered.connect(self._save_cuts_for_current_context)
        self.undo_action = QAction("Desfazer", self)
        self.undo_action.setShortcut(QKeySequence.StandardKey.Undo)
        self.undo_action.setToolTip("Disponível depois de uma alteração no editor.")
        self.undo_action.triggered.connect(lambda: self.editor_page.undo_stack.undo())
        self.redo_action = QAction("Refazer", self)
        self.redo_action.setShortcut(QKeySequence("Ctrl+Shift+Z"))
        self.redo_action.setToolTip("Disponível depois de desfazer uma alteração no editor.")
        self.redo_action.triggered.connect(lambda: self.editor_page.undo_stack.redo())
        self.automatic_action = QAction("Gerar cortes sugeridos", self)
        self.automatic_action.setEnabled(False)
        self.automatic_action.setToolTip(
            "Analisa a mídia e mostra os cortes na tela Cortes sugeridos."
        )
        self.automatic_action.triggered.connect(self._start_automatic_pipeline)
        self.cancel_automatic_action = QAction("Cancelar automático", self)
        self.cancel_automatic_action.setEnabled(False)
        self.cancel_automatic_action.setToolTip(
            "Fica disponível somente enquanto a criação automática está em execução."
        )
        self.cancel_automatic_action.triggered.connect(self._cancel_automatic_pipeline)

    def _create_toolbar(self) -> None:
        toolbar = QToolBar("Ferramentas principais", self)
        self.main_toolbar = toolbar
        toolbar.setMovable(False)
        new_action = toolbar.addAction("Novo projeto")
        new_action.triggered.connect(self._new_project)
        open_action = toolbar.addAction("Abrir projeto")
        open_action.triggered.connect(self._open_project)
        toolbar.addAction(self.save_action)
        save_as = toolbar.addAction("Salvar como")
        save_as.triggered.connect(lambda: self._save_project(save_as=True))
        toolbar.addSeparator()
        toolbar.addAction(self.undo_action)
        toolbar.addAction(self.redo_action)
        toolbar.addSeparator()
        toolbar.addAction(self.automatic_action)
        toolbar.addAction(self.cancel_automatic_action)
        toolbar.addSeparator()
        settings_action = toolbar.addAction("Configurações")
        settings_action.setToolTip("Abrir pastas locais e limite de tarefas simultâneas.")
        settings_action.triggered.connect(self._show_settings)
        help_action = toolbar.addAction("Ajuda")
        help_action.triggered.connect(self._show_help)
        about_action = toolbar.addAction("Sobre")
        about_action.triggered.connect(self._show_about)
        spacer = QWidget()
        spacer.setSizePolicy(spacer.sizePolicy().Policy.Expanding, spacer.sizePolicy().Policy.Preferred)
        toolbar.addWidget(spacer)
        compute_status = diagnose_compute_device()
        device_label = QLabel(
            f"{compute_status.device.upper()} · {compute_status.compute_type}  "
        )
        device_label.setToolTip(compute_status.detail)
        device_action = toolbar.addWidget(device_label)
        export_button = QPushButton("Exportar")
        export_button.clicked.connect(self.export_action.trigger)
        self.toolbar_export_item = toolbar.addWidget(export_button)
        self.toolbar_compact_items = (save_as, settings_action, help_action, about_action)
        self.toolbar_utility_items = (self.automatic_action, self.cancel_automatic_action)
        self.toolbar_device_item = device_action
        self.addToolBar(toolbar)

    def _update_editor_chrome(self, page_index: int) -> None:
        """Keep app navigation available while simplifying the editor toolbar."""
        editing = page_index == 3
        self.navigation.setVisible(True)
        for item in (*self.toolbar_compact_items, *self.toolbar_utility_items, self.toolbar_device_item):
            item.setVisible(not editing)

    def _create_central_area(self) -> None:
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.navigation = QListWidget()
        self.navigation.setObjectName("navigation")
        self.navigation.setFixedWidth(210)
        self.navigation.addItems(
            [
                "Importar",
                "Análise avançada",
                "Cortes sugeridos",
                "Editor completo",
                "Legendas",
                "Histórico",
            ]
        )
        self.navigation.setCurrentRow(0)

        self.pages = QStackedWidget()
        self.import_page = ImportPage()
        self.editor_page = EditorPage()
        self.pages.addWidget(self.import_page)
        self.analysis_page = AnalysisPage()
        self.pages.addWidget(self.analysis_page)
        self.suggestions_page = SuggestionsPage()
        self.pages.addWidget(self.suggestions_page)
        self.pages.addWidget(self.editor_page)
        self.subtitles_page = SubtitlesPage()
        self.pages.addWidget(self.subtitles_page)
        self.export_page = ExportPage()
        self.suggestions_page.attach_review_widget(self.export_page)
        self.history_page = HistoryPage()
        self.pages.addWidget(self.history_page)
        self.import_page.media_selected.connect(self._open_imported_media)
        self.editor_page.media_import_requested.connect(self.import_page.choose_local_file)
        self.subtitles_page.transcript_changed.connect(self._transcript_changed)
        self.analysis_page.analysis_finished.connect(self._analysis_finished)
        self.analysis_page.selection_settings_changed.connect(self._selection_settings_changed)
        self.analysis_page.face_analysis_finished.connect(self._face_analysis_finished)
        self.analysis_page.face_selection_changed.connect(self._face_selection_changed)
        self.analysis_page.speaker_analysis_finished.connect(self._speaker_analysis_finished)
        self.analysis_page.speaker_overrides_changed.connect(self._speaker_overrides_changed)
        self.suggestions_page.suggestions_changed.connect(self._suggestions_changed)
        self.suggestions_page.open_requested.connect(self._open_suggestion)
        self.suggestions_page.review_requested.connect(self._review_suggestion)
        self.suggestions_page.export_requested.connect(self._prepare_accepted_exports)
        self.editor_page.timeline_changed.connect(self._timeline_changed)
        self.editor_page.layers_changed.connect(self._layers_changed)
        self.editor_page.sequence_changed.connect(self._sequence_changed)
        self.editor_page.sequence_export_requested.connect(self._export_editor_sequence)
        self.editor_page.settings_changed.connect(self._editor_settings_changed)
        self.editor_page.reframe_keyframes_changed.connect(self._editor_reframe_changed)
        self.editor_page.automatic_requested.connect(self._start_automatic_pipeline)
        self.export_page.settings_changed.connect(self._export_settings_changed)
        self.export_page.cues_changed.connect(self._export_cues_changed)
        self.export_page.reframe_edit_requested.connect(self._open_export_reframe)
        self.export_page.suggestion_saved.connect(self._suggestion_saved)
        self.history_page.open_requested.connect(self._load_project_path)
        self.editor_page.undo_stack.canUndoChanged.connect(self.undo_action.setEnabled)
        self.editor_page.undo_stack.canRedoChanged.connect(self.redo_action.setEnabled)
        self.navigation.currentRowChanged.connect(self.pages.setCurrentIndex)

        layout.addWidget(self.navigation)
        layout.addWidget(self.pages, 1)
        self.setCentralWidget(container)

    def _open_imported_media(self, metadata) -> None:
        if metadata.local_path:
            self.project.source_path = metadata.local_path
            self.project.source_metadata = metadata.model_dump(mode="json")
            self.project.transcript = None
            self.project.scenes = []
            self.project.silences = []
            self.project.suggestions = []
            self.project.face_tracks = []
            self.project.reframe_keyframes = []
            self.project.selected_face_track_id = None
            self.project.speaker_keyframes = []
            self.project.speaker_overrides = []
            self.project.timeline_clips = create_initial_clips(
                round(metadata.duration_seconds * 1000),
                metadata.title,
            )
            self.project.layers = []
            self.project.sequences = []
            self.project.active_sequence_id = None
            self.editor_page.load_media(
                metadata.local_path,
                metadata.fps,
                metadata.width,
                metadata.height,
            )
            self.editor_page.set_reframe_data([], [], None)
            self.subtitles_page.set_media(metadata.local_path)
            self.suggestions_page.set_suggestions([])
            self.suggestions_page.set_media_source(metadata.local_path)
            self.analysis_page.set_context(
                metadata.local_path,
                None,
                round(metadata.duration_seconds * 1000),
                metadata.width or 0,
                metadata.height or 0,
                selection_settings=self.project.clip_selection,
            )
            self._sync_editor_state()
            self.automatic_action.setEnabled(True)
            self.navigation.setCurrentRow(3)

    def _transcript_changed(self, transcript) -> None:
        self.project.transcript = transcript
        self.analysis_page.set_transcript(transcript)
        self._sync_editor_state()

    def _analysis_finished(self, result) -> None:
        self.project.scenes = result.scenes
        self.project.silences = result.silences
        self.project.suggestions = result.suggestions
        self.analysis_page.set_scenes(result.scenes)
        self.analysis_page.silences = list(result.silences)
        self.suggestions_page.set_suggestions(result.suggestions)
        self._sync_editor_state()
        self.navigation.setCurrentRow(2)

    def _start_automatic_pipeline(self) -> None:
        if self.automatic_worker is not None:
            return
        if not self.project.source_path or not self.project.source_path.is_file():
            QMessageBox.warning(
                self,
                "Mídia ausente",
                "Importe ou baixe uma mídia autorizada antes de criar cortes automaticamente.",
            )
            return
        model_cache = AppConfig().whisper_model_cache
        transcriber = None
        if self.project.transcript is None:
            model_size = str(self.subtitles_page.model.currentData())
            allow_download = False
            if not whisper_model_is_cached(model_cache, model_size):
                answer = QMessageBox.question(
                    self,
                    "Modelo de transcrição ausente",
                    f"O Faster-Whisper {model_size} não está no computador. Autoriza o "
                    "download da publicação oficial Systran/Hugging Face para continuar?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if answer != QMessageBox.StandardButton.Yes:
                    self.statusBar().showMessage(
                        "Fluxo automático não iniciado: download não autorizado.", 8000
                    )
                    return
                allow_download = True
            transcriber = FasterWhisperTranscriber(
                model_size=model_size,
                model_cache=model_cache,
                certificate_cache=AppConfig().cache_dir / "certificates",
                allow_download=allow_download,
            )
        face_model = self._find_local_face_model()
        ranker = (
            self.analysis_page.semantic_ranker
            if self.project.clip_selection.ranking_mode == "automatic"
            else None
        )
        worker = FunctionWorker(
            create_automatic_cuts,
            self.project.source_path,
            self.project.transcript,
            self.project.clip_selection,
            ranker,
            transcriber,
            face_model,
            AppConfig().preview_dir,
            self.project.export,
            self.project.subtitle_style,
            self.project.reframe_settings,
            self.project.audio_settings,
            self.project.clip_selection.max_results,
        )
        worker.signals.progress.connect(self._automatic_progress)
        worker.signals.finished.connect(self._automatic_finished)
        worker.signals.failed.connect(self._automatic_failed)
        self.automatic_worker = worker
        self.automatic_action.setEnabled(False)
        self.cancel_automatic_action.setEnabled(True)
        message = "Encontrando e preparando cortes… Acompanhe em Cortes sugeridos."
        self.suggestions_page.set_media_source(self.project.source_path)
        self.suggestions_page.set_suggestions([])
        self.suggestions_page.set_processing(True, message)
        self.navigation.setCurrentRow(2)
        self.statusBar().showMessage(message)
        QThreadPool.globalInstance().start(worker)

    def _automatic_progress(self, state: dict) -> None:
        message = str(state.get("message", "Preparando cortes sugeridos…"))
        self.statusBar().showMessage(message)
        self.suggestions_page.set_processing(True, message)
        if state.get("status") == "suggestions_ready":
            suggestions = list(state.get("suggestions") or [])
            self.project.suggestions = suggestions
            self.suggestions_page.set_suggestions(suggestions)
            self.suggestions_page.set_processing(True, message)
            self._sync_editor_state()
        elif state.get("status") == "preview_ready":
            suggestions = list(state.get("suggestions") or [])
            if suggestions:
                self.project.suggestions = suggestions
                self.suggestions_page.set_suggestions(suggestions)
            self.suggestions_page.set_previews(list(state.get("previews") or []))

    def _automatic_finished(self, result) -> None:
        self.project.source_metadata = result.metadata.model_dump(mode="json")
        self.project.transcript = result.transcript
        self.project.scenes = result.analysis.scenes
        self.project.silences = result.analysis.silences
        self.project.suggestions = result.analysis.suggestions
        self.project.face_tracks = result.face_tracks
        self.project.reframe_keyframes = self._merge_manual_keyframes(result.reframe_keyframes)
        self.project.selected_face_track_id = None
        self.project.speaker_keyframes = result.speaker_keyframes
        self.project.speaker_overrides = []
        self.subtitles_page.set_media(self.project.source_path, result.transcript)
        self.analysis_page.set_context(
            self.project.source_path,
            result.transcript,
            round(result.metadata.duration_seconds * 1000),
            result.metadata.width or 0,
            result.metadata.height or 0,
            result.analysis.scenes,
            result.analysis.silences,
            self.project.clip_selection,
        )
        self.analysis_page.restore_faces(
            result.face_tracks,
            self.project.reframe_keyframes,
            None,
        )
        self.analysis_page.restore_speakers(result.speaker_keyframes, [])
        self.editor_page.set_reframe_data(
            result.face_tracks,
            self.project.reframe_keyframes,
            None,
            result.speaker_keyframes,
        )
        self.suggestions_page.set_suggestions(result.analysis.suggestions)
        self.suggestions_page.set_previews(result.previews)
        self.suggestions_page.set_media_source(self.project.source_path)
        complete_message = (
            (
                f"Concluído: {len(result.analysis.suggestions)} cortes; "
                f"{sum(item.framing_status == 'validated' for item in result.analysis.suggestions)} "
                "com rosto validado. Assista e use Editar e salvar este corte."
            )
            if result.analysis.suggestions
            else (
                "Análise concluída sem cortes. A transcrição não forneceu limites editoriais "
                "suficientemente seguros; revise a transcrição ou reduza a duração mínima."
            )
        )
        self.suggestions_page.set_processing(False, complete_message)
        self._sync_editor_state()
        self._finish_automatic_pipeline()
        self.navigation.setCurrentRow(2)
        self.statusBar().showMessage(
            f"Criação automática concluída: {len(result.analysis.suggestions)} cortes e "
            f"{len(result.previews)} versões verticais; {len(result.face_tracks)} observações faciais e "
            f"{len(result.speaker_keyframes)} decisões de falante.",
            12_000,
        )

    def _automatic_failed(self, message: str) -> None:
        self._finish_automatic_pipeline()
        if "cancelad" in message.lower():
            self.suggestions_page.set_processing(False, "Criação automática cancelada.")
            self.statusBar().showMessage("Criação automática cancelada.", 8000)
            return
        self.suggestions_page.set_processing(
            False,
            f"Criação automática não concluída: {message}",
        )
        self.statusBar().showMessage("Criação automática não concluída.", 8000)
        QMessageBox.critical(self, "Criação automática não concluída", message)

    def _cancel_automatic_pipeline(self) -> None:
        if self.automatic_worker:
            self.automatic_worker.cancel()
            self.cancel_automatic_action.setEnabled(False)
            self.suggestions_page.set_processing(
                True,
                "Cancelamento solicitado; concluindo a etapa local atual…",
            )
            self.statusBar().showMessage("Cancelando criação automática…")

    def _finish_automatic_pipeline(self) -> None:
        self.automatic_worker = None
        self.cancel_automatic_action.setEnabled(False)
        self.automatic_action.setEnabled(
            bool(self.project.source_path and self.project.source_path.is_file())
        )

    def _find_local_face_model(self) -> Path | None:
        selected_text = self.analysis_page.face_model_path.text().strip()
        return find_local_face_landmarker(
            Path(selected_text) if selected_text else None,
        )

    def _selection_settings_changed(self, settings) -> None:
        self.project.clip_selection = settings

    def _suggestions_changed(self, suggestions) -> None:
        self.project.suggestions = suggestions
        self._sync_export_context()

    def _prepare_accepted_exports(self) -> None:
        self.export_page.sequence_export_mode = False
        self._sync_export_context()
        if self.export_page.prepare_accepted():
            self.navigation.setCurrentRow(2)
            self.suggestions_page.show_review()

    def _export_editor_sequence(self) -> None:
        """Send the current non-destructive sequence to preview/export review."""
        self._sync_export_context()
        if self.export_page.prepare_sequence_export():
            self.navigation.setCurrentRow(2)
            self.suggestions_page.show_review()

    def _save_cuts_for_current_context(self) -> None:
        """Save the open individual cut; use acceptance only for a results batch."""
        if self.navigation.currentRow() == 3:
            self._export_editor_sequence()
            return
        if (
            self.navigation.currentRow() == 2
            and self.suggestions_page.workspace_tabs.currentIndex() == 1
            and self.export_page.review_suggestion is not None
        ):
            self.export_page.save_current_suggestion()
            return
        self._prepare_accepted_exports()

    def _open_suggestion(self, suggestion) -> None:
        """Open a suggestion as an editable, non-destructive sequence draft."""
        try:
            sequence = create_sequence_from_suggestion(suggestion)
        except ValueError as exc:
            QMessageBox.warning(self, "Sugestão inválida", str(exc))
            return
        self.project.sequences = [item for item in self.project.sequences if item.sequence_id != sequence.sequence_id]
        self.project.sequences.append(sequence)
        self.project.active_sequence_id = sequence.sequence_id
        self.project.timeline_clips = list(sequence.clips)
        self.project.layers = list(sequence.layers)
        self._sync_editor_state()
        self.editor_page.set_selection(0, sequence.duration_ms)
        self.navigation.setCurrentRow(3)
        self.statusBar().showMessage(
            "Sugestão aberta como rascunho editável. Arraste as alças, divida, adicione texto ou imagem e exporte quando terminar.",
            10_000,
        )

    def _review_suggestion(self, suggestion) -> None:
        self._sync_export_context()
        if self.export_page.prepare_suggestion(
            suggestion,
            self.suggestions_page.preview_for(suggestion),
        ):
            self.navigation.setCurrentRow(2)
            self.suggestions_page.show_review()

    def _open_export_reframe(self, clip) -> None:
        self.editor_page.set_selection(clip.start_ms, clip.end_ms)
        self.navigation.setCurrentRow(3)

    def _export_cues_changed(self, cues) -> None:
        if not self.project.transcript:
            return
        self.project.transcript = self.project.transcript.model_copy(update={"cues": list(cues)})
        self.subtitles_page.set_cues(list(cues))
        self.analysis_page.set_transcript(self.project.transcript)
        self.editor_page.timeline.set_track_data(
            self.project.timeline_clips,
            transcript=self.project.transcript.words,
            subtitles=cues,
            scenes=self.project.scenes,
            suggestions=self.project.suggestions,
            reframe=self.project.reframe_keyframes,
            layers=self.project.layers,
        )

    def _suggestion_saved(self, suggestion) -> None:
        self.suggestions_page.mark_suggestion_saved(suggestion)
        self.statusBar().showMessage(
            f"Corte salvo e marcado como aceito: {suggestion.title}",
            10_000,
        )

    def _face_analysis_finished(self, result) -> None:
        tracks, keyframes, selected_track_id = result
        self.project.face_tracks = tracks
        self.project.reframe_keyframes = self._merge_manual_keyframes(keyframes)
        self.project.selected_face_track_id = selected_track_id
        self.project.speaker_keyframes = []
        self.project.speaker_overrides = []
        self.analysis_page.restore_speakers([], [])
        self.editor_page.set_reframe_data(
            tracks,
            self.project.reframe_keyframes,
            selected_track_id,
        )
        self._sync_export_context()

    def _face_selection_changed(self, result) -> None:
        selected_track_id, keyframes = result
        self.project.selected_face_track_id = selected_track_id
        self.project.reframe_keyframes = self._merge_manual_keyframes(keyframes)
        self.editor_page.set_reframe_data(
            self.project.face_tracks,
            self.project.reframe_keyframes,
            selected_track_id,
        )
        self._sync_export_context()

    def _speaker_analysis_finished(self, result) -> None:
        speaker_keyframes, reframe_keyframes = result
        self.project.speaker_keyframes = speaker_keyframes
        self.project.reframe_keyframes = self._merge_manual_keyframes(reframe_keyframes)
        self.editor_page.set_reframe_data(
            self.project.face_tracks,
            self.project.reframe_keyframes,
            None,
            speaker_keyframes,
        )
        self._sync_export_context()

    def _speaker_overrides_changed(self, result) -> None:
        overrides, speaker_keyframes, reframe_keyframes = result
        self.project.speaker_overrides = overrides
        self.project.speaker_keyframes = speaker_keyframes
        self.project.reframe_keyframes = self._merge_manual_keyframes(reframe_keyframes)
        self.editor_page.set_reframe_data(
            self.project.face_tracks,
            self.project.reframe_keyframes,
            None,
            speaker_keyframes,
        )
        self._sync_export_context()

    def _timeline_changed(self, clips) -> None:
        self.project.timeline_clips = list(clips)
        self._sync_active_sequence(clips=list(clips))
        self._sync_export_context()

    def _layers_changed(self, layers) -> None:
        self.project.layers = list(layers)
        self._sync_active_sequence(layers=list(layers))
        self._sync_export_context()

    def _sequence_changed(self, sequence) -> None:
        self.project.sequences = [
            sequence if item.sequence_id == sequence.sequence_id else item
            for item in self.project.sequences
        ] or [sequence]
        self.project.active_sequence_id = sequence.sequence_id

    def _sync_active_sequence(self, *, clips=None, layers=None) -> None:
        if not self.project.active_sequence_id:
            return
        updated = []
        for sequence in self.project.sequences:
            if sequence.sequence_id != self.project.active_sequence_id:
                updated.append(sequence)
                continue
            updated.append(
                sequence.model_copy(
                    update={
                        "clips": list(clips) if clips is not None else sequence.clips,
                        "layers": list(layers) if layers is not None else sequence.layers,
                        "dirty": True,
                    }
                )
            )
        self.project.sequences = updated

    def _editor_settings_changed(self, settings) -> None:
        reframe, subtitle, audio, export = settings
        self.project.reframe_settings = reframe
        self.project.subtitle_style = subtitle
        self.project.audio_settings = audio
        self.project.export = export
        self.subtitles_page.set_style(subtitle)
        self._sync_export_context()

    def _editor_reframe_changed(self, keyframes) -> None:
        self.project.reframe_keyframes = keyframes
        self._sync_export_context()

    def _export_settings_changed(self, settings) -> None:
        self.project.export = settings
        self.editor_page.properties.set_watermark_settings(settings.watermark)

    def _sync_editor_state(self) -> None:
        self.editor_page.set_project_editor_state(
            self.project.timeline_clips,
            self.project.transcript,
            self.project.scenes,
            self.project.suggestions,
            self.project.reframe_keyframes,
            self.project.reframe_settings,
            self.project.subtitle_style,
            self.project.audio_settings,
            self.project.export,
            self.project.layers,
            self._active_sequence(),
        )
        self.subtitles_page.set_style(self.project.subtitle_style)
        self._sync_export_context()

    def _active_sequence(self):
        return next(
            (item for item in self.project.sequences if item.sequence_id == self.project.active_sequence_id),
            None,
        )

    def _sync_export_context(self) -> None:
        duration_ms = round(float(self.project.source_metadata.get("duration_seconds", 0)) * 1000)
        cues = self.project.transcript.cues if self.project.transcript else []
        words = self.project.transcript.words if self.project.transcript else []
        width = int(self.project.source_metadata.get("width") or 0)
        height = int(self.project.source_metadata.get("height") or 0)
        self.export_page.set_context(
            self.project.source_path,
            duration_ms,
            self.project.export,
            cues,
            self.project.subtitle_style,
            self.project.reframe_keyframes,
            self.project.suggestions,
            words,
            self.project.timeline_clips,
            self.project.reframe_settings,
            self.project.audio_settings,
            (width, height) if width and height else None,
            self.project.layers,
        )

    def _merge_manual_keyframes(self, automatic) -> list:
        manual = [item for item in self.project.reframe_keyframes if item.manual]
        manual_timestamps = {item.timestamp_ms for item in manual}
        return sorted(
            [item for item in automatic if item.timestamp_ms not in manual_timestamps] + manual,
            key=lambda item: item.timestamp_ms,
        )

    def _new_project(self) -> None:
        self.project = ProjectDocument(); self.project_path = None
        self.subtitles_page.set_media(None)
        self.analysis_page.set_context(None, None)
        self.analysis_page.restore_faces([], [], None)
        self.analysis_page.restore_speakers([], [])
        self.editor_page.set_reframe_data([], [], None)
        self.suggestions_page.set_suggestions([])
        self.suggestions_page.set_media_source(None)
        self._sync_editor_state()
        self.automatic_action.setEnabled(False)
        self.setWindowTitle("CortaFlow AI")
        self.navigation.setCurrentRow(0)

    def _open_project(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(self, "Abrir projeto", "", "Projeto CortaFlow (*.cortaflow.json *.json)")
        if filename:
            self._load_project_path(Path(filename))

    def _load_project_path(self, path: Path) -> None:
        selected_path = path
        if recovery_available(path):
            answer = QMessageBox.question(
                self,
                "Recuperar salvamento automático",
                "Existe uma versão automática mais recente. Deseja recuperá-la?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if answer == QMessageBox.StandardButton.Yes:
                selected_path = autosave_path(path)
        try:
            project = load_project(selected_path)
        except Exception as exc:
            QMessageBox.critical(self, "Falha ao abrir", str(exc))
            return
        self.project, self.project_path = project, path
        self.setWindowTitle(f"{project.name} — CortaFlow AI")
        self._record_history()
        if project.source_path and project.source_path.is_file():
            fps = project.source_metadata.get("fps") if project.source_metadata else None
            width = project.source_metadata.get("width") if project.source_metadata else None
            height = project.source_metadata.get("height") if project.source_metadata else None
            self.editor_page.load_media(project.source_path, fps, width, height)
            self.editor_page.set_reframe_data(
                project.face_tracks,
                project.reframe_keyframes,
                project.selected_face_track_id,
            )
            self.subtitles_page.set_media(project.source_path, project.transcript)
            duration = round(float(project.source_metadata.get("duration_seconds", 0)) * 1000)
            self.analysis_page.set_context(
                project.source_path,
                project.transcript,
                duration,
                width or 0,
                height or 0,
                project.scenes,
                project.silences,
                project.clip_selection,
            )
            self.analysis_page.restore_faces(
                project.face_tracks,
                project.reframe_keyframes,
                project.selected_face_track_id,
            )
            self.analysis_page.restore_speakers(
                project.speaker_keyframes,
                project.speaker_overrides,
            )
            if project.speaker_keyframes:
                self.editor_page.set_reframe_data(
                    project.face_tracks,
                    project.reframe_keyframes,
                    None,
                    project.speaker_keyframes,
                )
            self._sync_editor_state()
            self.suggestions_page.set_suggestions(project.suggestions)
            self.suggestions_page.set_media_source(project.source_path)
            self.automatic_action.setEnabled(True)

    def _save_project(self, checked: bool = False, save_as: bool = False) -> None:
        if self.project_path is None or save_as:
            filename, _ = QFileDialog.getSaveFileName(self, "Salvar projeto", "projeto.cortaflow.json", "Projeto CortaFlow (*.cortaflow.json)")
            if not filename: return
            self.project_path = Path(filename)
        try: save_project(self.project, self.project_path)
        except Exception as exc: QMessageBox.critical(self, "Falha ao salvar", str(exc)); return
        self._record_history()
        self.statusBar().showMessage(f"Projeto salvo: {self.project_path}", 5000)

    def _autosave(self) -> None:
        if self.project_path:
            try: save_autosave(self.project, self.project_path)
            except OSError: pass

    def _create_status_bar(self) -> None:
        status = QStatusBar()
        status.showMessage("Pronto")
        self.setStatusBar(status)

    def _show_about(self) -> None:
        QMessageBox.about(self, "Sobre o CortaFlow AI", "CortaFlow AI 0.1.0\nEditor local de vídeos autorizados.\n\nPySide6 · FFmpeg · Faster-Whisper · MediaPipe · OpenCV")

    def _show_settings(self) -> None:
        config = AppConfig()
        connection = initialize_database(config.data_dir / "cortaflow.db")
        try:
            stored_limit = int(get_setting(connection, "max_concurrent_tasks", config.max_concurrent_tasks))
        finally:
            connection.close()
        limit, accepted = QInputDialog.getInt(
            self,
            "Configurações locais",
            f"Limite de tarefas simultâneas (1 a 8):\n\nDados: {config.data_dir}\n"
            f"Cache/modelos: {config.cache_dir}\nLogs: {config.log_dir}",
            stored_limit,
            1,
            8,
        )
        if not accepted:
            return
        connection = initialize_database(config.data_dir / "cortaflow.db")
        try:
            set_setting(connection, "max_concurrent_tasks", limit)
        finally:
            connection.close()
        QThreadPool.globalInstance().setMaxThreadCount(limit)
        self.statusBar().showMessage(f"Limite atualizado para {limit} tarefa(s) simultânea(s).", 5000)

    def _show_help(self) -> None:
        QMessageBox.information(
            self,
            "Ajuda",
            "Fluxo recomendado:\n1. Importe uma mídia autorizada.\n"
            "2. Clique em Gerar cortes sugeridos; transcrição, cenas, rostos e falante são "
            "analisados em ordem.\n3. Em Cortes sugeridos, assista à versão vertical e "
            "confira o estado do enquadramento.\n4. Use Editar e salvar este corte para corrigir "
            "legenda, enquadramento ou marca-d'água.\n5. Atualize a prévia, aprove e escolha "
            "a pasta. O arquivo só é marcado como aceito depois de salvo.",
        )

    def _record_history(self) -> None:
        if not self.project_path:
            return
        config = AppConfig()
        connection = initialize_database(config.data_dir / "cortaflow.db")
        try:
            record_project_history(connection, self.project_path, self.project.name)
        finally:
            connection.close()
        self.history_page.refresh()

    def _apply_theme(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QWidget { background: #12141a; color: #eef1f7; }
            QToolBar { background: #1b1e26; border: 0; spacing: 6px; padding: 7px 10px; }
            QToolButton, QPushButton { background: #292e3a; border: 1px solid #3b4352;
                border-radius: 6px; padding: 7px 11px; color: #eef1f7; }
            QToolButton:hover, QPushButton:hover { background: #363e4e; border-color: #59647a; }
            QToolButton:pressed, QPushButton:pressed { background: #4e43b2; }
            QToolButton:disabled, QPushButton:disabled { background: #20232b;
                border-color: #2b303b; color: #737b8c; }
            #navigation { background: #181b22; border: 0; padding-top: 12px; }
            #navigation::item { padding: 12px 18px; margin: 2px 8px; border-radius: 6px; }
            #navigation::item:selected { background: #5b50d6; color: white; }
            #pageTitle { color: #aeb4c2; font-size: 20px; }
            QStatusBar { background: #1b1e26; color: #9ca5b6; }

            #editorWorkspace { background: #101218; }
            #editorHeader, #previewHeader, #transportHeader, #timelineHeader,
            #inspectorHeader { background: #1b1e27; border: 1px solid #292f3b; border-radius: 8px; }
            #editorResourcePanel { background: #1a1d24; border: 1px solid #2b313d; border-radius: 8px; }
            #editorResourceBrand { color: #f3f5fb; font-size: 16px; font-weight: 800; }
            #editorResourceLabel { color: #7f899c; font-size: 10px; font-weight: 800; letter-spacing: 1px; }
            #editorSourceCombo { min-width: 92px; padding: 4px 6px; }
            #editorImportButton { background: #5b50d6; border-color: #7168e9; font-weight: 700; padding: 7px 10px; }
            #editorImportButton:hover { background: #7168e9; }
            #editorResourceSearch { background: #222630; border-color: #343b49; padding: 7px 9px; }
            #editorResourceButton { background: #222630; border: 1px solid #303746; border-radius: 5px; color: #aeb7c7; padding: 5px 4px; }
            #editorResourceButton:hover { background: #2e3544; color: #ffffff; border-color: #4a556c; }
            #editorResourceButton:checked { background: #4e43b2; color: #ffffff; border-color: #7168e9; }
            #editorResourceDivider { color: #2f3644; }
            #editorResourceTitle { color: #eef1f7; font-size: 13px; font-weight: 700; }
            #editorAssetsScroll { background: transparent; }
            #editorAssetCard { background: #222630; border: 1px solid #303746; border-radius: 7px; }
            #editorAssetCard:hover { border-color: #7168e9; background: #292e3b; }
            #editorAssetPreview { background: #151820; border-radius: 4px; color: #8076dc; font-size: 10px; font-weight: 800; }
            #editorAssetTitle { color: #eef1f7; font-size: 11px; }
            #editorAssetMeta { color: #7f899c; font-size: 9px; }
            #editorEmptyState { color: #7f899c; font-size: 11px; padding: 16px; }

            #editorHeader { min-height: 52px; }
            #editorActionStrip { background: #1b1e27; border: 1px solid #292f3b; border-radius: 8px; }
            #editorActionStrip QLabel { color: #7f899c; font-size: 10px; font-weight: 800; letter-spacing: 1px; }
            #editorQuickAction { background: #252a35; border: 1px solid #353d4c; border-radius: 5px;
                color: #dce1ec; padding: 5px 10px; font-size: 11px; }
            #editorQuickAction:hover { background: #343b4b; border-color: #7168e9; color: #ffffff; }
            #editorSelectionLabel { color: #aeb7c7; font-size: 11px; }
            #editorHeader QLabel, #previewHeader QLabel, #transportHeader QLabel,
            #timelineHeader QLabel, #inspectorHeader QLabel { color: #aeb7c7; }
            #editorSectionTitle { color: #f5f7fb; font-size: 16px; font-weight: 700; }
            #editorSectionSubtitle, #editorRailHint, #previewMeta { color: #7f899c; font-size: 11px; }
            #editorStatusBadge { color: #8fe1c1; background: #1d3a35; border: 1px solid #2d675a;
                border-radius: 10px; padding: 4px 9px; font-size: 10px; font-weight: 700; }
            #editorIconButton { min-width: 34px; max-width: 34px; min-height: 30px; max-height: 30px;
                padding: 2px; font-size: 17px; }
            #previewSurface { background: #08090c; border: 1px solid #2c3340; border-radius: 8px; }
            #editorTimeline { background: #171a21; border: 1px solid #292f3b; border-radius: 8px; }
            #timelineWorkspace { background: #15171b; border: 1px solid #292d33; border-radius: 8px; }
            #editorTimeline QCheckBox { color: #9ca5b6; font-size: 10px; spacing: 3px; }
            #editorTimeline QComboBox { padding: 3px 5px; min-width: 86px; }
            #editorTimeline QPushButton { padding: 3px 7px; min-width: 24px; }
            #propertiesColumn { background: #171a21; border: 1px solid #292f3b; border-radius: 8px; }
            #editorInspector { background: #171a21; border: 0; }
            #editorToolRail { background: #1b1e27; border: 1px solid #292f3b; border-radius: 10px; }
            #editorBrandMark { color: white; background: #5b50d6; border-radius: 10px; font-size: 18px;
                font-weight: 800; min-height: 42px; max-height: 42px; }
            #editorRailLabel { color: #7f899c; font-size: 9px; font-weight: 700; letter-spacing: 1px; }
            #editorToolButton { background: transparent; border: 1px solid transparent; border-radius: 7px;
                color: #aeb7c7; font-size: 10px; padding: 5px 2px; }
            #editorToolButton:hover { background: #292f3b; color: #ffffff; }
            #editorToolButton:checked { background: #4e43b2; border-color: #7168e9; color: #ffffff; }
            #editorAiButton { color: #b8a9ff; border-color: #3f376f; }
            QTabWidget::pane { border: 1px solid #2d3442; border-radius: 6px; top: -1px; }
            QTabBar::tab { background: #1e222c; color: #929bad; padding: 7px 7px; margin-right: 1px; font-size: 10px; }
            QTabBar::tab:selected { background: #4e43b2; color: #ffffff; }
            #editorInspector QTabBar::scroller { width: 18px; }
            #editorInspector QTabBar::tear { width: 0px; }
            QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox { background: #202530; border: 1px solid #363e4d;
                border-radius: 5px; padding: 5px 7px; color: #eef1f7; }
            QSlider::groove:horizontal { height: 4px; background: #343b49; border-radius: 2px; }
            QSlider::handle:horizontal { width: 12px; margin: -5px 0; background: #7168e9; border-radius: 6px; }
            QScrollArea { border: 0; background: #171a21; }
            QScrollBar:horizontal { height: 10px; background: #171a21; }
            QScrollBar::handle:horizontal { background: #454d5d; border-radius: 5px; min-width: 30px; }
            QProgressBar { border: 1px solid #343b49; border-radius: 5px; text-align: center; background: #202530; }
            QProgressBar::chunk { background: #5b50d6; border-radius: 4px; }
            """
        )
