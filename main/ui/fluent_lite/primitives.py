"""Small neutral controls used by both the component gallery and feature pages."""
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QCheckBox as _QCheckBox, QFrame, QLabel, QStyle, QStyleOptionButton, QWidget

from core.ui_scale import widget_scaled as px
from core.ui_theme import get_ui_theme
from ui.outline_icons import outline_icon
from .theme import FONT_FAMILY, ITEM_RADIUS, css_color, ui_tokens


class CheckBox(_QCheckBox):
    def __init__(self, text="", parent=None):
        if isinstance(text, QWidget):
            parent, text = text, ""
        super().__init__(text, parent)
        self._apply_theme()
        get_ui_theme().theme_changed.connect(self._apply_theme)

    def _apply_theme(self, *_):
        t = ui_tokens(self)
        self.setStyleSheet(f"""
            QCheckBox {{ color: {t.text}; spacing: {px(self, 8)}px;
                font: {px(self, 14)}px {FONT_FAMILY}; }}
            QCheckBox::indicator {{ width: {px(self, 16)}px; height: {px(self, 16)}px; }}
            QCheckBox:disabled {{ color: {t.text_disabled}; }}
        """)
        self.update()

    def paintEvent(self, event):
        option = QStyleOptionButton()
        self.initStyleOption(option)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        t = ui_tokens(self)
        if not self.isEnabled():
            painter.setOpacity(.45)
        rect = self.style().subElementRect(QStyle.SubElement.SE_CheckBoxIndicator, option, self)
        box = QRectF(rect).adjusted(1, 1, -1, -1)
        selected = self.checkState() != Qt.CheckState.Unchecked
        painter.setBrush(css_color(t.accent if selected else t.input_background))
        painter.setPen(QPen(css_color(t.accent if selected else t.border_hover), 1))
        painter.drawRoundedRect(box, px(self, ITEM_RADIUS), px(self, ITEM_RADIUS))
        if self.checkState() == Qt.CheckState.PartiallyChecked:
            painter.setPen(QPen(QColor(t.primary_foreground), 1.75))
            painter.drawLine(box.center().x()-4, box.center().y(), box.center().x()+4, box.center().y())
        elif selected:
            outline_icon("check", t.primary_foreground).paint(painter, rect.adjusted(1,1,-1,-1))
        label = self.rect()
        if self.layoutDirection() == Qt.LayoutDirection.RightToLeft:
            label.setRight(rect.left()-px(self,8))
        else:
            label.setLeft(rect.right()+px(self,8))
        painter.setPen(QColor(t.text))
        painter.drawText(label, Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextShowMnemonic, self.text())
        if self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(t.ring), 1))
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(.5,.5,-.5,-.5), 3, 3)


class Badge(QLabel):
    VARIANTS = ("secondary", "outline", "primary", "destructive")

    def __init__(self, text="", parent=None, *, variant="secondary"):
        if variant not in self.VARIANTS:
            raise ValueError(f"Unknown badge variant: {variant}")
        super().__init__(text, parent)
        self.variant = variant
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._apply_theme()
        get_ui_theme().theme_changed.connect(self._apply_theme)

    def _apply_theme(self, *_):
        t = ui_tokens(self)
        bg, fg, border = t.surface_subtle, t.text, "transparent"
        if self.variant == "primary":
            bg, fg = t.accent_strong, t.primary_foreground
        elif self.variant == "outline":
            bg, border = "transparent", t.border
        elif self.variant == "destructive":
            bg, fg = t.destructive_background, "#FFFFFF"
        self.setStyleSheet(f"QLabel {{ background: {bg}; color: {fg}; border: 1px solid {border}; border-radius: {px(self,10)}px; min-height: {px(self,16)}px; padding: {px(self,2)}px {px(self,7)}px; font: 500 {px(self,12)}px {FONT_FAMILY}; }}")


class Separator(QFrame):
    def __init__(self, parent=None, *, vertical=False):
        super().__init__(parent)
        self.vertical = vertical
        self._apply_theme()
        get_ui_theme().theme_changed.connect(self._apply_theme)

    def _apply_theme(self, *_):
        if self.vertical:
            self.setFixedWidth(1)
        else:
            self.setFixedHeight(1)
        self.setStyleSheet(f"background: {ui_tokens(self).separator}; border: none;")
