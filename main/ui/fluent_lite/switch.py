"""Neutral animated switch with native button keyboard/accessibility semantics."""
from PySide6.QtCore import Property, QEasingCurve, QPropertyAnimation, QRectF, Qt, Signal, QSize
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QAbstractButton, QApplication

from core.ui_scale import widget_scaled as px
from core.ui_theme import get_ui_theme
from .theme import ui_tokens


class SwitchButton(QAbstractButton):
    checkedChanged = Signal(bool)

    def __init__(self, parent=None, indicatorPos=None):
        super().__init__(parent)
        self._progress = 0.0
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._animation = QPropertyAnimation(self, b"progress", self)
        self._animation.setDuration(145)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.toggled.connect(self._on_toggled)
        get_ui_theme().theme_changed.connect(self._apply_theme)
        self._apply_theme()

    def _apply_theme(self, *_):
        self.setFixedSize(px(self, 40), px(self, 24))
        self.update()

    def sizeHint(self):
        return QSize(px(self, 40), px(self, 24))

    def _get_progress(self):
        return self._progress

    def _set_progress(self, value):
        self._progress = float(value)
        self.update()

    progress = Property(float, _get_progress, _set_progress)

    def setOnText(self, text):
        self._on_text = str(text)

    def setOffText(self, text):
        self._off_text = str(text)

    def _on_toggled(self, checked):
        self._animation.stop()
        end = 1.0 if checked else 0.0
        if not self.isVisible() or QApplication.instance().property("uiReducedMotion"):
            self._set_progress(end)
        else:
            self._animation.setStartValue(self._progress)
            self._animation.setEndValue(end)
            self._animation.start()
        self.checkedChanged.emit(checked)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not event.isAutoRepeat():
            self.click()
            event.accept()
            return
        super().keyPressEvent(event)

    def paintEvent(self, event):
        t = ui_tokens(self)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.isEnabled():
            painter.setOpacity(.45)
        margin = px(self, 2)
        track = QRectF(margin, margin, self.width()-2*margin, self.height()-2*margin)
        off, on = QColor(t.switch_off), QColor(t.accent)
        color = QColor.fromRgbF(*(a+(b-a)*self._progress for a,b in zip(off.getRgbF(), on.getRgbF())))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawRoundedRect(track, track.height()/2, track.height()/2)
        diameter = track.height()-4
        x = track.left()+2 + (track.width()-diameter-4)*self._progress
        knob = QColor(t.primary_foreground if self.isChecked() else "#FFFFFF")
        painter.setBrush(knob)
        painter.drawEllipse(QRectF(x, track.top()+2, diameter, diameter))
        if self.hasFocus():
            painter.setPen(QPen(QColor(t.ring), 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(.5,.5,-.5,-.5), self.height()/2, self.height()/2)
