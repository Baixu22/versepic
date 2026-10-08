"""Stateful neutral buttons. Native QPushButton behaviour, custom surface only."""
from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPalette, QPen
from PySide6.QtWidgets import QPushButton as _QPushButton, QStyle, QStyleOptionButton

from core.ui_scale import widget_scaled as px
from core.ui_theme import get_ui_theme
from ui.motion import HoverAnimator
from .icon_label import draw_button_label
from .theme import CONTROL_RADIUS, FONT_FAMILY, MOTION_NORMAL, button_colors, css_color, tinted_icon, ui_tokens


class Button(_QPushButton):
    VARIANTS = ("default", "primary", "secondary", "outline", "ghost", "destructive", "destructive-ghost", "link")
    SIZES = {"xs": (24, 8), "sm": (32, 12), "md": (36, 14), "default": (36, 14),
             "lg": (40, 24), "icon": (36, 0), "icon-sm": (32, 0), "icon-lg": (40, 0)}

    def __init__(self, text="", parent=None, *, variant="primary", size="md", icon=None):
        if variant not in self.VARIANTS or size not in self.SIZES:
            raise ValueError("Unknown button variant or size")
        super().__init__(text, parent)
        self._variant, self._size = variant, size
        self._theme_icon_source = icon
        self._base_icon_size = 16
        self._hover = HoverAnimator(self, duration=MOTION_NORMAL)
        self._press = HoverAnimator(self, duration=90)
        self.pressed.connect(self._press.enter)
        self.released.connect(self._press.leave)
        self._keyboard_focus = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.toggled.connect(self._refresh_icon)
        get_ui_theme().theme_changed.connect(self._apply_theme)
        self._apply_theme()

    def setVariant(self, variant):
        if variant not in self.VARIANTS:
            raise ValueError(f"Unknown button variant: {variant}")
        self._variant = variant
        self._apply_theme()

    def setSize(self, size):
        if size not in self.SIZES:
            raise ValueError(f"Unknown button size: {size}")
        if self._size.startswith("icon") and not size.startswith("icon"):
            self.setMinimumSize(0, 0)
            self.setMaximumSize(16777215, 16777215)
        self._size = size
        self._apply_theme()

    def setBaseIconSize(self, size):
        self._base_icon_size = int(size)
        self._apply_theme()

    def setIcon(self, icon):
        self._theme_icon_source = icon
        self._refresh_icon()

    def _colors(self):
        return button_colors(ui_tokens(self), self._variant, checked=self.isChecked(), enabled=self.isEnabled())

    def _refresh_icon(self, *_):
        icon = self._theme_icon_source
        if icon is None:
            return
        if isinstance(icon, QIcon):
            super().setIcon(icon)
        else:
            super().setIcon(tinted_icon(icon, self._colors()[2]))
        self.update()

    def _apply_theme(self, *_):
        height, pad = self.SIZES[self._size]
        text = button_colors(ui_tokens(self), self._variant, checked=self.isChecked())[2]
        self._own_style = f"""
            QPushButton {{ min-height: {px(self, height - 10)}px;
                padding: {px(self, 4)}px {px(self, pad)}px;
                border: 1px solid transparent; border-radius: {px(self, CONTROL_RADIUS)}px;
                background: transparent; color: {text};
                font: 600 {px(self, 14)}px {FONT_FAMILY}; }}
            QPushButton:disabled {{ color: {ui_tokens(self).text_disabled}; }}
        """
        self.setStyleSheet(self._own_style)
        self.setIconSize(QSize(px(self, self._base_icon_size), px(self, self._base_icon_size)))
        if self._size.startswith("icon"):
            self.setFixedSize(px(self, height), px(self, height))
        self._refresh_icon()
        self.updateGeometry()
        self.update()

    def sizeHint(self):
        size = super().sizeHint()
        if self.text() and not self.icon().isNull() and self.styleSheet() == self._own_style:
            size.setWidth(size.width() + max(0, px(self, 8) - 4))
        return size

    def enterEvent(self, event):
        self._hover.enter()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover.leave()
        super().leaveEvent(event)

    def focusInEvent(self, event):
        self._keyboard_focus = event.reason() in (Qt.FocusReason.TabFocusReason, Qt.FocusReason.BacktabFocusReason, Qt.FocusReason.ShortcutFocusReason)
        self.update()
        super().focusInEvent(event)

    def focusOutEvent(self, event):
        self._keyboard_focus = False
        self.update()
        super().focusOutEvent(event)

    def changeEvent(self, event):
        from PySide6.QtCore import QEvent
        super().changeEvent(event)
        if event.type() == QEvent.Type.EnabledChange and hasattr(self, "_hover"):
            self._refresh_icon()
            self.update()

    def paintEvent(self, event):
        # Legacy feature pages can still deliberately supply their own QSS.
        if self.styleSheet() != self._own_style:
            return super().paintEvent(event)
        base, hover, foreground, border = self._colors()
        start, end = css_color(base), css_color(hover)
        progress = self._hover.value() if self.isEnabled() else 0.0
        fill = QColor.fromRgbF(*(a + (b - a) * progress for a, b in zip(start.getRgbF(), end.getRgbF())))
        if self.isDown() and self.isEnabled():
            fill = css_color(ui_tokens(self).accent_strong_pressed if self._variant in ("primary", "default") else hover)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        inset = self._press.value() * px(self, 1)
        rect = QRectF(self.rect()).adjusted(.5 + inset, .5 + inset, -.5 - inset, -.5 - inset)
        painter.setPen(QPen(css_color(border), 1))
        painter.setBrush(fill)
        painter.drawRoundedRect(rect, px(self, CONTROL_RADIUS), px(self, CONTROL_RADIUS))
        if self.hasFocus() and self._keyboard_focus:
            painter.setPen(QPen(QColor(ui_tokens(self).ring), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect.adjusted(2, 2, -2, -2), px(self, CONTROL_RADIUS - 2), px(self, CONTROL_RADIUS - 2))
        option = QStyleOptionButton()
        self.initStyleOption(option)
        option.palette.setColor(QPalette.ColorRole.ButtonText, QColor(foreground))
        option.state &= ~QStyle.StateFlag.State_HasFocus
        if self._variant == "link":
            font = painter.font()
            font.setUnderline(self.underMouse() and self.isEnabled())
            painter.setFont(font)
        draw_button_label(self, painter, option)


class IconButton(Button):
    def __init__(self, icon, parent=None, *, tooltip, variant="ghost"):
        super().__init__("", parent, variant=variant, size="icon", icon=icon)
        self.setToolTip(tooltip)
        self.setAccessibleName(tooltip)
