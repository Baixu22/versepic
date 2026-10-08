"""Review local OCR candidates, add missing areas, and copy/save a flattened image."""

import re

from PySide6.QtCore import Qt, QRectF, Signal
from PySide6.QtGui import QColor, QPen, QPixmap
from PySide6.QtWidgets import (
    QFileDialog, QGraphicsScene, QGraphicsView, QHBoxLayout,
    QListWidget, QListWidgetItem, QSplitter, QVBoxLayout,
)

from core.i18n import make_tr
from core.ui_scale import configure_dialog_control, dialog_scaled, scale_dialog_font
from core.ui_theme import get_ui_theme
from ui.dialogs import track_modeless_dialog
from ui.fluent_lite import (
    CaptionLabel, CheckBox, FluentTitleBar, FrostedFramelessDialog, LineEdit,
    PrimaryPushButton, PushButton, ui_tokens,
)
from .recognizer import NO_TEXT, recognize_async
from .redaction import redact_image, sensitive_lines
from .result_window import _reason_text

_tr = make_tr("RedactionWindow")


class _Preview(QGraphicsView):
    area_added = Signal(object)

    def __init__(self, image, parent):
        super().__init__(parent)
        scene = QGraphicsScene(self)
        self.setScene(scene)
        self._base = scene.addPixmap(QPixmap.fromImage(image))
        scene.setSceneRect(QRectF(image.rect()))
        self.setMinimumSize(dialog_scaled(260), dialog_scaled(180))
        self._start = None
        self._drag = None
        self.setCursor(Qt.CursorShape.CrossCursor)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fitInView(self.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            point = self.mapToScene(event.pos())
            if self.sceneRect().contains(point):
                self._start = point
                self._drag = self.scene().addRect(QRectF(point, point), QPen(QColor("#ff7043"), 2))
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._start is not None:
            rect = QRectF(self._start, self.mapToScene(event.pos())).normalized().intersected(self.sceneRect())
            self._drag.setRect(rect)
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._start is not None:
            rect = self._drag.rect().toAlignedRect()
            self.scene().removeItem(self._drag)
            self._drag = None
            self._start = None
            if rect.width() > 2 and rect.height() > 2:
                self.area_added.emit(rect)
            return
        super().mouseReleaseEvent(event)


class RedactionWindow(FrostedFramelessDialog):
    def __init__(self, image, parent=None):
        super().__init__(parent)
        scale_dialog_font(self)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setWindowTitle(_tr("Smart redact"))
        title = FluentTitleBar(self)
        self.setTitleBar(title)
        title.iconLabel.hide()
        title.hBoxLayout.setContentsMargins(dialog_scaled(12), 0, 0, 0)
        self._image = image.copy()
        self._image.setDevicePixelRatio(1)
        self._result = {"data": []}
        self._overlays = []
        self._manual = []
        self._thread = None

        self.preview = _Preview(self._image, self)
        self.preview.area_added.connect(self._add_manual)
        self.candidates = QListWidget(self)
        self.candidates.setMinimumWidth(dialog_scaled(210))
        self.candidates.itemChanged.connect(self._update_preview)
        split = QSplitter(self)
        split.addWidget(self.preview)
        split.addWidget(self.candidates)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)

        self.phones = CheckBox(_tr("Phone numbers"), self)
        self.emails = CheckBox(_tr("Email addresses"), self)
        self.phones.setChecked(True)
        self.emails.setChecked(True)
        self.phones.toggled.connect(self._rebuild)
        self.emails.toggled.connect(self._rebuild)
        self.keywords = LineEdit(self)
        self.keywords.setPlaceholderText(_tr("Keywords, separated by commas"))
        self.keywords.textChanged.connect(self._rebuild)
        options = QHBoxLayout()
        options.addWidget(self.phones)
        options.addWidget(self.emails)
        options.addWidget(self.keywords, 1)

        self.status = CaptionLabel(_tr("Recognizing..."), self)
        self.hint = CaptionLabel(_tr("Matched lines are covered in full. Uncheck to keep; drag on the image to cover more."), self)
        self.copy_button = PrimaryPushButton(_tr("Copy redacted image"), self)
        self.save_button = PushButton(_tr("Save…"), self)
        self.copy_button.clicked.connect(self._copy)
        self.save_button.clicked.connect(self._save)
        for control in (title, self.status, self.hint, self.copy_button, self.save_button, self.keywords, self.phones, self.emails):
            configure_dialog_control(control)
        self.copy_button.setEnabled(False)
        self.save_button.setEnabled(False)
        footer = QHBoxLayout()
        footer.addWidget(self.status, 1)
        footer.addWidget(self.save_button)
        footer.addWidget(self.copy_button)
        root = QVBoxLayout(self)
        root.setContentsMargins(dialog_scaled(12), title.height() + dialog_scaled(8), dialog_scaled(12), dialog_scaled(12))
        root.addLayout(options)
        root.addWidget(self.hint)
        root.addWidget(split, 1)
        root.addLayout(footer)
        self.resize(dialog_scaled(880), dialog_scaled(570))
        screen = self.screen().availableGeometry()
        self.resize(min(self.width(), screen.width()), min(self.height(), screen.height()))
        self.move(screen.center() - self.rect().center())
        self._apply_theme()
        get_ui_theme().theme_changed.connect(self._apply_theme)
        self._thread = recognize_async(self._image, on_details=self._recognized)
        self._thread.finished.connect(self._forget_thread)

    def _apply_theme(self, _tokens=None):
        t = ui_tokens(self)
        self.candidates.setStyleSheet(
            f"QListWidget {{background: {t.input_background}; color: {t.text}; border: 0; font-size: {dialog_scaled(13)}px;}}"
            "QListWidget::item {padding: 4px;}"
        )
        self.preview.setStyleSheet(f"QGraphicsView {{background: {t.input_background}; border: 0;}}")

    def _recognized(self, result, reason):
        if reason and reason != NO_TEXT:
            self.status.setText(_reason_text(reason))
            return
        self._result = result
        self._rebuild()

    def _rebuild(self, *_args):
        checks = {(self.candidates.item(i).text(), self.candidates.item(i).data(Qt.ItemDataRole.UserRole).getRect()):
                  self.candidates.item(i).checkState() for i in range(self.candidates.count())}
        entries = sensitive_lines(self._result, self._image.rect(), phones=self.phones.isChecked(),
                                  emails=self.emails.isChecked(), keywords=re.split(r"[,，\n]", self.keywords.text()))
        self.candidates.blockSignals(True)
        self.candidates.clear()
        for text, rect in entries + [(_tr("Manual area"), rect) for rect in self._manual]:
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, rect)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(checks.get((text, rect.getRect()), Qt.CheckState.Checked))
            self.candidates.addItem(item)
        self.candidates.blockSignals(False)
        self._update_preview()

    def _add_manual(self, rect):
        self._manual.append(rect)
        item = QListWidgetItem(_tr("Manual area"))
        item.setData(Qt.ItemDataRole.UserRole, rect)
        item.setCheckState(Qt.CheckState.Checked)
        self.candidates.addItem(item)
        self._update_preview()

    def selected_rectangles(self):
        return [self.candidates.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.candidates.count())
                if self.candidates.item(i).checkState() == Qt.CheckState.Checked]

    def _update_preview(self, *_args):
        for overlay in self._overlays:
            self.preview.scene().removeItem(overlay)
        rects = self.selected_rectangles()
        self._overlays = [self.preview.scene().addRect(QRectF(rect), QPen(Qt.PenStyle.NoPen), QColor("black"))
                          for rect in rects]
        self.status.setText(_tr("%1 areas covered").replace("%1", str(len(rects))))
        self.copy_button.setEnabled(bool(rects))
        self.save_button.setEnabled(bool(rects))

    def _copy(self):
        from core.clipboard_utils import copy_image_to_clipboard
        copy_image_to_clipboard(redact_image(self._image, self.selected_rectangles()))
        self.status.setText(_tr("Copied"))

    def _save(self):
        from core.save import SaveService
        path, _ = QFileDialog.getSaveFileName(self, _tr("Save…"), "redacted.png", "PNG (*.png);;JPEG (*.jpg);;PDF (*.pdf)")
        if path:
            ok = SaveService().save_qimage_to_path(redact_image(self._image, self.selected_rectangles()), path)
            self.status.setText(_tr("Saved") if ok else _tr("Save failed"))

    def _forget_thread(self):
        self._thread = None

    def closeEvent(self, event):
        if self._thread is not None:
            self._thread.cancel()
            self._thread = None
        super().closeEvent(event)


def show_redaction(image):
    window = RedactionWindow(image)
    track_modeless_dialog(window)
    window.show()
    window.raise_()
    window.activateWindow()
    return window
