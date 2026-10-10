"""A local image collection with reorderable layouts and one-image-per-page PDF export."""
from dataclasses import replace
from pathlib import Path
import threading
import uuid

from PySide6.QtCore import QSize, QThread, QTimer, Qt, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QDialog, QFileDialog, QFormLayout,
                               QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QProgressBar,
                               QSplitter, QVBoxLayout, QWidget)

from core.image_layout import (ExportCancelled, ImageLayoutError, LayoutOptions, PageOptions,
                               MAX_IMAGES, MAX_SOURCE_PIXELS, MAX_ENCODED_BYTES,
                               check_size, compose_images, decode_image, render_pdf_preview)
from core.save import SaveService
from core.ui_scale import configure_dialog_control, dialog_scaled, scale_dialog_font
from core.ui_theme import get_ui_theme
from ui.fluent_lite import BodyLabel, CaptionLabel, CheckBox, ComboBox, LineEdit, PrimaryPushButton, PushButton, SpinBox


class ImageSourcePicker(QDialog):
    """Metadata-only selection; original image decoding happens after explicit selection."""
    def __init__(self, manager=None, pins=None, parent=None):
        super().__init__(parent)
        scale_dialog_font(self)
        self.setWindowTitle(self.tr("Choose Images"))
        self.manager, self.pins = manager, pins
        self.offset = 0
        self.seen = set()
        self.list = QListWidget(self)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.search = LineEdit(self)
        self.search.setPlaceholderText(self.tr("Search image history"))
        search_button = PushButton(self.tr("Search"), self)
        search_button.clicked.connect(self.search_history)
        self.search.returnPressed.connect(self.search_history)
        self.more = PushButton(self.tr("Load more"), self)
        self.more.clicked.connect(self.load_more)
        choose = PrimaryPushButton(self.tr("Add selected"), self)
        choose.clicked.connect(self.accept)
        cancel = PushButton(self.tr("Cancel"), self)
        cancel.clicked.connect(self.reject)
        self.hint = CaptionLabel(self.tr("Ctrl / Shift selects multiple images. Nothing is copied or deleted."), self)
        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        row.addWidget(self.search, 1)
        row.addWidget(search_button)
        layout.addLayout(row)
        layout.addWidget(self.hint)
        layout.addWidget(self.list, 1)
        bottom = QHBoxLayout()
        bottom.addWidget(self.more)
        bottom.addStretch()
        bottom.addWidget(cancel)
        bottom.addWidget(choose)
        layout.addLayout(bottom)
        for widget in (self.search, search_button, self.more, choose, cancel, self.hint, self.list):
            configure_dialog_control(widget)
        if pins is not None:
            self.search.hide()
            search_button.hide()
            self.more.hide()
            for index, pin in enumerate(pins):
                self._row(self.tr("Pinned image %1").replace("%1", str(index + 1)), index)
        else:
            self.load_more()
        self.resize(dialog_scaled(560), dialog_scaled(460))
        self.setStyleSheet(f"QDialog {{ background: {get_ui_theme().tokens.window}; }}")

    def _row(self, title, identity):
        row = QListWidgetItem(str(title), self.list)
        row.setData(Qt.ItemDataRole.UserRole, identity)

    def search_history(self):
        self.offset = 0
        self.seen.clear()
        self.list.clear()
        self.load_more()

    def load_more(self):
        records = self.manager.get_history(offset=self.offset, limit=50, content_type="image", search=self.search.text().strip() or None)
        self.offset += len(records)
        for record in records:
            if record.id not in self.seen:
                self.seen.add(record.id)
                stamp = record.created_at.strftime("%Y-%m-%d %H:%M:%S") if record.created_at else str(record.id)
                self._row((record.title or self.tr("Image")) + " · " + stamp, record.id)
        self.more.setEnabled(len(records) == 50 and self.offset < 1000)
        if self.offset >= 1000:
            self.hint.setText(self.tr("Showing up to 1000 records. Search to narrow the list."))

    def selected(self):
        return [item.data(Qt.ItemDataRole.UserRole) for item in self.list.selectedItems()]


class _LayoutExport(QThread):
    progress = Signal(int, int)

    def __init__(self, images, destination, layout, pages, mode, service, output_options, parent, *, searchable=False):
        super().__init__(parent)
        self.images, self.destination = images, destination
        self.layout, self.pages, self.mode = layout, pages, mode
        self.service, self.output_options = service, output_options
        self.cancel_event = threading.Event()
        self.ok = False
        self.error = ""
        self.searchable = searchable
        from core.searchable_pdf import PdfTextReport
        self.text_report = PdfTextReport()

    def run(self):
        try:
            if self.mode == "pdf":
                self.ok = self.service.save_image_pages(self.images, self.destination, self.pages,
                                                        cancelled=self.cancel_event.is_set, progress=self.progress.emit,
                                                        **({"searchable": True, "text_report": self.text_report} if self.searchable else {}))
            else:
                result = compose_images(self.images, self.layout, cancelled=self.cancel_event.is_set, progress=self.progress.emit)
                self.ok = self.service.save_qimage_to_path(result, self.destination, output_options=self.output_options,
                                                          cancelled=self.cancel_event.is_set)
        except ExportCancelled:
            pass
        except Exception as exc:
            self.error = str(exc)


class ImageLayoutDialog(QDialog):
    def __init__(self, config=None):
        super().__init__()
        scale_dialog_font(self)
        self.setWindowTitle(self.tr("Image Layout and PDF"))
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.entries = {}
        self._worker = None
        self._close_pending = False
        self._preview = None
        self._hidden_for_capture = False
        self.save_service = SaveService(config)
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(60)
        self._preview_timer.timeout.connect(self.update_preview)
        root = QVBoxLayout(self)
        root.setContentsMargins(*[dialog_scaled(18)] * 4)
        root.setSpacing(dialog_scaled(10))
        self.controls = QWidget(self)
        top = QVBoxLayout(self.controls)
        top.setContentsMargins(0, 0, 0, 0)
        buttons = QHBoxLayout()
        for label, callback in (("Add history images", self.add_history), ("Add pinned images", self.add_pins), ("Add image files", self.add_files)):
            button = PushButton(self.tr(label), self)
            configure_dialog_control(button)
            button.clicked.connect(callback)
            buttons.addWidget(button)
        top.addLayout(buttons)
        self.mode = ComboBox(self)
        self.mode.addItem(self.tr("Combined image"), "image")
        self.mode.addItem(self.tr("One image per PDF page"), "pdf")
        self.direction = ComboBox(self)
        self.direction.addItem(self.tr("Vertical"), "vertical")
        self.direction.addItem(self.tr("Horizontal"), "horizontal")
        self.width_spin = SpinBox(self)
        self.width_spin.setRange(0, 16384)
        self.width_spin.setSpecialValueText(self.tr("Original widths"))
        self.gap = SpinBox(self)
        self.gap.setRange(0, 512)
        self.gap.setValue(12)
        self.padding = SpinBox(self)
        self.padding.setRange(0, 512)
        self.padding.setValue(16)
        self.background = ComboBox(self)
        for name, color in (("White", "#ffffff"), ("Transparent", "#00000000"), ("Dark", "#171717")):
            self.background.addItem(self.tr(name), color)
        self.paper = ComboBox(self)
        for name, value in (("Original size (96 pixels/inch)", "original"), ("A4", "a4"), ("Letter", "letter")):
            self.paper.addItem(self.tr(name), value)
        self.orientation = ComboBox(self)
        self.orientation.addItem(self.tr("Portrait"), False)
        self.orientation.addItem(self.tr("Landscape"), True)
        self.pdf_rotation = ComboBox(self)
        for degrees in (0,90,180,270):
            self.pdf_rotation.addItem(self.tr("%1° clockwise").replace("%1",str(degrees)), degrees)
        self.searchable = CheckBox(self.tr("Searchable PDF (fresh local OCR)"), self)
        self.searchable.setChecked(False)
        self.searchable.toggled.connect(self.update_preview)
        self._last_text_report = None
        self.margin = SpinBox(self)
        self.margin.setRange(0, 40)
        self.margin.setValue(10)
        self.margin.setSuffix(" mm")
        form_row = QHBoxLayout()
        form_a, form_b = QFormLayout(), QFormLayout()
        for form, rows in ((form_a, (("Output", self.mode), ("Direction", self.direction), ("Common width (px)", self.width_spin),
                                    ("Gap (px)", self.gap), ("Padding (px)", self.padding))),
                           (form_b, (("Background", self.background), ("PDF paper", self.paper), ("Orientation", self.orientation),
                                     ("Page margins", self.margin), ("Rotate PDF images", self.pdf_rotation)))):
            for name, control in rows:
                label = BodyLabel(self.tr(name), self)
                configure_dialog_control(label)
                configure_dialog_control(control)
                control.setAccessibleName(self.tr(name))
                form.addRow(label, control)
                if isinstance(control, SpinBox):
                    control.valueChanged.connect(self.schedule_preview)
                else:
                    control.currentIndexChanged.connect(self.schedule_preview)
            form_row.addLayout(form, 1)
        top.addLayout(form_row)
        configure_dialog_control(self.searchable)
        top.addWidget(self.searchable)
        root.addWidget(self.controls)
        self.hint = CaptionLabel(self.tr("Drag images to reorder. Layout size is used exactly; file quality follows settings. PDF pages have a white background and no OCR text layer."), self)
        configure_dialog_control(self.hint)
        self.hint.setWordWrap(True)
        root.addWidget(self.hint)
        splitter = QSplitter(self)
        self.list = QListWidget(splitter)
        self.list.setIconSize(QSize(dialog_scaled(64), dialog_scaled(48)))
        self.list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list.setAccessibleName(self.tr("Image order"))
        self.list.model().rowsMoved.connect(self.schedule_preview)
        self.list.currentRowChanged.connect(self.schedule_preview)
        self.preview = QLabel(self)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(dialog_scaled(220), dialog_scaled(200))
        splitter.addWidget(self.list)
        splitter.addWidget(self.preview)
        splitter.setSizes([dialog_scaled(260), dialog_scaled(520)])
        root.addWidget(splitter, 1)
        self.edit_controls = QWidget(self)
        edits = QHBoxLayout(self.edit_controls)
        edits.setContentsMargins(0, 0, 0, 0)
        for label, callback in (("Move up", lambda: self.move_current(-1)), ("Move down", lambda: self.move_current(1)),
                                ("Remove image", self.remove_current), ("Clear collection", self.clear_collection)):
            button = PushButton(self.tr(label), self)
            configure_dialog_control(button)
            button.clicked.connect(callback)
            edits.addWidget(button)
        root.addWidget(self.edit_controls)
        self.status = CaptionLabel(self.tr("Add images to begin. Up to 50 images and 64 megapixels in total."), self)
        configure_dialog_control(self.status)
        root.addWidget(self.status)
        self.progress = QProgressBar(self)
        self.progress.hide()
        root.addWidget(self.progress)
        bottom = QHBoxLayout()
        self.pdf_report_button = PushButton(self.tr("PDF text report"), self)
        self.pdf_report_button.setVisible(False)
        self.pdf_report_button.clicked.connect(self.show_pdf_report)
        bottom.addWidget(self.pdf_report_button)
        bottom.addStretch()
        self.markdown_button = PushButton(self.tr("Markdown report…"), self)
        self.markdown_button.setEnabled(False)
        self.markdown_button.clicked.connect(self.open_markdown_report)
        configure_dialog_control(self.markdown_button)
        bottom.addWidget(self.markdown_button)
        self.cancel_export = PushButton(self.tr("Cancel export"), self)
        self.cancel_export.hide()
        self.cancel_export.clicked.connect(self.cancel_job)
        self.export_button = PrimaryPushButton(self.tr("Export…"), self)
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self.choose_export)
        for button in (self.cancel_export, self.export_button):
            configure_dialog_control(button)
            bottom.addWidget(button)
        root.addLayout(bottom)
        self.resize(dialog_scaled(900), dialog_scaled(820))
        screen = QApplication.primaryScreen().availableGeometry()
        self.resize(min(self.width(), screen.width() - 40), min(self.height(), screen.height() - 40))
        get_ui_theme().theme_changed.connect(self._theme)
        QApplication.instance().aboutToQuit.connect(self.shutdown)
        self._theme()
        self.schedule_preview()

    def showEvent(self, event):
        super().showEvent(event)
        if QApplication.platformName() == "windows":
            from core.platform_utils import set_window_exclude_from_capture
            set_window_exclude_from_capture(int(self.winId()), True)

    def _theme(self, *_):
        t = get_ui_theme().tokens
        self.setStyleSheet(f"QDialog {{ background: {t.window}; }} QListWidget {{ background: {t.surface}; color: {t.text}; border: 1px solid {t.border}; }}"
                           f" QListWidget::item:selected {{ background: {t.accent_soft}; color: {t.text}; }}")
        self.preview.setStyleSheet(f"background: {t.surface_subtle}; border: 1px solid {t.border};")

    def ordered_entries(self):
        return [self.entries[self.list.item(i).data(Qt.ItemDataRole.UserRole)] for i in range(self.list.count())]

    def images(self):
        return [entry[1] for entry in self.ordered_entries()]

    def remaining_pixels(self):
        return MAX_SOURCE_PIXELS - sum(image.width() * image.height() for _, image, _ in self.entries.values())

    def add_image(self, title, image, identity=None):
        if self._worker is not None:
            raise ImageLayoutError("Wait for the export to finish")
        if identity and any(entry[2] == identity for entry in self.entries.values()):
            return False
        if len(self.entries) >= MAX_IMAGES:
            raise ImageLayoutError("At most 50 images can be collected")
        check_size(image.width(), image.height(), self.remaining_pixels())
        key = uuid.uuid4().hex
        # QImage is implicitly shared; no unnecessary full-size deep copy. Pixel edits detach safely.
        image = image.copy() if image.devicePixelRatio() != 1 else type(image)(image)
        image.setDevicePixelRatio(1)
        self.entries[key] = (str(title), image, identity)
        item = QListWidgetItem(str(title))
        item.setData(Qt.ItemDataRole.UserRole, key)
        thumbnail = image.scaled(96, 72, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        item.setIcon(QIcon(QPixmap.fromImage(thumbnail)))
        self.list.addItem(item)
        self.list.setCurrentItem(item)
        self.schedule_preview()
        return True

    def add_images_atomic(self, images):
        images = list(images)
        if self._worker is not None or len(self.entries) + len(images) > MAX_IMAGES:
            raise ImageLayoutError("Collection is full or exporting")
        remaining = self.remaining_pixels()
        for _title, image in images:
            check_size(image.width(), image.height(), remaining)
            remaining -= image.width() * image.height()
        previous = set(self.entries)
        try:
            for title, image in images:
                self.add_image(title, image)
        except Exception:
            for index in range(self.list.count()-1, -1, -1):
                key = self.list.item(index).data(Qt.ItemDataRole.UserRole)
                if key not in previous:
                    self.list.takeItem(index)
                    self.entries.pop(key, None)
            self.schedule_preview()
            raise

    def add_history_ids(self, manager, identifiers):
        failed = 0
        for identifier in identifiers:
            try:
                item = manager.get_item(identifier)
                if item is None or item.content_type != "image" or not item.image_id:
                    raise ImageLayoutError("History image is no longer available")
                identity = ("history", id(manager), item.id, item.image_id)
                if any(entry[2] == identity for entry in self.entries.values()):
                    continue
                data = manager.get_image_data(item.image_id)
                image = decode_image(data, self.remaining_pixels())
                self.add_image(item.title or self.tr("Image %1").replace("%1", str(item.id)), image, identity)
            except Exception:
                failed += 1
        self.update_preview()
        if failed:
            self.status.setText(self.tr("%1 image(s) could not be added: missing, invalid, or over the collection limit.").replace("%1", str(failed)))
        return failed

    def add_history(self):
        from clipboard.core import ClipboardManager
        manager = ClipboardManager()
        picker = ImageSourcePicker(manager=manager, parent=self)
        if picker.exec() == QDialog.DialogCode.Accepted:
            self.add_history_ids(manager, picker.selected())
        picker.deleteLater()

    def add_pins(self):
        from pin.pin_manager import PinManager
        pins = list(PinManager.instance().get_all_pins())
        picker = ImageSourcePicker(pins=pins, parent=self)
        if picker.exec() == QDialog.DialogCode.Accepted:
            self.add_pin_images([pins[index] for index in picker.selected()])
        picker.deleteLater()

    def add_pin_images(self, pins):
        failed = 0
        for pin in pins:
            try:
                if getattr(pin, "_is_closed", False):
                    raise ImageLayoutError("Pinned window closed")
                if any(entry[2] == ("pin", id(pin)) for entry in self.entries.values()):
                    continue
                size = pin.canvas.base_size if pin.canvas is not None else pin.size()
                check_size(round(size.width() * pin.devicePixelRatioF()), round(size.height() * pin.devicePixelRatioF()), self.remaining_pixels())
                def snapshot(window=pin):
                    image = window.get_current_image()
                    self.add_image(self.tr("Pinned image"), image, ("pin", id(window)))
                pin._with_edit_paused(snapshot)
            except Exception:
                failed += 1
        self.update_preview()
        if failed:
            self.status.setText(self.tr("%1 image(s) could not be added: missing, invalid, or over the collection limit.").replace("%1", str(failed)))
        return failed

    def add_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, self.tr("Choose Images"), "", "Images (*.png *.jpg *.jpeg *.bmp *.webp)")
        failed = 0
        for filename in paths:
            try:
                if Path(filename).stat().st_size > MAX_ENCODED_BYTES:
                    raise ImageLayoutError("File too large")
                with open(filename, "rb") as file:
                    data = file.read(MAX_ENCODED_BYTES + 1)
                self.add_image(Path(filename).name, decode_image(data, self.remaining_pixels()), ("file", str(Path(filename).resolve())))
            except Exception:
                failed += 1
        self.update_preview()
        if failed:
            self.status.setText(self.tr("%1 image(s) could not be added: missing, invalid, or over the collection limit.").replace("%1", str(failed)))

    def move_current(self, delta):
        if self._worker is not None:
            return
        row = self.list.currentRow()
        if row < 0 or not 0 <= row + delta < self.list.count():
            return
        item = self.list.takeItem(row)
        self.list.insertItem(row + delta, item)
        self.list.setCurrentItem(item)
        self.schedule_preview()

    def remove_current(self):
        if self._worker is not None:
            return
        row = self.list.currentRow()
        if row >= 0:
            item = self.list.takeItem(row)
            self.entries.pop(item.data(Qt.ItemDataRole.UserRole), None)
            self.schedule_preview()

    def clear_collection(self):
        if self._worker is not None:
            return
        self.list.clear()
        self.entries.clear()
        self.schedule_preview()

    def layout_options(self):
        return LayoutOptions(self.direction.currentData(), self.width_spin.value(), self.gap.value(), self.padding.value(), self.background.currentData())

    def page_options(self):
        return PageOptions(self.paper.currentData(), self.orientation.currentData(), self.margin.value(), self.pdf_rotation.currentData())

    def schedule_preview(self, *_):
        if hasattr(self, "markdown_button"):
            self.markdown_button.setEnabled(bool(self.entries) and self._worker is None)
        if self._worker is None:
            self._preview_timer.start()

    def update_preview(self):
        self._preview_timer.stop()
        if self._worker is not None:
            return
        images = self.images()
        pdf = self.mode.currentData() == "pdf"
        for control in (self.direction, self.width_spin, self.gap, self.padding, self.background):
            control.setEnabled(not pdf)
        self.searchable.setEnabled(pdf)
        self.pdf_rotation.setEnabled(pdf)
        self.hint.setText(self.tr("Searchable PDF re-runs OCR on the exact rotated output pixels. Never reuses cached text. Blank/failed pages or missing glyphs fall back to image-only and are reported. OCR can be wrong; review the result. Redacted exports never reuse pre-redaction text.") if pdf and self.searchable.isChecked() else
            self.tr("Drag images to reorder. Layout size is used exactly; file quality follows settings. PDF pages have a white background and no OCR text layer."))
        for control in (self.paper, self.margin):
            control.setEnabled(pdf)
        self.orientation.setEnabled(pdf and self.paper.currentData() != "original")
        self.export_button.setEnabled(False)
        self._preview = None
        self.preview.clear()
        if not images:
            self.status.setText(self.tr("Add images to begin. Up to 50 images and 64 megapixels in total."))
            return
        try:
            if pdf:
                options = self.page_options()
                for image in images:
                    options.geometry(image)
                index = max(0, self.list.currentRow())
                self._preview = render_pdf_preview(images[index], options)
                self.status.setText(self.tr("%1 pages · Previewing page %2").replace("%1", str(len(images))).replace("%2", str(index + 1)))
            else:
                options = self.layout_options()
                size, _ = options.geometry(images)
                self._preview = compose_images(images, options, preview_edge=1000)
                self.status.setText(self.tr("%1 images · %2 × %3 px").replace("%1", str(len(images))).replace("%2", str(size.width())).replace("%3", str(size.height())))
            self._show_preview()
            self.export_button.setEnabled(self._worker is None)
        except (ImageLayoutError, ValueError):
            self.status.setText(self.tr("This layout exceeds the image or page size limit. Reduce the width or choose A4 / Letter."))

    def _show_preview(self):
        if self._preview is not None:
            pixmap = QPixmap.fromImage(self._preview).scaled(self.preview.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            self.preview.setPixmap(pixmap)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "preview"):
            self._show_preview()

    def choose_export(self):
        pdf = self.mode.currentData() == "pdf"
        formats = "PDF (*.pdf)" if pdf else "PNG (*.png);;JPEG (*.jpg);;WebP (*.webp);;BMP (*.bmp)"
        destination, selected = QFileDialog.getSaveFileName(self, self.tr("Export collection"), "images.pdf" if pdf else "layout.png", formats)
        if not destination:
            return
        if not Path(destination).suffix:
            destination += "." + selected.split("*.")[1].split(")")[0]
        self.start_export(destination)

    def start_export(self, destination):
        if self._worker is not None:
            return False
        self.update_preview()
        if not self.export_button.isEnabled():
            return False
        mode = self.mode.currentData()
        extension = Path(destination).suffix.lower()
        if (mode == "pdf" and extension != ".pdf") or (mode == "image" and extension not in (".png", ".jpg", ".jpeg", ".webp", ".bmp")):
            self.status.setText(self.tr("Choose a file extension matching the selected output."))
            return False
        options = replace(self.save_service.output_options(), size_mode="original")
        self._worker = _LayoutExport(self.images(), destination, self.layout_options(), self.page_options(), mode, self.save_service, options, self,
                                     searchable=mode == "pdf" and self.searchable.isChecked())
        self._last_text_report = None
        self.pdf_report_button.setVisible(False)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._export_finished)
        self._set_busy(True)
        self.status.setText(self.tr("Recognizing PDF pages and exporting… Cancellation waits for the current local OCR call.") if self._worker.searchable else self.tr("Exporting…"))
        self._worker.start()
        return True

    def _set_busy(self, busy):
        self._preview_timer.stop()
        self.controls.setEnabled(not busy)
        self.edit_controls.setEnabled(not busy)
        self.list.setEnabled(not busy)
        self.export_button.setEnabled(not busy and bool(self.entries))
        if hasattr(self, "markdown_button"):
            self.markdown_button.setEnabled(not busy and bool(self.entries))
        self.cancel_export.setVisible(busy)
        self.progress.setVisible(busy)
        self.progress.setRange(0, max(1, len(self.entries)))
        self.progress.setValue(0)

    def _on_progress(self, count, total):
        self.progress.setRange(0, total)
        self.progress.setValue(count)

    def cancel_job(self):
        if self._worker is not None:
            self._worker.cancel_event.set()
            self.status.setText(self.tr("Cancelling…"))

    def _export_finished(self):
        worker = self._worker
        if worker is None:
            return
        worker.images = []
        self._worker = None
        self._set_busy(False)
        self.status.setText(self.tr("Export saved.") if worker.ok else
                            self.tr("Export cancelled.") if worker.cancel_event.is_set() else
                            self.tr("Export failed. Check image limits, folder permissions and free space."))
        if worker.ok and worker.searchable:
            self._last_text_report = worker.text_report
            self.pdf_report_button.setVisible(True)
            count = sum(not page["image_only"] for page in worker.text_report.pages)
            self.status.setText(self.tr("PDF saved: %1 of %2 pages have searchable text. Review the PDF text report.").replace("%1",str(count)).replace("%2",str(len(worker.text_report.pages))))
        worker.deleteLater()
        if self._close_pending:
            self.close()

    def open_markdown_report(self):
        """把当前集合的顺序与最终成图导出成本地 Markdown 问题报告。"""
        if not self.entries:
            return
        from ui.markdown_report_dialog import MarkdownReportDialog

        dialog = MarkdownReportDialog(self.ordered_entries(), self)
        dialog.exec()

    def show_pdf_report(self):
        if self._last_text_report is None:return
        from ui.dialogs import show_text_dialog
        reasons={"no_text":self.tr("No text recognized"),"ocr_failed":self.tr("OCR failed or unavailable"),"invalid_result":self.tr("Invalid OCR result"),
                 "text_limit":self.tr("Text limit exceeded"),"invalid_box":self.tr("Unsupported or invalid text box"),
                 "low_confidence":self.tr("Low confidence text"),"missing_glyphs":self.tr("Missing font glyphs")}
        rows=[]
        for page in self._last_text_report.pages:
            row=self.tr("Page %1: %2 text lines").replace("%1",str(page["page"])).replace("%2",str(page["embedded_lines"]))
            if page["image_only"]:row += " · " + self.tr("Image-only page")
            row += "\n" + ", ".join(reasons.get(k,k)+": "+str(v) for k,v in page["warnings"].items())
            rows.append(row)
        show_text_dialog(self,self.tr("PDF text report"),"\n\n".join(rows))

    def shutdown(self):
        self._preview_timer.stop()
        if self._worker is not None:
            self._worker.cancel_event.set()
            self._worker.wait()
            self._worker.images = []
        self.entries.clear()
        self._preview = None

    def reject(self):
        if self._worker is not None:
            self._close_pending = True
            self.cancel_job()
            return
        self.shutdown()
        self.list.clear()
        self.preview.clear()
        super().reject()

    def closeEvent(self, event):
        if self._worker is not None:
            self._close_pending = True
            self.cancel_job()
            event.ignore()
            return
        self.shutdown()
        self.list.clear()
        self.preview.clear()
        super().closeEvent(event)


def get_image_layout_window():
    app = QApplication.instance()
    window = getattr(app, "_image_layout_window", None)
    if window is None:
        window = ImageLayoutDialog()
        app._image_layout_window = window
        window.destroyed.connect(lambda: setattr(app, "_image_layout_window", None))
    return window


def show_image_layout():
    window = get_image_layout_window()
    window.show()
    window.raise_()
    window.activateWindow()
    return window
