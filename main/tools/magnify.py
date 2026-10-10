"""Drag a source rectangle; place a magnified callout of the original pixels."""
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QPen

from .base import Tool, ToolContext, color_with_opacity
from canvas.items import MagnifyCalloutItem
from canvas.undo import AddItemCommand
from core.logger import log_debug, T


class MagnifyTool(Tool):
    id = "magnify"
    MIN_SIZE = MagnifyCalloutItem.MIN_SOURCE

    def __init__(self):
        self.drawing = False
        self.start_pos = None
        self.current_item = None

    def on_press(self, pos: QPointF, button, ctx: ToolContext):
        if button != Qt.MouseButton.LeftButton:
            return
        self.drawing = True
        self.start_pos = pos
        pen = QPen(color_with_opacity(ctx.color, ctx.opacity), ctx.stroke_width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        source = QRectF(pos, pos)
        self.current_item = MagnifyCalloutItem(source, QRectF(0, 0, 1, 1), pen)
        self.current_item.setPos(pos)
        ctx.scene.addItem(self.current_item)

    def on_move(self, pos: QPointF, ctx: ToolContext):
        if not (self.drawing and self.current_item):
            return
        self._apply(QRectF(self.start_pos, pos).normalized())

    def on_release(self, pos: QPointF, ctx: ToolContext):
        if not self.drawing:
            return
        self.drawing = False
        item, self.current_item = self.current_item, None
        if item is None:
            return
        source = QRectF(self.start_pos, pos).normalized()
        if source.width() < self.MIN_SIZE or source.height() < self.MIN_SIZE:
            ctx.scene.removeItem(item)
            log_debug(T("绘制取消：尺寸过小 ({width:.1f}x{height:.1f} < {min_size})",
                        width=source.width(), height=source.height(), min_size=self.MIN_SIZE), "MagnifyTool")
            return
        self._apply(source, item)
        ctx.scene.removeItem(item)
        ctx.undo_stack.push(AddItemCommand(ctx.scene, item))
        ctx.scene.item_auto_select_requested.emit(item)
        log_debug(T("完成绘制"), "MagnifyTool")

    def _apply(self, source: QRectF, item=None):
        item = item or self.current_item
        zoom = MagnifyCalloutItem.DEFAULT_ZOOM
        callout = QRectF(source.right() + 8, source.top(), source.width() * zoom, source.height() * zoom)
        item.set_source_rect(source)
        item.setRect(QRectF(0, 0, callout.width(), callout.height()))
        item.setPos(callout.topLeft())
