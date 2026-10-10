"""Review local OCR candidates, add missing areas, and copy/save a flattened image."""

import re

from PySide6.QtCore import Qt, QRectF, Signal
from PySide6.QtGui import QColor, QPen, QPixmap
from PySide6.QtWidgets import (
    QDialog, QFileDialog, QGraphicsScene, QGraphicsView, QGridLayout, QHBoxLayout,
    QListWidget, QListWidgetItem, QSplitter, QVBoxLayout,
)

from core.i18n import make_tr
from core.ui_scale import configure_dialog_control, dialog_scaled, scale_dialog_font
from core.ui_theme import get_ui_theme
from ui.dialogs import track_modeless_dialog, show_confirm_dialog
from ui.fluent_lite import (
    CaptionLabel, CheckBox, ComboBox, FluentTitleBar, FrostedFramelessDialog, LineEdit,
    PrimaryPushButton, PushButton, ui_tokens,
)
from .recognizer import NO_TEXT, recognize_async
from .redaction import RedactionRules, RedactionPresetStore, redact_image, sensitive_lines, save_redacted_image
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
    def __init__(self, image, parent=None, *, sensitive=False):
        super().__init__(parent)
        scale_dialog_font(self)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.sensitive_capture = sensitive is True
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
        self._closed = False
        from settings import get_tool_settings_manager
        self.config = get_tool_settings_manager()
        self.preset_store = RedactionPresetStore(self.config)

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
        self.china_ids = CheckBox(_tr("Chinese IDs (date + checksum)"), self)
        self.bank_cards = CheckBox(_tr("Bank cards (Luhn checksum)"), self)
        self.ocr_lookalikes = CheckBox(_tr("Try OCR O/I/l substitutions"), self)
        self.phones.setChecked(True)
        self.emails.setChecked(True)
        self.rule_checks = {name: getattr(self, name) for name in RedactionRules.__dataclass_fields__}
        options = QGridLayout()
        for index, check in enumerate(self.rule_checks.values()):
            check.toggled.connect(self._rules_changed)
            options.addWidget(check, index // 3, index % 3)
        self.keywords = LineEdit(self)
        self.keywords.setPlaceholderText(_tr("Keywords, separated by commas"))
        self.keywords.setMaxLength(2000)
        self.keywords.textChanged.connect(self._rebuild)
        options.addWidget(self.keywords, 2, 0, 1, 3)
        self.presets = ComboBox(self)
        self.presets.setAccessibleName(_tr("Rule presets"))
        self.save_preset_button = PushButton(_tr("Save rules…"), self)
        self.delete_preset_button = PushButton(_tr("Delete preset"), self)
        preset_row = QHBoxLayout()
        preset_row.addWidget(self.presets, 1)
        preset_row.addWidget(self.save_preset_button)
        preset_row.addWidget(self.delete_preset_button)
        self.preset_status = CaptionLabel(_tr("Presets save rule switches only, never keywords, OCR text or images."), self)
        self.preset_status.setWordWrap(True)
        self.presets.currentIndexChanged.connect(self._apply_preset)
        self.save_preset_button.clicked.connect(self._save_preset)
        self.delete_preset_button.clicked.connect(self._delete_preset)
        self._load_presets()

        self.status = CaptionLabel(_tr("Recognizing..."), self)
        self.hint = CaptionLabel(_tr("Candidates are not proof of identity or complete privacy detection. OCR errors, split lines and unchecked rules can miss data. Review every line; uncheck false positives and drag to cover missed areas. Exports flatten black covers into new files at this resolution."), self)
        self.hint.setWordWrap(True)
        self.copy_button = PrimaryPushButton(_tr("Copy redacted image"), self)
        self.save_button = PushButton(_tr("Save…"), self)
        self.copy_button.clicked.connect(self._copy)
        self.save_button.clicked.connect(self._save)
        for control in (title, self.status, self.hint, self.copy_button, self.save_button, self.keywords,
                        *self.rule_checks.values(), self.presets, self.save_preset_button, self.delete_preset_button, self.preset_status):
            configure_dialog_control(control)
        self.copy_button.setEnabled(False)
        self.save_button.setEnabled(False)
        footer = QHBoxLayout()
        footer.addWidget(self.status, 1)
        footer.addWidget(self.save_button)
        footer.addWidget(self.copy_button)
        root = QVBoxLayout(self)
        root.setContentsMargins(dialog_scaled(12), title.height() + dialog_scaled(8), dialog_scaled(12), dialog_scaled(12))
        root.addLayout(preset_row)
        root.addWidget(self.preset_status)
        root.addLayout(options)
        root.addWidget(self.hint)
        root.addWidget(split, 1)
        root.addLayout(footer)
        self.resize(dialog_scaled(1000), dialog_scaled(710))
        screen = self.screen().availableGeometry()
        self.resize(min(self.width(), screen.width()), min(self.height(), screen.height()))
        self.move(screen.center() - self.rect().center())
        self._apply_theme()
        get_ui_theme().theme_changed.connect(self._apply_theme)
        if self.sensitive_capture:
            from core.capture_privacy import notice, install_text_guard
            install_text_guard(self)
            self.hint.setText(notice())
            self.save_button.setEnabled(False)
            self.save_preset_button.setEnabled(False)
            self.delete_preset_button.setEnabled(False)
        self._thread = recognize_async(self._image, on_details=self._recognized,
                                       **({"sensitive": True} if self.sensitive_capture else {}))
        self._thread.finished.connect(self._forget_thread)

    def current_rules(self):
        return RedactionRules(**{name: check.isChecked() for name, check in self.rule_checks.items()})

    def _load_presets(self, selected=None):
        self.presets.blockSignals(True)
        self.presets.clear()
        self.presets.addItem(_tr("Current rules"), None)
        self.presets.addItem(_tr("Contact details"), RedactionRules())
        self.presets.addItem(_tr("Identity and bank cards"), RedactionRules(False, False, True, True))
        self.presets.addItem(_tr("All checks (strict)"), RedactionRules(True, True, True, True))
        try:
            for record in self.preset_store.load():
                self.presets.addItem(record["name"], record)
        except (ValueError, OSError, TypeError):
            self.preset_status.setText(_tr("Saved rule presets could not be read. Existing settings were not changed."))
        index = next((i for i in range(4, self.presets.count()) if self.presets.itemText(i) == selected), 0)
        self.presets.setCurrentIndex(index)
        self.presets.blockSignals(False)
        self.delete_preset_button.setEnabled(index >= 4 and not self.sensitive_capture)

    def _rules_changed(self, *_):
        self.presets.blockSignals(True)
        self.presets.setCurrentIndex(0)
        self.presets.blockSignals(False)
        self.delete_preset_button.setEnabled(False)
        self._rebuild()

    def _apply_preset(self, *_):
        value = self.presets.currentData()
        self.delete_preset_button.setEnabled(isinstance(value, dict) and not self.sensitive_capture)
        if value is None:
            return
        rules = RedactionRules.parse(value["rules"]) if isinstance(value, dict) else value
        for name, check in self.rule_checks.items():
            check.blockSignals(True)
            check.setChecked(getattr(rules, name))
            check.blockSignals(False)
        self._rebuild()

    def _save_preset(self):
        from core.capture_privacy import blocked
        if blocked(self):
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(_tr("Save rule preset"))
        scale_dialog_font(dialog)
        layout = QVBoxLayout(dialog)
        layout.addWidget(CaptionLabel(_tr("Preset name (rule switches only)"), dialog))
        name = LineEdit(dialog)
        name.setMaxLength(40)
        name.setAccessibleName(_tr("Preset name"))
        layout.addWidget(name)
        row = QHBoxLayout()
        cancel, save = PushButton(_tr("Cancel"), dialog), PrimaryPushButton(_tr("Save"), dialog)
        row.addWidget(cancel)
        row.addWidget(save)
        layout.addLayout(row)
        cancel.clicked.connect(dialog.reject)
        save.clicked.connect(dialog.accept)
        dialog.setMinimumWidth(dialog_scaled(380))
        dialog.setStyleSheet(f"QDialog {{ background: {get_ui_theme().tokens.window}; }}")
        try:
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            saved = self.preset_store.save(name.text(), self.current_rules())
            self._load_presets(saved)
            self.preset_status.setText(_tr("Rule switches saved. Keywords and image data were not saved."))
        except (ValueError, OSError, TypeError):
            self.preset_status.setText(_tr("Could not save preset. Use a unique name (1–40 characters), up to 20 presets, and writable settings."))
        finally:
            dialog.deleteLater()

    def _delete_preset(self):
        from core.capture_privacy import blocked
        if blocked(self):
            return
        value = self.presets.currentData()
        if not isinstance(value, dict):
            return
        if not show_confirm_dialog(self, _tr("Delete preset"), _tr("Delete only this saved rule combination? Images and history will not be changed."), plain_text=True):
            return
        try:
            self.preset_store.delete(value["name"])
            self._load_presets()
            self.preset_status.setText(_tr("Preset deleted. Current switches and images were kept."))
        except (ValueError, OSError, TypeError):
            self.preset_status.setText(_tr("Could not delete preset. Existing data was kept."))

    def _apply_theme(self, _tokens=None):
        t = ui_tokens(self)
        self.candidates.setStyleSheet(
            f"QListWidget {{background: {t.input_background}; color: {t.text}; border: 0; font-size: {dialog_scaled(13)}px;}}"
            "QListWidget::item {padding: 4px;}"
        )
        self.preview.setStyleSheet(f"QGraphicsView {{background: {t.input_background}; border: 0;}}")

    def _recognized(self, result, reason):
        if self._closed:
            return
        if reason and reason != NO_TEXT:
            self.status.setText(_reason_text(reason))
            return
        self._result = result
        self._rebuild()

    def _rebuild(self, *_args):
        if self._closed:
            return
        checks = {(self.candidates.item(i).text(), self.candidates.item(i).data(Qt.ItemDataRole.UserRole).getRect()):
                  self.candidates.item(i).checkState() for i in range(self.candidates.count())}
        entries = sensitive_lines(self._result, self._image.rect(),
            **{name: check.isChecked() for name, check in self.rule_checks.items()},
            keywords=re.split(r"[,，\n]", self.keywords.text()))
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
        self.save_button.setEnabled(bool(rects) and not self.sensitive_capture)

    def _copy(self):
        if self.sensitive_capture:
            from core.capture_privacy import copy_private
            if copy_private(redact_image(self._image, self.selected_rectangles()), self):
                self.status.setText(_tr("Copied"))
            return
        from core.clipboard_utils import copy_image_to_clipboard
        copy_image_to_clipboard(redact_image(self._image, self.selected_rectangles()))
        self.status.setText(_tr("Copied"))

    def _save(self):
        from core.capture_privacy import blocked
        if blocked(self):
            return
        path, _ = QFileDialog.getSaveFileName(self, _tr("Save…"), "redacted.png", "PNG (*.png);;JPEG (*.jpg);;PDF (*.pdf)")
        if not path:
            return
        try:
            ok = save_redacted_image(self._image, self.selected_rectangles(), path, self.config)
            self.status.setText(_tr("Saved") if ok else _tr("Save failed"))
        except FileExistsError:
            self.status.setText(_tr("Choose a new filename. Redaction never overwrites an existing file."))
        except (ValueError, OSError):
            self.status.setText(_tr("Save failed. Choose a new PNG, JPEG or PDF file."))

    def _forget_thread(self):
        self._thread = None

    def closeEvent(self, event):
        self._closed = True
        from core.capture_privacy import remove_text_guard
        remove_text_guard(self)
        if self._thread is not None:
            self._thread.cancel()
            self._thread = None
        super().closeEvent(event)


def show_redaction(image, *, sensitive=False):
    window = RedactionWindow(image, **({"sensitive": True} if sensitive else {}))
    track_modeless_dialog(window)
    window.show()
    window.raise_()
    window.activateWindow()
    return window
