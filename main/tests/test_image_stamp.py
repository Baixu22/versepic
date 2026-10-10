# -*- coding: utf-8 -*-
"""TF-0037 插图：位图插入、等比缩放、层叠、工程与钉图继承、非法图安全处理。"""
import pytest
from PySide6.QtCore import QPoint, QPointF, QRectF, QSize
from PySide6.QtGui import QColor, QFont, QImage, QPen
from PySide6.QtWidgets import QWidget

from canvas.items import ArrowItem, ImageStampItem, TextItem
from canvas.scene import CanvasScene
from canvas.undo import RemoveItemCommand
from core.editable_project import Assets, dump_item, load_item
from core.export import ExportService

SIZE = 200


def _scene():
    image = QImage(SIZE, SIZE, QImage.Format.Format_ARGB32)
    image.fill(QColor("white"))
    scene = CanvasScene(image, QRectF(0, 0, SIZE, SIZE), enable_mosaic=True)
    scene.selection_model.initialize_confirmed_rect(QRectF(0, 0, SIZE, SIZE))
    return scene, image


def _stamp_image(width=40, height=20):
    """一半透明、一半纯红的小图，用来验证透明合成。"""
    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(QColor(0, 0, 0, 0))
    for y in range(height):
        for x in range(width):
            if x >= width // 2:
                image.setPixelColor(x, y, QColor(255, 0, 0, 255))
    return image


def _stamps(scene):
    return [item for item in scene.items() if isinstance(item, ImageStampItem)]


def test_insert_centers_stamp_and_is_undoable(qapp):
    scene, _ = _scene()
    before = scene.undo_stack.count()

    item = scene.add_image_stamp(_stamp_image())

    assert _stamps(scene) == [item]
    assert scene.undo_stack.count() == before + 1
    assert item.rect().width() <= SIZE and item.rect().height() <= SIZE
    # 默认落在选区中心
    assert abs(item.rect().center().x() - SIZE / 2) < 1.5
    assert abs(item.rect().center().y() - SIZE / 2) < 1.5

    scene.undo_stack.undo()
    assert _stamps(scene) == []
    scene.undo_stack.redo()
    assert len(_stamps(scene)) == 1


def test_resize_keeps_source_aspect_ratio(qapp):
    scene, _ = _scene()
    item = scene.add_image_stamp(_stamp_image(40, 20))

    item.setRect(QRectF(0, 0, 80, 10))

    assert item.rect().width() == pytest.approx(80.0)
    assert item.rect().height() == pytest.approx(40.0), "高度必须跟着宽高比走"
    item.scale_stroke_width(0.5)
    assert item.rect().width() == pytest.approx(40.0)
    assert item.rect().height() == pytest.approx(20.0)


def test_layer_order_is_above_annotations_below_text(qapp):
    scene, _ = _scene()
    stamp = scene.add_image_stamp(_stamp_image())
    arrow = ArrowItem(QPointF(4, 4), QPointF(40, 40), QPen(QColor("red"), 2))
    text = TextItem("说明", QPointF(10, 10), QFont("Arial", 10), QColor("black"))
    scene.addItem(arrow)
    scene.addItem(text)

    assert arrow.zValue() < stamp.zValue() < text.zValue()


def test_transparent_pixels_compose_on_export(qapp):
    scene, _ = _scene()
    item = scene.add_image_stamp(_stamp_image(40, 20))
    item.setRect(QRectF(20, 20, 40, 20))

    exported = ExportService(scene).export(QRectF(0, 0, SIZE, SIZE))

    # 左半透明 → 露出白色底图；右半纯红 → 红色进成图
    assert exported.pixelColor(25, 30).getRgb()[:3] == (255, 255, 255)
    assert exported.pixelColor(55, 30).getRgb()[:3] == (255, 0, 0)


def test_invalid_and_oversized_images_are_rejected(qapp):
    with pytest.raises(ValueError):
        ImageStampItem.validate_image(QImage())

    wide = QImage(ImageStampItem.MAX_EDGE + 1, 1, QImage.Format.Format_ARGB32)
    with pytest.raises(ValueError):
        ImageStampItem.validate_image(wide)


def test_load_file_rejects_missing_and_broken_files(qapp, tmp_path):
    with pytest.raises(ValueError):
        ImageStampItem.load_file(tmp_path / "missing.png")

    broken = tmp_path / "broken.png"
    broken.write_bytes(b"not an image")
    with pytest.raises(ValueError):
        ImageStampItem.load_file(broken)


def test_project_roundtrip_keeps_pixels_and_rect(qapp):
    scene, _ = _scene()
    item = scene.add_image_stamp(_stamp_image(40, 20), rect=QRectF(12, 18, 40, 20))

    record = dump_item(item, Assets(), QPointF(0, 0))
    assert record["kind"] == "ImageStampItem"

    images = {record["data"]["image"]: item.image()}
    restored = load_item(record, images)
    assert restored.rect() == item.rect()
    assert restored.image().size() == item.image().size()
    assert restored.image().pixelColor(39, 0).getRgb()[:3] == (255, 0, 0)


def test_delete_and_undo_round_trip(qapp):
    scene, _ = _scene()
    item = scene.add_image_stamp(_stamp_image())

    scene.undo_stack.push(RemoveItemCommand(scene, item))
    assert _stamps(scene) == []
    scene.undo_stack.undo()
    assert len(_stamps(scene)) == 1


def test_pin_inherits_stamp_pixels(qapp, qtbot):
    from pin.pin_canvas import PinCanvas

    scene, source = _scene()
    scene.add_image_stamp(_stamp_image(40, 20), rect=QRectF(20, 20, 40, 20))
    items = scene.get_drawing_items_in_rect(QRectF(0, 0, SIZE, SIZE))

    parent = QWidget()
    qtbot.addWidget(parent)
    parent.toolbar = None
    parent.view = None
    parent._is_editing = False
    pin = PinCanvas(parent, QSize(SIZE, SIZE), source.copy())
    try:
        pin.initialize_from_items(items, QPoint(0, 0))
        clones = [it for it in pin.scene.items() if isinstance(it, ImageStampItem)]
        assert len(clones) == 1
        assert clones[0].rect() == QRectF(20, 20, 40, 20)
        assert clones[0].image().pixelColor(39, 0).getRgb()[:3] == (255, 0, 0)
    finally:
        pin.cleanup()
