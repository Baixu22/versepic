"""Reviewable latest-seam adjustment and screen-oriented matching exclusions."""
from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QDialog, QFormLayout, QHBoxLayout, QLabel, QVBoxLayout

from core.ui_scale import configure_dialog_control, dialog_scaled, scale_dialog_font
from core.ui_theme import get_ui_theme
from ui.fluent_lite import CaptionLabel, ComboBox, PrimaryPushButton, PushButton, SpinBox
from .session import join_images


def qimage(image):
    rgba = image.convert("RGBA")
    return QImage(rgba.tobytes(), rgba.width, rgba.height, rgba.width*4, QImage.Format.Format_RGBA8888).copy()


class IgnorePreview(QLabel):
    picked = Signal(int, int)

    def __init__(self, image, parent):
        super().__init__(parent)
        self.original_size = image.size
        preview = image.copy()
        preview.thumbnail((1000, 600))
        self.image = qimage(preview)
        self.top = self.right = 0
        self.setMinimumSize(dialog_scaled(280), dialog_scaled(180))

    def image_rect(self):
        scale = min(self.width()/self.image.width(), self.height()/self.image.height())
        w, h = self.image.width()*scale, self.image.height()*scale
        return QRectF((self.width()-w)/2, (self.height()-h)/2, w, h)

    def paintEvent(self, event):
        painter = QPainter(self)
        rect = self.image_rect()
        painter.drawImage(rect, self.image, QRectF(self.image.rect()))
        top = rect.height()*self.top/self.original_size[1]
        right = rect.width()*self.right/self.original_size[0]
        painter.fillRect(QRectF(rect.x(), rect.y(), rect.width(), top), QColor(230,70,30,140))
        painter.fillRect(QRectF(rect.right()-right, rect.y(), right, rect.height()), QColor(230,70,30,140))
        painter.setPen(QPen(QColor("#ef4444"), 2))
        painter.drawRect(rect)
        painter.end()

    def mousePressEvent(self, event):
        rect = self.image_rect()
        point = event.position()
        if event.button() == Qt.MouseButton.LeftButton and rect.contains(point):
            self.picked.emit(round((point.y()-rect.y())/rect.height()*self.original_size[1]),
                             round((rect.right()-point.x())/rect.width()*self.original_size[0]))


class StitchAdjustmentDialog(QDialog):
    def __init__(self, session, *, ignore=False, parent=None):
        super().__init__(parent)
        scale_dialog_font(self)
        self.session, self.ignore_mode = session, ignore
        self.setWindowTitle(self.tr("Matching exclusions") if ignore else self.tr("Adjust latest seam"))
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.WindowTitleHint | Qt.WindowType.WindowCloseButtonHint | Qt.WindowType.WindowStaysOnTopHint)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(*[dialog_scaled(16)]*4)
        layout.setSpacing(dialog_scaled(10))
        self.hint = CaptionLabel(self.tr("Highlighted pixels are excluded from matching only, not removed from the output. Coordinates follow the original screen, even for horizontal or reverse capture.") if ignore else
                                 self.tr("Review the two latest frames. Overlap counts pixels already present; adjust it to remove duplicate rows or restore missing content. Capturing is paused while this window is open."), self)
        configure_dialog_control(self.hint)
        layout.addWidget(self.hint)
        form = QFormLayout()
        if ignore:
            image = session.state.last_frame
            self.preview = IgnorePreview(image, self)
            self.top = SpinBox(self)
            self.top.setRange(0, image.height-8)
            self.top.setValue(session.ignore_top)
            self.right = SpinBox(self)
            self.right.setRange(0, image.width-8)
            self.right.setValue(session.ignore_right)
            self.pick_axis = ComboBox(self)
            self.pick_axis.addItem(self.tr("Click to set header height"), "top")
            self.pick_axis.addItem(self.tr("Click to set scrollbar width"), "right")
            form.addRow(self.tr("Top exclusion (px)"), self.top)
            form.addRow(self.tr("Right exclusion (px)"), self.right)
            form.addRow(self.tr("Preview action"), self.pick_axis)
            self.preview.picked.connect(self._pick)
            self.top.valueChanged.connect(self.update_preview)
            self.right.valueChanged.connect(self.update_preview)
            controls = (self.top, self.right, self.pick_axis)
        else:
            before, image, overlap, direction, _ = session.seam()
            self.before, self.frame = before, image
            self.preview = QLabel(self)
            self.preview.setMinimumSize(dialog_scaled(300), dialog_scaled(250))
            self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.overlap = SpinBox(self)
            length = image.height if session.axis == "vertical" else image.width
            self.overlap.setRange(0, length-1)
            self.overlap.setValue(overlap)
            self.direction = ComboBox(self)
            self.direction.addItem(self.tr("Append below / right"), "down")
            self.direction.addItem(self.tr("Prepend above / left"), "up")
            self.direction.setCurrentIndex(1 if direction == "up" else 0)
            self.direction.setEnabled(before.direction is None)
            form.addRow(self.tr("Overlap (px)"), self.overlap)
            form.addRow(self.tr("New frame direction"), self.direction)
            self.overlap.valueChanged.connect(self.update_preview)
            self.direction.currentIndexChanged.connect(self.update_preview)
            controls = (self.overlap, self.direction)
        for control in controls:
            configure_dialog_control(control)
        layout.addLayout(form)
        layout.addWidget(self.preview, 1)
        self.status = CaptionLabel(self)
        configure_dialog_control(self.status)
        layout.addWidget(self.status)
        bottom = QHBoxLayout()
        if ignore:
            reset = PushButton(self.tr("No exclusions"), self)
            configure_dialog_control(reset)
            reset.clicked.connect(self._reset)
            bottom.addWidget(reset)
        bottom.addStretch()
        cancel = PushButton(self.tr("Cancel"), self)
        self.apply = PrimaryPushButton(self.tr("Apply"), self)
        cancel.clicked.connect(self.reject)
        self.apply.clicked.connect(self.accept)
        for control in (cancel, self.apply):
            configure_dialog_control(control)
            bottom.addWidget(control)
        layout.addLayout(bottom)
        get_ui_theme().theme_changed.connect(self._theme)
        self._theme()
        self.resize(dialog_scaled(740), dialog_scaled(640))
        self.update_preview()

    def _theme(self, *_):
        self.setStyleSheet(f"QDialog {{ background: {get_ui_theme().tokens.window}; }}")

    def _pick(self, top, right):
        if self.pick_axis.currentData() == "top":
            self.top.setValue(top)
        else:
            self.right.setValue(right)

    def _reset(self):
        self.top.setValue(0)
        self.right.setValue(0)

    def update_preview(self, *_):
        if self.ignore_mode:
            self.preview.top, self.preview.right = self.top.value(), self.right.value()
            self.preview.update()
            self.status.setText(self.tr("These settings affect future matching; the existing stitched image stays unchanged."))
            return
        overlap = self.overlap.value()
        direction = self.direction.currentData()
        # Bounded two-frame preview, not a second copy of the complete long image.
        previous, incoming = self.before.last_frame, self.frame
        scale = min(1.0, 900/max(*previous.size, *incoming.size))
        if scale < 1:
            size = (max(1, round(previous.width*scale)), max(1, round(previous.height*scale)))
            previous, incoming = previous.resize(size), incoming.resize(size)
        limit = (incoming.height if self.session.axis == "vertical" else incoming.width)-1
        preview_overlap = min(limit, round(overlap*scale))
        result = join_images(previous, incoming, self.session.axis, direction, preview_overlap)
        image = qimage(result)
        painter = QPainter(image)
        painter.setPen(QPen(QColor("#ef4444"), 2))
        shift = (incoming.height if self.session.axis == "vertical" else incoming.width)-preview_overlap
        boundary = shift if direction == "up" else (previous.height if self.session.axis == "vertical" else previous.width)
        if self.session.axis == "vertical":
            painter.drawLine(0, boundary, image.width(), boundary)
        else:
            painter.drawLine(boundary, 0, boundary, image.height())
        painter.end()
        self.preview.setPixmap(QPixmap.fromImage(image).scaled(self.preview.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        length = self.frame.height if self.session.axis == "vertical" else self.frame.width
        self.status.setText(self.tr("New content: %1 px. Red line marks the join; only this preview includes it.").replace("%1", str(length-overlap)))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "status"):
            self.update_preview()
