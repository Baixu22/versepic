# -*- coding: utf-8 -*-
"""TF-0036 编号说明列表：说明与编号绑定、导出旁注/下方步骤列表。"""
from PySide6.QtCore import QPoint, QPointF, QRectF, QSize
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QWidget

from canvas.items import NumberItem
from canvas.scene import CanvasScene
from canvas.undo import NumberCaptionCommand, RemoveItemCommand, RemoveNumberAndRenumberCommand
from core.editable_project import Assets, dump_item, load_item
from core.export import ExportService
from core.number_legend import (
    PLACEMENT_BOTTOM,
    PLACEMENT_OFF,
    PLACEMENT_SIDE,
    LegendEntry,
    LegendOptions,
    collect_entries,
    normalize_placement,
    render,
    wrap_caption,
)

SIZE = 200


def _scene():
    image = QImage(SIZE, SIZE, QImage.Format.Format_ARGB32)
    image.fill(QColor("white"))
    scene = CanvasScene(image, QRectF(0, 0, SIZE, SIZE), enable_mosaic=True)
    scene.selection_model.initialize_confirmed_rect(QRectF(0, 0, SIZE, SIZE))
    return scene, image


def _number(scene, number, pos=(20, 20), caption=""):
    item = NumberItem(number, QPointF(*pos), 12, QColor("#FF0000"), None)
    item.set_caption(caption)
    scene.addItem(item)
    return item


def _pairs(entries):
    return [(entry.number, entry.caption) for entry in entries]


def test_entries_follow_number_order_and_skip_empty_captions(qapp):
    scene, _ = _scene()
    _number(scene, 2, caption="第二步", pos=(60, 20))
    _number(scene, 1, caption="第一步", pos=(20, 20))
    _number(scene, 3, caption="", pos=(100, 20))

    assert _pairs(collect_entries(scene.items())) == [(1, "第一步"), (2, "第二步")]


def test_caption_command_is_undoable(qapp):
    scene, _ = _scene()
    item = _number(scene, 1, caption="")

    scene.undo_stack.push(NumberCaptionCommand(item, "", "第一步说明"))
    assert item.caption == "第一步说明"

    scene.undo_stack.undo()
    assert item.caption == ""

    scene.undo_stack.redo()
    assert item.caption == "第一步说明"


def test_delete_undo_and_renumber_keep_caption_with_its_number(qapp):
    scene, _ = _scene()
    _number(scene, 1, caption="第一步")
    second = _number(scene, 2, caption="第二步", pos=(60, 20))
    _number(scene, 3, caption="第三步", pos=(100, 20))

    scene.undo_stack.push(RemoveItemCommand(scene, second))
    assert _pairs(collect_entries(scene.items())) == [(1, "第一步"), (3, "第三步")]
    scene.undo_stack.undo()
    assert _pairs(collect_entries(scene.items())) == [(1, "第一步"), (2, "第二步"), (3, "第三步")]

    # 删除 2 并按当前数字重排：3 变成 2，说明必须跟着它自己的图元一起走
    scene.undo_stack.push(RemoveNumberAndRenumberCommand(scene, second))
    assert _pairs(collect_entries(scene.items())) == [(1, "第一步"), (2, "第三步")]
    scene.undo_stack.undo()
    assert _pairs(collect_entries(scene.items())) == [(1, "第一步"), (2, "第二步"), (3, "第三步")]


def test_project_roundtrip_keeps_caption_and_legacy_records_still_load(qapp):
    scene, _ = _scene()
    item = _number(scene, 3, caption="导入图片并核对尺寸")
    record = dump_item(item, Assets(), QPointF(0, 0))
    assert record["data"]["caption"] == "导入图片并核对尺寸"

    restored = load_item(record, {})
    assert restored.caption == "导入图片并核对尺寸"

    legacy = dict(record)
    legacy["data"] = {k: v for k, v in record["data"].items() if k != "caption"}
    legacy_item = load_item(legacy, {})
    assert legacy_item.caption == "", "旧工程没有 caption 字段也必须能打开"


def test_pin_clone_keeps_caption(qapp, qtbot):
    from pin.pin_canvas import PinCanvas

    scene, source = _scene()
    _number(scene, 1, caption="钉图里的说明")
    items = scene.get_drawing_items_in_rect(QRectF(0, 0, SIZE, SIZE))

    parent = QWidget()
    qtbot.addWidget(parent)
    parent.toolbar = None
    parent.view = None
    parent._is_editing = False
    pin = PinCanvas(parent, QSize(SIZE, SIZE), source.copy())
    try:
        pin.initialize_from_items(items, QPoint(0, 0))
        clones = [item for item in pin.scene.items() if isinstance(item, NumberItem)]
        assert len(clones) == 1
        assert clones[0].caption == "钉图里的说明"
    finally:
        pin.cleanup()


def test_wrap_keeps_every_character_and_honours_newlines(qapp):
    from PySide6.QtGui import QFont, QFontMetrics

    metrics = QFontMetrics(QFont())
    text = "第一步：打开设置窗口，确认是 Mixed English words 与中文混排\n第二步：检查编号说明不会截断"
    lines = wrap_caption(text, metrics, 120)

    assert len(lines) > 2
    assert "".join(line.replace(" ", "") for line in lines).startswith("第一步：打开设置窗口")

    joined = "".join(line for line in lines)
    normalized_source = text.replace("\n", "").replace(" ", "")
    assert joined.replace(" ", "") == normalized_source, "折行不能丢字"


def test_render_bottom_and_side_place_legend_without_losing_the_image(qapp):
    image = QImage(60, 40, QImage.Format.Format_ARGB32)
    image.fill(QColor("#123456"))
    entries = [LegendEntry(1, "很长的说明文字，需要折行显示并且不能截断。" * 2)]

    bottom = render(image, entries, LegendOptions(placement=PLACEMENT_BOTTOM))
    assert bottom.width() == image.width()
    assert bottom.height() > image.height()
    assert bottom.pixelColor(2, 2) == image.pixelColor(2, 2)

    side = render(image, entries, LegendOptions(placement=PLACEMENT_SIDE))
    assert side.width() > image.width()
    assert side.height() == image.height()
    assert side.pixelColor(2, 2) == image.pixelColor(2, 2)


def test_off_or_no_entries_returns_the_original_image(qapp):
    image = QImage(32, 24, QImage.Format.Format_ARGB32)
    image.fill(QColor("white"))
    entries = [LegendEntry(1, "说明")]
    assert render(image, entries, LegendOptions(placement=PLACEMENT_OFF)) is image
    assert render(image, [], LegendOptions(placement=PLACEMENT_BOTTOM)) is image
    assert normalize_placement("nonsense") == PLACEMENT_OFF


def test_export_service_appends_legend_only_when_enabled(qapp):
    from settings import get_tool_settings_manager

    manager = get_tool_settings_manager()
    before = manager.get_app_setting("number_legend_placement", "off")
    scene, _ = _scene()
    _number(scene, 1, caption="导出时的说明")
    service = ExportService(scene)
    rect = QRectF(0, 0, SIZE, SIZE)
    try:
        manager.set_app_setting("number_legend_placement", PLACEMENT_OFF)
        plain = service.export(rect)
        assert service.export_with_legend(rect).size() == plain.size(), "关闭时不能改变成图"

        manager.set_app_setting("number_legend_placement", PLACEMENT_BOTTOM)
        with_legend = service.export_with_legend(rect)
        assert with_legend.width() == plain.width()
        assert with_legend.height() > plain.height()
        assert with_legend.pixelColor(2, 2) == plain.pixelColor(2, 2), "原图内容不能被说明覆盖"
    finally:
        manager.set_app_setting("number_legend_placement", before)
def test_number_tool_applies_caption_to_selected_item_with_undo(qapp):
    from canvas.smart_edit_controller import SmartEditController
    from tools.number import NumberTool

    scene, _ = _scene()
    item = _number(scene, 1)

    class _View:
        pass

    view = _View()
    view.smart_edit_controller = SmartEditController(scene)
    view.smart_edit_controller.selected_item = item

    assert NumberTool.apply_caption_change("第一步说明", view, scene.undo_stack) is True
    assert item.caption == "第一步说明"
    scene.undo_stack.undo()
    assert item.caption == ""

    # 没有选中序号时输入不生效，也不会占撤销
    view.smart_edit_controller.selected_item = None
    count = scene.undo_stack.count()
    assert NumberTool.apply_caption_change("散落说明", view, scene.undo_stack) is False
    assert scene.undo_stack.count() == count


def test_legend_placement_persists_from_number_panel(qapp):
    from settings import get_tool_settings_manager
    from ui.toolbar import Toolbar

    manager = get_tool_settings_manager()
    before = manager.get_app_setting("number_legend_placement", "off")
    toolbar = Toolbar()
    try:
        panel = toolbar.number_panel
        assert hasattr(panel, "caption_edit") and hasattr(panel, "legend_combo")
        panel.legend_combo.setCurrentIndex(panel.legend_combo.findData(PLACEMENT_BOTTOM))
        assert manager.get_app_setting("number_legend_placement", "off") == PLACEMENT_BOTTOM
        panel.refresh_legend_placement()
        assert panel.legend_combo.currentData() == PLACEMENT_BOTTOM
    finally:
        manager.set_app_setting("number_legend_placement", before)
        toolbar.deleteLater()


def test_selecting_a_number_fills_its_caption_into_the_panel(qapp):
    from canvas.view import CanvasView
    from ui.toolbar import Toolbar

    scene, _ = _scene()
    view = CanvasView(scene)
    toolbar = Toolbar()
    try:
        item = _number(scene, 1, caption="选中后的说明")
        view._show_panel_for_selection(item, toolbar)
        assert toolbar.number_panel.caption_edit.text() == "选中后的说明"

        other = _number(scene, 2, caption="", pos=(60, 20))
        view._show_panel_for_selection(other, toolbar)
        assert toolbar.number_panel.caption_edit.text() == "", "换选没有说明的编号要清空"
    finally:
        toolbar.deleteLater()
        view.close()
        scene.deleteLater()
