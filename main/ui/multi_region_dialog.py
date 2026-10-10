"""Multi-region selection over a frozen desktop; overlays never enter exported pixels."""
from PySide6.QtCore import QRect, QRectF, Qt
from PySide6.QtGui import QColor, QCursor, QImage, QKeySequence, QPainter, QPen, QShortcut
from PySide6.QtWidgets import QApplication, QDialog, QFrame, QHBoxLayout, QListWidget, QVBoxLayout

from capture.multi_region import MultiRegionSelection
from core.ui_scale import configure_dialog_control, dialog_scaled, scale_dialog_font
from core.ui_theme import get_ui_theme
from ui.fluent_lite import CaptionLabel, PrimaryPushButton, PushButton


class MultiRegionDialog(QDialog):
    def __init__(self, source, bounds, *, max_regions, max_pixels, parent=None):
        super().__init__(parent)
        if source.isNull() or source.size() != bounds.size():
            raise ValueError("Frozen frame dimensions do not match its desktop bounds")
        self.source = QImage(source)  # implicit sharing freezes the frame without a second desktop allocation
        self.bounds = QRect(bounds)
        self.selection = MultiRegionSelection(QRect(0, 0, source.width(), source.height()), max_regions, max_pixels)
        self._origin = None
        self._drag_rect = QRect()
        self._panel_corner = 0
        self._controls_screen = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        self.setWindowTitle(self.tr("Multiple Regions"))
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setGeometry(bounds)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.panel = QFrame(self)
        self.panel.setObjectName("MultiRegionControls")
        self.panel.setCursor(Qt.CursorShape.ArrowCursor)
        scale_dialog_font(self.panel)
        layout = QVBoxLayout(self.panel)
        layout.setContentsMargins(*[dialog_scaled(12)] * 4)
        self.hint = CaptionLabel(self.tr("Drag to add regions from this frozen frame. Overlaps are exported separately. Existing annotations are not included."), self.panel)
        configure_dialog_control(self.hint)
        layout.addWidget(self.hint)
        self.list = QListWidget(self.panel)
        self.list.setAccessibleName(self.tr("Region order"))
        self.list.setMinimumHeight(dialog_scaled(140))
        self.list.currentRowChanged.connect(self.update)
        layout.addWidget(self.list)
        for entries in ((("Move up", lambda: self.move_region(-1)), ("Move down", lambda: self.move_region(1)),
                         ("Remove", self.remove_region)),
                        (("Undo", self.undo), ("Redo", self.redo), ("Clear", self.clear_regions))):
            row = QHBoxLayout()
            for label, callback in entries:
                button = PushButton(self.tr(label), self.panel)
                configure_dialog_control(button)
                button.clicked.connect(callback)
                row.addWidget(button)
                if label in ("Undo", "Redo"):
                    setattr(self, label.lower() + "_button", button)
            layout.addLayout(row)
        self.status = CaptionLabel(self.panel)
        configure_dialog_control(self.status)
        layout.addWidget(self.status)
        move = PushButton(self.tr("Move controls"), self.panel)
        configure_dialog_control(move)
        move.clicked.connect(self.move_controls)
        layout.addWidget(move)
        row = QHBoxLayout()
        cancel = PushButton(self.tr("Cancel"), self.panel)
        self.collect = PrimaryPushButton(self.tr("Collect regions"), self.panel)
        for button in (cancel, self.collect):
            configure_dialog_control(button)
            row.addWidget(button)
        cancel.clicked.connect(self.reject)
        self.collect.clicked.connect(self.accept)
        layout.addLayout(row)
        self.shortcuts = []
        for sequence, callback in (("Ctrl+Z", self.undo), ("Ctrl+Y", self.redo), ("Ctrl+Shift+Z", self.redo),
                                   ("Delete", self.remove_region), ("Return", self.accept), ("Escape", self.reject),
                                   ("Tab", self.toggle_controls)):
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.activated.connect(callback)
            self.shortcuts.append(shortcut)
        self._theme()
        get_ui_theme().theme_changed.connect(self._theme)
        self.sync_list()

    def _theme(self, *_):
        tokens = get_ui_theme().tokens
        self.panel.setStyleSheet(f"QFrame#MultiRegionControls {{ background: {tokens.surface}; border: 1px solid {tokens.border}; border-radius: 10px; }}"
                                f"QListWidget {{ background: {tokens.surface}; color: {tokens.text}; border: 1px solid {tokens.border}; }}"
                                f"QListWidget::item:selected {{ background: {tokens.accent_soft}; color: {tokens.text}; }}")
        self.update()

    def showEvent(self, event):
        super().showEvent(event)
        self.setGeometry(self.bounds)
        self.place_controls()
        if QApplication.platformName() == "windows":
            from core.platform_utils import set_window_exclude_from_capture
            set_window_exclude_from_capture(int(self.winId()), True)
        self.setFocus()

    def place_controls(self):
        available = self._controls_screen.availableGeometry().intersected(self.bounds).translated(-self.bounds.topLeft())
        self.panel.setFixedWidth(min(dialog_scaled(370), max(220, available.width() - 24)))
        self.panel.adjustSize()
        x = available.left() + 12 if self._panel_corner % 2 else available.right() - self.panel.width() - 12
        y = available.top() + 12 if self._panel_corner < 2 else available.bottom() - self.panel.height() - 12
        self.panel.move(max(0, x), max(0, y))
        self.panel.raise_()

    def move_controls(self):
        self._panel_corner = (self._panel_corner + 1) % 4
        self.place_controls()

    def toggle_controls(self):
        self.panel.setVisible(not self.panel.isVisible())

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._origin = event.position().toPoint()
            self._drag_rect = QRect()
            self.setFocus()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._origin is not None:
            self._drag_rect = QRect(self._origin, event.position().toPoint()).normalized().intersected(self.rect())
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._origin is not None:
            rect = QRect(self._origin, event.position().toPoint())
            self._origin = None
            self._drag_rect = QRect()
            try:
                self.selection.add(rect)
                self.sync_list(len(self.selection.regions) - 1)
            except ValueError:
                self.status.setText(self.tr("Region is too small or exceeds the remaining collection capacity."))
            self.update()
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def sync_list(self, selected=None):
        if selected is None:
            selected = self.list.currentRow()
        self.list.clear()
        for index, rect in enumerate(self.selection.regions):
            self.list.addItem(f"{index+1} · {rect.width()} × {rect.height()} · ({rect.x()+self.bounds.x()}, {rect.y()+self.bounds.y()})")
        if self.list.count():
            self.list.setCurrentRow(min(max(0, selected), self.list.count() - 1))
        self.collect.setEnabled(bool(self.selection.regions))
        self.undo_button.setEnabled(self.selection.can_undo)
        self.redo_button.setEnabled(self.selection.can_redo)
        self.status.setText(self.tr("%1 regions · Tab hides controls · Enter collects · Esc cancels").replace("%1", str(self.list.count())))
        self.update()

    def move_region(self, delta):
        row = self.list.currentRow()
        if self.selection.move(row, delta):
            self.sync_list(row + delta)

    def remove_region(self):
        if self.selection.remove(self.list.currentRow()):
            self.sync_list()

    def clear_regions(self):
        if self.selection.clear():
            self.sync_list()

    def undo(self):
        if self.selection.undo():
            self.sync_list()

    def redo(self):
        if self.selection.redo():
            self.sync_list()

    def accept(self):
        if self.selection.regions:
            super().accept()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.drawImage(QRectF(self.rect()), self.source, QRectF(0, 0, self.source.width(), self.source.height()))
        painter.fillRect(self.rect(), QColor(0, 0, 0, 115))
        for rect in self.selection.regions:
            painter.drawImage(rect, self.source, rect)
        for index, rect in enumerate(self.selection.regions):
            painter.setPen(QPen(QColor("#ffffff" if index == self.list.currentRow() else "#22d3ee"), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(rect.adjusted(0, 0, -1, -1))
            label = QRect(rect.x(), rect.y(), 28, 24)
            painter.fillRect(label, QColor("#0e7490"))
            painter.setPen(Qt.GlobalColor.white)
            painter.drawText(label, Qt.AlignmentFlag.AlignCenter, str(index+1))
        if not self._drag_rect.isEmpty():
            painter.setPen(QPen(QColor("#22d3ee"), 2, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(self._drag_rect)
        painter.end()
