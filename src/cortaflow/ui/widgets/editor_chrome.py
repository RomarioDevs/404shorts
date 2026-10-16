"""Professional editor workspace widgets.

The widgets in this module are presentation-only. Editing commands remain in
``EditorPage`` so the visual redesign does not replace the existing domain or
service layer.
"""

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


class EditorToolRail(QFrame):
    """Compact tool rail kept for compatibility with existing consumers."""

    tool_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("editorToolRail")
        self.setMinimumWidth(82)
        self.setMaximumWidth(96)
        self.buttons: dict[str, QToolButton] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 12, 8, 12)
        layout.setSpacing(6)

        brand = QLabel("CF")
        brand.setObjectName("editorBrandMark")
        brand.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(brand)

        label = QLabel("EDITAR")
        label.setObjectName("editorRailLabel")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(label)
        layout.addSpacing(6)

        tools = (
            ("media", "Mídia", "▧"),
            ("audio", "Áudio", "♫"),
            ("text", "Texto", "T"),
            ("captions", "Legendas", "CC"),
            ("effects", "Efeitos", "✦"),
            ("transitions", "Transições", "◈"),
            ("image", "Imagem", "▣"),
        )
        for key, title, glyph in tools:
            button = self._create_tool_button(key, title, glyph)
            layout.addWidget(button)

        layout.addStretch(1)

        ai_button = self._create_tool_button("ai", "IA", "AI")
        ai_button.setObjectName("editorAiButton")
        layout.addWidget(ai_button)

        help_label = QLabel("F1 ajuda")
        help_label.setObjectName("editorRailHint")
        help_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(help_label)

    def _create_tool_button(self, key: str, title: str, glyph: str) -> QToolButton:
        button = QToolButton(self)
        button.setObjectName("editorToolButton")
        button.setText(f"{glyph}\n{title}")
        button.setToolTip(title)
        button.setCheckable(True)
        button.setAutoExclusive(True)
        button.setMinimumHeight(52)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(lambda _checked=False, name=key: self._request(name))
        self.buttons[key] = button
        return button

    def _request(self, key: str) -> None:
        button = self.buttons.get(key)
        if button is not None:
            button.setChecked(True)
        self.tool_requested.emit(key)

    def activate(self, key: str) -> None:
        button = self.buttons.get(key)
        if button is not None:
            button.setChecked(True)


class EditorResourcePanel(QFrame):
    """CapCut-inspired resource browser for the left side of the editor."""

    resource_requested = Signal(str)
    import_requested = Signal()
    asset_requested = Signal(str)

    _resources = (
        ("media", "Mídia", "▧"),
        ("audio", "Áudio", "♫"),
        ("text", "Texto", "T"),
        ("image", "Imagem", "IMG"),
        ("stickers", "Stickers", "★"),
        ("effects", "Efeitos", "✦"),
        ("transitions", "Transições", "◈"),
        ("filters", "Filtros", "◐"),
        ("captions", "Legendas", "CC"),
        ("templates", "Modelos", "▤"),
        ("ai", "IA", "AI"),
    )

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("editorResourcePanel")
        self.setMinimumWidth(350)
        self.setMaximumWidth(480)
        self.buttons: dict[str, QToolButton] = {}
        self.current_resource = "media"
        self.current_media: Path | None = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(8)

        rail = QWidget(self)
        rail_layout = QVBoxLayout(rail)
        rail_layout.setContentsMargins(0, 3, 0, 3)
        rail_layout.setSpacing(5)
        rail.setFixedWidth(42)
        layout.addWidget(rail)

        content = QWidget(self)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(4, 4, 4, 4)
        content_layout.setSpacing(8)
        layout.addWidget(content, 1)
        layout = content_layout

        top_row = QHBoxLayout()
        brand = QLabel("CortaFlow")
        brand.setObjectName("editorResourceBrand")
        top_row.addWidget(brand)
        top_row.addStretch(1)
        self.import_button = QPushButton("＋ Importar")
        self.import_button.setObjectName("editorImportButton")
        self.import_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.import_button.clicked.connect(self.import_requested)
        top_row.addWidget(self.import_button)
        layout.addLayout(top_row)

        project_row = QHBoxLayout()
        project_label = QLabel("BIBLIOTECA")
        project_label.setObjectName("editorResourceLabel")
        project_row.addWidget(project_label)
        project_row.addStretch(1)
        self.source_combo = QComboBox()
        self.source_combo.addItems(["Projeto", "Meu computador", "Favoritos", "Biblioteca"])
        self.source_combo.setObjectName("editorSourceCombo")
        project_row.addWidget(self.source_combo)
        layout.addLayout(project_row)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Pesquisar mídia, texto ou efeitos...")
        self.search.setObjectName("editorResourceSearch")
        self.search.textChanged.connect(self._filter_cards)
        layout.addWidget(self.search)

        for key, title, glyph in self._resources:
            button = QToolButton(self)
            button.setObjectName("editorResourceButton")
            button.setText(glyph)
            button.setToolTip(title)
            button.setCheckable(True)
            button.setAutoExclusive(True)
            button.setFixedSize(36, 36)
            button.clicked.connect(lambda _checked=False, name=key: self._request(name))
            self.buttons[key] = button
            rail_layout.addWidget(button)
        rail_layout.addStretch(1)

        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setObjectName("editorResourceDivider")
        layout.addWidget(divider)

        self.section_title = QLabel("Mídia do projeto")
        self.section_title.setObjectName("editorResourceTitle")
        layout.addWidget(self.section_title)

        self.assets_scroll = QScrollArea()
        self.assets_scroll.setWidgetResizable(True)
        self.assets_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.assets_scroll.setObjectName("editorAssetsScroll")
        self.assets_container = QWidget()
        self.asset_grid = QGridLayout(self.assets_container)
        self.asset_grid.setContentsMargins(0, 0, 0, 0)
        self.asset_grid.setHorizontalSpacing(8)
        self.asset_grid.setVerticalSpacing(8)
        self.assets_scroll.setWidget(self.assets_container)
        layout.addWidget(self.assets_scroll, 1)

        self.empty_state = QLabel(
            "Nenhum recurso no projeto.\n\nUse Importar para adicionar vídeos, imagens ou áudios."
        )
        self.empty_state.setObjectName("editorEmptyState")
        self.empty_state.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_state.setWordWrap(True)
        self.asset_grid.addWidget(self.empty_state, 0, 0, 1, 2)
        self._request("media")

    def _request(self, key: str) -> None:
        self.current_resource = key
        button = self.buttons.get(key)
        if button is not None:
            button.setChecked(True)
        labels = dict((key, title) for key, title, _ in self._resources)
        self.section_title.setText(labels.get(key, "Recursos"))
        self._render_resource_cards(key)
        self.resource_requested.emit(key)

    def activate(self, key: str) -> None:
        self._request(key)

    def set_media(self, path: Path | None) -> None:
        self.current_media = path.resolve() if path else None
        self._request("media")

    def _render_resource_cards(self, resource: str) -> None:
        while self.asset_grid.count():
            item = self.asset_grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.empty_state = None

        cards: list[tuple[str, str, str, str | None, bool]] = []
        if resource == "media" and self.current_media:
            cards.append((
                self.current_media.name,
                "MIDIA DE ORIGEM DO PROJETO",
                self.current_media.suffix.upper() or "ARQUIVO",
                None,
                True,
            ))
        elif resource == "audio":
            cards.append(("Audio original", "FAIXA VINCULADA AO VIDEO", "DISPONIVEL", None, True))
            cards.append(("Adicionar musica", "FAIXA DE MUSICA SEPARADA", "INDISPONIVEL", None, False))
        elif resource == "text":
            cards.append(("Texto basico", "CAMADA DE TEXTO EDITAVEL", "ADICIONAR", "text-basic", True))
            cards.append(("Titulo principal", "MODELO DE TITULO", "ADICIONAR", "text-title", True))
        elif resource == "image":
            cards.append(("Adicionar imagem", "CAMADA DE IMAGEM", "IMPORTAR", "image-add", True))
        elif resource == "captions":
            cards.append(("Legendas", "EDITE NA PAGINA LEGENDAS", "ABRIR ABA", "captions-page", True))
        elif resource in {"effects", "transitions", "filters", "stickers", "templates", "ai"}:
            cards.append(("Indisponivel nesta versao", "RECURSO NAO IMPLEMENTADO", "INDISPONIVEL", None, False))

        if not cards:
            empty = QLabel(
                "Nenhum recurso nesta categoria.\n"
                "Use Importar para carregar midia ou adicionar texto e imagem pela timeline."
            )
            empty.setObjectName("editorEmptyState")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setWordWrap(True)
            self.asset_grid.addWidget(empty, 0, 0, 1, 2)
            return

        for index, (title, subtitle, badge, action, enabled) in enumerate(cards):
            card = QFrame()
            card.setObjectName("editorAssetCard")
            card.setProperty("searchText", f"{title} {subtitle} {badge}".lower())
            card.setEnabled(enabled)
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(8, 8, 8, 8)
            card_layout.setSpacing(3)
            preview = QLabel(badge)
            preview.setObjectName("editorAssetPreview")
            preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
            preview.setMinimumHeight(62)
            card_layout.addWidget(preview)
            title_label = QLabel(title)
            title_label.setObjectName("editorAssetTitle")
            title_label.setWordWrap(True)
            card_layout.addWidget(title_label)
            subtitle_label = QLabel(subtitle)
            subtitle_label.setObjectName("editorAssetMeta")
            card_layout.addWidget(subtitle_label)
            if action:
                button_text = "Abrir página" if action == "captions-page" else "Adicionar"
                add_button = QPushButton(button_text)
                add_button.clicked.connect(
                    lambda _checked=False, selected_action=action:
                        self.asset_requested.emit(selected_action)
                )
                card_layout.addWidget(add_button)
            self.asset_grid.addWidget(card, index // 2, index % 2)

    def _filter_cards(self, text: str) -> None:
        query = text.strip().lower()
        for index in range(self.asset_grid.count()):
            item = self.asset_grid.itemAt(index)
            widget = item.widget()
            if widget is None:
                continue
            haystack = str(widget.property("searchText") or "")
            widget.setVisible(not query or query in haystack)


class EditorSectionHeader(QFrame):
    """Small header used to give the workspace a clear professional hierarchy."""

    def __init__(self, title: str, subtitle: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("editorSectionHeader")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(1)
        title_label = QLabel(title)
        title_label.setObjectName("editorSectionTitle")
        layout.addWidget(title_label)
        if subtitle:
            subtitle_label = QLabel(subtitle)
            subtitle_label.setObjectName("editorSectionSubtitle")
            layout.addWidget(subtitle_label)


__all__ = ["EditorToolRail", "EditorResourcePanel", "EditorSectionHeader"]
