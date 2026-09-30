"""Polished native input controls with stable application-facing names."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QComboBox, QDoubleSpinBox as _QDoubleSpinBox
from PySide6.QtWidgets import QStyle, QStyleOptionComboBox, QStylePainter
from PySide6.QtWidgets import QLineEdit as _QLineEdit
from PySide6.QtWidgets import QSpinBox as _QSpinBox
from PySide6.QtWidgets import QTextEdit as _QTextEdit

from core.ui_scale import widget_scaled as _px
from core.ui_theme import get_ui_theme

from .text_context_menu import TextContextMenuMixin, install_text_context_menu
from .theme import (
    ACCENT, FONT_FAMILY, INPUT_CONTENT_HEIGHT, INPUT_PADDING_H, INPUT_PADDING_V,
    INPUT_RADIUS, ui_tokens,
)


def _input_qss(widget=None):
    t = ui_tokens(widget)
    s = lambda value: _px(widget, value)
    return f"""
    QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox {{
        min-height: {s(INPUT_CONTENT_HEIGHT)}px;
        padding: {s(INPUT_PADDING_V)}px {s(INPUT_PADDING_H)}px; color: {t.text};
        background: {t.input_background}; border: 1px solid transparent;
        border-radius: {s(INPUT_RADIUS)}px;
        font: {s(13)}px {FONT_FAMILY}; selection-background-color: {t.accent};
        selection-color: {t.selected_text};
    }}
    QComboBox:hover, QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover {{
        border-color: {t.border}; background: {t.input_background};
    }}
    QComboBox:focus, QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
        border: 1px solid {t.ring}; background: {t.input_background};
    }}
    QComboBox:disabled, QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{
        color: {t.text_disabled}; background: {t.surface_subtle}; border-color: {t.border};
    }}
    QComboBox::drop-down {{ width: {s(24)}px; border: none; }}
    QComboBox::down-arrow {{ image: none; }}
    QComboBox QAbstractItemView {{
        color: {t.text}; background: {t.popup_background}; border: 1px solid {t.border};
        border-radius: {s(INPUT_RADIUS)}px; padding: {s(5)}px; outline: none;
        selection-background-color: {t.accent_soft}; selection-color: {t.text};
    }}
    QComboBox QAbstractItemView::item {{ border-radius: {s(10)}px; min-height: {s(INPUT_CONTENT_HEIGHT)}px; padding: {s(3)}px {s(8)}px; }}
    QSpinBox::up-button, QDoubleSpinBox::up-button,
    QSpinBox::down-button, QDoubleSpinBox::down-button {{
        width: {s(18)}px; border: none; background: transparent;
    }}
    """


class _ThemedInput:
    def _init_theme(self):
        self._apply_theme()
        get_ui_theme().theme_changed.connect(self._apply_theme)

    def _apply_theme(self, _tokens=None):
        self.setStyleSheet(_input_qss(self))


class ComboBox(_ThemedInput, QComboBox):
    # Drop-downs need room for their popup arrow plus a readable entry.
    BASE_MIN_WIDTH = 96

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_theme()

    def _apply_theme(self, _tokens=None):
        super()._apply_theme(_tokens)
        # The scaled floor must not push past a ceiling the caller pinned with
        # setFixedWidth: when min exceeds max Qt honours min, and the box grows
        # out of line with the rest of its column.
        self.setMinimumWidth(min(_px(self, self.BASE_MIN_WIDTH), self.maximumWidth()))

    def showPopup(self):
        super().showPopup()
        from ui.motion import cancel_motion, fade_show
        popup = self.view().window()
        cancel_motion(popup)
        fade_show(popup, duration=120, rise_px=0)

    def paintEvent(self, event):
        """A left-aligned value and explicit outline chevron, including item icons."""
        from PySide6.QtCore import QRect
        from ui.outline_icons import outline_icon
        painter = QStylePainter(self)
        option = QStyleOptionComboBox()
        self.initStyleOption(option)
        text = option.currentText
        option.currentText = ""
        painter.drawComplexControl(QStyle.ComplexControl.CC_ComboBox, option)
        tokens = ui_tokens(self)
        color = tokens.text if self.isEnabled() else tokens.text_disabled
        painter.setPen(QColor(color))
        side = _px(self, 16)
        left = _px(self, 12)
        if not option.currentIcon.isNull():
            option.currentIcon.paint(painter, QRect(left, (self.height() - side) // 2, side, side))
            left += side + _px(self, 8)
        bounds = self.rect().adjusted(left, 0, -_px(self, 32), 0)
        text = painter.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, bounds.width())
        painter.drawText(bounds, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)
        outline_icon("chevron-down", color).paint(painter, QRect(self.width() - _px(self, 26), (self.height()-side)//2, side, side))


class LineEdit(TextContextMenuMixin, _ThemedInput, _QLineEdit):
    def __init__(self, parent=None, *, use_default_style: bool = True):
        super().__init__(parent)
        if use_default_style:
            self._init_theme()


class TextEdit(TextContextMenuMixin, _QTextEdit):
    """Multiline input with the same theme, selection and focus as LineEdit."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._apply_theme()
        get_ui_theme().theme_changed.connect(self._apply_theme)

    def _apply_theme(self, *_):
        from .theme import scrollbar_qss
        t = ui_tokens(self)
        self.setStyleSheet(f"""
            QTextEdit {{ color: {t.text}; background: {t.input_background};
                border: 1px solid {t.border}; border-radius: {_px(self, INPUT_RADIUS)}px;
                padding: {_px(self, 10)}px; font: {_px(self, 13)}px {FONT_FAMILY};
                selection-background-color: {t.accent}; selection-color: {t.selected_text}; }}
            QTextEdit:hover {{ border-color: {t.border_hover}; }}
            QTextEdit:focus {{ border-color: {t.ring}; }}
            QTextEdit:disabled {{ color: {t.text_disabled}; background: {t.surface_subtle}; }}
        """ + scrollbar_qss(self))


class SpinBox(_ThemedInput, _QSpinBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_theme()
        # 跟下拉框一样居中：数值比框窄得多，贴左显得空。
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        install_text_context_menu(self.lineEdit())


class DoubleSpinBox(_ThemedInput, _QDoubleSpinBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_theme()
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        install_text_context_menu(self.lineEdit())
