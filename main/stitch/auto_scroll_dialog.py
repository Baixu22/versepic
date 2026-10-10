"""Explicit opt-in limits for automatic scrolling."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QFormLayout, QHBoxLayout, QVBoxLayout
from core.ui_scale import configure_dialog_control, dialog_scaled, scale_dialog_font
from core.ui_theme import get_ui_theme
from ui.fluent_lite import BodyLabel, CaptionLabel, ComboBox, PrimaryPushButton, PushButton, SpinBox
from .auto_scroll import AutoScrollOptions


class AutoScrollDialog(QDialog):
    def __init__(self, direction=None, parent=None):
        super().__init__(parent)
        scale_dialog_font(self)
        self.setWindowTitle(self.tr("Automatic scrolling"))
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.WindowTitleHint | Qt.WindowType.WindowCloseButtonHint | Qt.WindowType.WindowStaysOnTopHint)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(*[dialog_scaled(16)]*4)
        hint = CaptionLabel(self.tr("After Start, activate the intended app and put the pointer inside the selected capture area within 3 seconds. Scrolling is addressed only to that window. Keep it visible and focused. Esc stops; some applications may not support this input."), self)
        configure_dialog_control(hint)
        layout.addWidget(hint)
        form = QFormLayout()
        self.direction = ComboBox(self)
        self.direction.addItem(self.tr("Down / right"), "down")
        self.direction.addItem(self.tr("Up / left"), "up")
        self.direction.setCurrentIndex(1 if direction == "up" else 0)
        self.direction.setEnabled(direction is None)
        configure_dialog_control(self.direction)
        self.labels=[]
        label=BodyLabel(self.tr("Direction"),self)
        configure_dialog_control(label)
        self.labels.append(label)
        form.addRow(label, self.direction)
        self.inputs = {}
        for name, label, low, high, value in (
            ("wheel_steps", "Wheel notches per step", 1,5,1),
            ("interval_ms", "Wait after each scroll (ms)",250,3000,600),
            ("max_steps", "Maximum scroll steps",1,200,40),
            ("timeout_seconds", "Maximum duration (seconds)",5,180,60),
            ("max_length", "Maximum image length (px)",1000,100000,20000),
        ):
            widget=SpinBox(self)
            configure_dialog_control(widget)
            widget.setRange(low, high)
            widget.setValue(value)
            title=BodyLabel(self.tr(label),self)
            configure_dialog_control(title)
            self.labels.append(title)
            form.addRow(title, widget)
            self.inputs[name]=widget
        layout.addLayout(form)
        bottom=QHBoxLayout()
        bottom.addStretch()
        cancel=PushButton(self.tr("Cancel"),self)
        self.start=PrimaryPushButton(self.tr("Start in 3 seconds"),self)
        cancel.clicked.connect(self.reject)
        self.start.clicked.connect(self.accept)
        for button in (cancel,self.start):
            configure_dialog_control(button)
            bottom.addWidget(button)
        layout.addLayout(bottom)
        get_ui_theme().theme_changed.connect(self._theme)
        self._theme()
        self.resize(dialog_scaled(540), self.sizeHint().height())

    def _theme(self,*_):
        self.setStyleSheet(f"QDialog {{ background: {get_ui_theme().tokens.window}; }}")

    def options(self):
        return AutoScrollOptions(direction=self.direction.currentData(), **{key:widget.value() for key,widget in self.inputs.items()})
