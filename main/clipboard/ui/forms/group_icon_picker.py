"""Lazy, keyboard-accessible group icon picker with virtualized emoji cells."""
from PySide6.QtCore import QPoint, QRectF, QSize, Qt, QTextBoundaryFinder
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QListWidget, QListWidgetItem, QStyle,
    QStyledItemDelegate, QVBoxLayout,
)

from ui.fluent_lite import Button, LineEdit
from ui.fluent_lite.theme import ITEM_RADIUS, POPUP_RADIUS, ui_tokens
from ..layout_scale import scale_ui
from ..resources.emoji_data import get_emoji_groups, get_group_icon


def first_grapheme(text):
    text = text.strip()
    finder = QTextBoundaryFinder(QTextBoundaryFinder.BoundaryType.Grapheme, text)
    end = finder.toNextBoundary()
    # Qt boundaries count UTF-16 code units, not Python code points.
    return text.encode("utf-16-le")[:end * 2].decode("utf-16-le") if end > 0 else ""


class EmojiDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        tokens = ui_tokens(self.parent())
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(option.rect).adjusted(2, 2, -2, -2)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        if selected or option.state & QStyle.StateFlag.State_MouseOver:
            painter.setPen(QPen(QColor(tokens.ring), 1) if selected else Qt.PenStyle.NoPen)
            painter.setBrush(QColor(tokens.accent_soft if selected else tokens.surface_hover))
            painter.drawRoundedRect(rect, scale_ui(ITEM_RADIUS), scale_ui(ITEM_RADIUS))
        font = QFont("Segoe UI Emoji")
        font.setPixelSize(scale_ui(21))
        painter.setFont(font)
        painter.setPen(QColor(tokens.text))
        painter.drawText(option.rect, Qt.AlignmentFlag.AlignCenter, index.data())
        painter.restore()


class EmojiButton(Button):
    def _apply_theme(self, *_):
        super()._apply_theme()
        self._own_style += f"QPushButton {{ font: {scale_ui(20)}px 'Segoe UI Emoji'; }}"
        self.setStyleSheet(self._own_style)


class GroupIconPopup(QFrame):
    def __init__(self, dialog):
        super().__init__(dialog, Qt.WindowType.Popup)
        self.dialog = dialog
        self.form_token = dialog._detail_form_token
        self.setObjectName("GroupIconPopup")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.setFixedSize(scale_ui(348), scale_ui(344))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(scale_ui(12), scale_ui(12), scale_ui(12), scale_ui(12))
        layout.setSpacing(scale_ui(8))
        self.input = LineEdit(self)
        self.input.setPlaceholderText(dialog.tr("Enter or paste emoji..."))
        self.input.setAccessibleName(dialog.tr("Select Icon"))
        self.input.setMaxLength(64)
        self.input.returnPressed.connect(lambda: self.choose(first_grapheme(self.input.text())))
        layout.addWidget(self.input)
        self.order, self.groups = get_emoji_groups()
        tabs = QHBoxLayout()
        tabs.setSpacing(0)
        self.tabs = []
        for index, name in enumerate(self.order):
            button = EmojiButton(get_group_icon(name), self, variant="ghost", size="icon-sm")
            button.setAutoDefault(False)
            button.setCheckable(True)
            button.setToolTip(name)
            button.setAccessibleName(name)
            button.clicked.connect(lambda checked=False, i=index: self.show_category(i))
            tabs.addWidget(button)
            self.tabs.append(button)
        tabs.addStretch()
        layout.addLayout(tabs)
        self.grid = QListWidget(self)
        self.grid.setViewMode(QListWidget.ViewMode.IconMode)
        self.grid.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.grid.setMovement(QListWidget.Movement.Static)
        self.grid.setUniformItemSizes(True)
        self.grid.setGridSize(QSize(scale_ui(38), scale_ui(38)))
        self.grid.setMouseTracking(True)
        self.grid.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.grid.setItemDelegate(EmojiDelegate(self.grid))
        self.grid.itemClicked.connect(lambda item: self.choose(item.text()))
        self.grid.itemActivated.connect(lambda item: self.choose(item.text()))
        layout.addWidget(self.grid, 1)
        self._apply_theme()
        self.show_category(0)

    def _apply_theme(self, *_):
        self.setStyleSheet(
            "QFrame#GroupIconPopup { background: transparent; border: none; }"
            "QListWidget { background: transparent; border: none; outline: none; }"
        )
        for button in self.tabs:
            button._apply_theme()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        tokens = ui_tokens(self)
        painter.setBrush(QColor(tokens.surface))
        painter.setPen(QPen(QColor(tokens.border), 1))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(.5, .5, -.5, -.5),
                                scale_ui(POPUP_RADIUS), scale_ui(POPUP_RADIUS))

    def show_category(self, index):
        for i, button in enumerate(self.tabs):
            button.setChecked(i == index)
        self.grid.clear()
        for emoji in self.groups[self.order[index]]:
            item = QListWidgetItem(emoji)
            item.setSizeHint(self.grid.gridSize())
            item.setToolTip(emoji)
            self.grid.addItem(item)
        self.grid.setCurrentRow(0)
        self.grid.scrollToTop()

    def choose(self, icon):
        if icon and self.form_token == self.dialog._detail_form_token:
            self.dialog.icon_input.setText(icon)
            self.hide()
            self.dialog.icon_picker_button.setFocus()

    def open_at(self, button):
        point = button.mapToGlobal(QPoint(0, button.height() + scale_ui(6)))
        available = button.screen().availableGeometry()
        point.setX(max(available.left(), min(point.x(), available.right() - self.width() + 1)))
        if point.y() + self.height() > available.bottom():
            point.setY(button.mapToGlobal(QPoint(0, 0)).y() - self.height() - scale_ui(6))
        point.setY(max(available.top(), point.y()))
        self.move(point)
        self.show()
        self.grid.setFocus()


def create_group_icon_picker(dialog, current_icon="📁"):
    dialog.icon_input = LineEdit(dialog.detail_content)
    dialog.icon_input.setText(current_icon)
    dialog.icon_input.setMaxLength(64)
    dialog.icon_input.hide()
    button = EmojiButton(current_icon, dialog.detail_content, variant="outline", size="icon")
    button.setAutoDefault(False)
    button.setToolTip(dialog.tr("Select Icon"))
    button.setAccessibleName(dialog.tr("Select Icon"))
    dialog.icon_picker_button = button
    dialog._icon_popup = None

    def open_picker():
        if dialog._icon_popup is None:
            dialog._icon_popup = GroupIconPopup(dialog)
        dialog._icon_popup.open_at(button)

    button.clicked.connect(open_picker)
    dialog.icon_input.textChanged.connect(lambda text: button.setText(first_grapheme(text)))
    return button


def on_icon_input_changed(dialog, text):
    icon = first_grapheme(text)
    if icon != text:
        dialog.icon_input.setText(icon)


def on_preset_icon_clicked(dialog, icon):
    dialog.icon_input.setText(first_grapheme(icon))
