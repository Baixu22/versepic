"""Scoped popup primitives; never borrow tooltip colours from another window."""
import weakref

from PySide6.QtCore import QEvent, QObject, QPoint, Qt, QTimer
from PySide6.QtWidgets import QApplication, QLabel, QMenu, QToolTip
from shiboken6 import isValid

from core.ui_scale import widget_scaled as px
from core.ui_theme import get_ui_theme
from ui.motion import fade_show, cancel_motion
from .theme import FONT_FAMILY, ui_tokens


class Menu(QMenu):
    def __init__(self, title="", parent=None):
        super().__init__(title, parent)
        self._apply_theme()
        self.aboutToShow.connect(self._apply_theme)
        get_ui_theme().theme_changed.connect(self._apply_theme)

    def showEvent(self, event):
        super().showEvent(event)
        cancel_motion(self)
        fade_show(self, duration=120, rise_px=0)

    def _apply_theme(self, *_):
        t = ui_tokens(self)
        self.setStyleSheet(f"""
            QMenu {{ color: {t.text}; background-color: {t.popup_background};
                border: 1px solid {t.border}; border-radius: {px(self, 14)}px;
                padding: {px(self,4)}px; font: {px(self,13)}px {FONT_FAMILY}; }}
            QMenu::item {{ border-radius: {px(self,10)}px; padding: {px(self,7)}px {px(self,32)}px {px(self,7)}px {px(self,24)}px; }}
            QMenu::item:selected {{ color: {t.text}; background-color: {t.popup_hover}; }}
            QMenu::item:disabled {{ color: {t.text_disabled}; }}
            QMenu::separator {{ height: 1px; margin: {px(self,4)}px; background: {t.separator}; }}
        """)


class ToolTip(QObject):
    """One lazily-created tooltip per root; install once with ToolTip.install(root)."""
    def __init__(self, root):
        super().__init__(root)
        self.root = root
        self.label = None
        self._owner = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)
        QApplication.instance().installEventFilter(self)
        get_ui_theme().theme_changed.connect(self.hide)

    @classmethod
    def install(cls, root):
        existing = getattr(root, "_kit_tooltip", None)
        if existing is None:
            existing = root._kit_tooltip = cls(root)
        return existing

    def showFor(self, widget, position=None):
        if not widget.isEnabled() or not widget.toolTip():
            self.hide()
            return
        QToolTip.hideText()
        if self.label is None:
            self.label = QLabel(self.root, Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
            self.label.setObjectName("KitToolTip")
            self.label.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
            self.label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            self.label.setTextFormat(Qt.TextFormat.PlainText)
            self.label.setWordWrap(True)
        t = ui_tokens(widget)
        background, foreground = t.accent_strong, t.primary_foreground
        clipboard_theme = getattr(self.root, "current_theme", None)
        if clipboard_theme is not None:
            background = clipboard_theme.colors.text_primary
            foreground = clipboard_theme.colors.bg_primary
        self.label.setStyleSheet(f"""QLabel#KitToolTip {{
            color: {foreground}; background-color: {background};
            border: 1px solid {t.border_hover}; border-radius: {px(widget,10)}px;
            padding: {px(widget,6)}px {px(widget,9)}px;
            font: {px(widget,12)}px {FONT_FAMILY}; }}""")
        self.label.setMaximumWidth(px(widget, 320))
        self.label.setText(widget.toolTip())
        self.label.adjustSize()
        # Anchor to the control so pointer movement does not shift the tooltip.
        anchor = widget.mapToGlobal(QPoint(widget.width() // 2, widget.height()))
        point = anchor + QPoint(-self.label.width() // 2, px(widget, 8))
        screen = QApplication.screenAt(point) or widget.screen()
        bounds = screen.availableGeometry()
        point.setX(max(bounds.left()+4, min(point.x(), bounds.right()-self.label.width()-4)))
        if point.y()+self.label.height() > bounds.bottom()-4:
            top = widget.mapToGlobal(QPoint(0, 0)).y()
            point.setY(max(bounds.top()+4, top-self.label.height()-px(widget, 8)))
        self.label.move(point)
        self._owner = weakref.ref(widget)
        cancel_motion(self.label)
        self.label.show()
        fade_show(self.label, duration=120, rise_px=0)
        self._timer.start(4500)

    def hide(self, *_):
        self._timer.stop()
        if self.label is not None and isValid(self.label):
            cancel_motion(self.label)
            self.label.hide()
        self._owner = None

    def eventFilter(self, obj, event):
        kind = event.type()
        owner = self._owner() if self._owner else None
        if kind in (QEvent.Type.Hide, QEvent.Type.Leave, QEvent.Type.Destroy) and (obj is owner or obj is self.root):
            self.hide()
        if kind in (QEvent.Type.MouseButtonPress, QEvent.Type.KeyPress, QEvent.Type.WindowDeactivate):
            self.hide()
        if kind == QEvent.Type.ToolTip and hasattr(obj, "toolTip"):
            if obj is self.root or self.root.isAncestorOf(obj):
                self.showFor(obj, event.globalPos())
                event.accept()
                return True
        return False
