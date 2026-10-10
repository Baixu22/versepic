"""Exportable magnified callout of background pixels, not the color-picker loupe."""
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QImage, QPainter, QPainterPath, QPen, QColor
from PySide6.QtWidgets import QGraphicsItem

from .background_item import BackgroundItem
from .drawing_items import DrawingItemMixin


class MagnifyCalloutItem(DrawingItemMixin, QGraphicsItem):
    """A dashed source box plus an opaque magnified copy of the original image.

    Samples BackgroundItem.image() only. Other annotations, this item, and edit
    handles never enter the copy, so overlapping the callout onto its source
    cannot recurse or pick up UI chrome.
    """

    MIN_SOURCE = 8.0
    MIN_ZOOM = 1.0
    MAX_ZOOM = 8.0
    DEFAULT_ZOOM = 2.0

    def __init__(self, source_scene: QRectF, callout_local: QRectF, pen: QPen):
        super().__init__()
        self._init_drawing_mixin()
        self.setZValue(20)
        self._pen = QPen(pen)
        self._source_scene = QRectF(source_scene).normalized()
        self._rect = QRectF(callout_local).normalized()
        if self._rect.isEmpty():
            self._rect = QRectF(0, 0, self._source_scene.width() * self.DEFAULT_ZOOM,
                                self._source_scene.height() * self.DEFAULT_ZOOM)

    def pen(self) -> QPen:
        return QPen(self._pen)

    def setPen(self, pen: QPen):
        self._pen = QPen(pen)
        self.update()

    def rect(self) -> QRectF:
        return QRectF(self._rect)

    def setRect(self, rect: QRectF):
        rect = QRectF(rect).normalized()
        sw = max(1.0, self._source_scene.width())
        sh = max(1.0, self._source_scene.height())
        zoom = max(rect.width() / sw, rect.height() / sh)
        zoom = min(max(zoom, self.MIN_ZOOM), self.MAX_ZOOM)
        self.prepareGeometryChange()
        self._rect = QRectF(rect.x(), rect.y(), sw * zoom, sh * zoom)
        self.update()

    def source_rect(self) -> QRectF:
        return QRectF(self._source_scene)

    def set_source_rect(self, rect: QRectF):
        self.prepareGeometryChange()
        self._source_scene = QRectF(rect).normalized()
        self.update()

    def translate_background_anchor(self, dx: float, dy: float):
        self.prepareGeometryChange()
        self._source_scene.translate(dx, dy)
        self.update()

    def zoom(self) -> float:
        sw = self._source_scene.width()
        if sw <= 0:
            return self.DEFAULT_ZOOM
        return self._rect.width() / sw

    def itemChange(self, change, value):
        if change in (
            QGraphicsItem.GraphicsItemChange.ItemPositionChange,
            QGraphicsItem.GraphicsItemChange.ItemTransformChange,
        ):
            self.prepareGeometryChange()
        return super().itemChange(change, value)

    def _source_local(self) -> QRectF:
        return self.mapFromScene(self._source_scene).boundingRect()

    def boundingRect(self) -> QRectF:
        extra = max(2.0, self._pen.widthF()) + 2.0
        return self._rect.united(self._source_local()).adjusted(-extra, -extra, extra, extra)

    def shape(self) -> QPainterPath:
        path = QPainterPath()
        path.addRect(self._rect)
        path.addRect(self._source_local())
        return path

    def _sample(self) -> QImage:
        scene = self.scene()
        if scene is None:
            return QImage()
        background = next((item for item in scene.items() if isinstance(item, BackgroundItem)), None)
        if background is None:
            return QImage()
        image = background.image()
        if image is None or image.isNull():
            return QImage()
        origin = background.offset()
        source = self._source_scene.translated(-origin.x(), -origin.y())
        x = int(round(source.x()))
        y = int(round(source.y()))
        width = max(1, int(round(source.width())))
        height = max(1, int(round(source.height())))
        crop = image.copy(x, y, width, height)
        if crop.isNull():
            return QImage()
        return crop.scaled(
            max(1, int(round(self._rect.width()))),
            max(1, int(round(self._rect.height()))),
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.FastTransformation,
        )

    def paint(self, painter, option, widget=None):
        sample = self._sample()
        if not sample.isNull():
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
            painter.drawImage(self._rect, sample)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(self._pen)
        painter.drawRect(self._rect)
        dash = QPen(self._pen)
        dash.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(dash)
        painter.drawRect(self._source_local())
        painter.setPen(self._pen)
        painter.drawLine(self._source_local().center(), self._rect.center())
        selection = self.selection_frame_pen()
        if selection is not None:
            painter.setPen(selection)
            painter.drawRect(self._rect)

    def set_stroke_width(self, width: float):
        self._pen.setWidthF(max(1.0, float(width)))
        self.update()

    def scale_stroke_width(self, scale: float) -> bool:
        self._pen.setWidthF(max(1.0, self._pen.widthF() * scale))
        self.update()
        return True

    def set_visual_opacity(self, opacity: float) -> bool:
        opacity = max(0.0, min(1.0, float(opacity)))
        color = QColor(self._pen.color())
        color.setAlphaF(opacity)
        self._pen.setColor(color)
        self.setOpacity(1.0)
        self.update()
        return True

    def get_stroke_width(self):
        return float(self._pen.widthF())

    def get_visual_opacity(self):
        return float(self._pen.color().alphaF())
