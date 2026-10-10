"""导出水印（TF-0038）：在成图上叠加可选的文字或图片标识。

只作用于"已经合成好的成图"：原图、工程与源文件都不改，水印也不参与画布编辑。
默认关闭；文字水印只使用用户自己填的内容，不去读窗口标题或身份信息。
位置、边距、透明度与缩放都在这里统一计算，预览和各格式导出走同一条链路。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter

POSITION_BOTTOM_RIGHT = "bottom_right"
POSITION_BOTTOM_LEFT = "bottom_left"
POSITION_TOP_RIGHT = "top_right"
POSITION_TOP_LEFT = "top_left"
POSITION_CENTER = "center"
POSITIONS = (
    POSITION_BOTTOM_RIGHT,
    POSITION_BOTTOM_LEFT,
    POSITION_TOP_RIGHT,
    POSITION_TOP_LEFT,
    POSITION_CENTER,
)

KIND_TEXT = "text"
KIND_IMAGE = "image"
KINDS = (KIND_TEXT, KIND_IMAGE)

DEFAULT_POSITION = POSITION_BOTTOM_RIGHT
DEFAULT_MARGIN = 16
DEFAULT_OPACITY = 0.6
DEFAULT_SCALE = 1.0
DEFAULT_COLOR = "#FFFFFF"
MAX_TEXT_CHARS = 200
MAX_IMAGE_EDGE = 8192
MAX_IMAGE_PIXELS = 24_000_000


@dataclass(frozen=True)
class WatermarkOptions:
    enabled: bool = False
    kind: str = KIND_TEXT
    text: str = ""
    image_path: str = ""
    position: str = DEFAULT_POSITION
    margin: int = DEFAULT_MARGIN
    opacity: float = DEFAULT_OPACITY
    scale: float = DEFAULT_SCALE
    color: str = DEFAULT_COLOR

    def normalized(self) -> "WatermarkOptions":
        return WatermarkOptions(
            enabled=bool(self.enabled),
            kind=self.kind if self.kind in KINDS else KIND_TEXT,
            text=str(self.text or "")[:MAX_TEXT_CHARS],
            image_path=str(self.image_path or ""),
            position=self.position if self.position in POSITIONS else DEFAULT_POSITION,
            margin=max(0, min(512, int(self.margin))),
            opacity=min(1.0, max(0.0, float(self.opacity))),
            scale=min(8.0, max(0.1, float(self.scale))),
            color=self.color or DEFAULT_COLOR,
        )

    def has_content(self) -> bool:
        if self.kind == KIND_TEXT:
            return bool(self.text.strip())
        return bool(self.image_path.strip())


def options_from_mapping(raw) -> WatermarkOptions:
    """把配置/表单字典收敛成合法选项；不认识的取值一律回退到安全默认。"""
    data = raw if isinstance(raw, dict) else {}
    return WatermarkOptions(
        enabled=bool(data.get("enabled", False)),
        kind=data.get("kind", KIND_TEXT),
        text=data.get("text", ""),
        image_path=data.get("image_path", ""),
        position=data.get("position", DEFAULT_POSITION),
        margin=data.get("margin", DEFAULT_MARGIN),
        opacity=data.get("opacity", DEFAULT_OPACITY),
        scale=data.get("scale", DEFAULT_SCALE),
        color=data.get("color", DEFAULT_COLOR),
    ).normalized()


def load_options(manager=None) -> WatermarkOptions:
    """从应用设置读水印选项；读不到就是"关闭 + 空内容"。"""
    if manager is None:
        try:
            from settings import get_tool_settings_manager

            manager = get_tool_settings_manager()
        except Exception:
            manager = None
    if manager is None:
        return WatermarkOptions()
    keys = {
        "enabled": ("watermark_enabled", False),
        "kind": ("watermark_kind", KIND_TEXT),
        "text": ("watermark_text", ""),
        "image_path": ("watermark_image_path", ""),
        "position": ("watermark_position", DEFAULT_POSITION),
        "opacity": ("watermark_opacity", DEFAULT_OPACITY),
        "scale": ("watermark_scale", DEFAULT_SCALE),
    }
    data = {}
    for field, (key, default) in keys.items():
        try:
            data[field] = manager.get_app_setting(key, default)
        except Exception:
            data[field] = default
    return options_from_mapping(data)


def load_watermark_image(path) -> QImage | None:
    """载入图片水印；缺失/过大/不是图片返回 None，调用方按"没有水印"处理。"""
    target = Path(str(path or ""))
    if not target.is_file():
        return None
    try:
        if target.stat().st_size > 64 * 1024 * 1024:
            return None
    except OSError:
        return None
    image = QImage(str(target))
    if image.isNull():
        return None
    if max(image.width(), image.height()) > MAX_IMAGE_EDGE or image.width() * image.height() > MAX_IMAGE_PIXELS:
        return None
    return image


def _fit_font_size(text: str, base_size: float, max_width: float, max_height: float) -> float:
    """字号按"放得下"收缩：小图上的水印也不越界、不被裁掉。"""
    size = max(6.0, float(base_size))
    while size > 6.0:
        metrics = QFontMetricsF(_font(size))
        bounds = metrics.boundingRect(text)
        if bounds.width() <= max_width and bounds.height() <= max_height:
            return size
        size *= 0.9
    return 6.0


def _font(size: float) -> QFont:
    font = QFont()
    font.setBold(True)
    font.setPointSizeF(max(6.0, float(size)))
    return font


def _place(rect: QRectF, size: tuple, position: str, margin: int, width: int, height: int) -> QRectF:
    """按位置与边距摆放到成图内；任何情况下都夹在边界内。"""
    w, h = size
    left = margin
    right = width - margin - w
    top = margin
    bottom = height - margin - h
    if position == POSITION_BOTTOM_LEFT:
        x, y = left, bottom
    elif position == POSITION_TOP_RIGHT:
        x, y = right, top
    elif position == POSITION_TOP_LEFT:
        x, y = left, top
    elif position == POSITION_CENTER:
        x, y = (width - w) / 2.0, (height - h) / 2.0
    else:  # bottom_right
        x, y = right, bottom
    x = min(max(0.0, x), max(0.0, width - w))
    y = min(max(0.0, y), max(0.0, height - h))
    return QRectF(x, y, w, h)


def render(image: QImage, options: WatermarkOptions) -> QImage:
    """在成图上叠加水印；未启用、没有内容或空图时原样返回（不复制、不改原图）。"""
    if image is None or image.isNull():
        return image
    options = options.normalized()
    if not options.enabled or not options.has_content():
        return image

    if options.kind == KIND_TEXT:
        return _render_text(image, options)
    return _render_image(image, options)


def _render_text(image: QImage, options: WatermarkOptions) -> QImage:
    text = options.text.strip()
    if not text:
        return image
    margin = options.margin
    max_width = max(16.0, image.width() - margin * 2.0)
    max_height = max(12.0, image.height() - margin * 2.0)
    base_size = max(10.0, min(image.width(), image.height()) * 0.045 * options.scale)
    size = _fit_font_size(text, base_size, max_width, max_height)
    font = _font(size)
    metrics = QFontMetricsF(font)
    bounds = metrics.boundingRect(text)

    out = QImage(image)
    painter = QPainter(out)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        target = _place(QRectF(0, 0, bounds.width(), bounds.height()), (bounds.width(), bounds.height()), options.position, margin, image.width(), image.height())
        baseline = target.bottom() - metrics.descent()

        color = QColor(options.color)
        shadow = QColor(0, 0, 0, int(120 * options.opacity))
        text_color = QColor(color)
        text_color.setAlphaF(options.opacity)

        painter.setFont(font)
        painter.setPen(shadow)
        painter.drawText(target.translated(max(1.0, size * 0.06), max(1.0, size * 0.06)), int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), text)
        painter.setPen(text_color)
        painter.drawText(target, int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), text)
        del baseline
    finally:
        painter.end()
    return out


def _render_image(image: QImage, options: WatermarkOptions) -> QImage:
    logo = load_watermark_image(options.image_path)
    if logo is None:
        return image
    margin = options.margin
    max_w = max(8.0, image.width() - margin * 2.0)
    max_h = max(8.0, image.height() - margin * 2.0)
    target_w = min(logo.width(), max(8.0, image.width() * 0.25)) * options.scale
    ratio = logo.height() / max(1.0, float(logo.width()))
    target_h = target_w * ratio
    if target_w > max_w or target_h > max_h:
        factor = min(max_w / target_w, max_h / target_h)
        target_w *= factor
        target_h *= factor
    target = _place(QRectF(0, 0, target_w, target_h), (target_w, target_h), options.position, margin, image.width(), image.height())

    out = QImage(image)
    painter = QPainter(out)
    try:
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.setOpacity(options.opacity)
        painter.drawImage(target, logo)
    finally:
        painter.end()
    return out


def preview(image: QImage, options: WatermarkOptions) -> QImage:
    """设置页预览：与导出走同一套渲染，位置和透明度所见即所得。"""
    return render(image, options)
