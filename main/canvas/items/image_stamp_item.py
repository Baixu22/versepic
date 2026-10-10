"""插图图元（TF-0037）：把外部位图放进截图，可移动、等比缩放、删除与撤销。

只做"把一张有界位图贴进成图"这一件事：不做滤镜/调色，也不长期引用外部文件——
插入时读一次像素，之后图元自带副本，源文件被移动或删除不影响已经插入的图。
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QImage, QPainter, QPainterPath
from PySide6.QtWidgets import QGraphicsItem

from .drawing_items import DrawingItemMixin


class ImageStampItem(DrawingItemMixin, QGraphicsItem):
    """插入的位图图元。"""

    # 安全上限：单边、总像素、文件字节都设限，避免一张超大图把内存吃穿
    MAX_EDGE = 8192
    MAX_PIXELS = 24_000_000
    MAX_FILE_BYTES = 64 * 1024 * 1024
    MIN_SIZE = 8.0
    CLICK_MARGIN = 4.0
    # 层叠规则：盖住底图和普通标注（z=20），但压在文字（z=30）下面
    STAMP_Z_VALUE = 25

    def __init__(self, image: QImage, rect: QRectF = None):
        super().__init__()
        self._init_drawing_mixin()
        self._image = QImage(image)
        height = max(1, self._image.height())
        self._aspect = max(1e-6, float(self._image.width()) / float(height))
        self._rect = QRectF(0, 0, 1, 1)
        if rect is None:
            rect = QRectF(0, 0, float(self._image.width()), float(self._image.height()))
        self.setRect(rect)
        self.setZValue(self.STAMP_Z_VALUE)

    # ------------------------------------------------------------------
    # 载入与校验
    # ------------------------------------------------------------------

    @classmethod
    def validate_image(cls, image) -> QImage:
        """尺寸/像素预算校验；不合格抛 ValueError，调用方负责给用户反馈。"""
        if not isinstance(image, QImage) or image.isNull():
            raise ValueError("invalid image")
        width, height = int(image.width()), int(image.height())
        if width <= 0 or height <= 0:
            raise ValueError("empty image")
        if max(width, height) > cls.MAX_EDGE or width * height > cls.MAX_PIXELS:
            raise ValueError("image too large")
        return image

    @classmethod
    def load_file(cls, path) -> QImage:
        """从文件读一次像素；缺失、过大、不是图片都抛 ValueError。"""
        target = Path(str(path))
        if not target.is_file():
            raise ValueError("file not found")
        if target.stat().st_size > cls.MAX_FILE_BYTES:
            raise ValueError("file too large")
        image = QImage(str(target))
        if image.isNull():
            raise ValueError("unsupported image")
        return cls.validate_image(image)

    # ------------------------------------------------------------------
    # 几何
    # ------------------------------------------------------------------

    def image(self) -> QImage:
        return QImage(self._image)

    def source_size(self):
        return self._image.size()

    def aspect_ratio(self) -> float:
        return float(self._aspect)

    def rect(self) -> QRectF:
        return QRectF(self._rect)

    def visualRect(self) -> QRectF:
        return QRectF(self._rect)

    def setRect(self, rect: QRectF):
        """按宽度重算高度：无论从哪里改尺寸，插图始终保持原始宽高比。"""
        target = QRectF(rect)
        width = max(self.MIN_SIZE, float(target.width()))
        height = max(self.MIN_SIZE, width / self._aspect)
        self.prepareGeometryChange()
        self._rect = QRectF(target.x(), target.y(), width, height)
        self.update()

    def boundingRect(self) -> QRectF:
        margin = self.CLICK_MARGIN
        return self._rect.adjusted(-margin, -margin, margin, margin)

    def shape(self) -> QPainterPath:
        path = QPainterPath()
        path.addRect(self._rect)
        return path

    # ------------------------------------------------------------------
    # 绘制
    # ------------------------------------------------------------------

    def paint(self, painter: QPainter, option, widget=None):
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.drawImage(self._rect, self._image)

        selection_pen = self.selection_frame_pen()
        if selection_pen is not None:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(selection_pen)
            painter.drawRect(self._rect)

    # ------------------------------------------------------------------
    # 统一属性接口
    # ------------------------------------------------------------------

    def set_stroke_width(self, width: float):
        """对插图，宽度就是它的显示宽度，高度按宽高比走。"""
        self.setRect(QRectF(self._rect.x(), self._rect.y(), max(self.MIN_SIZE, float(width)), 1.0))

    def scale_stroke_width(self, scale: float) -> bool:
        self.set_stroke_width(self._rect.width() * float(scale))
        return True

    def get_stroke_width(self):
        return float(self._rect.width())

    def set_visual_opacity(self, opacity: float) -> bool:
        self.setOpacity(max(0.0, min(1.0, float(opacity))))
        self.update()
        return True

    def get_visual_opacity(self):
        return max(0.0, min(1.0, float(self.opacity())))
