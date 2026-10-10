# -*- coding: utf-8 -*-
"""常用标注样式预设对话框（TF-0039）。

把当前工具的样式存成命名预设，之后可以应用、重命名、删除。应用语义分两种，
界面上直接写明：画布上选中了同工具的图元就改那个图元（可撤销）；否则改的是
"以后新建这个工具"的默认值。对话框不参与工具栏自定义布局。
"""
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from core.annotation_presets import (
    TOOL_FIELDS,
    apply_preset_to_item,
    apply_to_tool_defaults,
    capture_tool_values,
    delete_preset,
    find_preset,
    load_presets,
    rename_preset,
    upsert_preset,
)
from settings import get_tool_settings_manager
from ui.fluent_lite import BodyLabel, ComboBox, LineEdit, PrimaryPushButton, PushButton

TOOL_LABELS = (
    ("arrow", "Arrow"),
    ("pen", "Pen"),
    ("highlighter", "Highlighter"),
    ("rect", "Rectangle"),
    ("ellipse", "Ellipse"),
    ("number", "Number"),
    ("text", "Text"),
    ("mosaic", "Mosaic"),
    ("callout", "Text callout"),
    ("magnify", "Magnify region"),
)


class AnnotationPresetDialog(QDialog):
    """命名样式预设的保存/应用/重命名/删除。"""

    def __init__(self, toolbar=None, view=None, parent=None):
        parent_widget = parent if parent is not None else (toolbar if isinstance(toolbar, QWidget) else None)
        super().__init__(parent_widget)
        self.toolbar = toolbar
        self.view = view
        self.manager = get_tool_settings_manager()
        self.setWindowTitle(self.tr("Annotation Presets"))
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        tool_row = QHBoxLayout()
        tool_row.addWidget(BodyLabel(self.tr("Tool"), self))
        self.tool_combo = ComboBox(self)
        for tool_id, label in TOOL_LABELS:
            if tool_id in TOOL_FIELDS:
                self.tool_combo.addItem(self.tr(label), tool_id)
        tool_row.addWidget(self.tool_combo, 1)
        layout.addLayout(tool_row)

        preset_row = QHBoxLayout()
        preset_row.addWidget(BodyLabel(self.tr("Preset"), self))
        self.preset_combo = ComboBox(self)
        preset_row.addWidget(self.preset_combo, 1)
        layout.addLayout(preset_row)

        name_row = QHBoxLayout()
        name_row.addWidget(BodyLabel(self.tr("Name"), self))
        self.name_edit = LineEdit(self)
        self.name_edit.setMaxLength(40)
        name_row.addWidget(self.name_edit, 1)
        layout.addLayout(name_row)

        buttons = QHBoxLayout()
        self.save_btn = PushButton(self.tr("Save current style"), self)
        self.apply_btn = PrimaryPushButton(self.tr("Apply"), self)
        self.rename_btn = PushButton(self.tr("Rename"), self)
        self.delete_btn = PushButton(self.tr("Delete"), self)
        for button in (self.save_btn, self.apply_btn, self.rename_btn, self.delete_btn):
            buttons.addWidget(button)
        layout.addLayout(buttons)

        self.hint = QLabel(
            self.tr("With a matching item selected, Apply edits that item (undoable). Otherwise it changes the defaults for new annotations."),
            self,
        )
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)
        self.status = QLabel("", self)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        self.tool_combo.currentIndexChanged.connect(self._reload_presets)
        self.preset_combo.currentIndexChanged.connect(self._on_preset_selected)
        self.save_btn.clicked.connect(self._save_current)
        self.apply_btn.clicked.connect(self._apply_current)
        self.rename_btn.clicked.connect(self._rename_current)
        self.delete_btn.clicked.connect(self._delete_current)

        current = getattr(toolbar, "current_tool", None)
        if current in TOOL_FIELDS:
            index = self.tool_combo.findData(current)
            if index >= 0:
                self.tool_combo.setCurrentIndex(index)
        self._reload_presets()

    # ------------------------------------------------------------------

    def current_tool_id(self) -> str:
        return self.tool_combo.currentData()

    def _current_preset(self):
        name = self.preset_combo.currentData()
        if not name:
            return None
        return find_preset(self.manager, self.current_tool_id(), name)

    def _reload_presets(self, *_args):
        current = self.preset_combo.currentData()
        self.preset_combo.blockSignals(True)
        self.preset_combo.clear()
        for preset in load_presets(self.manager):
            if preset.tool_id == self.current_tool_id():
                self.preset_combo.addItem(preset.name, preset.name)
        index = self.preset_combo.findData(current)
        if index >= 0:
            self.preset_combo.setCurrentIndex(index)
        self.preset_combo.blockSignals(False)
        self._on_preset_selected()

    def _on_preset_selected(self, *_args):
        preset = self._current_preset()
        if preset is not None:
            self.name_edit.setText(preset.name)

    def _selected_matching_item(self, tool_id):
        controller = getattr(self.view, "smart_edit_controller", None)
        item = getattr(controller, "selected_item", None) if controller else None
        if item is None:
            return None
        getter = getattr(controller, "get_item_tool_id", None)
        if callable(getter):
            try:
                if getter(item) != tool_id:
                    return None
            except Exception:
                return None
        return item

    def _undo_stack(self):
        scene = getattr(self.view, "scene", None) or getattr(self.view, "canvas_scene", None)
        return getattr(scene, "undo_stack", None) if scene is not None else None

    def _refresh_toolbar(self, tool_id):
        toolbar = self.toolbar
        if toolbar is None:
            return
        try:
            if getattr(toolbar, "current_tool", None) == tool_id:
                toolbar._show_panel_for_tool(tool_id)
            toolbar._sync_panel_from_settings(tool_id)
        except Exception:
            pass

    def _save_current(self):
        name = self.name_edit.text().strip()
        if not name:
            self.status.setText(self.tr("Give the preset a name first."))
            return
        tool_id = self.current_tool_id()
        values = capture_tool_values(self.manager, tool_id)
        preset = upsert_preset(self.manager, name, tool_id, values)
        if preset is None:
            self.status.setText(self.tr("Could not save this preset."))
            return
        self._reload_presets()
        self.preset_combo.setCurrentIndex(max(0, self.preset_combo.findData(name)))
        self.status.setText(self.tr("Saved."))

    def _apply_current(self):
        preset = self._current_preset()
        if preset is None:
            self.status.setText(self.tr("Pick a preset first."))
            return
        item = self._selected_matching_item(preset.tool_id)
        if item is not None and apply_preset_to_item(preset, item, self._undo_stack()):
            self.status.setText(self.tr("Applied to the selected item (undoable)."))
            self._refresh_toolbar(preset.tool_id)
            return
        if apply_to_tool_defaults(self.manager, preset):
            self.status.setText(self.tr("Applied to the defaults for new annotations."))
            self._refresh_toolbar(preset.tool_id)
            return
        self.status.setText(self.tr("Nothing to apply."))

    def _rename_current(self):
        preset = self._current_preset()
        if preset is None:
            self.status.setText(self.tr("Pick a preset first."))
            return
        new_name = self.name_edit.text().strip()
        if rename_preset(self.manager, preset.tool_id, preset.name, new_name):
            self._reload_presets()
            self.preset_combo.setCurrentIndex(max(0, self.preset_combo.findData(new_name)))
            self.status.setText(self.tr("Renamed."))
        else:
            self.status.setText(self.tr("Rename failed: empty or duplicate name."))

    def _delete_current(self):
        preset = self._current_preset()
        if preset is None:
            self.status.setText(self.tr("Pick a preset first."))
            return
        if delete_preset(self.manager, preset.tool_id, preset.name):
            self.name_edit.clear()
            self._reload_presets()
            self.status.setText(self.tr("Deleted."))
        else:
            self.status.setText(self.tr("Could not delete this preset."))
