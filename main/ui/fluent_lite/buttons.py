"""Native Qt buttons styled as a cohesive modern Fluent-like family."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QToolButton, QWidget

from core.ui_scale import widget_scaled as _px
from core.ui_theme import get_ui_theme

from .theme import (
    FONT_FAMILY, INPUT_CONTENT_HEIGHT,
    INPUT_PADDING_V, INPUT_RADIUS, button_qss, to_qicon, ui_tokens,
)
from .button_base import Button


def _button_args(text, parent, icon):
    if isinstance(text, QWidget):
        parent, text = text, ""
    elif not isinstance(text, str) and text is not None:
        icon, text = text, ""
    return text or "", parent, icon


class _ScaledIcon:
    """Icon sizing held as a base value that _apply_theme rescales each time.

    _apply_theme runs on construction, on every theme change and whenever
    configure_dialog_control() marks the widget, and each run re-derives the
    icon size.  A plain setIconSize() therefore survives none of them; callers
    that want a different size set the base through this instead.
    """

    _base_icon_size = 16

    def setBaseIconSize(self, base) -> None:
        self._base_icon_size = int(base)
        self._apply_theme()

    def _apply_scaled_icon_size(self) -> None:
        side = _px(self, self._base_icon_size)
        self.setIconSize(QSize(side, side))


class PushButton(Button):
    def __init__(self, text="", parent=None, icon=None):
        text, parent, icon = _button_args(text, parent, icon)
        super().__init__(text, parent, variant="outline", icon=icon)


class ColorSwatchButton(PushButton):
    """一块颜色本身就是内容的按钮：设置页里选主题色、遮罩色、配色都用它。

    外框几何取输入控件那一套（见 theme.INPUT_*）——它总是和下拉框排在同一
    列里，高度或圆角差一点就看得出来。填充色走 setFill()，不要在外面直接
    setStyleSheet：_apply_theme 在主题切换和缩放标记时会重设样式表，外面写
    的会被冲掉。
    """

    def __init__(self, parent=None):
        self._fill = "transparent"
        self._selected = False
        self._text_color = None
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def setFill(self, fill: str):
        """fill 是 CSS 背景值：一个 rgb()/#hex，或者 qlineargradient(...)。"""
        self._fill = fill
        self._apply_theme()

    def setSelected(self, selected: bool):
        self._selected = bool(selected)
        self._apply_theme()

    def setTextColor(self, color):
        """按钮上那个勾的颜色。填充色深浅由调用方决定，主题决定不了。"""
        self._text_color = color
        self._apply_theme()

    def _style_sheet(self):
        t = ui_tokens(self)
        s = lambda value: _px(self, value)
        border = f"2px solid {t.accent}" if self._selected else f"1px solid {t.border}"
        hover = border if self._selected else f"1px solid {t.border_hover}"
        return f"""
        QPushButton {{ background: {self._fill}; border: {border};
         border-radius: {s(INPUT_RADIUS)}px; min-height: {s(INPUT_CONTENT_HEIGHT)}px;
         padding: {s(INPUT_PADDING_V)}px 0; color: {self._text_color or t.text};
         font: 600 {s(14)}px {FONT_FAMILY}; outline: none; }}
        QPushButton:hover {{ border: {hover}; }}
        """

    def _apply_theme(self, *_):
        # A swatch paints the chosen colour, while retaining Button's native behaviour.
        super()._apply_theme()
        self.setStyleSheet(self._style_sheet())


class PrimaryPushButton(Button):
    def __init__(self, text="", parent=None, icon=None):
        text, parent, icon = _button_args(text, parent, icon)
        super().__init__(text, parent, variant="primary", icon=icon)


class TransparentPushButton(Button):
    def __init__(self, text="", parent=None, icon=None):
        text, parent, icon = _button_args(text, parent, icon)
        super().__init__(text, parent, variant="ghost", icon=icon)


class HyperlinkButton(TransparentPushButton):
    def __init__(self, url="", text="", parent=None, icon=None):
        super().__init__(text, parent, icon)
        self.setVariant("link")
        self._url = url
        self.clicked.connect(self._open_url)

    def _open_url(self):
        if self._url:
            QDesktopServices.openUrl(QUrl(self._url))

    def setUrl(self, url):
        self._url = str(url)


class TransparentToolButton(_ScaledIcon, QToolButton):
    _base_side = 30

    def __init__(self, icon=None, parent=None):
        if isinstance(icon, QWidget):
            parent, icon = icon, None
        super().__init__(parent)
        self._theme_icon_source = None
        self._apply_theme()
        get_ui_theme().theme_changed.connect(self._apply_theme)
        if icon is not None:
            self.setIcon(icon)

    def setBaseMetrics(self, side, icon_size) -> None:
        """Set both base sizes at once, for the same reason as setBaseIconSize.

        Taking them together keeps callers to a single restyle.
        """
        self._base_side = int(side)
        self._base_icon_size = int(icon_size)
        self._apply_theme()

    def setIcon(self, icon):
        self._theme_icon_source = icon
        super().setIcon(to_qicon(icon, self))

    def _apply_theme(self, _tokens=None):
        s = lambda value: _px(self, value)
        self.setFixedSize(s(self._base_side), s(self._base_side))
        self._apply_scaled_icon_size()
        self.setStyleSheet(button_qss(self, variant="ghost", selector="QToolButton") +
                          "QToolButton { min-height: 0; padding: 0; }")
        if self._theme_icon_source is not None:
            super().setIcon(to_qicon(self._theme_icon_source, self))
