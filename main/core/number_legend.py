"""编号说明列表（TF-0036）：把带说明的序号图元排成旁注或下方步骤列表。

不新增图元类型，也不改画布上的绘制：只在导出阶段按编号顺序收集
（编号 -> 说明），把说明排版到成图的下方或右侧。长文本自动换行、
显式换行按原样保留，整段都画出来，不截断。
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QImage, QPainter

PLACEMENT_OFF = "off"
PLACEMENT_BOTTOM = "bottom"
PLACEMENT_SIDE = "side"
PLACEMENTS = (PLACEMENT_OFF, PLACEMENT_BOTTOM, PLACEMENT_SIDE)
DEFAULT_PLACEMENT = PLACEMENT_OFF

DEFAULT_FONT_SIZE = 13
DEFAULT_MARGIN = 16
DEFAULT_GAP = 10
DEFAULT_LINE_SPACING = 4
MAX_CAPTION_CHARS = 2000
MIN_COLUMN_WIDTH = 120
MAX_SIDE_COLUMN = 420


def normalize_placement(value) -> str:
    """把任意来源的取值收敛成合法位置；不认识的值一律回退到不附带。"""
    return value if value in PLACEMENTS else DEFAULT_PLACEMENT


@dataclass(frozen=True)
class LegendOptions:
    placement: str = DEFAULT_PLACEMENT
    font_size: int = DEFAULT_FONT_SIZE
    margin: int = DEFAULT_MARGIN
    gap: int = DEFAULT_GAP
    line_spacing: int = DEFAULT_LINE_SPACING
    background: str = "#FFFFFF"
    text_color: str = "#202020"
    number_color: str = "#FF0000"
    side_column_ratio: float = 0.36

    def normalized(self) -> "LegendOptions":
        return LegendOptions(
            placement=normalize_placement(self.placement),
            font_size=max(6, int(self.font_size)),
            margin=max(0, int(self.margin)),
            gap=max(0, int(self.gap)),
            line_spacing=max(0, int(self.line_spacing)),
            background=self.background,
            text_color=self.text_color,
            number_color=self.number_color,
            side_column_ratio=min(0.6, max(0.15, float(self.side_column_ratio))),
        )


@dataclass(frozen=True)
class LegendEntry:
    number: int
    caption: str
    color: str = ""


def collect_entries(items) -> list:
    """按编号顺序收集 (编号, 说明)；没有说明的序号跳过，保持编号与说明同行。"""
    from canvas.items import NumberItem

    found = [item for item in list(items or ()) if isinstance(item, NumberItem)]
    found.sort(key=_order_key)
    entries = []
    for item in found:
        caption = str(getattr(item, "caption", "") or "").strip()
        if not caption:
            continue
        color = getattr(item, "color", None)
        entries.append(
            LegendEntry(
                number=int(getattr(item, "number", 0)),
                caption=caption,
                color=color.name() if isinstance(color, QColor) else "",
            )
        )
    return entries


def _order_key(item):
    order = getattr(item, "number_order", None)
    try:
        order_key = int(order) if order is not None else 0
    except (TypeError, ValueError):
        order_key = 0
    pos = item.pos() if hasattr(item, "pos") else None
    return (
        int(getattr(item, "number", 0)),
        order_key,
        float(pos.y()) if pos is not None else 0.0,
        float(pos.x()) if pos is not None else 0.0,
    )


def wrap_caption(text, metrics: QFontMetrics, max_width: float) -> list:
    """按像素宽度折行：显式换行保留，拉丁尽量在空格断，CJK 按字符断，不丢字。"""
    width = max(8.0, float(max_width))
    lines: list = []
    for raw in str(text).split("\n"):
        remaining = raw.rstrip()
        if not remaining:
            lines.append("")
            continue
        while remaining:
            fit = len(remaining)
            while fit > 1 and metrics.horizontalAdvance(remaining[:fit]) > width:
                fit -= 1
            if fit < len(remaining):
                space = remaining.rfind(" ", 0, fit + 1)
                if space > 0:
                    fit = space
            lines.append(remaining[:fit].rstrip())
            remaining = remaining[fit:].lstrip()
    return lines or [""]


def _font(options: LegendOptions) -> QFont:
    font = QFont()
    font.setPointSize(int(options.font_size))
    font.setBold(False)
    return font


def _number_font(options: LegendOptions) -> QFont:
    font = _font(options)
    font.setBold(True)
    return font


def _column_width(image_size: QSize, options: LegendOptions) -> int:
    if options.placement == PLACEMENT_SIDE:
        return int(max(MIN_COLUMN_WIDTH, min(MAX_SIDE_COLUMN, image_size.width() * options.side_column_ratio)))
    return int(max(MIN_COLUMN_WIDTH, image_size.width() - options.margin * 2))


def layout_entries(entries, options: LegendOptions, image_size: QSize) -> dict:
    """算出说明区尺寸与每条的折行结果（测量与绘制共用，避免两处算法不一致）。"""
    options = options.normalized()
    metrics = QFontMetrics(_font(options))
    number_metrics = QFontMetrics(_number_font(options))
    column = _column_width(image_size, options)
    prefix_w = max(number_metrics.horizontalAdvance(str(entry.number)) for entry in entries) + options.gap
    text_width = max(16.0, column - prefix_w)
    line_h = max(metrics.height(), number_metrics.height())
    blocks = []
    for entry in entries:
        lines = wrap_caption(entry.caption, metrics, text_width)
        blocks.append((entry, lines))
    total_h = options.margin * 2
    for _entry, lines in blocks:
        total_h += len(lines) * line_h + (len(lines) - 1) * options.line_spacing + options.gap
    total_h -= options.gap if blocks else 0
    width = column + options.margin * 2
    height = total_h
    return {"blocks": blocks, "prefix_w": prefix_w, "line_h": line_h, "width": width, "height": height, "margin": options.margin}


def measure_legend(entries, options: LegendOptions, image_size: QSize) -> QSize:
    if not entries:
        return QSize(0, 0)
    info = layout_entries(entries, options.normalized(), image_size)
    return QSize(info["width"], info["height"])


def render(image: QImage, entries, options: LegendOptions) -> QImage:
    """把说明区拼到成图下方或右侧；未开启、没有说明或空图时原样返回。"""
    if image is None or image.isNull() or not entries:
        return image
    options = options.normalized()
    if options.placement == PLACEMENT_OFF:
        return image

    info = layout_entries(entries, options, image.size())
    margin = info["margin"]
    if options.placement == PLACEMENT_BOTTOM:
        out = QImage(image.width(), image.height() + info["height"], QImage.Format.Format_ARGB32_Premultiplied)
        origin_y = image.height()
    else:
        out = QImage(image.width() + info["width"], image.height(), QImage.Format.Format_ARGB32_Premultiplied)
        origin_y = 0
    out.fill(QColor(options.background))

    painter = QPainter(out)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.drawImage(0, 0, image)

        text_font = _font(options)
        number_font = _number_font(options)
        text_color = QColor(options.text_color)
        default_number = QColor(options.number_color)

        if options.placement == PLACEMENT_BOTTOM:
            x0 = margin
        else:
            x0 = image.width() + margin
        y = origin_y + margin
        for entry, lines in info["blocks"]:
            painter.setFont(number_font)
            painter.setPen(QColor(entry.color) if entry.color else default_number)
            line_h = info["line_h"]
            painter.drawText(
                QRectF(x0, y, info["prefix_w"], line_h),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop),
                str(entry.number),
            )
            painter.setFont(text_font)
            painter.setPen(text_color)
            text_x = x0 + info["prefix_w"]
            for index, line in enumerate(lines):
                painter.drawText(
                    QRectF(text_x, y + index * (line_h + options.line_spacing), info["width"] - info["prefix_w"] - margin * 2, line_h),
                    int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop),
                    line,
                )
            y += len(lines) * line_h + (len(lines) - 1) * options.line_spacing + options.gap
    finally:
        painter.end()
    return out
