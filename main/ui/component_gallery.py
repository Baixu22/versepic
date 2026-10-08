"""Run with PYTHONPATH=main: python -m ui.component_gallery [--capture DIR].

Uses the production controls, with no settings, clipboard database or network access.
"""
from pathlib import Path
import argparse

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QGridLayout, QHBoxLayout, QScrollArea, QVBoxLayout, QWidget

from core.ui_scale import configure_dialog_controls, dialog_scaled, get_dialog_scale
from core.ui_theme import get_ui_theme
from ui.dialogs import StandardDialog
from ui.fluent_lite import (
    Badge, BodyLabel, Button, CaptionLabel, CheckBox, ComboBox, FluentIcon, IconButton,
    LineEdit, Menu, RadioButton, SegmentedWidget, Separator, SimpleCardWidget,
    SpinBox, SwitchButton, TextEdit, ToolTip, scrollbar_qss,
)


class ComponentGallery(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("VersePic · Qt components")
        self.resize(dialog_scaled(940), dialog_scaled(820))
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        heading = QHBoxLayout()
        heading.addWidget(BodyLabel("VersePic / Components", self), 1)
        heading.addWidget(BodyLabel("Dark mode", self))
        self.dark = SwitchButton(self)
        self.dark.setAccessibleName("Dark mode")
        self.dark.setChecked(get_ui_theme().is_dark)
        self.dark.toggled.connect(lambda value: get_ui_theme().set_mode("dark" if value else "light", persist=False))
        heading.addWidget(self.dark)
        outer.addLayout(heading)
        outer.addWidget(CaptionLabel("Shared Qt controls · shadcn/ui reference · Tab to explore", self))
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.content = QWidget(scroll)
        grid = QGridLayout(self.content)
        grid.setContentsMargins(0, 8, 0, 0)
        grid.setSpacing(16)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        scroll.setWidget(self.content)
        outer.addWidget(scroll)
        self.status = BodyLabel("Ready", self)
        outer.addWidget(self.status)
        self._scroll = scroll
        self._grid = grid

        card = self._card("Button", "Variants share size, focus and disabled states.", 0, 0)
        for variants in (("primary", "secondary", "outline"), ("ghost", "destructive", "link")):
            row = QHBoxLayout()
            for variant in variants:
                button = Button(variant.title(), self, variant=variant, size="sm")
                button.clicked.connect(lambda checked=False, name=variant: self.status.setText(f"{name.title()} clicked"))
                row.addWidget(button)
            card.addLayout(row)
        disabled = Button("Unavailable", self, variant="outline", size="sm")
        disabled.setEnabled(False)
        card.addWidget(disabled)

        card = self._card("Input / Select", "Shared borders, validation and native editing.", 0, 1)
        self.input = LineEdit(self)
        self.input.setPlaceholderText("Search clipboard…")
        self.input.setAccessibleName("Search clipboard")
        card.addWidget(self.input)
        self.select = ComboBox(self)
        self.select.addItems(["All content", "Text", "Images", "Files"])
        self.select.setAccessibleName("Content type")
        card.addWidget(self.select)
        invalid = CheckBox("Show validation error", self)
        invalid.toggled.connect(self.input.setInvalid)
        card.addWidget(invalid)

        card = self._card("Checkbox / Radio / Switch", "Space to toggle. Arrow keys select radio options.", 1, 0)
        self.check = CheckBox("Keep clipboard open", self)
        card.addWidget(self.check)
        mixed = CheckBox("Some items selected", self)
        mixed.setTristate(True)
        mixed.setCheckState(Qt.CheckState.PartiallyChecked)
        card.addWidget(mixed)
        radios = QWidget(self)
        row = QHBoxLayout(radios)
        row.setContentsMargins(0, 0, 0, 0)
        first, second = RadioButton("Copy", radios), RadioButton("Paste", radios)
        first.setChecked(True)
        row.addWidget(first)
        row.addWidget(second)
        card.addWidget(radios)
        self.reduced = CheckBox("Reduce motion", self)
        self.reduced.toggled.connect(lambda value: QApplication.instance().setProperty("uiReducedMotion", value))
        card.addWidget(self.reduced)

        card = self._card("Tabs / Badge", "Arrow keys, Home and End select a tab.", 1, 1)
        self.tabs = SegmentedWidget(self)
        for key in ("Recent", "Pinned", "Groups"):
            self.tabs.addItem(key, key)
        self.tab_content = BodyLabel("Recent items", self)
        self.tabs.currentItemChanged.connect(lambda key: self.tab_content.setText(f"{key} items"))
        card.addWidget(self.tabs)
        card.addWidget(self.tab_content)
        card.addWidget(Separator(self))
        row = QHBoxLayout()
        for name in ("primary", "secondary", "outline", "destructive"):
            row.addWidget(Badge(name.title(), self, variant=name))
        card.addLayout(row)

        card = self._card("Textarea / Number", "Native selection, undo and a shared context menu.", 2, 0)
        self.text = TextEdit(self)
        self.text.setPlainText("A reusable Qt component.\n可复用组件，共用同一套样式。")
        self.text.setAccessibleName("Note")
        self.text.setFixedHeight(dialog_scaled(80))
        card.addWidget(self.text)
        self.number = SpinBox(self)
        self.number.setRange(1, 100)
        self.number.setValue(24)
        self.number.setAccessibleName("History limit")
        card.addWidget(self.number)

        card = self._card("Menu / Tooltip / Dialog", "Escape closes the active popup or dialog.", 2, 1)
        self.menu_button = Button("Open menu", self, variant="outline")
        self.menu = Menu(parent=self.menu_button)
        self.menu.addAction("Copy").triggered.connect(lambda: self.status.setText("Copy action selected"))
        pinned = self.menu.addAction("Pinned")
        pinned.setCheckable(True)
        self.menu.addSeparator()
        self.menu.addAction("Unavailable").setEnabled(False)
        self.menu_button.setMenu(self.menu)
        card.addWidget(self.menu_button)
        row = QHBoxLayout()
        self.tip_button = IconButton(FluentIcon.INFO, self, tooltip="Available with mouse or keyboard focus")
        row.addWidget(self.tip_button)
        dialog_button = Button("Open dialog", self, variant="secondary")
        dialog_button.clicked.connect(self._show_dialog)
        row.addWidget(dialog_button)
        card.addLayout(row)
        card.addWidget(CaptionLabel("Dialogs use the same buttons and follow the active theme.", self))

        ToolTip.install(self)
        configure_dialog_controls(self)
        get_ui_theme().theme_changed.connect(self._apply_theme)

    def _card(self, title, description, row, column):
        frame = SimpleCardWidget(self.content)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(*(dialog_scaled(16) for _ in range(4)))
        layout.setSpacing(dialog_scaled(10))
        layout.addWidget(BodyLabel(title, frame))
        layout.addWidget(CaptionLabel(description, frame))
        self._grid.addWidget(frame, row, column)
        return layout

    def _apply_theme(self, *_):
        self._scroll.setStyleSheet(scrollbar_qss(self))

    def _show_dialog(self):
        dialog = StandardDialog(self, "Save changes?", "This example uses the same dialog as the application.")
        save = dialog.button_box.addButton("Save", QDialogButtonBox.ButtonRole.AcceptRole)
        cancel = dialog.button_box.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
        save.clicked.connect(dialog.accept)
        cancel.clicked.connect(dialog.reject)
        cancel.setDefault(True)
        self.status.setText("Saved" if dialog.exec() else "Cancelled")
        dialog.deleteLater()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", type=Path)
    parser.add_argument("--scale", type=int, default=100, choices=get_dialog_scale().PERCENT_OPTIONS)
    args = parser.parse_args()
    app = QApplication([])
    app.setStyle("Fusion")
    get_ui_theme().init(application=app)
    get_ui_theme().set_mode("light", persist=False)
    get_dialog_scale().set_percent(args.scale)
    window = ComponentGallery()
    window.show()
    if args.capture:
        args.capture.mkdir(parents=True, exist_ok=True)

        def capture():
            from PySide6.QtTest import QTest
            app.setProperty("uiReducedMotion", True)
            for dark in (False, True):
                window.dark.setChecked(dark)
                QTest.qWait(80)
                path = args.capture / f"components-{'dark' if dark else 'light'}-{args.scale}.png"
                if not window.grab().save(str(path)):
                    raise RuntimeError(f"Could not save {path}")
                print(path.resolve())
            app.quit()

        QTimer.singleShot(100, capture)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
