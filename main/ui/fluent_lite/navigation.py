"""Lightweight route-based sidebar navigation."""

from enum import Enum
from typing import Optional

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPalette
from PySide6.QtWidgets import QButtonGroup, QPushButton, QStyle, QStyleOptionButton, QVBoxLayout, QWidget

from core.ui_scale import dialog_scaled, widget_scaled
from core.ui_theme import get_ui_theme
from ui.motion import HoverAnimator

from .icon_label import draw_button_label
from .theme import CONTROL_RADIUS, FONT_FAMILY, MOTION_NORMAL, css_color, tinted_icon, to_qicon, ui_tokens


class NavigationItemPosition(Enum):
    TOP = 0
    BOTTOM = 1


class NavigationItemButton(QPushButton):
    """Nav item whose pill background fades in/out over 150ms on hover.

    The stylesheet keeps owning text, icon and border colours; this widget
    only paints the rounded fill before the base class draws the label, so
    hovering eases through the fill colour instead of snapping.  Colours are
    supplied through :meth:`set_fill_colors` and default to the Fluent-lite
    sidebar look, keeping other pages pixel-identical to the old QSS fill.
    """

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self._keyboard_focus = False
        self._hover_fill: Optional[QColor] = None
        self._checked_fill: Optional[QColor] = None
        self._fill_radius = dialog_scaled(CONTROL_RADIUS)
        self._hover_animator = HoverAnimator(self, duration=MOTION_NORMAL)
        self._selection_animator = HoverAnimator(self, duration=MOTION_NORMAL)
        self.toggled.connect(lambda selected: self._selection_animator.enter() if selected else self._selection_animator.leave())

    def set_fill_colors(self, hover: str = None, checked: str = None, radius=None):
        """Restyle the painted fill; None colours fall back to no extra fill."""
        self._hover_fill = css_color(hover) if hover else None
        self._checked_fill = css_color(checked) if checked else None
        if radius is not None:
            self._fill_radius = int(radius)
        self.update()

    def enterEvent(self, event):
        self._hover_animator.enter()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover_animator.leave()
        super().leaveEvent(event)

    def focusInEvent(self, event):
        self._keyboard_focus = event.reason() in (Qt.FocusReason.TabFocusReason, Qt.FocusReason.BacktabFocusReason, Qt.FocusReason.ShortcutFocusReason)
        super().focusInEvent(event)
        self.update()

    def focusOutEvent(self, event):
        self._keyboard_focus = False
        super().focusOutEvent(event)
        self.update()

    def sizeHint(self):
        size = super().sizeHint()
        if self.text() and not self.icon().isNull():
            size.setWidth(size.width() + max(0, widget_scaled(self, 8) - 4))
        return size

    def paintEvent(self, event):
        painter = QPainter(self)
        fill = self._fill_color()
        if fill is not None:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(fill)
            rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
            painter.drawRoundedRect(rect, self._fill_radius, self._fill_radius)
        option = QStyleOptionButton()
        self.initStyleOption(option)
        if not self._keyboard_focus:
            option.state &= ~QStyle.StateFlag.State_HasFocus
        self.style().drawControl(QStyle.ControlElement.CE_PushButtonBevel, option, painter, self)
        tokens = ui_tokens(self)
        foreground = (tokens.text_disabled if not self.isEnabled() else
                      tokens.accent_text if self.isChecked() else
                      tokens.text if self.underMouse() else tokens.text_muted)
        option.palette.setColor(QPalette.ColorRole.ButtonText, QColor(foreground))
        source = getattr(self, "_navigation_icon", None)
        if source is not None and not isinstance(source, QIcon):
            option.icon = tinted_icon(source, foreground)
        draw_button_label(self, painter, option, centered=False)

    def _fill_color(self):
        selected = self._selection_animator.value()
        hovered = self._hover_animator.value()
        if self._checked_fill is None or self._hover_fill is None:
            return None
        hover = QColor(self._hover_fill)
        hover.setAlphaF(hover.alphaF() * hovered)
        checked = self._checked_fill
        return QColor.fromRgbF(*(a + (b - a) * selected for a, b in zip(hover.getRgbF(), checked.getRgbF())))



class NavigationInterface(QWidget):
    def __init__(self, parent=None, showMenuButton=False, showReturnButton=False, collapsible=False):
        super().__init__(parent)
        self._items = {}
        self._icons = {}
        self._current = None
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(dialog_scaled(4))
        self._top = QVBoxLayout()
        self._top.setSpacing(dialog_scaled(4))
        self._bottom = QVBoxLayout()
        self._bottom.setSpacing(dialog_scaled(4))
        self._layout.addLayout(self._top)
        self._layout.addStretch(1)
        self._layout.addLayout(self._bottom)
        self.setStyleSheet("background: transparent;")
        get_ui_theme().theme_changed.connect(self._apply_theme)

    def addItem(self, routeKey, icon, text, onClick, position=NavigationItemPosition.TOP, tooltip=None):
        button = NavigationItemButton(str(text), self)
        button.setObjectName("FluentLiteNavItem")
        button.setCheckable(True)
        button.setIconSize(QSize(dialog_scaled(16), dialog_scaled(16)))
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        # Labels are already visible in the expanded navigation.  Creating a
        # duplicate tooltip for every item leaves an unwanted popup on hover;
        # only opt in when a caller has genuinely extra context to show.
        if tooltip:
            button.setToolTip(str(tooltip))
        button.clicked.connect(lambda checked=False, key=routeKey: self.setCurrentItem(key))
        if onClick:
            button.clicked.connect(onClick)
        self._group.addButton(button)
        self._items[routeKey] = button
        button._navigation_icon = icon
        button.setAutoDefault(False)
        self._icons[routeKey] = icon
        button.toggled.connect(lambda _checked, key=routeKey: self._apply_icon(key))
        self._style_button(button)
        self._apply_icon(routeKey)
        target = self._bottom if position == NavigationItemPosition.BOTTOM else self._top
        target.addWidget(button)
        return button

    def _style_button(self, button):
        t = ui_tokens(button)
        # The fill itself is painted by NavigationItemButton so hovering can
        # fade; the stylesheet background stays transparent on every state.
        button.set_fill_colors(t.surface_hover, t.accent_soft, radius=dialog_scaled(CONTROL_RADIUS))
        button.setStyleSheet(f"""
            QPushButton#FluentLiteNavItem {{ min-height: {dialog_scaled(32)}px; padding: {dialog_scaled(2)}px {dialog_scaled(12)}px; text-align: left;
                color: {t.text_muted}; background: transparent; border: 1px solid transparent; border-radius: {dialog_scaled(CONTROL_RADIUS)}px;
                font: 500 {dialog_scaled(14)}px {FONT_FAMILY}; }}
            QPushButton#FluentLiteNavItem:hover {{ color: {t.text}; background: transparent; }}
            QPushButton#FluentLiteNavItem:checked {{ color: {t.accent_text}; background: transparent; }}
            QPushButton#FluentLiteNavItem:focus {{ border-color: {t.ring}; }}
            QPushButton#FluentLiteNavItem:disabled {{ color: {t.text_disabled}; }}
        """)

    def _apply_icon(self, route_key):
        """选中项的图标跟文字一起换成强调色，其余跟正文色。"""
        button = self._items[route_key]
        icon = self._icons[route_key]
        if button.isChecked() and not isinstance(icon, QIcon):
            button.setIcon(tinted_icon(icon, ui_tokens(button).accent_text))
        else:
            button.setIcon(to_qicon(icon, button))

    def _apply_theme(self, _tokens=None):
        for route_key, button in self._items.items():
            self._style_button(button)
            self._apply_icon(route_key)

    def setCurrentItem(self, routeKey):
        button = self._items.get(routeKey)
        if button is None:
            return
        self._current = routeKey
        button.setChecked(True)

    def clearCurrentItem(self):
        self._group.setExclusive(False)
        for button in self._items.values():
            button.setChecked(False)
        self._group.setExclusive(True)
        self._current = None

    def setExpandWidth(self, width):
        self._expand_width = int(width)

    def setMinimumExpandWidth(self, width):
        self._minimum_expand_width = int(width)

    def expand(self, useAni=True):
        if getattr(self, "_expand_width", 0):
            self.setMinimumWidth(self._expand_width)

    def widget(self, routeKey):
        return self._items.get(routeKey)
