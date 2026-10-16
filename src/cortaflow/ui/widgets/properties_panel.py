"""Right-side editor properties for clips, reframe, subtitles, audio and export."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from cortaflow.domain.editing import AudioSettings, LayerItem, ReframeSettings, SubtitleStyle, TimelineClip
from cortaflow.domain.project import ExportSettings, WatermarkSettings


class PropertiesPanel(QWidget):
    settings_changed = Signal(object)
    clip_update_requested = Signal(object)
    manual_keyframe_requested = Signal()
    layer_keyframe_requested = Signal()
    layer_update_requested = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumWidth(280)
        self.setMaximumWidth(360)
        self._loading = False
        self.selected_clip: TimelineClip | None = None
        self.selected_layer: LayerItem | None = None
        self.watermark_settings = WatermarkSettings()
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        self._create_clip_tab()
        self._create_layer_tab()
        self._create_reframe_tab()
        self._create_face_tab()
        self._create_subtitle_tab()
        self._create_audio_tab()
        self._create_export_tab()
        self.set_settings(
            ReframeSettings(),
            SubtitleStyle(),
            AudioSettings(),
            ExportSettings(),
        )

    def _create_clip_tab(self) -> None:
        page, form = self._form_page()
        self.clip_label = QLabel("Nenhum clipe selecionado")
        self.clip_timeline_start = self._spin(0, 86_400_000)
        self.clip_source_start = self._spin(0, 86_400_000)
        self.clip_source_end = self._spin(1, 86_400_000)
        self.clip_transition = self._spin(0, 5000)
        self.clip_speed = self._double(0.25, 4, 0.05)
        self.clip_fade_in = self._spin(0, 5000)
        self.clip_fade_out = self._spin(0, 5000)
        self.clip_effect = QComboBox()
        for label, value in (("Sem efeito", "none"), ("Desfoque", "blur"), ("Preto e branco", "grayscale"), ("Vintage", "vintage")):
            self.clip_effect.addItem(label, value)
        apply_button = QPushButton("Aplicar ao clipe")
        apply_button.clicked.connect(self._emit_clip_update)
        form.addRow(self.clip_label)
        form.addRow("Posição (ms)", self.clip_timeline_start)
        form.addRow("Origem início (ms)", self.clip_source_start)
        form.addRow("Origem fim (ms)", self.clip_source_end)
        form.addRow("Transição (fade de entrada, ms)", self.clip_transition)
        self.clip_transition.setToolTip(
            "Na exportação, este valor e Fade entrada usam o maior dos dois tempos."
        )
        form.addRow("Velocidade", self.clip_speed)
        form.addRow("Fade entrada (ms)", self.clip_fade_in)
        form.addRow("Fade saída (ms)", self.clip_fade_out)
        form.addRow("Efeito", self.clip_effect)
        form.addRow(apply_button)
        self.tabs.addTab(page, "Corte")

    def _create_layer_tab(self) -> None:
        page, form = self._form_page()
        self.layer_label = QLabel("Nenhuma camada selecionada")
        self.layer_timeline_start = self._spin(0, 86_400_000)
        self.layer_timeline_end = self._spin(1, 86_400_000)
        self.layer_text = QLineEdit()
        self.layer_font = QLineEdit("Arial")
        self.layer_font_size = self._spin(8, 240)
        self.layer_x = self._double(0, 100, 1)
        self.layer_y = self._double(0, 100, 1)
        self.layer_width = self._double(1, 100, 1)
        self.layer_height = self._double(1, 100, 1)
        self.layer_opacity = self._double(0, 1, 0.05)
        self.layer_visible = QCheckBox("Camada visível")
        apply_button = QPushButton("Aplicar à camada")
        apply_button.clicked.connect(self._emit_layer_update)
        keyframe_button = QPushButton("Adicionar keyframe no cursor")
        keyframe_button.clicked.connect(self.layer_keyframe_requested)
        form.addRow(self.layer_label)
        form.addRow("Início na timeline (ms)", self.layer_timeline_start)
        form.addRow("Fim na timeline (ms)", self.layer_timeline_end)
        form.addRow("Texto", self.layer_text)
        form.addRow("Fonte", self.layer_font)
        form.addRow("Tamanho", self.layer_font_size)
        form.addRow("Posição X (%)", self.layer_x)
        form.addRow("Posição Y (%)", self.layer_y)
        form.addRow("Largura (%)", self.layer_width)
        form.addRow("Altura (%)", self.layer_height)
        form.addRow("Opacidade", self.layer_opacity)
        form.addRow(self.layer_visible)
        form.addRow(apply_button)
        form.addRow(keyframe_button)
        self.tabs.addTab(page, "Camada")

    def _create_reframe_tab(self) -> None:
        page, form = self._form_page()
        self.aspect = QComboBox()
        self.aspect.addItems(["9:16", "16:9", "1:1", "4:5", "original"])
        self.crop_x, self.crop_y = self._spin(0, 20000), self._spin(0, 20000)
        self.crop_x.setToolTip("A moldura do preview atualiza estes valores ao ser arrastada.")
        self.crop_y.setToolTip("A moldura do preview atualiza estes valores ao ser arrastada.")
        self.zoom = self._double(0.25, 4, 0.05)
        self.smoothing = self._double(0, 1, 0.05)
        self.max_speed = self._spin(1, 1000)
        self.reframe_auto = QCheckBox("Modo automático")
        keyframe_button = QPushButton("Adicionar keyframe no cursor")
        keyframe_button.clicked.connect(self.manual_keyframe_requested)
        form.addRow("Proporção", self.aspect)
        form.addRow("Posição X", self.crop_x)
        form.addRow("Posição Y", self.crop_y)
        form.addRow("Zoom", self.zoom)
        form.addRow("Suavização", self.smoothing)
        form.addRow("Velocidade máx.", self.max_speed)
        form.addRow(self.reframe_auto)
        form.addRow(keyframe_button)
        self.tabs.addTab(page, "Enquadramento")
        for widget in (self.aspect, self.crop_x, self.crop_y, self.zoom, self.smoothing, self.max_speed, self.reframe_auto):
            self._connect_change(widget)

    def _create_face_tab(self) -> None:
        page, form = self._form_page()
        self.face_info = QLabel(
            "Detecção, trava de rosto e correções do falante ficam na página Analisar. "
            "O editor mostra o ID acompanhado na prévia."
        )
        self.face_info.setWordWrap(True)
        form.addRow(self.face_info)
        self.tabs.addTab(page, "Rosto")

    def _create_subtitle_tab(self) -> None:
        page, form = self._form_page()
        self.font_name = QLineEdit("Arial")
        self.font_size = self._spin(12, 160)
        self.primary_color = QLineEdit("#FFFFFF")
        self.highlight_color = QLineEdit("#FFD54F")
        self.outline_color = QLineEdit("#000000")
        self.outline_width = self._spin(0, 12)
        self.shadow = self._spin(0, 12)
        self.subtitle_background = QCheckBox("Fundo")
        self.subtitle_position = QComboBox()
        for label, value in (("Superior", "top"), ("Centro", "center"), ("Inferior", "bottom")):
            self.subtitle_position.addItem(label, value)
        self.max_words = self._spin(2, 7)
        self.subtitle_preset = QComboBox()
        self.subtitle_preset.addItem("Clean · leitura confortável", "clean")
        self.subtitle_preset.addItem("Dynamic · palavra falada", "dynamic")
        self.subtitle_preset.addItem("Viral · impacto rápido", "viral")
        self.animated = QCheckBox("Destaque da palavra falada")
        for label, widget in (
            ("Fonte", self.font_name), ("Tamanho", self.font_size), ("Cor", self.primary_color),
            ("Destaque", self.highlight_color),
            ("Contorno", self.outline_color), ("Largura", self.outline_width), ("Sombra", self.shadow),
            ("Posição", self.subtitle_position), ("Máx. palavras", self.max_words),
            ("Preset", self.subtitle_preset),
        ):
            form.addRow(label, widget)
        form.addRow(self.subtitle_background)
        form.addRow(self.animated)
        self.tabs.addTab(page, "Legenda")
        for widget in (
            self.font_name, self.font_size, self.primary_color, self.highlight_color, self.outline_color,
            self.outline_width, self.shadow, self.subtitle_background,
            self.subtitle_position, self.max_words, self.subtitle_preset, self.animated,
        ):
            self._connect_change(widget)

    def _create_audio_tab(self) -> None:
        page, form = self._form_page()
        self.audio_volume = self._double(0, 2, 0.05)
        self.normalize_audio = QCheckBox("Normalizar para -16 LUFS")
        form.addRow("Volume", self.audio_volume)
        form.addRow(self.normalize_audio)
        self.tabs.addTab(page, "Áudio")
        self._connect_change(self.audio_volume)
        self._connect_change(self.normalize_audio)

    def _create_export_tab(self) -> None:
        page, form = self._form_page()
        self.resolution = QComboBox()
        self.resolution.addItem("1920 × 1080", (1920, 1080))
        self.resolution.addItem("1080 × 1920", (1080, 1920))
        self.resolution.addItem("1080 × 1350", (1080, 1350))
        self.resolution.addItem("1080 × 1080", (1080, 1080))
        self.resolution.addItem("1280 × 720", (1280, 720))
        self.resolution.addItem("720 × 1280", (720, 1280))
        self.codec = QComboBox()
        self.codec.addItem("H.264", "h264")
        self.codec.addItem("H.265", "h265")
        self.export_fps = self._double(12, 120, 1)
        self.quality = self._spin(0, 51)
        self.use_nvenc = QCheckBox("Usar NVIDIA NVENC quando disponível")
        form.addRow("Resolução", self.resolution)
        form.addRow("Codec", self.codec)
        form.addRow("FPS", self.export_fps)
        form.addRow("Qualidade", self.quality)
        form.addRow(self.use_nvenc)
        self.tabs.addTab(page, "Exportação")
        for widget in (self.resolution, self.codec, self.export_fps, self.quality, self.use_nvenc):
            self._connect_change(widget)

    def set_settings(
        self,
        reframe: ReframeSettings,
        subtitle: SubtitleStyle,
        audio: AudioSettings,
        export: ExportSettings,
    ) -> None:
        self._loading = True
        self.aspect.setCurrentText(reframe.aspect_ratio)
        self.crop_x.setValue(reframe.x)
        self.crop_y.setValue(reframe.y)
        self.zoom.setValue(reframe.zoom)
        self.smoothing.setValue(reframe.smoothing)
        self.max_speed.setValue(reframe.max_speed_px)
        self.reframe_auto.setChecked(reframe.automatic)
        self.font_name.setText(subtitle.font_name)
        self.font_size.setValue(subtitle.font_size)
        self.primary_color.setText(subtitle.primary_color)
        self.highlight_color.setText(subtitle.highlight_color)
        self.outline_color.setText(subtitle.outline_color)
        self.outline_width.setValue(subtitle.outline_width)
        self.shadow.setValue(subtitle.shadow)
        self.subtitle_background.setChecked(subtitle.background)
        self.subtitle_position.setCurrentIndex(self.subtitle_position.findData(subtitle.position))
        self.max_words.setValue(subtitle.max_words)
        self.subtitle_preset.setCurrentIndex(self.subtitle_preset.findData(subtitle.preset))
        self.animated.setChecked(subtitle.animated)
        self.audio_volume.setValue(audio.volume)
        self.normalize_audio.setChecked(audio.normalize)
        resolution_index = self.resolution.findData((export.width, export.height))
        self.resolution.setCurrentIndex(max(0, resolution_index))
        self.codec.setCurrentIndex(max(0, self.codec.findData(export.codec)))
        self.export_fps.setValue(export.fps)
        self.quality.setValue(export.quality)
        self.use_nvenc.setChecked(export.use_nvenc)
        self.watermark_settings = export.watermark.model_copy(deep=True)
        self._loading = False

    def set_selected_clip(self, clip: TimelineClip | None) -> None:
        self.selected_clip = clip
        if clip is None:
            self.clip_label.setText("Nenhum clipe selecionado")
            return
        self.clip_label.setText(f"{clip.label} · {clip.track}")
        self.clip_timeline_start.setValue(clip.timeline_start_ms)
        self.clip_source_start.setValue(clip.source_start_ms)
        self.clip_source_end.setValue(clip.source_end_ms)
        self.clip_transition.setValue(clip.transition_ms)
        self.clip_speed.setValue(clip.speed)
        self.clip_fade_in.setValue(clip.fade_in_ms)
        self.clip_fade_out.setValue(clip.fade_out_ms)
        self.clip_effect.setCurrentIndex(max(0, self.clip_effect.findData(clip.effect)))

    def set_selected_layer(self, layer: LayerItem | None) -> None:
        self.selected_layer = layer
        self._loading = True
        if layer is None:
            self.layer_label.setText("Nenhuma camada selecionada")
            self.layer_text.clear()
        else:
            self.layer_label.setText(f"{layer.kind.title()} · {layer.item_id}")
            self.layer_timeline_start.setValue(layer.timeline_start_ms)
            self.layer_timeline_end.setValue(layer.timeline_end_ms)
            self.layer_text.setText(layer.text)
            self.layer_font.setText(layer.font_name)
            self.layer_font_size.setValue(layer.font_size)
            self.layer_x.setValue(layer.x_percent)
            self.layer_y.setValue(layer.y_percent)
            self.layer_width.setValue(layer.width_percent)
            self.layer_height.setValue(layer.height_percent)
            self.layer_opacity.setValue(layer.opacity)
            self.layer_visible.setChecked(layer.visible)
        self._loading = False

    def _emit_layer_update(self) -> None:
        if self._loading or self.selected_layer is None:
            return
        if self.layer_timeline_end.value() <= self.layer_timeline_start.value():
            return
        self.layer_update_requested.emit(
            {
                "item_id": self.selected_layer.item_id,
                "timeline_start_ms": self.layer_timeline_start.value(),
                "timeline_end_ms": self.layer_timeline_end.value(),
                "text": self.layer_text.text(),
                "font_name": self.layer_font.text().strip() or "Arial",
                "font_size": self.layer_font_size.value(),
                "x_percent": self.layer_x.value(),
                "y_percent": self.layer_y.value(),
                "width_percent": self.layer_width.value(),
                "height_percent": self.layer_height.value(),
                "opacity": self.layer_opacity.value(),
                "visible": self.layer_visible.isChecked(),
            }
        )

    def set_watermark_settings(self, watermark: WatermarkSettings) -> None:
        """Keep watermark state when export settings are edited from either page."""
        self.watermark_settings = watermark.model_copy(deep=True)

    def set_manual_crop_origin(self, x: int, y: int) -> None:
        """Apply a dragged crop position and keep it fixed for the export."""
        self._loading = True
        self.crop_x.setValue(x)
        self.crop_y.setValue(y)
        self.reframe_auto.setChecked(False)
        self._loading = False
        self._emit_settings()

    def _emit_settings(self) -> None:
        if self._loading:
            return
        try:
            reframe = ReframeSettings(
                aspect_ratio=self.aspect.currentText(), x=self.crop_x.value(), y=self.crop_y.value(),
                zoom=self.zoom.value(), smoothing=self.smoothing.value(),
                max_speed_px=self.max_speed.value(), automatic=self.reframe_auto.isChecked(),
            )
            subtitle = SubtitleStyle(
                font_name=self.font_name.text().strip() or "Arial", font_size=self.font_size.value(),
                primary_color=self.primary_color.text().strip(), outline_color=self.outline_color.text().strip(),
                highlight_color=self.highlight_color.text().strip(),
                outline_width=self.outline_width.value(), shadow=self.shadow.value(),
                background=self.subtitle_background.isChecked(), position=self.subtitle_position.currentData(),
                max_words=self.max_words.value(), preset=self.subtitle_preset.currentData(),
                animated=self.animated.isChecked(),
            )
            audio = AudioSettings(volume=self.audio_volume.value(), normalize=self.normalize_audio.isChecked())
            width, height = self.resolution.currentData()
            export = ExportSettings(
                width=width, height=height, fps=self.export_fps.value(), codec=self.codec.currentData(),
                quality=self.quality.value(), use_nvenc=self.use_nvenc.isChecked(),
                normalize_audio=self.normalize_audio.isChecked(),
                watermark=self.watermark_settings.model_copy(deep=True),
            )
        except ValueError:
            return
        self.settings_changed.emit((reframe, subtitle, audio, export))

    def _emit_clip_update(self) -> None:
        if self.selected_clip:
            self.clip_update_requested.emit(
                {
                    "clip_id": self.selected_clip.clip_id,
                    "timeline_start_ms": self.clip_timeline_start.value(),
                    "source_start_ms": self.clip_source_start.value(),
                    "source_end_ms": self.clip_source_end.value(),
                    "transition_ms": self.clip_transition.value(),
                    "speed": self.clip_speed.value(),
                    "fade_in_ms": self.clip_fade_in.value(),
                    "fade_out_ms": self.clip_fade_out.value(),
                    "effect": self.clip_effect.currentData(),
                }
            )

    def _connect_change(self, widget: QWidget) -> None:
        signal = (
            widget.currentIndexChanged if isinstance(widget, QComboBox)
            else widget.textChanged if isinstance(widget, QLineEdit)
            else widget.toggled if isinstance(widget, QCheckBox)
            else widget.valueChanged
        )
        signal.connect(self._emit_settings)

    @staticmethod
    def _form_page() -> tuple[QWidget, QFormLayout]:
        page = QWidget()
        return page, QFormLayout(page)

    @staticmethod
    def _spin(minimum: int, maximum: int) -> QSpinBox:
        widget = QSpinBox()
        widget.setRange(minimum, maximum)
        return widget

    @staticmethod
    def _double(minimum: float, maximum: float, step: float) -> QDoubleSpinBox:
        widget = QDoubleSpinBox()
        widget.setRange(minimum, maximum)
        widget.setSingleStep(step)
        widget.setDecimals(3)
        return widget
