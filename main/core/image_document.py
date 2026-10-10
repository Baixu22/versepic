"""Non-destructive file-image geometry; annotations remain in original image coordinates."""
from dataclasses import dataclass
import os
from pathlib import Path

from PySide6.QtCore import QRect, QRectF, QSize, Qt
from PySide6.QtGui import QImage
from core.image_layout import MAX_ENCODED_BYTES, decode_image
from pin.pin_image_transform import PinImageTransform

MAX_EDITOR_PIXELS = 32_000_000


def load_editor_image(filename):
    path = Path(filename)
    if path.suffix.lower() not in (".png", ".jpg", ".jpeg", ".bmp", ".webp") or not path.is_file():
        raise ValueError("Choose a local PNG, JPEG, BMP or WebP image")
    if path.stat().st_size > MAX_ENCODED_BYTES:
        raise ValueError("Image file exceeds 64 MiB")
    with path.open("rb") as stream:
        data = stream.read(MAX_ENCODED_BYTES + 1)
    image = decode_image(data, remaining_pixels=MAX_EDITOR_PIXELS)
    return image, str(path.resolve())


def same_file(first, second):
    if not first or not second:
        return False
    if os.path.normcase(os.path.realpath(first)) == os.path.normcase(os.path.realpath(second)):
        return True
    try:
        return os.path.samefile(first, second)
    except OSError:
        return False


@dataclass(frozen=True)
class ImageGeometry:
    crop: tuple
    rotation: int = 0
    flip_h: bool = False
    flip_v: bool = False
    output_width: int = 0

    def validate(self, size):
        if (len(self.crop) != 4 or any(type(v) is not int for v in self.crop)
                or self.crop[2] < 1 or self.crop[3] < 1
                or not QRect(0, 0, size.width(), size.height()).contains(QRect(*self.crop))
                or type(self.rotation) is not int or self.rotation not in (0, 90, 180, 270)
                or type(self.flip_h) is not bool or type(self.flip_v) is not bool
                or type(self.output_width) is not int or not 0 <= self.output_width <= 16384):
            raise ValueError("Invalid image crop, transform or output size")
        output = self.output_size()
        if output.width() * output.height() > MAX_EDITOR_PIXELS or max(output.width(), output.height()) > 100000:
            raise ValueError("Output exceeds the editor image limit")

    def transform(self):
        transform = PinImageTransform()
        for _ in range(self.rotation // 90):
            transform.rotate_cw()
        if self.flip_h:
            transform.flip_horizontal()
        if self.flip_v:
            transform.flip_vertical()
        return transform

    def native_output_size(self):
        return self.transform().display_size(QSize(self.crop[2], self.crop[3]))

    def output_size(self):
        native = self.native_output_size()
        if not self.output_width:
            return native
        return QSize(self.output_width, max(1, round(native.height() * self.output_width / native.width())))

    def apply_to_pixels(self, image):
        if image.size() != QSize(self.crop[2], self.crop[3]):
            raise ValueError("Rendered crop dimensions do not match the geometry")
        result = self.transform().transform_image(image)
        if result.size() != self.output_size():
            result = result.scaled(self.output_size(), Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
        if result.isNull():
            raise ValueError("Could not allocate edited image")
        if result.devicePixelRatio() != 1:
            result = QImage(result)
            result.setDevicePixelRatio(1)
        return result

    def scene_rect(self):
        return QRectF(*self.crop)
