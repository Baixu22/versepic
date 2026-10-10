"""组合标注（TF-0035）：箭头 + 文字气泡的关联关系。

一个组合标注由两个已有图元组成：文字图元当气泡，箭头图元指向被标注的位置。
这里只维护两者之间的关联和几何同步，不新增图元类型，也不改导出/工程格式——
两个图元本来就能被截图渲染、钉图克隆和工程编解码处理。

关联存成图元上的普通属性，不建场景级注册表：

- 图元自己带着关联，移动/复制/删除时关系跟着图元走；
- 关系是"气泡边缘 -> 目标点"的软连接：移动或放大气泡会重算箭尾，
  箭头尖端始终留在用户当初指的那个点上；
- 工程重新打开后关系丢失也不画错——箭头和气泡各画各的，只是不再联动。
  工程编解码会在两端都在时按保存的目标点重新连上。
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtWidgets import QGraphicsItem

PARTNER_ATTR = "_callout_partner"
TARGET_ATTR = "_callout_target"
ROLE_ATTR = "_callout_role"

ROLE_ARROW = "arrow"
ROLE_BUBBLE = "bubble"


def partner_of(item):
    """返回与 item 关联的另一半；不是组合标注的一部分时返回 None。"""
    if item is None:
        return None
    return getattr(item, PARTNER_ATTR, None)


def is_callout_part(item) -> bool:
    """该图元是否属于一个组合标注。"""
    return partner_of(item) is not None


def role_of(item):
    return getattr(item, ROLE_ATTR, None) if item is not None else None


def expand_with_partners(items) -> list:
    """把图元列表展开成"含各自组合标注另一半"的列表，保持顺序并去重。"""
    expanded: list = []
    seen: set = set()
    for item in items or ():
        for node in (item, partner_of(item)):
            if node is None:
                continue
            key = id(node)
            if key in seen:
                continue
            seen.add(key)
            expanded.append(node)
    return expanded


def link_callout(arrow, bubble, target=None) -> None:
    """把箭头和文字气泡连成一个组合标注，target 是箭头尖端要指向的点。"""
    if arrow is None or bubble is None or arrow is bubble:
        return
    point = QPointF(target) if target is not None else QPointF(arrow.end_pos)
    setattr(arrow, PARTNER_ATTR, bubble)
    setattr(arrow, ROLE_ATTR, ROLE_ARROW)
    setattr(bubble, PARTNER_ATTR, arrow)
    setattr(bubble, ROLE_ATTR, ROLE_BUBBLE)
    setattr(bubble, TARGET_ATTR, point)
    # 位置变化的 itemChange 通知需要这个标志位，否则拖动气泡不会回调
    try:
        bubble.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
    except Exception:
        pass
    _watch_bubble_contents(bubble)
    sync_arrow_to_bubble(bubble)


def unlink(item) -> None:
    """拆开关联，两端都恢复成普通图元。"""
    partner = partner_of(item)
    for node in (item, partner):
        if node is None:
            continue
        for attr in (PARTNER_ATTR, TARGET_ATTR, ROLE_ATTR):
            try:
                delattr(node, attr)
            except AttributeError:
                pass


def callout_target(item):
    """组合标注指向的场景坐标；两端谁拿着目标点都能查。"""
    if item is None:
        return None
    target = getattr(item, TARGET_ATTR, None)
    if target is None:
        target = getattr(partner_of(item), TARGET_ATTR, None)
    return QPointF(target) if target is not None else None


def set_callout_target(item, target) -> None:
    """更新组合标注的目标点（拖动箭头尖端后调用）。"""
    point = QPointF(target)
    setattr(item, TARGET_ATTR, point)
    partner = partner_of(item)
    if partner is not None:
        setattr(partner, TARGET_ATTR, QPointF(point))


def bubble_scene_rect(bubble) -> QRectF:
    """气泡在场景坐标下的矩形（用交互框，含内边距和光标活动区）。"""
    rect_fn = getattr(bubble, "interaction_rect", None)
    local = rect_fn() if callable(rect_fn) else bubble.boundingRect()
    return bubble.mapRectToScene(local)


def anchor_on_rect(rect: QRectF, tip: QPointF) -> QPointF:
    """从气泡中心朝 tip 的方向与矩形边界的交点；tip 在框内时落在该方向的远侧边上。"""
    center = rect.center()
    delta = tip - center
    if delta.x() == 0 and delta.y() == 0:
        return QPointF(center)
    half_w = rect.width() / 2.0
    half_h = rect.height() / 2.0
    scale_x = half_w / abs(delta.x()) if delta.x() else float("inf")
    scale_y = half_h / abs(delta.y()) if delta.y() else float("inf")
    scale = min(scale_x, scale_y)
    if scale == float("inf"):
        return QPointF(center)
    return center + delta * scale


def sync_arrow_to_bubble(bubble) -> bool:
    """按当前气泡矩形重算箭尾，尖端保持不动；成功返回 True。

    尖端以箭头当前的 end 为准：用户拖动箭头本体以后，那才是它真正指向的
    位置，不能按旧的目标点把尖端拉回去。箭头不在场景里（刚建好/工程读回）
    时退回记录的目标点。
    """
    arrow = partner_of(bubble)
    if arrow is None:
        return False
    if arrow.scene() is not None:
        tip_scene = arrow.mapToScene(QPointF(arrow.end_pos))
    else:
        tip_scene = callout_target(bubble)
    if tip_scene is None:
        return False
    anchor_scene = anchor_on_rect(bubble_scene_rect(bubble), tip_scene)
    if arrow.scene() is not None and bubble.scene() is not None:
        anchor = arrow.mapFromScene(anchor_scene)
        tip = arrow.mapFromScene(tip_scene)
    else:
        anchor, tip = anchor_scene, QPointF(tip_scene)
    arrow.set_positions(anchor, tip)
    set_callout_target(arrow, tip_scene)
    return True


def _watch_bubble_contents(bubble) -> None:
    """文字变化会改变气泡尺寸，箭头要跟着重新落到气泡边缘。"""
    if getattr(bubble, "_callout_watching", False):
        return
    document_fn = getattr(bubble, "document", None)
    document = document_fn() if callable(document_fn) else None
    if document is None:
        return
    try:
        document.contentsChanged.connect(lambda bubble=bubble: sync_arrow_to_bubble(bubble))
    except Exception:
        return
    bubble._callout_watching = True
