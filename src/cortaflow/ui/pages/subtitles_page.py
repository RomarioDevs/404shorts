"""Transcription controls and editable subtitle table."""

from pathlib import Path
from typing import Any

from PySide6.QtCore import QThreadPool, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cortaflow.config import AppConfig
from cortaflow.domain.clip import format_timestamp
from cortaflow.domain.subtitle import SubtitleCue, Transcript
from cortaflow.domain.editing import SubtitleStyle
from cortaflow.services.subtitles import (
    burn_subtitles,
    export_subtitles,
    export_vtt,
    merge_manual_corrections,
    save_transcript,
)
from cortaflow.services.transcription import (
    FasterWhisperTranscriber,
    diagnose_compute_device,
    whisper_model_is_cached,
)
from cortaflow.workers.base_worker import FunctionWorker


class SubtitlesPage(QWidget):
    transcript_changed = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.source_path: Path | None = None
        self.transcript: Transcript | None = None
        self.cues: list[SubtitleCue] = []
        self.style = SubtitleStyle()
        self.current_worker: FunctionWorker | None = None
        self._media_generation = 0
        self.thread_pool = QThreadPool.globalInstance()

        layout = QVBoxLayout(self)
        controls = QHBoxLayout()
        controls.addWidget(QLabel("Modelo"))
        self.model = QComboBox()
        self.model.addItem("Pequeno · menor uso de memória", "small")
        self.model.addItem("Médio · maior precisão", "medium")
        self.model.addItem("Turbo · rápido em GPU", "turbo")
        controls.addWidget(self.model)
        controls.addWidget(QLabel("Idioma"))
        self.language = QComboBox()
        self.language.addItem("Detectar automaticamente", None)
        self.language.addItem("Português", "pt")
        controls.addWidget(self.language)
        compute_status = diagnose_compute_device()
        self.device_label = QLabel(
            f"Processamento: {compute_status.device.upper()} · {compute_status.compute_type}"
        )
        self.device_label.setToolTip(compute_status.detail)
        controls.addWidget(self.device_label)
        controls.addStretch()
        self.transcribe_button = QPushButton("Transcrever")
        self.transcribe_button.clicked.connect(self.start_transcription)
        controls.addWidget(self.transcribe_button)
        self.cancel_button = QPushButton("Cancelar")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_current)
        controls.addWidget(self.cancel_button)
        layout.addLayout(controls)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        layout.addWidget(self.progress)
        self.status = QLabel("Importe uma mídia para iniciar a transcrição.")
        layout.addWidget(self.status)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Início", "Fim", "Texto"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.itemChanged.connect(self._edited)
        layout.addWidget(self.table, 1)

        buttons = QHBoxLayout()
        self.json_button = QPushButton("Salvar JSON")
        self.json_button.clicked.connect(self.export_json)
        self.srt_button = QPushButton("Exportar SRT")
        self.srt_button.clicked.connect(lambda: self.export_subtitle_file(False))
        self.ass_button = QPushButton("Exportar ASS animado")
        self.ass_button.clicked.connect(lambda: self.export_subtitle_file(True))
        self.vtt_button = QPushButton("Exportar WebVTT")
        self.vtt_button.clicked.connect(self.export_vtt_file)
        self.burn_button = QPushButton("Aplicar legenda ao vídeo")
        self.burn_button.clicked.connect(self.start_burn)
        for button in (self.json_button, self.srt_button, self.ass_button, self.vtt_button, self.burn_button):
            buttons.addWidget(button)
        buttons.addStretch()
        layout.addLayout(buttons)
        self._update_actions()

    def set_media(self, path: Path | None, transcript: Transcript | None = None) -> None:
        """Select the source and restore any transcript already stored in the project."""
        self._media_generation += 1
        worker = self.current_worker
        if worker is not None:
            self.current_worker = None
            worker.cancel()
            self.progress.hide()
        self.source_path = path.resolve() if path else None
        self.transcript = transcript
        self.set_cues(transcript.cues if transcript else [])
        if path:
            self.status.setText(f"Mídia pronta para transcrição: {path.name}")
        else:
            self.status.setText("Importe uma mídia para iniciar a transcrição.")
        self._update_actions()

    def set_style(self, style: SubtitleStyle) -> None:
        self.style = style

    def set_cues(self, cues: list[SubtitleCue]) -> None:
        self.cues = list(cues)
        self.table.blockSignals(True)
        self.table.setRowCount(len(cues))
        for row, cue in enumerate(cues):
            start_item = QTableWidgetItem(format_timestamp(cue.start_ms, include_millis=True))
            end_item = QTableWidgetItem(format_timestamp(cue.end_ms, include_millis=True))
            start_item.setFlags(start_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            end_item.setFlags(end_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 0, start_item)
            self.table.setItem(row, 1, end_item)
            self.table.setItem(row, 2, QTableWidgetItem(cue.text))
        self.table.blockSignals(False)
        self._update_actions()

    def start_transcription(self) -> None:
        if not self.source_path:
            QMessageBox.warning(self, "Mídia ausente", "Importe uma mídia antes de transcrever.")
            return
        model_cache = AppConfig().whisper_model_cache
        model_size = str(self.model.currentData())
        allow_download = False
        if not whisper_model_is_cached(model_cache, model_size):
            answer = QMessageBox.question(
                self,
                "Modelo de transcrição ausente",
                f"O modelo Faster-Whisper {model_size} não está no computador. "
                "Autoriza baixá-lo da publicação oficial Systran/Hugging Face?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                self.status.setText("Transcrição não iniciada: download do modelo não autorizado.")
                return
            allow_download = True
        transcriber = FasterWhisperTranscriber(
            model_size=model_size,
            model_cache=model_cache,
            certificate_cache=AppConfig().cache_dir / "certificates",
            allow_download=allow_download,
        )
        worker = FunctionWorker(transcriber.transcribe, self.source_path, self.language.currentData())
        self._connect_worker(worker, self._transcription_progress, self._transcription_finished)
        self._start_worker(worker, "Carregando o modelo de transcrição…")

    def _transcription_progress(self, state: dict[str, Any]) -> None:
        device = str(state.get("device", "")).upper()
        if state.get("status") == "fallback":
            self.device_label.setText("Processamento: CPU · int8 (fallback)")
            self.status.setText(str(state.get("message")))
        elif state.get("status") == "loading_model":
            self.status.setText(f"Carregando modelo {state.get('model')} em {device}…")
        else:
            position = format_timestamp(int(state.get("position_ms", 0)))
            self.status.setText(f"Transcrevendo em {device} · processado até {position}")

    def _transcription_finished(self, generated: Transcript) -> None:
        merged = merge_manual_corrections(self.cues, generated.cues)
        self.transcript = generated.model_copy(update={"cues": merged})
        self.set_cues(merged)
        self._finish_worker()
        probability = self.transcript.language_probability
        confidence = f" · confiança {probability:.0%}" if probability is not None else ""
        self.status.setText(f"Transcrição concluída · idioma {self.transcript.language}{confidence}")
        self.transcript_changed.emit(self.transcript)

    def _edited(self, item: QTableWidgetItem) -> None:
        if item.column() != 2 or not (0 <= item.row() < len(self.cues)):
            return
        self.cues[item.row()] = self.cues[item.row()].model_copy(
            update={"text": item.text(), "manually_edited": True}
        )
        if self.transcript:
            self.transcript = self.transcript.model_copy(update={"cues": list(self.cues)})
            self.transcript_changed.emit(self.transcript)

    def export_json(self) -> None:
        if not self.transcript:
            return
        filename, _ = QFileDialog.getSaveFileName(
            self, "Salvar transcrição", "transcricao.json", "Transcrição JSON (*.json)"
        )
        if filename:
            save_transcript(self.transcript, Path(filename))
            self.status.setText(f"Transcrição salva: {filename}")

    def export_subtitle_file(self, animated: bool) -> None:
        if not self.cues:
            return
        suffix = "ass" if animated else "srt"
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Exportar legendas",
            f"legendas.{suffix}",
            f"Legendas (*.{suffix})",
        )
        if filename:
            export_subtitles(self.cues, Path(filename), animated=animated, style=self.style)
            self.status.setText(f"Legendas exportadas: {filename}")

    def export_vtt_file(self) -> None:
        if not self.cues:
            return
        filename, _ = QFileDialog.getSaveFileName(
            self, "Exportar WebVTT", "legendas.vtt", "Legendas WebVTT (*.vtt)"
        )
        if filename:
            export_vtt(self.cues, Path(filename))
            self.status.setText(f"WebVTT exportado: {filename}")

    def start_burn(self) -> None:
        if not self.source_path or not self.cues:
            QMessageBox.warning(self, "Legenda ausente", "Transcreva ou carregue legendas primeiro.")
            return
        filename, _ = QFileDialog.getSaveFileName(
            self, "Salvar vídeo legendado", "video-legendado.mp4", "Vídeo MP4 (*.mp4)"
        )
        if not filename:
            return
        destination = Path(filename)
        if destination.exists():
            QMessageBox.warning(self, "Arquivo existente", "Escolha um novo nome para não sobrescrever um arquivo.")
            return
        worker = FunctionWorker(
            burn_subtitles,
            self.source_path,
            destination,
            list(self.cues),
            self.style,
        )
        self._connect_worker(
            worker,
            lambda _state: self.status.setText("Aplicando legendas ao vídeo…"),
            self._burn_finished,
        )
        self._start_worker(worker, "Aplicando legendas ao vídeo…")

    def _burn_finished(self, destination: Path) -> None:
        self._finish_worker()
        self.status.setText(f"Vídeo legendado concluído: {destination}")
        QMessageBox.information(self, "Vídeo concluído", f"Arquivo salvo em:\n{destination}")

    def cancel_current(self) -> None:
        if self.current_worker:
            self.current_worker.cancel()
            self.cancel_button.setEnabled(False)
            self.status.setText("Cancelando operação…")

    def _start_worker(self, worker: FunctionWorker, status: str) -> None:
        self.current_worker = worker
        self.progress.show()
        self.status.setText(status)
        self._update_actions()
        self.thread_pool.start(worker)

    def _connect_worker(self, worker, progress_handler, finished_handler) -> None:
        generation = self._media_generation
        worker.signals.progress.connect(
            lambda payload, worker=worker, generation=generation:
                self._dispatch_worker(worker, generation, progress_handler, payload)
        )
        worker.signals.finished.connect(
            lambda payload, worker=worker, generation=generation:
                self._dispatch_worker(worker, generation, finished_handler, payload)
        )
        worker.signals.failed.connect(
            lambda message, worker=worker, generation=generation:
                self._dispatch_worker(worker, generation, self._operation_failed, message)
        )

    def _dispatch_worker(self, worker, generation, handler, payload) -> None:
        if worker is self.current_worker and generation == self._media_generation:
            handler(payload)

    def _finish_worker(self) -> None:
        self.current_worker = None
        self.progress.hide()
        self._update_actions()

    def _operation_failed(self, message: str) -> None:
        self._finish_worker()
        if "cancelad" in message.lower():
            self.status.setText("Operação cancelada.")
            return
        self.status.setText("Operação não concluída.")
        QMessageBox.critical(self, "Operação não concluída", message)

    def _update_actions(self) -> None:
        busy = self.current_worker is not None
        has_cues = bool(self.cues)
        self.transcribe_button.setEnabled(self.source_path is not None and not busy)
        self.cancel_button.setEnabled(busy)
        for button in (self.json_button, self.srt_button, self.ass_button, self.vtt_button):
            button.setEnabled(has_cues and not busy)
        self.json_button.setEnabled(self.transcript is not None and not busy)
        self.burn_button.setEnabled(self.source_path is not None and has_cues and not busy)
