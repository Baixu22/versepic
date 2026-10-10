"""Edit one screenshot region without changing the captured pixels or annotations."""
from math import ceil, gcd

from PySide6.QtCore import QRect, QSignalBlocker, Qt
from PySide6.QtWidgets import QDialog, QFormLayout, QHBoxLayout, QVBoxLayout

from core.ui_scale import configure_dialog_control, dialog_scaled, scale_dialog_font
from core.ui_theme import get_ui_theme
from ui.fluent_lite import BodyLabel, CaptionLabel, ComboBox, PrimaryPushButton, PushButton, SpinBox, LineEdit


class RegionGeometryDialog(QDialog):
    def __init__(self, rect, bounds, *, locked=False, padding=0, config=None, layout_signature=None, parent=None):
        super().__init__(parent)
        scale_dialog_font(self)
        self.setWindowTitle(self.tr("Exact Region"))
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.WindowTitleHint
                            | Qt.WindowType.WindowCloseButtonHint | Qt.WindowType.WindowStaysOnTopHint)
        self._bounds = QRect(bounds)
        self._padding = max(0, int(padding))
        if self._bounds.width() < 8 or self._bounds.height() < 8:
            raise ValueError("Capture bounds must be at least 8 by 8 pixels")
        self._syncing = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(*[dialog_scaled(20)] * 4)
        layout.setSpacing(dialog_scaled(12))
        hint = CaptionLabel(self.tr("Physical pixels. Negative coordinates are valid on other screens."), self)
        configure_dialog_control(hint)
        layout.addWidget(hint)
        form = QFormLayout()
        form.setSpacing(dialog_scaled(12))
        self.fields = {}
        ranges = {"x": (bounds.left(), bounds.right() - 7), "y": (bounds.top(), bounds.bottom() - 7),
                  "width": (8, bounds.width()), "height": (8, bounds.height())}
        values = {"x": rect.x(), "y": rect.y(), "width": rect.width(), "height": rect.height()}
        for key, label in (("x", "X"), ("y", "Y"), ("width", "Width"), ("height", "Height")):
            field = SpinBox(self)
            configure_dialog_control(field)
            field.setObjectName("region_" + key)
            field.setAccessibleName(self.tr(label))
            field.setRange(*ranges[key])
            field.setKeyboardTracking(False)
            field.setValue(values[key])
            field.valueChanged.connect(lambda value, axis=key: self._changed(axis))
            self.fields[key] = field
            name = BodyLabel(self.tr(label), self)
            configure_dialog_control(name)
            form.addRow(name, field)
        self.ratio_combo = ComboBox(self)
        configure_dialog_control(self.ratio_combo)
        self.ratio_combo.setAccessibleName(self.tr("Aspect Ratio"))
        for label, ratio in ((self.tr("Free"), None), ("1:1", (1, 1)), ("4:3", (4, 3)), ("16:9", (16, 9))):
            self.ratio_combo.addItem(label, ratio)
        if locked:
            divisor = gcd(max(1, rect.width()), max(1, rect.height()))
            ratio = (rect.width() // divisor, rect.height() // divisor)
            found = next((i for i in range(1, self.ratio_combo.count())
                          if tuple(self.ratio_combo.itemData(i)) == ratio), -1)
            if found < 0:
                self.ratio_combo.addItem(self.tr("Current ratio"), ratio)
                found = self.ratio_combo.count() - 1
            self.ratio_combo.setCurrentIndex(found)
        self.ratio_combo.currentIndexChanged.connect(lambda: self._changed("width"))
        name = BodyLabel(self.tr("Aspect Ratio"), self)
        configure_dialog_control(name)
        form.addRow(name, self.ratio_combo)
        layout.addLayout(form)
        self.output_size = CaptionLabel(self)
        configure_dialog_control(self.output_size)
        layout.addWidget(self.output_size)
        self.saved_size = CaptionLabel(self)
        configure_dialog_control(self.saved_size)
        layout.addWidget(self.saved_size)
        self.message = CaptionLabel(self)
        configure_dialog_control(self.message)
        layout.addWidget(self.message)
        buttons = QHBoxLayout()
        buttons.addStretch()
        self.cancel_button = PushButton(self.tr("Cancel"), self)
        self.apply_button = PrimaryPushButton(self.tr("Apply"), self)
        for button in (self.cancel_button, self.apply_button):
            configure_dialog_control(button)
            buttons.addWidget(button)
        self.cancel_button.clicked.connect(self.reject)
        self.apply_button.clicked.connect(self._accept_valid)
        self.apply_button.setDefault(True)
        layout.addLayout(buttons)
        self.resize(dialog_scaled(450), self.sizeHint().height())
        get_ui_theme().theme_changed.connect(self._theme)
        self._theme()
        self._build_presets(layout, config, layout_signature)
        self._validate()

    def _theme(self, *_):
        self.setStyleSheet(f"QDialog {{ background: {get_ui_theme().tokens.window}; }}")

    def ratio(self):
        value = self.ratio_combo.currentData()
        return tuple(value) if value is not None else None

    def selected_rect(self):
        return QRect(*(self.fields[key].value() for key in ("x", "y", "width", "height")))

    def _changed(self, axis):
        if self._syncing or not hasattr(self, "ratio_combo"):
            return
        self._preset_mismatch = False
        ratio = self.ratio()
        if ratio is not None and axis in ("width", "height"):
            a, b = ratio
            minimum = max(ceil(8 / a), ceil(8 / b))
            maximum = min(self._bounds.width() // a, self._bounds.height() // b)
            if maximum >= minimum:
                value = self.fields[axis].value()
                multiple = min(maximum, max(minimum, round(value / (a if axis == "width" else b))))
                self._syncing = True
                try:
                    for key, component in (("width", a), ("height", b)):
                        with QSignalBlocker(self.fields[key]):
                            self.fields[key].setValue(multiple * component)
                finally:
                    self._syncing = False
        self._validate()

    def _validate(self):
        rect = self.selected_rect()
        ratio = self.ratio()
        self.fields["width"].setSingleStep(ratio[0] if ratio else 1)
        self.fields["height"].setSingleStep(ratio[1] if ratio else 1)
        valid = self._bounds.contains(rect) and (ratio is None or rect.width() * ratio[1] == rect.height() * ratio[0])
        self.apply_button.setEnabled(valid and not getattr(self, "_preset_mismatch", False))
        if hasattr(self, "preset_save"):
            self.preset_save.setEnabled(valid and self._presets_valid and bool(self.preset_name.text().strip()))
        output = self.tr("Output: %1 × %2 px").replace("%1", str(rect.width() + 2 * self._padding)).replace("%2", str(rect.height() + 2 * self._padding))
        if self._padding:
            output += self.tr(" (including border/shadow)")
        self.output_size.setText(output)
        options = getattr(self, "_output_options", None)
        self.saved_size.setVisible(options is not None and options.size_mode != "original")
        if options is not None:
            try:
                width, height = options.output_size(rect.width() + 2 * self._padding, rect.height() + 2 * self._padding)
                self.saved_size.setText(self.tr("Saved file: %1 × %2 px").replace("%1", str(width)).replace("%2", str(height)))
            except ValueError:
                self.saved_size.setText(self.tr("Saved file would be too large. Reduce the output width."))
        self.message.setText(self.tr("Ratio presets use whole-pixel multiples.") if valid else
                             self.tr("The region or ratio does not fit the captured desktop."))
        return valid and not getattr(self, "_preset_mismatch", False)

    def _accept_valid(self):
        for field in self.fields.values():
            field.interpretText()
        if self._validate():
            self.accept()

    def _build_presets(self, layout, config, signature):
        from capture.region_presets import RegionPresetStore, current_screen_layout
        from settings import get_tool_settings_manager
        self._preset_store = RegionPresetStore(config or get_tool_settings_manager())
        from core.image_output import ImageOutputOptions
        self._output_options = ImageOutputOptions.from_config(self._preset_store.config)
        self._layout_signature = signature if signature is not None else current_screen_layout()
        self._preset_mismatch = False
        self._presets_valid = True
        box = QVBoxLayout()
        row = QHBoxLayout()
        row.addWidget(BodyLabel(self.tr("Saved Regions"), self))
        self.preset_combo = ComboBox(self)
        configure_dialog_control(self.preset_combo)
        row.addWidget(self.preset_combo, 1)
        box.addLayout(row)
        self.preset_name = LineEdit(self)
        configure_dialog_control(self.preset_name)
        self.preset_name.setMaxLength(64)
        self.preset_name.setPlaceholderText(self.tr("Preset name"))
        box.addWidget(self.preset_name)
        row = QHBoxLayout()
        self.preset_save = PushButton(self.tr("Save preset"), self)
        self.preset_rename = PushButton(self.tr("Rename"), self)
        self.preset_delete = PushButton(self.tr("Delete preset"), self)
        for button in (self.preset_save, self.preset_rename, self.preset_delete):
            configure_dialog_control(button)
            row.addWidget(button)
        box.addLayout(row)
        self.preset_status = CaptionLabel(self.tr("Preset changes are saved immediately; Apply changes the selection."), self)
        configure_dialog_control(self.preset_status)
        box.addWidget(self.preset_status)
        layout.insertLayout(0, box)
        self.preset_combo.currentIndexChanged.connect(self._preset_changed)
        self.preset_name.textChanged.connect(self._preset_buttons)
        self.preset_save.clicked.connect(self._save_preset)
        self.preset_rename.clicked.connect(self._rename_preset)
        self.preset_delete.clicked.connect(self._delete_preset)
        self._reload_presets()

    def _reload_presets(self, selected=None):
        try:
            records = self._preset_store.load()
            self._presets_valid = True
        except ValueError:
            records = []
            self._presets_valid = False
            self.preset_status.setText(self.tr("Saved region data is invalid. Existing data was left unchanged."))
        with QSignalBlocker(self.preset_combo):
            self.preset_combo.clear()
            self.preset_combo.addItem(self.tr("No preset"), None)
            for record in records:
                self.preset_combo.addItem(record["name"], record["id"])
            self.preset_combo.setCurrentIndex(max(0, self.preset_combo.findData(selected)))
        self._preset_buttons()

    def _preset_buttons(self):
        selected = self.preset_combo.currentData() is not None
        named = bool(self.preset_name.text().strip())
        self.preset_rename.setEnabled(self._presets_valid and selected and named)
        self.preset_delete.setEnabled(self._presets_valid and selected)
        self.preset_save.setText(self.tr("Update preset") if selected else self.tr("Save preset"))
        self._validate()

    def _preset_changed(self):
        identifier = self.preset_combo.currentData()
        self._preset_mismatch = False
        if identifier is None:
            self.preset_name.clear()
            self.preset_status.setText(self.tr("Preset changes are saved immediately; Apply changes the selection."))
            self._preset_buttons()
            return
        try:
            record = self._preset_store.get(identifier)
            self.preset_name.setText(record["name"])
            rect, locked = self._preset_store.resolve(identifier, self._layout_signature, self._bounds)
            self._syncing = True
            for key, value in (("x", rect.x()), ("y", rect.y()), ("width", rect.width()), ("height", rect.height())):
                with QSignalBlocker(self.fields[key]):
                    self.fields[key].setValue(value)
            index = 0
            if locked:
                divisor = gcd(rect.width(), rect.height())
                ratio = (rect.width() // divisor, rect.height() // divisor)
                index = next((i for i in range(1, self.ratio_combo.count()) if tuple(self.ratio_combo.itemData(i)) == ratio), -1)
                if index < 0:
                    self.ratio_combo.addItem(f"{ratio[0]}:{ratio[1]}", ratio)
                    index = self.ratio_combo.count() - 1
            with QSignalBlocker(self.ratio_combo):
                self.ratio_combo.setCurrentIndex(index)
            self.preset_status.setText(self.tr("Saved region loaded."))
        except ValueError:
            self._preset_mismatch = True
            self.preset_status.setText(self.tr("Screen layout or scale changed. Review the current region and update the preset, or choose No preset."))
        finally:
            self._syncing = False
        self._preset_buttons()

    def _save_preset(self):
        try:
            identifier = self._preset_store.save(self.preset_name.text(), self.selected_rect(), self._layout_signature,
                                                  identifier=self.preset_combo.currentData(), locked=self.ratio() is not None)
            self._preset_mismatch = False
            self._reload_presets(identifier)
            self.preset_status.setText(self.tr("Preset saved."))
        except (ValueError, OSError):
            self.preset_status.setText(self.tr("Could not save preset. Check the name and settings location."))

    def _rename_preset(self):
        try:
            identifier = self.preset_combo.currentData()
            self._preset_store.rename(identifier, self.preset_name.text())
            self._reload_presets(identifier)
            if not self._preset_mismatch:
                self.preset_status.setText(self.tr("Preset renamed."))
        except (ValueError, OSError):
            self.preset_status.setText(self.tr("Could not rename preset. Names must be unique."))

    def _delete_preset(self):
        try:
            self._preset_store.delete(self.preset_combo.currentData())
            self._preset_mismatch = False
            self.preset_name.clear()
            self._reload_presets()
            self.preset_status.setText(self.tr("Preset deleted."))
        except (ValueError, OSError):
            self.preset_status.setText(self.tr("Could not delete preset."))
