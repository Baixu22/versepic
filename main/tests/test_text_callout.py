# -*- coding: utf-8 -*-
"""TF-0035 组合标注：箭头 + 文字气泡的创建、联动、撤销、导出与钉图继承。

新建的气泡是 provisional 文字：真正入栈发生在失焦那一刻，而 QGraphicsScene 的
焦点事件只有在 scene 活跃（有 show()/activateWindow() 过的 CanvasView）时才真的
触发——和 test_text_item_undo_safe_clear.py 里的做法保持一致。
"""
import pytest
from PySide6.QtCore import QPoint, QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPen
from PySide6.QtWidgets import QWidget

from canvas.items import ArrowItem, TextItem
from canvas.items.callout_link import (
    ROLE_ARROW,
    ROLE_BUBBLE,
    bubble_scene_rect,
    callout_target,
    is_callout_part,
    partner_of,
    role_of,
)
from canvas.scene import CanvasScene
from canvas.undo import BatchRemoveCommand, RemoveItemCommand
from canvas.view import CanvasView
from core.export import ExportService

SIZE = 48


def _unique_image():
    image = QImage(SIZE, SIZE, QImage.Format.Format_ARGB32)
    for y in range(SIZE):
        for x in range(SIZE):
            image.setPixelColor(x, y, QColor(x * 5 % 256, y * 7 % 256, (x + y) * 3 % 256))
    return image


@pytest.fixture
def canvas(qapp):
    """活跃的截图场景；focus 相关断言依赖它是 isActive()。"""
    image = _unique_image()
    scene = CanvasScene(image, QRectF(0, 0, SIZE, SIZE), enable_mosaic=True)
    scene.selection_model.initialize_confirmed_rect(QRectF(0, 0, SIZE, SIZE))
    view = CanvasView(scene)
    view.show()
    view.activateWindow()
    qapp.processEvents()
    assert scene.isActive(), "scene 没有真正激活，失焦提交会静默失效"
    try:
        yield scene, image
    finally:
        view.close()
        scene.deleteLater()
        qapp.processEvents()


def _halves(scene):
    arrows = [item for item in scene.items() if isinstance(item, ArrowItem)]
    bubbles = [item for item in scene.items() if isinstance(item, TextItem)]
    return arrows, bubbles


def _draw(scene, qapp, start=(6, 6), end=(30, 26), text="看这里"):
    """走真实工具事件路径画一条组合标注，并提交文字。"""
    scene.activate_tool("callout")
    controller = scene.tool_controller
    controller.on_press(QPointF(*start), Qt.MouseButton.LeftButton)
    controller.on_move(QPointF(*end))
    controller.on_release(QPointF(*end))
    arrows, bubbles = _halves(scene)
    assert len(arrows) == 1 and len(bubbles) == 1
    arrow, bubble = arrows[0], bubbles[0]
    if text is not None:
        bubble.setPlainText(text)
    bubble.clearFocus()
    qapp.processEvents()
    return arrow, bubble


def _edge_distance(point: QPointF, rect: QRectF) -> float:
    """点到矩形边界的距离；框内时算最近一条边。"""
    dx = max(rect.left() - point.x(), 0.0, point.x() - rect.right())
    dy = max(rect.top() - point.y(), 0.0, point.y() - rect.bottom())
    if dx or dy:
        return (dx * dx + dy * dy) ** 0.5
    return min(
        point.x() - rect.left(),
        rect.right() - point.x(),
        point.y() - rect.top(),
        rect.bottom() - point.y(),
    )


def _export(scene):
    """逐像素取 RGB：两张图的内部缓冲格式/步长可能不同，直接比 constBits 会误报。"""
    image = ExportService(scene).export(QRectF(0, 0, SIZE, SIZE))
    return bytes(
        channel
        for y in range(image.height())
        for x in range(image.width())
        for channel in image.pixelColor(x, y).getRgb()[:3]
    )


def test_drag_creates_linked_pair_and_commits_as_one_step(qapp, canvas):
    scene, _ = canvas
    before = scene.undo_stack.count()
    arrow, bubble = _draw(scene, qapp)

    assert partner_of(arrow) is bubble
    assert partner_of(bubble) is arrow
    assert role_of(arrow) == ROLE_ARROW
    assert role_of(bubble) == ROLE_BUBBLE
    assert is_callout_part(arrow) and is_callout_part(bubble)
    assert arrow.end_pos == QPointF(30, 26)
    assert callout_target(arrow) == QPointF(30, 26)
    assert scene.undo_stack.count() == before + 1, "箭头和气泡必须只占一步撤销"

    scene.undo_stack.undo()
    assert _halves(scene) == ([], [])
    scene.undo_stack.redo()
    arrows, bubbles = _halves(scene)
    assert len(arrows) == 1 and len(bubbles) == 1


def test_empty_callout_is_discarded_without_undo_entry(qapp, canvas):
    scene, _ = canvas
    before = scene.undo_stack.count()
    _draw(scene, qapp, text=None)

    assert _halves(scene) == ([], []), "没写字的组合标注不该留下半条箭头"
    assert scene.undo_stack.count() == before, "空标注不该占用一次撤销"


def test_tiny_drag_does_not_create_callout(qapp, canvas):
    scene, _ = canvas
    before = scene.undo_stack.count()
    scene.activate_tool("callout")
    controller = scene.tool_controller
    controller.on_press(QPointF(6, 6), Qt.MouseButton.LeftButton)
    controller.on_move(QPointF(9, 9))
    controller.on_release(QPointF(9, 9))

    assert _halves(scene) == ([], [])
    assert scene.undo_stack.count() == before


def test_moving_bubble_keeps_tip_and_rehangs_arrow(qapp, canvas):
    scene, _ = canvas
    arrow, bubble = _draw(scene, qapp)
    tip = QPointF(arrow.end_pos)
    old_start = QPointF(arrow.start_pos)

    bubble.setPos(bubble.pos() + QPointF(0, 14))

    assert arrow.end_pos == tip, "移动气泡不能把指向挪走"
    assert arrow.start_pos != old_start, "箭尾应跟着气泡重新落点"
    assert _edge_distance(arrow.start_pos, bubble_scene_rect(bubble)) < 1.5


def test_moving_arrow_body_then_bubble_keeps_current_tip(qapp, canvas):
    scene, _ = canvas
    arrow, bubble = _draw(scene, qapp)

    arrow.setPos(arrow.pos() + QPointF(6, -4))
    moved_tip = arrow.mapToScene(QPointF(arrow.end_pos))
    bubble.setPos(bubble.pos() + QPointF(0, 10))

    assert arrow.mapToScene(QPointF(arrow.end_pos)) == moved_tip, "尖端不能回跳到旧目标"
    assert _edge_distance(arrow.mapToScene(QPointF(arrow.start_pos)), bubble_scene_rect(bubble)) < 1.5


def test_longer_text_keeps_arrow_on_bubble_edge(qapp, canvas):
    scene, _ = canvas
    arrow, bubble = _draw(scene, qapp, text="短")
    tip = QPointF(arrow.end_pos)

    bubble.setPlainText("这是一段明显更长的说明文字，用来把气泡撑宽，箭头必须还在边上。")

    assert arrow.end_pos == tip
    assert _edge_distance(arrow.start_pos, bubble_scene_rect(bubble)) < 1.5


def test_delete_either_part_removes_both_and_undo_restores_pair(qapp, canvas):
    scene, _ = canvas
    arrow, bubble = _draw(scene, qapp)

    scene.undo_stack.push(RemoveItemCommand(scene, arrow))
    assert _halves(scene) == ([], []), "删掉箭头必须连气泡一起走"

    scene.undo_stack.undo()
    arrows, bubbles = _halves(scene)
    assert len(arrows) == 1 and len(bubbles) == 1
    assert partner_of(arrows[0]) is bubbles[0]

    scene.undo_stack.push(RemoveItemCommand(scene, bubble))
    assert _halves(scene) == ([], []), "删掉气泡同样要连箭头一起走"


def test_batch_remove_expands_to_partner(qapp, canvas):
    scene, _ = canvas
    _, bubble = _draw(scene, qapp)

    scene.undo_stack.push(BatchRemoveCommand(scene, [bubble]))
    assert _halves(scene) == ([], [])


def test_standalone_arrow_and_text_are_not_grouped(qapp, canvas):
    scene, _ = canvas
    arrow = ArrowItem(QPointF(4, 4), QPointF(20, 20), QPen(QColor("red"), 2))
    text = TextItem("独立文字", QPointF(4, 26), QFont("Arial", 9), QColor("black"))
    scene.addItem(arrow)
    scene.addItem(text)

    scene.undo_stack.push(RemoveItemCommand(scene, arrow))

    assert arrow.scene() is None
    assert text.scene() is scene, "普通文字不能被普通箭头的删除带走"


def test_callout_tool_selects_both_halves_and_keeps_native_tools(qapp, canvas):
    scene, _ = canvas
    arrow, bubble = _draw(scene, qapp)
    from canvas.smart_edit_controller import SmartEditController

    editor = SmartEditController(scene)

    editor.current_tool_id = "callout"
    assert editor.can_select_item(arrow, 0) is True
    assert editor.can_select_item(bubble, 0) is True

    editor.current_tool_id = "arrow"
    assert editor.can_select_item(arrow, 0) is True
    editor.current_tool_id = "text"
    assert editor.can_select_item(bubble, 0) is True

    editor.current_tool_id = "rect"
    assert editor.can_select_item(arrow, 0) is False


def test_callout_is_exported_and_undo_restores_plain_render(qapp, canvas):
    scene, _ = canvas
    base = _export(scene)

    _draw(scene, qapp)
    with_callout = _export(scene)
    assert with_callout != base, "组合标注必须真的画进导出图"

    scene.undo_stack.undo()
    assert _export(scene) == base, "撤销后应回到没有标注的原始渲染"


def test_pin_inherits_callout_link(qapp, qtbot, canvas):
    from pin.pin_canvas import PinCanvas

    scene, source = canvas
    _draw(scene, qapp)
    items = scene.get_drawing_items_in_rect(QRectF(0, 0, SIZE, SIZE))

    parent = QWidget()
    qtbot.addWidget(parent)
    parent.toolbar = None
    parent.view = None
    parent._is_editing = False
    pin = PinCanvas(parent, QSize(SIZE, SIZE), source.copy())
    try:
        pin.initialize_from_items(items, QPoint(0, 0))
        clones = [item for item in pin.scene.items() if isinstance(item, (ArrowItem, TextItem))]
        assert len(clones) == 2
        assert all(is_callout_part(item) for item in clones), "钉图克隆后组合标注仍应保持关联"
    finally:
        pin.cleanup()


def test_toolbar_and_layout_expose_callout(qapp):
    from ui.toolbar import Toolbar
    from ui.toolbar_layout import MORE, default_layout

    layout = dict(default_layout())
    assert layout["callout"] == MORE

    toolbar = Toolbar()
    try:
        assert "callout" in toolbar._folded_keys
        toolbar.select_tool("callout")
        assert toolbar.current_tool == "callout"
        assert toolbar.callout_btn.isChecked()
    finally:
        toolbar.deleteLater()
