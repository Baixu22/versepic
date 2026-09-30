"""Stateful neutral buttons. Native QPushButton behaviour, custom surface only."""
from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPalette, QPen
from PySide6.QtWidgets import QApplication, QPushButton as _QPushButton, QStyle, QStyleOptionButton

from core.ui_scale import widget_scaled as px
from core.ui_theme import get_ui_theme
from ui.motion import HoverAnimator
from .theme import FONT_FAMILY, css_color, tinted_icon, to_qicon, ui_tokens


class Button(_QPushButton):
    VARIANTS = ("primary", "secondary", "outline", "ghost", "destructive", "link")
    SIZES = {"sm": (30, 12), "md": (36, 14), "lg": (42, 18), "icon": (34, 0)}

    def __init__(self, text="", parent=None, *, variant="primary", size="md", icon=None):
        if variant not in self.VARIANTS or size not in self.SIZES:
            raise ValueError("Unknown button variant or size")
        super().__init__(text, parent)
        self._variant, self._size = variant, size
        self._theme_icon_source = icon
        self._base_icon_size = 16
        self._hover = HoverAnimator(self, duration=140)
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
        self._size = size
        self._apply_theme()

    def setBaseIconSize(self, size):
        self._base_icon_size = int(size)
        self._apply_theme()

    def setIcon(self, icon):
        self._theme_icon_source = icon
        self._refresh_icon()

    def _colors(self):
        t = ui_tokens(self)
        if not self.isEnabled():
            return t.surface_subtle, t.surface_subtle, t.text_disabled, t.border
        if self._variant == "primary":
            return t.accent_strong, t.accent_strong_hover, t.primary_foreground, "transparent"
        if self._variant == "destructive":
            return t.danger_soft, t.danger_soft, t.danger, "transparent"
        if self.isChecked() or self._variant == "secondary":
            return t.accent_soft, t.surface_hover, t.text, "transparent"
        if self._variant in ("ghost", "link"):
            return "transparent", t.surface_hover, t.text, "transparent"
        return t.input_background, t.surface_hover, t.text, t.border

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
        text = self._colors()[2]
        self._own_style = f"""
            QPushButton {{ min-height: {px(self, height - 10)}px;
                padding: {px(self, 4)}px {px(self, pad)}px;
                border: 1px solid transparent; border-radius: {px(self, 18)}px;
                background: transparent; color: {text};
                font: 600 {px(self, 13)}px {FONT_FAMILY}; }}
        """
        self.setStyleSheet(self._own_style)
        self.setIconSize(QSize(px(self, self._base_icon_size), px(self, self._base_icon_size)))
        if self._size == "icon":
            self.setFixedSize(px(self, height), px(self, height))
        else:
            self.setMinimumWidth(0)
            self.setMaximumWidth(16777215)
            self.setMaximumHeight(16777215)
        self._refresh_icon()
        self.updateGeometry()
        self.update()

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
            fill = css_color(ui_tokens(self).accent_strong_pressed if self._variant == "primary" else ui_tokens(self).accent_soft)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        inset = self._press.value() * px(self, 1)
        rect = QRectF(self.rect()).adjusted(.5 + inset, .5 + inset, -.5 - inset, -.5 - inset)
        painter.setPen(QPen(css_color(border), 1))
        painter.setBrush(fill)
        painter.drawRoundedRect(rect, px(self, 18), px(self, 18))
        if self.hasFocus() and self._keyboard_focus:
            painter.setPen(QPen(QColor(ui_tokens(self).ring), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect.adjusted(2, 2, -2, -2), px(self, 16), px(self, 16))
        option = QStyleOptionButton()
        self.initStyleOption(option)
        option.palette.setColor(QPalette.ColorRole.ButtonText, QColor(foreground))
        option.state &= ~QStyle.StateFlag.State_HasFocus
        self.style().drawControl(QStyle.ControlElement.CE_PushButtonLabel, option, painter, self)


class IconButton(Button):
    def __init__(self, icon, parent=None, *, tooltip, variant="ghost"):
        super().__init__("", parent, variant=variant, size="icon", icon=icon)
        self.setToolTip(tooltip)
        self.setAccessibleName(tooltip)
