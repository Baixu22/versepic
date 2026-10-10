# -*- coding: utf-8 -*-
"""TF-0039 标注样式预设：保存/应用/重命名/删除、非法字段回退、重启保留。"""
import pytest

from core.annotation_presets import (
    MAX_NAME_CHARS,
    SETTING_KEY,
    apply_to_tool_defaults,
    capture_tool_values,
    delete_preset,
    find_preset,
    load_presets,
    rename_preset,
    sanitize_values,
    upsert_preset,
)
from settings import get_tool_settings_manager


@pytest.fixture(autouse=True)
def clean_presets():
    manager = get_tool_settings_manager()
    before = manager.get_app_setting(SETTING_KEY, "")
    yield manager
    manager.set_app_setting(SETTING_KEY, before)


def test_upsert_load_roundtrip_survives_restart():
    manager = get_tool_settings_manager()
    preset = upsert_preset(manager, "红色粗箭头", "arrow", {"color": "#FF0000", "stroke_width": 12})
    assert preset is not None

    stored = load_presets(manager)
    assert [(p.name, p.tool_id) for p in stored] == [("红色粗箭头", "arrow")]
    # 重新读一遍＝重启后读同一份设置
    again = find_preset(manager, "arrow", "红色粗箭头")
    assert again is not None and again.values["stroke_width"] == 12.0


def test_invalid_or_expired_fields_are_dropped_or_clamped():
    values = sanitize_values("arrow", {
        "color": "not-a-color",
        "stroke_width": 99999,
        "opacity": 5.0,
        "arrow_style": "future-style",
        "made_up_field": 1,
    })
    assert "made_up_field" not in values
    assert "color" not in values
    assert values["stroke_width"] == 2048.0
    assert values["opacity"] == 1.0
    assert "arrow_style" not in values


def test_corrupt_or_stale_store_falls_back_to_valid_entries():
    manager = get_tool_settings_manager()
    manager.set_app_setting(SETTING_KEY, "{not json")
    assert load_presets(manager) == []

    manager.set_app_setting(SETTING_KEY, '[{"name":"好","tool_id":"arrow","values":{"stroke_width":4}}, {"name":"","tool_id":"arrow","values":{}}, {"name":"坏工具","tool_id":"nope","values":{"x":1}}, "junk"]')
    stored = load_presets(manager)
    assert [p.name for p in stored] == ["好"]


def test_upsert_dedups_by_tool_and_name():
    manager = get_tool_settings_manager()
    upsert_preset(manager, "常用", "rect", {"color": "#FF0000", "stroke_width": 2})
    upsert_preset(manager, "常用", "rect", {"color": "#00FF00", "stroke_width": 6})

    stored = [p for p in load_presets(manager) if p.tool_id == "rect"]
    assert len(stored) == 1
    assert stored[0].values["stroke_width"] == 6.0


def test_rename_and_delete_preset():
    manager = get_tool_settings_manager()
    upsert_preset(manager, "旧名", "text", {"font_size": 20})
    assert rename_preset(manager, "text", "旧名", "新名") is True
    assert find_preset(manager, "text", "旧名") is None
    assert find_preset(manager, "text", "新名") is not None

    upsert_preset(manager, "冲突", "text", {"font_size": 22})
    assert rename_preset(manager, "text", "新名", "冲突") is False, "重名不能覆盖"

    assert delete_preset(manager, "text", "新名") is True
    assert find_preset(manager, "text", "新名") is None
    assert delete_preset(manager, "text", "不存在") is False


def test_apply_preset_writes_tool_defaults():
    manager = get_tool_settings_manager()
    preset = upsert_preset(manager, "绿箭头", "arrow", {"color": "#00FF00", "stroke_width": 5})
    assert apply_to_tool_defaults(manager, preset) is True

    settings = manager.get_tool_settings("arrow")
    assert settings.get("color") == "#00ff00"
    assert float(settings.get("stroke_width")) == 5.0


def test_capture_tool_values_uses_whitelist_only():
    manager = get_tool_settings_manager()
    values = capture_tool_values(manager, "mosaic")
    assert "block_size" in values
    assert "not_a_real_key" not in values
    assert capture_tool_values(manager, "nope") == {}


def test_unknown_tool_or_overlong_name_is_rejected():
    manager = get_tool_settings_manager()
    assert upsert_preset(manager, "x", "nope", {"color": "#FF0000"}) is None
    preset = upsert_preset(manager, "名" * 100, "arrow", {"stroke_width": 3})
    assert preset is not None and len(preset.name) <= MAX_NAME_CHARS



def test_apply_preset_to_selected_item_is_undoable(qapp):
    from PySide6.QtCore import QPointF, QRectF
    from PySide6.QtGui import QColor, QImage, QPen

    from canvas.items import ArrowItem
    from canvas.scene import CanvasScene
    from canvas.undo import CommandUndoStack
    from core.annotation_presets import apply_preset_to_item, upsert_preset

    manager = get_tool_settings_manager()
    preset = upsert_preset(manager, "蓝粗箭头", "arrow", {"color": "#0000FF", "stroke_width": 7})
    scene = CanvasScene(QImage(80, 60, QImage.Format.Format_ARGB32), QRectF(0, 0, 80, 60), enable_mosaic=True)
    item = ArrowItem(QPointF(4, 4), QPointF(40, 40), QPen(QColor("#FF0000"), 2), "single")
    scene.addItem(item)
    scene.undo_stack = CommandUndoStack()
    before_width = item.base_width

    assert apply_preset_to_item(preset, item, scene.undo_stack) is True
    assert item.color.name() == "#0000ff"
    assert item.base_width == 7.0

    scene.undo_stack.undo()
    assert item.base_width == before_width

    scene.undo_stack.redo()
    assert item.base_width == 7.0

def test_preset_dialog_saves_and_applies_to_item_or_defaults(qapp):
    from PySide6.QtCore import QPointF, QRectF
    from PySide6.QtGui import QColor, QImage, QPen

    from canvas.items import ArrowItem
    from canvas.scene import CanvasScene
    from canvas.smart_edit_controller import SmartEditController
    from ui.preset_dialog import AnnotationPresetDialog

    manager = get_tool_settings_manager()
    scene = CanvasScene(QImage(80, 60, QImage.Format.Format_ARGB32), QRectF(0, 0, 80, 60), enable_mosaic=True)
    item = ArrowItem(QPointF(4, 4), QPointF(40, 40), QPen(QColor("#FF0000"), 2), "single")
    scene.addItem(item)

    class _View:
        pass

    view = _View()
    view.scene = scene
    view.smart_edit_controller = SmartEditController(scene)
    view.smart_edit_controller.selected_item = item

    class _Toolbar:
        current_tool = "arrow"

        def _show_panel_for_tool(self, tool_id):
            pass

        def _sync_panel_from_settings(self, tool_id):
            pass

    dialog = AnnotationPresetDialog(_Toolbar(), view)
    try:
        dialog.tool_combo.setCurrentIndex(dialog.tool_combo.findData("arrow"))
        manager.update_settings("arrow", color="#0000FF", stroke_width=8)
        dialog.name_edit.setText("蓝粗")
        dialog._save_current()
        assert find_preset(manager, "arrow", "蓝粗") is not None

        # 选中图元：应用改图元，且可撤销；工具默认值不动
        manager.update_settings("arrow", color="#FF0000", stroke_width=3)
        item.base_width = 2.0
        dialog.preset_combo.setCurrentIndex(dialog.preset_combo.findData("蓝粗"))
        dialog._apply_current()
        assert item.base_width == 8.0
        assert item.color.name() == "#0000ff"
        scene.undo_stack.undo()
        assert item.base_width == 2.0

        # 没有选中：应用写新建默认值
        view.smart_edit_controller.selected_item = None
        dialog._apply_current()
        assert float(manager.get_tool_settings("arrow").get("stroke_width")) == 8.0
        assert manager.get_tool_settings("arrow").get("color") == "#0000ff"
    finally:
        dialog.deleteLater()
