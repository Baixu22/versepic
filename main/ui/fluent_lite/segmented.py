"""Neutral segmented control, retaining route keys and native keyboard navigation."""
from PySide6.QtCore import QEvent, Signal, Qt
from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QWidget

from core.ui_scale import widget_scaled as px
from core.ui_theme import get_ui_theme
from .button_base import Button
from .theme import CONTROL_RADIUS, ui_tokens


class _TabButton(Button):
    def _colors(self):
        t = ui_tokens(self)
        if self.isChecked() and self.isEnabled():
            return t.surface_strong, t.surface_strong, t.text, t.border
        return super()._colors()


class SegmentedWidget(QWidget):
    currentItemChanged = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items = {}
        self._current = None
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(3, 3, 3, 3)
        self._layout.setSpacing(2)
        self.setObjectName("KitSegments")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._apply_theme()
        get_ui_theme().theme_changed.connect(self._apply_theme)

    def _apply_theme(self, *_):
        t = ui_tokens(self)
        self._layout.setContentsMargins(*(px(self, 3) for _ in range(4)))
        self._layout.setSpacing(px(self, 2))
        self.setStyleSheet(f"QWidget#KitSegments {{ background: {t.surface_subtle}; border: none; border-radius: {px(self, CONTROL_RADIUS + 2)}px; }}")
        for button in self._items.values():
            button._apply_theme()

    def addItem(self, routeKey, text, onClick=None):
        self.insertItem(len(self._items), routeKey, text, onClick)

    def insertItem(self, index, routeKey, text, onClick=None):
        if routeKey in self._items:
            raise ValueError(f"Duplicate segment: {routeKey}")
        button = _TabButton(str(text), self, variant="ghost", size="sm")
        button.setCheckable(True)
        button.installEventFilter(self)
        button.clicked.connect(lambda checked=False, key=routeKey: self.setCurrentItem(key))
        if onClick:
            button.clicked.connect(onClick)
        self._group.addButton(button)
        self._layout.insertWidget(index, button)
        self._items[routeKey] = button
        button.setFocusPolicy(Qt.FocusPolicy.StrongFocus if self._current is None else Qt.FocusPolicy.ClickFocus)
        if self._current is None:
            self.setCurrentItem(routeKey)

    def setCurrentItem(self, routeKey):
        if routeKey not in self._items:
            return
        self._items[routeKey].setChecked(True)
        for key, button in self._items.items():
            button.setFocusPolicy(Qt.FocusPolicy.StrongFocus if key == routeKey else Qt.FocusPolicy.ClickFocus)
        if self._current != routeKey:
            self._current = routeKey
            self.currentItemChanged.emit(routeKey)

    def currentItem(self):
        return self._current

    def setIndicatorColor(self, light, dark=None):
        # Compatibility: the kit's selected tab always follows its neutral scope.
        self._indicator = str(light)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.KeyPress and event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Home, Qt.Key.Key_End):
            buttons = [self._layout.itemAt(i).widget() for i in range(self._layout.count())]
            buttons = [button for button in buttons if button.isEnabled()]
            if obj in buttons and buttons:
                step = 1 if event.key() == Qt.Key.Key_Right else -1
                if self.layoutDirection() == Qt.LayoutDirection.RightToLeft:
                    step = -step
                target = buttons[(buttons.index(obj)+step) % len(buttons)]
                if event.key() == Qt.Key.Key_Home:
                    target = buttons[0]
                elif event.key() == Qt.Key.Key_End:
                    target = buttons[-1]
                target.setFocus(Qt.FocusReason.TabFocusReason)
                target.click()
                return True
        return super().eventFilter(obj, event)
