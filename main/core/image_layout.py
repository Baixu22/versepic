"""Bounded, pixel-based image layouts and one-image-per-page PDF geometry."""
from dataclasses import dataclass
import math

from PySide6.QtCore import QBuffer, QIODevice, QMarginsF, QRectF, QSize, QSizeF, Qt
from PySide6.QtGui import QColor, QImage, QImageReader, QPainter, QPageLayout, QPageSize, QPdfWriter

MAX_IMAGES = 50
MAX_SOURCE_PIXELS = 64_000_000
MAX_OUTPUT_PIXELS = 100_000_000
MAX_DIMENSION = 100_000
MAX_ENCODED_BYTES = 64 * 1024 * 1024


class ImageLayoutError(ValueError):
    pass


class ExportCancelled(Exception):
    pass


def check_cancel(cancelled):
    if cancelled and cancelled():
        raise ExportCancelled()


def check_size(width, height, limit=MAX_SOURCE_PIXELS):
    if width < 1 or height < 1 or max(width, height) > MAX_DIMENSION or width * height > limit:
        raise ImageLayoutError("Image dimensions exceed the layout limit")


def decode_image(data, remaining_pixels=MAX_SOURCE_PIXELS):
    """Inspect compressed dimensions before decoding; never trust thumbnails as originals."""
    if not data or len(data) > MAX_ENCODED_BYTES:
        raise ImageLayoutError("Image data is missing or too large")
    buffer = QBuffer()
    buffer.setData(data)
    buffer.open(QIODevice.OpenModeFlag.ReadOnly)
    reader = QImageReader(buffer)
    reader.setDecideFormatFromContent(True)
    reader.setAutoTransform(True)
    size = reader.size()
    check_size(size.width(), size.height(), remaining_pixels)
    image = reader.read()
    if image.isNull():
        raise ImageLayoutError("Image could not be decoded")
    check_size(image.width(), image.height(), remaining_pixels)
    image.setDevicePixelRatio(1)
    return image


def validate_images(images):
    if not images or len(images) > MAX_IMAGES:
        raise ImageLayoutError("Choose between 1 and 50 images")
    total = 0
    for image in images:
        check_size(image.width(), image.height())
        total += image.width() * image.height()
        if total > MAX_SOURCE_PIXELS:
            raise ImageLayoutError("Selected images exceed the 64 megapixel input limit")


@dataclass(frozen=True)
class LayoutOptions:
    direction: str = "vertical"
    common_width: int = 0
    gap: int = 12
    padding: int = 16
    background: str = "#ffffff"

    def geometry(self, images):
        validate_images(images)
        if (self.direction not in ("vertical", "horizontal") or not 0 <= self.common_width <= 16384
                or not 0 <= self.gap <= 512 or not 0 <= self.padding <= 512 or not QColor(self.background).isValid()):
            raise ImageLayoutError("Invalid layout options")
        sizes = [(self.common_width, max(1, round(im.height() * self.common_width / im.width())))
                 if self.common_width else (im.width(), im.height()) for im in images]
        width = max(w for w, h in sizes) if self.direction == "vertical" else sum(w for w, h in sizes) + self.gap * (len(sizes) - 1)
        height = max(h for w, h in sizes) if self.direction == "horizontal" else sum(h for w, h in sizes) + self.gap * (len(sizes) - 1)
        width += self.padding * 2
        height += self.padding * 2
        check_size(width, height, MAX_OUTPUT_PIXELS)
        rects = []
        offset = self.padding
        for w, h in sizes:
            if self.direction == "vertical":
                rects.append(QRectF((width - w) // 2, offset, w, h))
                offset += h + self.gap
            else:
                rects.append(QRectF(offset, (height - h) // 2, w, h))
                offset += w + self.gap
        return QSize(width, height), rects


def compose_images(images, options, *, preview_edge=None, cancelled=None, progress=None):
    size, rects = options.geometry(images)
    scale = min(1.0, preview_edge / max(size.width(), size.height())) if preview_edge else 1.0
    result = QImage(max(1, math.ceil(size.width() * scale)), max(1, math.ceil(size.height() * scale)),
                    QImage.Format.Format_ARGB32_Premultiplied)
    if result.isNull():
        raise ImageLayoutError("Could not allocate image layout")
    result.fill(QColor(options.background))
    painter = QPainter(result)
    try:
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.scale(scale, scale)
        for index, (image, target) in enumerate(zip(images, rects)):
            check_cancel(cancelled)
            painter.drawImage(target, image, QRectF(0, 0, image.width(), image.height()))
            if progress:
                progress(index + 1, len(images))
    finally:
        painter.end()
    check_cancel(cancelled)
    return result


@dataclass(frozen=True)
class PageOptions:
    mode: str = "original"
    landscape: bool = False
    margin_mm: int = 10
    rotation: int = 0

    def image(self, source):
        if self.rotation not in (0, 90, 180, 270):
            raise ImageLayoutError("Invalid page rotation")
        if not self.rotation:
            return source
        from PySide6.QtGui import QTransform
        return source.transformed(QTransform().rotate(self.rotation))

    def geometry(self, image):
        check_size(image.width(), image.height())
        if self.rotation not in (0,90,180,270):
            raise ImageLayoutError("Invalid page rotation")
        image_width,image_height = (image.height(),image.width()) if self.rotation in (90,270) else (image.width(),image.height())
        if self.mode not in ("original", "a4", "letter") or not 0 <= self.margin_mm <= 40:
            raise ImageLayoutError("Invalid page options")
        margin = self.margin_mm * 72 / 25.4
        if self.mode == "original":
            # 96 physical image pixels per inch; page sizes have whole-point precision in Qt.
            width = math.ceil(image_width * 72 / 96 + 2 * margin)
            height = math.ceil(image_height * 72 / 96 + 2 * margin)
        else:
            width, height = (595, 842) if self.mode == "a4" else (612, 792)
            if self.landscape:
                width, height = height, width
        if max(width, height) > 14400:
            raise ImageLayoutError("Original-size PDF page is too large; choose A4 or Letter")
        scale = min((width - 2 * margin) / image_width, (height - 2 * margin) / image_height)
        w, h = image_width * scale, image_height * scale
        return QSizeF(width, height), QRectF((width - w) / 2, (height - h) / 2, w, h)


def render_pdf_preview(image, options, edge=1000):
    size, target = options.geometry(image)
    image = options.image(image)
    scale = min(1.0, edge / max(size.width(), size.height()))
    result = QImage(max(1, math.ceil(size.width() * scale)), max(1, math.ceil(size.height() * scale)), QImage.Format.Format_RGB32)
    result.fill(Qt.GlobalColor.white)
    painter = QPainter(result)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    painter.scale(scale, scale)
    painter.drawImage(target, image, QRectF(0, 0, image.width(), image.height()))
    painter.end()
    return result


def write_pdf_pages(images, destination, options, *, cancelled=None, progress=None):
    validate_images(images)
    geometries = [options.geometry(image) for image in images]  # Validate all pages before writing.
    check_cancel(cancelled)
    writer = QPdfWriter(destination)
    writer.setCreator("VersePic")
    writer.setResolution(144)
    def set_page(size):
        layout = QPageLayout(QPageSize(size, QPageSize.Unit.Point, "Image", QPageSize.SizeMatchPolicy.ExactMatch), QPageLayout.Orientation.Portrait,
                             QMarginsF(0, 0, 0, 0), QPageLayout.Unit.Point)
        layout.setMode(QPageLayout.Mode.FullPageMode)
        writer.setPageLayout(layout)
    set_page(geometries[0][0])
    painter = QPainter(writer)
    if not painter.isActive():
        raise ImageLayoutError("PDF writer could not be started")
    painter.setRenderHint(QPainter.RenderHint.LosslessImageRendering)
    try:
        for index, (image, (size, target)) in enumerate(zip(images, geometries)):
            check_cancel(cancelled)
            image = options.image(image)
            if index:
                set_page(size)
                if not writer.newPage():
                    raise ImageLayoutError("PDF page could not be written")
            painter.save()
            painter.scale(writer.width() / size.width(), writer.height() / size.height())
            painter.fillRect(QRectF(0, 0, size.width(), size.height()), Qt.GlobalColor.white)
            painter.drawImage(target, image, QRectF(0, 0, image.width(), image.height()))
            painter.restore()
            if progress:
                progress(index + 1, len(images))
    finally:
        painter.end()
    check_cancel(cancelled)
    return True
