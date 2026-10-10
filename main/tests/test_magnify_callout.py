# -*- coding: utf-8 -*-
"""Magnify callout: background pixels only, no recursive UI sampling."""
import pytest
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPen
from PySide6.QtWidgets import QWidget

from canvas.items import MagnifyCalloutItem, RectItem
from canvas.scene import CanvasScene
from canvas.undo import EditItemCommand
from core.editable_project import ProjectError, dump_item, load_item
from core.export import ExportService
from pin.pin_canvas import PinCanvas
from settings import get_tool_settings_manager

SIZE = 32


@pytest.fixture(autouse=True)
def magnify_settings():
    manager = get_tool_settings_manager()
    before = manager.get_tool_settings("magnify").to_dict()
    manager.update_settings("magnify", color="#FF0000", stroke_width=1, opacity=1.0)
    yield
    manager.update_settings("magnify", **before)


def _unique_image():
    image = QImage(SIZE, SIZE, QImage.Format.Format_ARGB32)
    for y in range(SIZE):
        for x in range(SIZE):
            image.setPixelColor(x, y, QColor(x * 7 % 256, y * 11 % 256, (x + y) * 3 % 256))
    return image


def _scene(image=None):
    image = image or _unique_image()
    scene = CanvasScene(image, QRectF(0, 0, SIZE, SIZE), enable_mosaic=True)
    scene.selection_model.initialize_confirmed_rect(QRectF(0, 0, SIZE, SIZE))
    return scene, image


def _draw(scene, start, end):
    scene.activate_tool("magnify")
    controller = scene.tool_controller
    controller.on_press(QPointF(*start), Qt.MouseButton.LeftButton)
    controller.on_move(QPointF(*end))
    controller.on_release(QPointF(*end))


def _items(scene):
    return [item for item in scene.items() if isinstance(item, MagnifyCalloutItem)]


def _export(scene, rect=QRectF(0, 0, SIZE, SIZE)):
    return ExportService(scene).export(rect)


def _color(image, x, y):
    return image.pixelColor(int(x), int(y))


def test_tiny_drags_are_dropped_and_completed_draw_is_undoable(qapp):
    scene, _ = _scene()
    _draw(scene, (4, 4), (8, 8))
    assert _items(scene) == []
    _draw(scene, (4, 4), (12, 12))
    [item] = _items(scene)
    assert item.source_rect() == QRectF(4, 4, 8, 8)
    assert item.zoom() == pytest.approx(2.0)
    scene.undo_stack.undo()
    assert _items(scene) == []


def test_callout_pixels_match_nearest_neighbor_source(qapp):
    scene, source = _scene()
    _draw(scene, (4, 4), (12, 12))
    [item] = _items(scene)
    exported = _export(scene)
    sx, sy = 8, 8
    expected = source.pixelColor(sx, sy)
    local_x = (sx - item.source_rect().x()) * item.zoom()
    local_y = (sy - item.source_rect().y()) * item.zoom()
    cx = item.pos().x() + local_x + item.zoom() / 2
    cy = item.pos().y() + local_y + item.zoom() / 2
    actual = _color(exported, cx, cy)
    assert actual.getRgb()[:3] == expected.getRgb()[:3], (item.pos(), item.rect(), item.source_rect(), actual.getRgb(), expected.getRgb())


def test_moving_the_callout_does_not_shift_sampled_pixels(qapp):
    scene, source = _scene()
    _draw(scene, (4, 4), (12, 12))
    [item] = _items(scene)
    before = item._sample()
    item.setPos(item.pos() + QPointF(-4, 2))
    after = item._sample()
    assert bytes(before.constBits()) == bytes(after.constBits())
    assert item.source_rect() == QRectF(4, 4, 8, 8)
    exported = _export(scene)
    expected = source.pixelColor(8, 8)
    local_x = (8 - item.source_rect().x()) * item.zoom()
    local_y = (8 - item.source_rect().y()) * item.zoom()
    cx = item.pos().x() + local_x + item.zoom() / 2
    cy = item.pos().y() + local_y + item.zoom() / 2
    assert _color(exported, cx, cy).getRgb()[:3] == expected.getRgb()[:3]


def test_overlapping_callout_does_not_sample_itself_or_handles(qapp):
    scene, source = _scene()
    _draw(scene, (4, 4), (12, 12))
    [item] = _items(scene)
    item.setPos(QPointF(4, 4))  # callout covers the source
    sample = item._sample()
    assert sample.pixelColor(8, 8).getRgb()[:3] == source.pixelColor(8, 8).getRgb()[:3]
    overlay = RectItem(QRectF(4, 4, 8, 8), QPen(QColor("white"), 8))
    overlay.setZValue(50)
    scene.addItem(overlay)
    still = item._sample()
    assert still.pixelColor(8, 8).getRgb()[:3] == source.pixelColor(8, 8).getRgb()[:3]


def test_rect_tool_does_not_take_the_callout(qapp):
    scene, _ = _scene()
    _draw(scene, (4, 4), (12, 12))
    [item] = _items(scene)
    from canvas.smart_edit_controller import SmartEditController
    editor = SmartEditController(scene)
    editor.current_tool_id = "rect"
    assert editor.get_item_tool_id(item) == "magnify"
    assert editor.can_select_item(item, 0) is False
    editor.current_tool_id = "magnify"
    assert editor.can_select_item(item, 0) is True


def test_eraser_removes_callout(qapp):
    scene, _ = _scene()
    _draw(scene, (4, 4), (12, 12))
    [item] = _items(scene)
    tool = scene.tool_controller.tools["eraser"]
    tool._try_erase_item(item)
    assert _items(scene) == []


def test_pin_clone_offsets_source_and_keeps_pixels(qapp, qtbot):
    from PySide6.QtCore import QPoint, QSize
    scene, source = _scene()
    _draw(scene, (4, 4), (12, 12))
    items = scene.get_drawing_items_in_rect(QRectF(0, 0, SIZE, SIZE))
    crop = source.copy(2, 2, 30, 30)
    parent = QWidget(); qtbot.addWidget(parent)
    parent.toolbar = None; parent.view = None; parent._is_editing = False
    pin = PinCanvas(parent, QSize(30, 30), crop)
    try:
        pin.initialize_from_items(items, QPoint(2, 2))
        [cloned] = [item for item in pin.scene.items() if isinstance(item, MagnifyCalloutItem)]
        assert cloned.source_rect() == QRectF(2, 2, 8, 8)
        sample = cloned._sample()
        assert sample.pixelColor(8, 8).getRgb()[:3] == source.pixelColor(8, 8).getRgb()[:3]
    finally:
        pin.cleanup()


def test_project_roundtrip_and_unknown_kind_message(qapp, tmp_path):
    scene, _ = _scene()
    _draw(scene, (4, 4), (12, 12))
    [item] = _items(scene)
    from core.editable_project import Assets
    record = dump_item(item, Assets(), QPointF(0, 0))
    assert record["kind"] == "MagnifyCalloutItem"
    restored = load_item(record, {})
    assert restored.source_rect() == item.source_rect()
    assert restored.rect() == item.rect()
    with pytest.raises(ProjectError, match="Unsupported annotation type or newer project version"):
        load_item({"kind": "FutureCalloutItem", "common": {"pos": [0, 0], "origin": [0, 0],
                   "transform": [1, 0, 0, 1, 0, 0], "rotation": 0, "scale": 1, "z": 0,
                   "opacity": 1, "visible": True}, "data": {}}, {})


def test_resize_keeps_uniform_zoom_and_undo_restores_source(qapp):
    scene, _ = _scene()
    _draw(scene, (4, 4), (12, 12))
    [item] = _items(scene)
    old = {"rect": item.rect(), "source_rect": item.source_rect(), "pos": item.pos()}
    item.setRect(QRectF(0, 0, 24, 10))
    assert item.zoom() == pytest.approx(3.0)
    item.set_source_rect(QRectF(2, 2, 8, 8))
    new = {"rect": item.rect(), "source_rect": item.source_rect(), "pos": item.pos()}
    scene.undo_stack.push(EditItemCommand(item, old, new))
    scene.undo_stack.undo()
    assert item.source_rect() == QRectF(4, 4, 8, 8)
    assert item.zoom() == pytest.approx(2.0)


def test_default_toolbar_folds_magnify(qapp):
    from ui.toolbar import Toolbar
    toolbar = Toolbar()
    try:
        assert "magnify" in toolbar._folded_keys
        toolbar.select_tool("magnify")
        assert toolbar.current_tool == "magnify"
        assert toolbar.magnify_btn.isChecked()
    finally:
        toolbar.deleteLater()


@pytest.mark.parametrize("language", ["en", "zh", "ja", "ko"])
def test_compiled_magnify_labels(language):
    from pathlib import Path
    from PySide6.QtCore import QTranslator
    translator = QTranslator()
    main = Path(__file__).resolve().parents[1]
    assert translator.load(str(main / "translations" / f"app_{language}.qm"))
    assert translator.translate("Toolbar", "Magnify region")
    assert translator.translate("ToolbarLayoutDialog", "Magnify region")
