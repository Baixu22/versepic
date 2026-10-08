"""Shared visual tokens for the lightweight UI component library."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from functools import lru_cache

from PySide6.QtGui import QColor, QFont, QIcon, QLinearGradient, QPainter

from core.resource_manager import ResourceManager
from core.ui_theme import (
    RADIUS_LG, RADIUS_MD, RADIUS_SM, RADIUS_XL, get_ui_theme,
)


FONT_FAMILY = '"Microsoft YaHei UI", "Segoe UI Variable Text", "Segoe UI", sans-serif'
# Legacy names remain import-compatible; new code resolves ui_tokens(widget).
ACCENT = "#171717"
ACCENT_HOVER = "#303030"
ACCENT_PRESSED = "#404040"
ACCENT_SOFT = "#F0F0F0"
ACCENT_SUBTLE = "rgba(0, 0, 0, 0.06)"
FOCUS_RING = "#737373"

# 输入类控件（下拉框、数字框、单行输入）的外框度量。要和它们排在同一列、
# 看起来该是一家的控件——比如外观页那几个色块按钮——按这里取值，不要各写
# 一套数字，否则改了一边就会高矮或圆角对不上。
#
# 圆角统一读 core.ui_theme 里那一份 shadcn 刻度，不再在这里另立一套：
# 设置窗口、内容管理、剪贴板窗口三类页面的同类控件因此圆角一致。
CONTROL_RADIUS = RADIUS_MD
ITEM_RADIUS = RADIUS_SM
SURFACE_RADIUS = RADIUS_LG
WINDOW_RADIUS = RADIUS_XL
POPUP_RADIUS = RADIUS_MD
CONTROL_HEIGHT = 36
WORKSPACE_SIDEBAR_WIDTH = 172
WORKSPACE_HEADER_HEIGHT = 52
WORKSPACE_MARGIN = 12
WORKSPACE_PADDING = 24
MOTION_FAST = 120
MOTION_NORMAL = 150
INPUT_RADIUS = CONTROL_RADIUS
INPUT_CONTENT_HEIGHT = 26
INPUT_PADDING_V = 4
INPUT_PADDING_H = 11
INPUT_HEIGHT = INPUT_CONTENT_HEIGHT + 2 * INPUT_PADDING_V + 2


def ui_font(size=14, weight=QFont.Weight.Normal):
    font = QFont()
    font.setFamilies(["Microsoft YaHei UI", "Segoe UI Variable Text", "Segoe UI"])
    font.setPixelSize(size)
    font.setWeight(weight)
    # Prefer outlines over embedded bitmap strikes at small Chinese text sizes.
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias | QFont.StyleStrategy.PreferOutline)
    # Align glyph strokes to physical pixels, including translucent windows.
    font.setHintingPreference(QFont.HintingPreference.PreferFullHinting)
    return font


def button_colors(tokens, variant, *, checked=False, enabled=True):
    """Shared surface recipe for painted buttons and native button QSS."""
    t = tokens
    if not enabled:
        return t.surface_subtle, t.surface_subtle, t.text_disabled, t.border
    if variant in ("primary", "default"):
        return t.accent_strong, t.accent_strong_hover, t.primary_foreground, "transparent"
    if variant == "destructive-ghost":
        return "transparent", t.danger_soft, t.danger, "transparent"
    if variant == "destructive":
        return t.destructive_background, QColor(t.destructive_background).darker(110).name(), "#FFFFFF", "transparent"
    if checked or variant == "secondary":
        return t.accent_soft, t.surface_hover, t.text, "transparent"
    if variant == "link":
        return "transparent", "transparent", t.accent_text, "transparent"
    if variant == "ghost":
        return "transparent", t.surface_hover, t.text, "transparent"
    return t.surface, t.surface_hover, t.text, t.border


def button_qss(widget=None, *, variant="outline", selector="QPushButton", scale=None):
    """Same palette/geometry for Qt-owned buttons (toolbars, dialog button boxes)."""
    from core.ui_scale import widget_scaled
    s = scale or (lambda value: widget_scaled(widget, value))
    t = ui_tokens(widget)
    bg, hover, fg, border = button_colors(t, variant)
    disabled, _, disabled_fg, disabled_border = button_colors(t, variant, enabled=False)
    pressed = t.accent_strong_pressed if variant in ("primary", "default") else hover
    return f"""
        {selector} {{ min-height: {s(INPUT_CONTENT_HEIGHT)}px;
            padding: {s(INPUT_PADDING_V)}px {s(14)}px;
            color: {fg}; background: {bg}; border: 1px solid {border};
            border-radius: {s(CONTROL_RADIUS)}px; font: 600 {s(14)}px {FONT_FAMILY}; }}
        {selector}:hover {{ background: {hover}; }}
        {selector}:pressed {{ background: {pressed}; }}
        {selector}:checked {{ background: {t.accent_soft}; color: {t.text}; }}
        {selector}:focus {{ border-color: {t.ring}; }}
        {selector}:disabled {{ background: {disabled}; color: {disabled_fg}; border-color: {disabled_border}; }}
    """


def menu_qss(widget=None, *, tokens=None, scale=None, font_size=14):
    """One menu recipe, including native editor menus and window theme overrides."""
    from core.ui_scale import widget_scaled
    s = scale or (lambda value: widget_scaled(widget, value))
    t = tokens or ui_tokens(widget)
    return f"""
        QMenu {{ color: {t.text}; background-color: {t.popup_background};
            border: 1px solid {t.border}; border-radius: {s(POPUP_RADIUS)}px;
            padding: {s(4)}px; font: {s(font_size)}px {FONT_FAMILY}; }}
        QMenu::item {{ color: {t.text}; background-color: transparent;
            border-radius: {s(ITEM_RADIUS)}px; padding: {s(6)}px {s(28)}px {s(6)}px {s(24)}px; }}
        QMenu::item:selected {{ color: {t.text}; background-color: {t.popup_hover}; }}
        QMenu::item:disabled {{ color: {t.text_disabled}; background-color: transparent; }}
        QMenu::separator {{ height: 1px; margin: {s(4)}px; background-color: {t.separator}; }}
    """

def ui_tokens(widget=None):
    """Return semantic colours, honoring an optional top-level theme scope."""
    current = widget
    while current is not None:
        override = getattr(current, "_ui_theme_tokens_override", None)
        if override is not None:
            return override
        parent_widget = getattr(current, "parentWidget", None)
        current = parent_widget() if callable(parent_widget) else None
    return get_ui_theme().tokens


def scrollbar_qss(widget=None) -> str:
    """应用窗口统一的细滚动条：7px 圆角滑块，没有两端箭头，滑轨透明，悬停换强调色。

    设置窗口、剪贴板管理窗口原先各写一份，数值已经对不上（一份写死颜色，一份跟主题），
    新窗口不再抄第三份，都拼这一段。
    """
    t = ui_tokens(widget)
    return f"""
    QScrollBar:vertical {{ width: 7px; margin: 3px 0; background: transparent; }}
    QScrollBar:horizontal {{ height: 7px; margin: 0 3px; background: transparent; }}
    QScrollBar::handle:vertical {{ min-height: 30px; background: {t.border_hover}; border-radius: 3px; }}
    QScrollBar::handle:horizontal {{ min-width: 30px; background: {t.border_hover}; border-radius: 3px; }}
    QScrollBar::handle:hover {{ background: {t.accent}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
    """


def to_qicon(icon, widget=None) -> QIcon:
    """Convert an icon and tint SVG-backed UI icons for the current theme."""
    if isinstance(icon, QIcon):
        return icon
    if icon is None:
        return QIcon()
    render = getattr(icon, "render_icon", None)
    if callable(render):
        return render(ui_tokens(widget).text)
    icon_id = getattr(icon, "value", getattr(icon, "name", ""))
    preserve_color = str(icon_id).upper().endswith("WHITE")
    factory = getattr(icon, "icon", None)
    if callable(factory):
        source = factory()
        path = getattr(icon, "path", lambda: "")()
    else:
        path = str(icon)
        source = ResourceManager.get_icon(path)
    if preserve_color or source.isNull():
        return source
    return _tinted_icon(path, ui_tokens(widget).text)


def css_color(value: str) -> QColor:
    """Parse a token colour for QPainter; QColor itself rejects rgb()/rgba()."""
    text = value.strip()
    if text.startswith(("rgba(", "rgb(")):
        channels = [part.strip() for part in text[text.index("(") + 1:-1].split(",")]
        color = QColor(*(int(channel) for channel in channels[:3]))
        if len(channels) == 4:
            color.setAlphaF(float(channels[3]))
        return color
    return QColor(text)


def tinted_icon(icon, color: str) -> QIcon:
    """Tint a FluentIcon or an SVG path to an explicit colour."""
    render = getattr(icon, "render_icon", None)
    if callable(render):
        return render(color)
    path_getter = getattr(icon, "path", None)
    path = path_getter() if callable(path_getter) else str(icon)
    return _tinted_icon(path, color)


@lru_cache(maxsize=128)
def _tinted_icon(path: str, color: str) -> QIcon:
    source = ResourceManager.get_icon(path)
    # Retain the source's raster sizes instead of reducing every control from
    # a single 64px bitmap. Assets stay in memory for one-file installations.
    result = QIcon()
    for size in source.availableSizes():
        pixmap = source.pixmap(size)
        if pixmap.isNull():
            continue
        painter = QPainter(pixmap)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        painter.fillRect(pixmap.rect(), QColor(color))
        painter.end()
        result.addPixmap(pixmap)
    return result if not result.isNull() else source



def paint_solid_background(widget, radius: int = 8) -> None:
    """Paint an opaque rounded solid background for frameless dialogs.

    Replaces the former acrylic/blur detection path.  A subtle vertical
    gradient plus a hairline border keeps it looking polished while staying
    cheap to repaint.
    """
    painter = QPainter(widget)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
    painter.fillRect(widget.rect(), Qt.GlobalColor.transparent)

    rect = QRectF(widget.rect()).adjusted(0.5, 0.5, -0.5, -0.5)

    gradient = QLinearGradient(0, 0, 0, widget.height())
    tokens = ui_tokens(widget)
    gradient.setColorAt(0.0, QColor(tokens.window_top))
    gradient.setColorAt(1.0, QColor(tokens.window_bottom))

    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
    painter.setBrush(gradient)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(rect, radius, radius)

    pen = painter.pen()
    pen.setColor(QColor(tokens.window_border))
    pen.setWidthF(1.0)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(rect, radius, radius)
