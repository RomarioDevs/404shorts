"""Scene, silence and automatic clip analysis page."""

from functools import partial
from pathlib import Path
from typing import Any

from PySide6.QtCore import QThreadPool, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from cortaflow.config import AppConfig
from cortaflow.domain.analysis import AnalysisResult, ClipSelectionSettings
from cortaflow.domain.project import ReframeKeyframe
from cortaflow.domain.subtitle import Transcript
from cortaflow.domain.tracking import FaceTrackPoint
from cortaflow.domain.tracking import SpeakerKeyframe, SpeakerOverride
from cortaflow.services.analysis_service import analyze_media
from cortaflow.services.auto_reframe import generate_reframe_keyframes
from cortaflow.services.face_analysis import analyze_faces
from cortaflow.services.face_detection import find_local_face_landmarker
from cortaflow.services.semantic_models import SemanticModelManager, find_ollama_assets
from cortaflow.services.semantic_ranking import OllamaClipRanker, QwenClipRanker
from cortaflow.services.speaker_analysis import (
    analyze_active_speaker,
    apply_speaker_overrides,
)
from cortaflow.services.auto_reframe import generate_speaker_reframe_keyframes
from cortaflow.workers.base_worker import FunctionWorker


class AnalysisPage(QWidget):
    analysis_finished = Signal(object)
    face_analysis_finished = Signal(object)
    face_selection_changed = Signal(object)
    speaker_analysis_finished = Signal(object)
    speaker_overrides_changed = Signal(object)
    selection_settings_changed = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.source_path: Path | None = None
        self.transcript: Transcript | None = None
        self.total_duration_ms = 0
        self.source_width = 0
        self.source_height = 0
        self.scenes = []
        self.silences = []
        self.face_tracks: list[FaceTrackPoint] = []
        self.reframe_keyframes: list[ReframeKeyframe] = []
        self.speaker_keyframes: list[SpeakerKeyframe] = []
        self.speaker_overrides: list[SpeakerOverride] = []
        self.selection_settings = ClipSelectionSettings()
        model_manager = SemanticModelManager(AppConfig().cache_dir / "models" / "semantic")
        ollama_assets = find_ollama_assets()
        semantic_assets = model_manager.assets()
        if ollama_assets:
            self.semantic_ranker = OllamaClipRanker(ollama_assets)
            semantic_status = "IA semântica pronta · Ollama · Qwen3-4B Q4_K_M."
        elif semantic_assets:
            self.semantic_ranker = QwenClipRanker(semantic_assets)
            semantic_status = (
                f"IA semântica local pronta · {semantic_assets.backend} · Qwen3-4B Q4_K_M."
            )
        else:
            self.semantic_ranker = None
            semantic_status = (
                "IA semântica não localizada · o modo automático usará a heurística local."
            )
        self.current_worker: FunctionWorker | None = None
        self.thread_pool = QThreadPool.globalInstance()

        layout = QVBoxLayout(self)
        title = QLabel("Analisar conteúdo")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        self.summary = QLabel("Importe e transcreva uma mídia para gerar sugestões.")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        duration_row = QHBoxLayout()
        duration_row.addWidget(QLabel("Duração mínima (s)"))
        self.minimum_seconds = QSpinBox()
        self.minimum_seconds.setRange(5, 179)
        duration_row.addWidget(self.minimum_seconds)
        duration_row.addWidget(QLabel("preferida (s)"))
        self.preferred_seconds = QSpinBox()
        self.preferred_seconds.setRange(5, 179)
        duration_row.addWidget(self.preferred_seconds)
        duration_row.addWidget(QLabel("máxima (s)"))
        self.maximum_seconds = QSpinBox()
        self.maximum_seconds.setRange(5, 179)
        duration_row.addWidget(self.maximum_seconds)
        duration_row.addWidget(QLabel("quantidade"))
        self.maximum_results = QSpinBox()
        self.maximum_results.setRange(1, 50)
        duration_row.addWidget(self.maximum_results)
        duration_row.addStretch()
        layout.addLayout(duration_row)
        ranking_row = QHBoxLayout()
        ranking_row.addWidget(QLabel("Modo de ranking"))
        self.ranking_mode = QComboBox()
        self.ranking_mode.addItem("Automático · IA local com fallback", "automatic")
        self.ranking_mode.addItem("Somente heurística local", "heuristic")
        ranking_row.addWidget(self.ranking_mode)
        self.auto_accept = QCheckBox("Aceitar automaticamente a partir de")
        ranking_row.addWidget(self.auto_accept)
        self.auto_accept_score = QSpinBox()
        self.auto_accept_score.setRange(0, 100)
        self.auto_accept_score.setSuffix("%")
        self.auto_accept_score.setValue(80)
        ranking_row.addWidget(self.auto_accept_score)
        ranking_row.addStretch()
        layout.addLayout(ranking_row)
        goal_row = QHBoxLayout()
        goal_row.addWidget(QLabel("Objetivo dos cortes"))
        self.selection_goal = QComboBox()
        self.selection_goal.addItem("Equilibrado · relevância e potencial", "balanced")
        self.selection_goal.addItem("Fiel ao conteúdo · ideias completas", "faithful")
        self.selection_goal.addItem("Maior potencial de compartilhamento", "viral")
        self.selection_goal.addItem("Tema específico", "topic")
        goal_row.addWidget(self.selection_goal)
        self.topic_prompt = QLineEdit()
        self.topic_prompt.setPlaceholderText("Tema que deve aparecer nos cortes")
        goal_row.addWidget(self.topic_prompt, 1)
        layout.addLayout(goal_row)
        context_row = QHBoxLayout()
        context_row.addWidget(QLabel("Público"))
        self.audience = QLineEdit()
        self.audience.setPlaceholderText("Ex.: torcedores brasileiros interessados em opinião")
        context_row.addWidget(self.audience, 1)
        context_row.addWidget(QLabel("Vocabulário-chave"))
        self.vocabulary = QLineEdit()
        self.vocabulary.setPlaceholderText("Separe termos por vírgula: Palmeiras, Flamengo, Cimed")
        context_row.addWidget(self.vocabulary, 1)
        layout.addLayout(context_row)
        self.ranking_status = QLabel(semantic_status)
        self.ranking_status.setWordWrap(True)
        layout.addWidget(self.ranking_status)
        row = QHBoxLayout()
        self.analyze_button = QPushButton("Detectar cenas, silêncios e cortes")
        self.analyze_button.clicked.connect(self.start_analysis)
        self.cancel_button = QPushButton("Cancelar")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_current)
        row.addWidget(self.analyze_button)
        row.addWidget(self.cancel_button)
        row.addStretch()
        layout.addLayout(row)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        layout.addWidget(self.progress)
        self.status = QLabel("")
        layout.addWidget(self.status)

        face_title = QLabel("Rostos e reenquadramento 9:16")
        face_title.setObjectName("pageTitle")
        layout.addWidget(face_title)
        model_row = QHBoxLayout()
        self.face_model_path = QLineEdit()
        self.face_model_path.setPlaceholderText("Selecione um modelo Face Landmarker .task obtido da fonte oficial")
        local_face_model = find_local_face_landmarker()
        if local_face_model:
            self.face_model_path.setText(str(local_face_model))
        model_button = QPushButton("Selecionar modelo local")
        model_button.clicked.connect(self.choose_face_model)
        model_row.addWidget(self.face_model_path, 1)
        model_row.addWidget(model_button)
        layout.addLayout(model_row)
        face_row = QHBoxLayout()
        self.analyze_faces_button = QPushButton("Detectar e rastrear rostos")
        self.analyze_faces_button.clicked.connect(self.start_face_analysis)
        self.face_selector = QComboBox()
        self.face_selector.addItem("Automático · maior rosto", None)
        self.apply_face_button = QPushButton("Acompanhar rosto selecionado")
        self.apply_face_button.clicked.connect(self.apply_face_selection)
        face_row.addWidget(self.analyze_faces_button)
        face_row.addWidget(self.face_selector)
        face_row.addWidget(self.apply_face_button)
        face_row.addStretch()
        layout.addLayout(face_row)
        self.face_status = QLabel(
            "Modelo facial local pronto; a criação automática detectará os rostos."
            if local_face_model
            else "Nenhum rosto analisado. Somente caixas e IDs temporários serão armazenados."
        )
        self.face_status.setWordWrap(True)
        layout.addWidget(self.face_status)

        speaker_title = QLabel("Falante ativo")
        speaker_title.setObjectName("pageTitle")
        layout.addWidget(speaker_title)
        speaker_row = QHBoxLayout()
        self.analyze_speaker_button = QPushButton("Analisar falante ativo")
        self.analyze_speaker_button.clicked.connect(self.start_speaker_analysis)
        speaker_row.addWidget(self.analyze_speaker_button)
        speaker_row.addStretch()
        layout.addLayout(speaker_row)
        correction_row = QHBoxLayout()
        correction_row.addWidget(QLabel("Correção manual · início (s)"))
        self.override_start = QDoubleSpinBox()
        self.override_start.setDecimals(3)
        correction_row.addWidget(self.override_start)
        correction_row.addWidget(QLabel("fim (s)"))
        self.override_end = QDoubleSpinBox()
        self.override_end.setDecimals(3)
        correction_row.addWidget(self.override_end)
        self.override_face = QComboBox()
        correction_row.addWidget(self.override_face)
        self.add_override_button = QPushButton("Aplicar correção")
        self.add_override_button.clicked.connect(self.add_speaker_override)
        correction_row.addWidget(self.add_override_button)
        correction_row.addStretch()
        layout.addLayout(correction_row)
        self.speaker_status = QLabel(
            "A identificação é probabilística; em caso de incerteza, o enquadramento mostra o grupo."
        )
        self.speaker_status.setWordWrap(True)
        layout.addWidget(self.speaker_status)
        layout.addStretch()
        for widget in (
            self.minimum_seconds,
            self.preferred_seconds,
            self.maximum_seconds,
            self.maximum_results,
            self.auto_accept_score,
        ):
            widget.valueChanged.connect(self._selection_edited)
        self.ranking_mode.currentIndexChanged.connect(self._selection_edited)
        self.selection_goal.currentIndexChanged.connect(self._selection_edited)
        self.topic_prompt.textChanged.connect(self._selection_edited)
        self.audience.textChanged.connect(self._selection_edited)
        self.vocabulary.textChanged.connect(self._selection_edited)
        self.auto_accept.toggled.connect(self._selection_edited)
        self._load_selection_settings(self.selection_settings)
        self._update_actions()

    def set_context(
        self,
        source_path: Path | None,
        transcript: Transcript | None,
        total_duration_ms: int = 0,
        source_width: int = 0,
        source_height: int = 0,
        scenes: list | None = None,
        silences: list | None = None,
        selection_settings: ClipSelectionSettings | None = None,
    ) -> None:
        self.source_path = source_path.resolve() if source_path else None
        self.transcript = transcript
        self.total_duration_ms = max(0, total_duration_ms)
        self.source_width = max(0, source_width)
        self.source_height = max(0, source_height)
        self.scenes = list(scenes or [])
        self.silences = list(silences or [])
        self.selection_settings = selection_settings or self.selection_settings
        self._load_selection_settings(self.selection_settings)
        maximum_seconds = self.total_duration_ms / 1000
        self.override_start.setRange(0, maximum_seconds)
        self.override_end.setRange(0, maximum_seconds)
        self.override_end.setValue(maximum_seconds)
        if source_path and transcript:
            self.summary.setText("Mídia e transcrição prontas para análise local.")
        elif source_path:
            self.summary.setText("Transcreva a mídia antes de gerar cortes sugeridos.")
        else:
            self.summary.setText("Importe e transcreva uma mídia para gerar sugestões.")
        self._update_actions()

    def set_transcript(self, transcript: Transcript | None) -> None:
        self.set_context(
            self.source_path,
            transcript,
            self.total_duration_ms,
            self.source_width,
            self.source_height,
            self.scenes,
            self.silences,
            self.selection_settings,
        )

    def set_scenes(self, scenes: list) -> None:
        self.scenes = list(scenes)

    def restore_faces(
        self,
        tracks: list[FaceTrackPoint],
        keyframes: list[ReframeKeyframe],
        selected_track_id: int | None,
    ) -> None:
        self.face_tracks = list(tracks)
        self.reframe_keyframes = list(keyframes)
        self._populate_face_selector(selected_track_id)
        self._populate_override_faces()
        self.face_status.setText(
            f"{len(self.face_tracks)} observações anônimas · {len(set(point.track_id for point in tracks))} IDs temporários."
            if tracks
            else "Nenhum rosto analisado. Somente caixas e IDs temporários serão armazenados."
        )
        self._update_actions()

    def restore_speakers(
        self,
        keyframes: list[SpeakerKeyframe],
        overrides: list[SpeakerOverride],
    ) -> None:
        self.speaker_keyframes = list(keyframes)
        self.speaker_overrides = list(overrides)
        if keyframes:
            uncertain = sum(item.uncertain for item in keyframes)
            self.speaker_status.setText(
                f"{len(keyframes)} decisões · {uncertain} incertas · {len(overrides)} correções manuais."
            )
        self._update_actions()

    def start_analysis(self) -> None:
        if not self.source_path or not self.transcript:
            QMessageBox.warning(self, "Dados incompletos", "Importe e transcreva uma mídia primeiro.")
            return
        analysis_options = {}
        if self.face_tracks:
            analysis_options["face_tracks"] = list(self.face_tracks)
        if self.selection_settings.ranking_mode == "automatic" and self.semantic_ranker:
            analysis_options["ranker"] = self.semantic_ranker
        operation = partial(analyze_media, **analysis_options) if analysis_options else analyze_media
        worker = FunctionWorker(
            operation,
            self.source_path,
            self.transcript,
            self.total_duration_ms,
            self.selection_settings,
        )
        worker.signals.progress.connect(self._progressed)
        worker.signals.finished.connect(self._finished)
        worker.signals.failed.connect(self._failed)
        self.current_worker = worker
        self.progress.show()
        self.status.setText("Iniciando análise…")
        self._update_actions()
        self.thread_pool.start(worker)

    def _selection_edited(self) -> None:
        self.auto_accept_score.setEnabled(self.auto_accept.isChecked())
        goal = self.selection_goal.currentData()
        topic = self.topic_prompt.text().strip()
        self.topic_prompt.setEnabled(goal == "topic")
        if goal == "topic" and not topic:
            self.topic_prompt.setFocus()
            return
        minimum = self.minimum_seconds.value()
        maximum = self.maximum_seconds.value()
        if minimum > maximum:
            sender = self.sender()
            if sender is self.minimum_seconds:
                self.maximum_seconds.setValue(minimum)
                maximum = minimum
            else:
                self.minimum_seconds.setValue(maximum)
                minimum = maximum
        preferred = min(max(self.preferred_seconds.value(), minimum), maximum)
        if preferred != self.preferred_seconds.value():
            self.preferred_seconds.setValue(preferred)
        self.selection_settings = ClipSelectionSettings(
            min_seconds=minimum,
            preferred_seconds=preferred,
            max_seconds=maximum,
            max_results=self.maximum_results.value(),
            ranking_mode=self.ranking_mode.currentData(),
            selection_goal=goal,
            topic_prompt=topic,
            audience=self.audience.text().strip(),
            vocabulary=[
                item.strip()
                for item in self.vocabulary.text().split(",")
                if item.strip()
            ][:60],
            auto_accept_threshold=(
                self.auto_accept_score.value() / 100 if self.auto_accept.isChecked() else None
            ),
        )
        self.selection_settings_changed.emit(self.selection_settings)

    def _load_selection_settings(self, settings: ClipSelectionSettings) -> None:
        widgets = (
            self.minimum_seconds,
            self.preferred_seconds,
            self.maximum_seconds,
            self.maximum_results,
            self.ranking_mode,
            self.selection_goal,
            self.topic_prompt,
            self.audience,
            self.vocabulary,
            self.auto_accept,
            self.auto_accept_score,
        )
        for widget in widgets:
            widget.blockSignals(True)
        self.minimum_seconds.setValue(settings.min_seconds)
        self.preferred_seconds.setValue(settings.preferred_seconds)
        self.maximum_seconds.setValue(settings.max_seconds)
        self.maximum_results.setValue(settings.max_results)
        self.ranking_mode.setCurrentIndex(max(0, self.ranking_mode.findData(settings.ranking_mode)))
        self.selection_goal.setCurrentIndex(
            max(0, self.selection_goal.findData(settings.selection_goal))
        )
        self.topic_prompt.setText(settings.topic_prompt)
        self.topic_prompt.setEnabled(settings.selection_goal == "topic")
        self.audience.setText(settings.audience)
        self.vocabulary.setText(", ".join(settings.vocabulary))
        self.auto_accept.setChecked(settings.auto_accept_threshold is not None)
        if settings.auto_accept_threshold is not None:
            self.auto_accept_score.setValue(round(settings.auto_accept_threshold * 100))
        self.auto_accept_score.setEnabled(settings.auto_accept_threshold is not None)
        for widget in widgets:
            widget.blockSignals(False)

    def _progressed(self, state: dict[str, Any]) -> None:
        self.status.setText(str(state.get("message", "Analisando…")))

    def _finished(self, result: AnalysisResult) -> None:
        release = getattr(self.semantic_ranker, "release", None)
        if callable(release):
            release()
        self._finish_worker()
        self.summary.setText(
            f"{len(result.scenes)} cenas · {len(result.silences)} silêncios · "
            f"{len(result.suggestions)} cortes sugeridos"
        )
        self.status.setText("Análise concluída.")
        self.scenes = list(result.scenes)
        self.analysis_finished.emit(result)

    def choose_face_model(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Selecionar modelo oficial Face Landmarker",
            "",
            "Modelo MediaPipe (*.task);;Todos os arquivos (*)",
        )
        if filename:
            self.face_model_path.setText(filename)
            self._update_actions()

    def start_face_analysis(self) -> None:
        if not self.source_path:
            QMessageBox.warning(self, "Mídia ausente", "Importe uma mídia antes de analisar rostos.")
            return
        model_path = Path(self.face_model_path.text().strip())
        if model_path.suffix.lower() != ".task" or not model_path.is_file():
            QMessageBox.warning(
                self,
                "Modelo ausente",
                "Selecione um arquivo .task oficial do MediaPipe Face Landmarker.",
            )
            return
        selected = self.face_selector.currentData()
        worker = FunctionWorker(
            analyze_faces,
            self.source_path,
            model_path,
            list(self.scenes),
            selected,
            200,
        )
        worker.signals.progress.connect(self._face_progressed)
        worker.signals.finished.connect(self._faces_finished)
        worker.signals.failed.connect(self._failed)
        self.current_worker = worker
        self.progress.show()
        self.face_status.setText("Iniciando detecção facial local…")
        self._update_actions()
        self.thread_pool.start(worker)

    def _face_progressed(self, state: dict[str, Any]) -> None:
        position = int(state.get("position_ms", 0))
        duration = int(state.get("duration_ms", 0))
        percentage = round(position * 100 / duration) if duration else 0
        self.face_status.setText(
            f"Analisando rostos localmente · {percentage}% · {state.get('faces', 0)} no quadro"
        )

    def _faces_finished(self, result: tuple[list[FaceTrackPoint], list[ReframeKeyframe]]) -> None:
        self.face_tracks, self.reframe_keyframes = result
        selected = self.face_selector.currentData()
        self._populate_face_selector(selected)
        self._finish_worker()
        unique_ids = sorted({point.track_id for point in self.face_tracks})
        self.face_status.setText(
            f"Análise facial concluída · {len(unique_ids)} IDs temporários · "
            f"{len(self.reframe_keyframes)} enquadramentos."
        )
        self.face_analysis_finished.emit(
            (list(self.face_tracks), list(self.reframe_keyframes), self.face_selector.currentData())
        )

    def apply_face_selection(self) -> None:
        if not self.face_tracks:
            return
        selected = self.face_selector.currentData()
        self.reframe_keyframes = generate_reframe_keyframes(
            self.face_tracks,
            self.source_width,
            self.source_height,
            selected_track_id=selected,
            scene_boundaries_ms=[scene.start_ms for scene in self.scenes if scene.start_ms > 0],
        )
        label = f"rosto {selected}" if selected is not None else "modo automático"
        self.face_status.setText(f"Enquadramento atualizado para {label}.")
        self.face_selection_changed.emit((selected, list(self.reframe_keyframes)))

    def _populate_face_selector(self, selected_track_id: int | None) -> None:
        self.face_selector.blockSignals(True)
        self.face_selector.clear()
        self.face_selector.addItem("Automático · maior rosto", None)
        for track_id in sorted({point.track_id for point in self.face_tracks}):
            self.face_selector.addItem(f"Rosto temporário {track_id}", track_id)
        index = self.face_selector.findData(selected_track_id)
        self.face_selector.setCurrentIndex(max(0, index))
        self.face_selector.blockSignals(False)
        self._populate_override_faces()

    def _populate_override_faces(self) -> None:
        selected = self.override_face.currentData()
        self.override_face.clear()
        for track_id in sorted({point.track_id for point in self.face_tracks}):
            self.override_face.addItem(f"Rosto temporário {track_id}", track_id)
        index = self.override_face.findData(selected)
        if index >= 0:
            self.override_face.setCurrentIndex(index)

    def start_speaker_analysis(self) -> None:
        if not self.source_path or not self.face_tracks:
            QMessageBox.warning(
                self,
                "Rostos ausentes",
                "Detecte e rastreie os rostos antes de analisar o falante ativo.",
            )
            return
        worker = FunctionWorker(
            analyze_active_speaker,
            self.source_path,
            list(self.face_tracks),
            self.source_width,
            self.source_height,
            self.transcript,
            list(self.silences),
            list(self.scenes),
            list(self.speaker_overrides),
        )
        worker.signals.progress.connect(self._speaker_progressed)
        worker.signals.finished.connect(self._speaker_finished)
        worker.signals.failed.connect(self._failed)
        self.current_worker = worker
        self.progress.show()
        self.speaker_status.setText("Analisando voz, energia e movimento da boca…")
        self._update_actions()
        self.thread_pool.start(worker)

    def _speaker_progressed(self, state: dict[str, Any]) -> None:
        if state.get("status") == "audio":
            self.speaker_status.setText("Extraindo energia e atividade de voz…")
        elif state.get("status") == "speaker":
            track_id = state.get("track_id")
            label = f"rosto {track_id}" if track_id else "incerto/grupo"
            confidence = float(state.get("confidence", 0) or 0)
            self.speaker_status.setText(
                f"Correlacionando evidências · foco atual: {label} · "
                f"confiança {confidence:.0%}"
            )

    def _speaker_finished(
        self,
        result: tuple[list[SpeakerKeyframe], list[ReframeKeyframe]],
    ) -> None:
        self.speaker_keyframes, self.reframe_keyframes = result
        self._finish_worker()
        uncertain = sum(item.uncertain for item in self.speaker_keyframes)
        switches = sum(
            previous.track_id is not None
            and current.track_id is not None
            and previous.track_id != current.track_id
            for previous, current in zip(self.speaker_keyframes, self.speaker_keyframes[1:])
        )
        average_confidence = (
            sum(item.confidence for item in self.speaker_keyframes) / len(self.speaker_keyframes)
            if self.speaker_keyframes else 0
        )
        self.speaker_status.setText(
            f"Análise concluída · confiança média {average_confidence:.0%} · "
            f"{uncertain} decisões incertas de {len(self.speaker_keyframes)} · "
            f"{switches} troca(s) de falante."
        )
        self.speaker_analysis_finished.emit(
            (list(self.speaker_keyframes), list(self.reframe_keyframes))
        )

    def add_speaker_override(self) -> None:
        track_id = self.override_face.currentData()
        if track_id is None:
            return
        try:
            override = SpeakerOverride(
                start_ms=round(self.override_start.value() * 1000),
                end_ms=round(self.override_end.value() * 1000),
                track_id=track_id,
            )
        except ValueError as exc:
            QMessageBox.warning(self, "Intervalo inválido", str(exc))
            return
        self.speaker_overrides.append(override)
        self.speaker_keyframes = apply_speaker_overrides(
            self.speaker_keyframes,
            self.speaker_overrides,
        )
        self.reframe_keyframes = generate_speaker_reframe_keyframes(
            self.face_tracks,
            self.speaker_keyframes,
            self.source_width,
            self.source_height,
            scene_boundaries_ms=[scene.start_ms for scene in self.scenes if scene.start_ms > 0],
        )
        self.speaker_status.setText(
            f"Correção manual salva para o rosto {track_id}; ela terá prioridade sobre a IA."
        )
        self.speaker_overrides_changed.emit(
            (
                list(self.speaker_overrides),
                list(self.speaker_keyframes),
                list(self.reframe_keyframes),
            )
        )

    def cancel_current(self) -> None:
        if self.current_worker:
            self.current_worker.cancel()
            self.cancel_button.setEnabled(False)
            self.status.setText("Cancelando análise…")

    def _failed(self, message: str) -> None:
        self._finish_worker()
        if "cancelad" in message.lower():
            self.status.setText("Análise cancelada.")
            return
        self.status.setText("Análise não concluída.")
        QMessageBox.critical(self, "Falha na análise", message)

    def _finish_worker(self) -> None:
        self.current_worker = None
        self.progress.hide()
        self._update_actions()

    def _update_actions(self) -> None:
        busy = self.current_worker is not None
        self.analyze_button.setEnabled(
            self.source_path is not None and self.transcript is not None and not busy
        )
        self.cancel_button.setEnabled(busy)
        self.analyze_faces_button.setEnabled(self.source_path is not None and not busy)
        self.apply_face_button.setEnabled(bool(self.face_tracks) and not busy)
        self.face_selector.setEnabled(bool(self.face_tracks) and not busy)
        self.analyze_speaker_button.setEnabled(bool(self.face_tracks) and not busy)
        self.override_face.setEnabled(bool(self.face_tracks) and not busy)
        self.add_override_button.setEnabled(bool(self.face_tracks) and not busy)
