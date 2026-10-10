"""Explicit GIF output controls; preferences live only for the current export."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QFormLayout, QHBoxLayout, QVBoxLayout

from core.ui_scale import configure_dialog_control, dialog_scaled, scale_dialog_font
from core.ui_theme import get_ui_theme
from ui.fluent_lite import BodyLabel, CaptionLabel, ComboBox, PrimaryPushButton, PushButton, SpinBox
from .composer import output_size, timeline_encoder_available


class GifExportDialog(QDialog):
    def __init__(self, store, frame_start, frame_end, speed, cursor, parent=None, *, output_format="gif"):
        super().__init__(parent)
        self.store = store
        self.output_format = output_format
        self.setWindowTitle(self.tr("Export silent MP4") if output_format == "mp4" else self.tr("Export GIF"))
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        scale_dialog_font(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(*[dialog_scaled(20)] * 4)
        layout.setSpacing(dialog_scaled(14))
        title = BodyLabel(self.tr("Silent MP4 output") if output_format == "mp4" else self.tr("GIF output"), self)
        layout.addWidget(title)
        summary = CaptionLabel(self.tr("Frames %1–%2 · speed %3× · cursor %4")
            .replace("%1", str(frame_start + 1)).replace("%2", str(frame_end + 1))
            .replace("%3", str(speed)).replace("%4", self.tr("on") if cursor else self.tr("off")), self)
        summary.setWordWrap(True)
        layout.addWidget(summary)
        form = QFormLayout()
        form.setSpacing(dialog_scaled(12))
        self.size_mode = ComboBox(self)
        self.size_mode.addItem(self.tr("Original size"), 0)
        self.size_mode.addItem(self.tr("Custom width"), 1)
        self.width = SpinBox(self)
        self.width.setRange(1, 65535)
        self.width.setValue(store.width)
        self.width.setSuffix(" px")
        self.fps = ComboBox(self)
        self.fps.addItem(self.tr("Keep timing (up to 50 fps)"), 0)
        if output_format == "mp4":
            self.fps.clear()
            self.fps.addItem(self.tr("Original timing (no audio)"), 0)
        for value in (() if output_format == "mp4" else (5, 10, 15, 20, 25, 30, 50)):
            self.fps.addItem(self.tr("Limit to %1 fps").replace("%1", str(value)), value)
        for label, widget in ((self.tr("Size"), self.size_mode), (self.tr("Width"), self.width), (self.tr("Frame rate"), self.fps)):
            configure_dialog_control(widget)
            widget.setAccessibleName(label)
            form.addRow(label, widget)
        layout.addLayout(form)
        self.output = BodyLabel("", self)
        self.output.setWordWrap(True)
        self.output.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.output)
        note = CaptionLabel(self.tr("Frame-rate limits drop frames, never add frames. GIF uses 10 ms timing steps and at least 20 ms per frame. Total time is rounded once; very short clips last at least 20 ms. File size is shown after export, not estimated."), self)
        if output_format == "mp4":
            note.setText(self.tr("Silent H.264 video, with no audio track. Trim and speed are retained. Odd dimensions add one black row or column on the bottom or right, without stretching. Timing uses 1 ms steps; equal timestamps are merged. File size is shown after export."))
        note.setWordWrap(True)
        layout.addWidget(note)
        row = QHBoxLayout()
        row.addStretch()
        self.cancel_button = PushButton(self.tr("Cancel"), self)
        self.export_button = PrimaryPushButton(self.tr("Export"), self)
        row.addWidget(self.cancel_button)
        row.addWidget(self.export_button)
        layout.addLayout(row)
        self.cancel_button.clicked.connect(self.reject)
        self.export_button.clicked.connect(self.accept)
        self.size_mode.currentIndexChanged.connect(self._update)
        self.width.valueChanged.connect(self._update)
        get_ui_theme().theme_changed.connect(self._theme)
        self._theme()
        self._update()
        self.resize(dialog_scaled(520), self.sizeHint().height())

    def options(self):
        return {"gif_width": self.width.value() if self.size_mode.currentData() else 0,
                "fps": self.fps.currentData()}

    def _update(self, *_):
        self.width.setEnabled(bool(self.size_mode.currentData()))
        valid = True
        try:
            if self.output_format == "mp4":
                from .mp4_export import output_geometry
                _, _, w, h = output_geometry(self.store, self.options()["gif_width"])
            else:
                w, h = output_size(self.store, self.options()["gif_width"])
            text = self.tr("Output: %1 × %2 pixels").replace("%1", str(w)).replace("%2", str(h))
        except ValueError:
            valid = False
            text = self.tr("Choose a smaller size: maximum 16 megapixels, 65535 pixels per edge and 16× enlargement.")
        if self.output_format == "mp4":
            from .mp4_export import encoder_available
            if not valid:
                text = self.tr("Choose a smaller MP4 size: maximum 16 megapixels, 8192 pixels per edge and 16× enlargement.")
            if not encoder_available():
                valid = False
                text = self.tr("H.264 encoding is unavailable. Install the required PyAV package or use GIF instead.")
        elif not timeline_encoder_available():
            valid = False
            text = self.tr("The installed GIF encoder is outdated. Build/install rust_libs/gifrecorder from this checkout before exporting.")
        self.output.setText(text)
        self.export_button.setEnabled(valid)

    def _theme(self, *_):
        self.setStyleSheet(f"GifExportDialog {{ background: {get_ui_theme().tokens.window}; }}")
