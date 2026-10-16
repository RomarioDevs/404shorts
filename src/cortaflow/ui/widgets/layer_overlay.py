"""Canvas leve para selecionar e posicionar camadas sobre o preview."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QImage, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import QWidget

from cortaflow.domain.editing import LayerItem, layer_transform_at


class LayerOverlay(QWidget):
    layer_selected = Signal(str)
    layer_moved = Signal(str, float, float)
    preview_background_pressed = Signal(QPointF)
    preview_background_moved = Signal(QPointF)
    preview_background_released = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setMouseTracking(True)
        self.setToolTip("Arraste dentro da moldura roxa para ajustar o corte. Segure Alt para arrastar sobre uma camada.")
        self.layers: list[LayerItem] = []
        self.position_ms = 0
        self.duration_ms = 1
        self.selected_id: str | None = None
        self._drag_id: str | None = None
        self._drag_offset = QPointF()
        self._background_dragging = False
        self._image_cache: dict[str, QImage] = {}
        self.output_rect = QRectF()

    def set_output_rect(self, rect: QRectF) -> None:
        self.output_rect = QRectF(rect)
        self.update()

    def set_layers(self, layers: list[LayerItem]) -> None:
        self.layers = list(layers)
        image_cache: dict[str, QImage] = {}
        for layer in self.layers:
            if layer.kind == "image" and layer.source_path:
                image = self._image_cache.get(layer.source_path)
                if image is None:
                    image = QImage(layer.source_path)
                if not image.isNull():
                    image_cache[layer.source_path] = image
        self._image_cache = image_cache
        self.update()

    def set_position(self, position_ms: int) -> None:
        self.position_ms = position_ms
        self.update()

    def set_duration(self, duration_ms: int) -> None:
        self.duration_ms = max(1, duration_ms)
        self.update()

    def select_layer(self, item_id: str | None) -> None:
        self.selected_id = item_id
        self.update()

    def _visible_layers(self) -> list[LayerItem]:
        return [
            layer for layer in self.layers
            if layer.visible and layer.timeline_start_ms <= self.position_ms < layer.timeline_end_ms
        ]

    def _rect(self, layer: LayerItem):
        bounds = self.output_rect if not self.output_rect.isEmpty() else QRectF(self.rect())
        width = bounds.width() * layer.width_percent / 100
        height = bounds.height() * layer.height_percent / 100
        transform = layer_transform_at(layer, self.position_ms)
        left = bounds.left() + bounds.width() * transform.x_percent / 100 - width / 2
        top = bounds.top() + bounds.height() * transform.y_percent / 100 - height / 2
        return left, top, width, height

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        point = event.position()
        force_crop_drag = bool(event.modifiers() & Qt.KeyboardModifier.AltModifier)
        if not force_crop_drag:
            for layer in reversed(self._visible_layers()):
                left, top, width, height = self._rect(layer)
                if left <= point.x() <= left + width and top <= point.y() <= top + height:
                    self.selected_id = layer.item_id
                    self._drag_id = layer.item_id
                    self._drag_offset = QPointF(point.x() - left, point.y() - top)
                    self.layer_selected.emit(layer.item_id)
                    self.update()
                    return
        self._background_dragging = True
        self.preview_background_pressed.emit(point)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._background_dragging and event.buttons() & Qt.MouseButton.LeftButton:
            self.preview_background_moved.emit(event.position())
            return
        if not self._drag_id or not event.buttons() & Qt.MouseButton.LeftButton:
            return
        layer = next((item for item in self.layers if item.item_id == self._drag_id), None)
        if layer is None:
            return
        _, _, width, height = self._rect(layer)
        bounds = self.output_rect if not self.output_rect.isEmpty() else QRectF(self.rect())
        center_x = event.position().x() - self._drag_offset.x() + width / 2
        center_y = event.position().y() - self._drag_offset.y() + height / 2
        x_percent = ((center_x - bounds.left()) / max(1, bounds.width())) * 100
        y_percent = ((center_y - bounds.top()) / max(1, bounds.height())) * 100
        x_percent = max(0.0, min(100.0, x_percent))
        y_percent = max(0.0, min(100.0, y_percent))
        self.layer_moved.emit(self._drag_id, x_percent, y_percent)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_id = None
            if self._background_dragging:
                self._background_dragging = False
                self.preview_background_released.emit()

    def paintEvent(self, event: object) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        bounds = self.output_rect if not self.output_rect.isEmpty() else QRectF(self.rect())
        painter.setClipRect(bounds)
        for layer in self._visible_layers():
            left, top, width, height = self._rect(layer)
            rect = QRectF(left, top, width, height)
            painter.save()
            painter.setOpacity(layer_transform_at(layer, self.position_ms).opacity)
            image = self._image_cache.get(layer.source_path or "") if layer.kind == "image" else None
            if image is not None:
                painter.drawImage(rect, image)
            elif layer.kind == "image":
                painter.fillRect(rect, QColor(24, 28, 40, 150))
                painter.setPen(QColor(layer.color))
                painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "Imagem indisponível")
            else:
                painter.fillRect(rect, QColor(20, 24, 32, 130 if layer.background else 35))
                painter.setFont(QFont(layer.font_name, max(8, round(layer.font_size * self.height() / 1080))))
                painter.setPen(QColor(layer.color))
                painter.drawText(rect, Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, layer.text)
            painter.restore()
            if layer.item_id == self.selected_id:
                painter.setPen(QPen(QColor("#55d6a8"), 2, Qt.PenStyle.DashLine))
                painter.drawRect(left, top, width, height)
