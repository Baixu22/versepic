"""组合标注工具：从气泡位置拖到被标注的位置，落笔即输入文字。

一次拖拽生成一组关联标注——箭头指向落点，文字气泡落在起点，并立刻进入编辑。
两个图元都是已有类型：气泡是 TextItem（背景就是气泡），箭头是 ArrowItem。
关联和几何同步在 canvas.items.callout_link 里，工具本身只管创建。
"""

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QFont, QPen

from .base import Tool, ToolContext, color_with_opacity
from canvas.items import ArrowItem, TextItem
from canvas.items.callout_link import link_callout
from core.logger import log_debug, T


def _distance(a: QPointF, b: QPointF) -> float:
    delta = b - a
    return (delta.x() ** 2 + delta.y() ** 2) ** 0.5


class CalloutTool(Tool):
    """箭头 + 文字气泡的组合标注。"""

    id = "callout"

    # 小于此长度不算标注，避免误点留下一条没有指向的短箭头
    MIN_LENGTH = 10

    def __init__(self):
        self.drawing = False
        self.start_pos = None
        self.current_item = None

    def on_press(self, pos: QPointF, button, ctx: ToolContext):
        if button != Qt.MouseButton.LeftButton:
            return
        self.drawing = True
        self.start_pos = QPointF(pos)
        pen = QPen(color_with_opacity(ctx.color, ctx.opacity), ctx.stroke_width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        self.current_item = ArrowItem(pos, pos, pen, self._arrow_style(ctx))
        ctx.scene.addItem(self.current_item)

    def on_move(self, pos: QPointF, ctx: ToolContext):
        if self.drawing and self.current_item:
            self.current_item.set_positions(self.start_pos, pos)

    def on_release(self, pos: QPointF, ctx: ToolContext):
        if not self.drawing:
            return
        self.drawing = False
        arrow, self.current_item = self.current_item, None
        if arrow is None:
            return

        if _distance(self.start_pos, pos) < self.MIN_LENGTH:
            ctx.scene.removeItem(arrow)
            log_debug(T("绘制取消：长度过短"), "CalloutTool")
            return

        arrow.set_positions(self.start_pos, pos)
        bubble = self._create_bubble(self.start_pos, ctx)
        link_callout(arrow, bubble, pos)

        # 立刻输入说明；内容为空失焦时，文字图元会把气泡和箭头一起撤出场景
        bubble.setFocus()
        cursor = bubble.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        bubble.setTextCursor(cursor)
        ctx.scene.item_auto_select_requested.emit(bubble)
        log_debug(T("创建组合标注: {pos}", pos=self.start_pos), "CalloutTool")

    def on_deactivate(self, ctx: ToolContext):
        """工具停用时清除焦点，空标注按既有文字规则整条作废。"""
        focus = ctx.scene.focusItem() if ctx.scene else None
        if focus is not None:
            focus.clearFocus()

    # ------------------------------------------------------------------

    def _arrow_style(self, ctx: ToolContext) -> str:
        if not ctx.settings_manager:
            return ArrowItem.STYLE_SINGLE
        settings = ctx.settings_manager.get_tool_settings("callout")
        return ArrowItem.normalize_style(settings.get("arrow_style"))

    def _create_bubble(self, pos: QPointF, ctx: ToolContext) -> TextItem:
        """气泡沿用文字工具的字体/描边/阴影设置，背景始终打开当气泡底。"""
        settings = ctx.settings_manager.get_tool_settings("text") if ctx.settings_manager else None

        def value(key, default=None):
            if settings is None:
                return default
            try:
                current = settings.get(key)
            except Exception:
                current = None
            return default if current is None else current

        from core.constants import normalize_text_font_family

        font = QFont(
            normalize_text_font_family(value("font_family", "")),
            int(float(value("font_size", 14))),
        )
        font.setBold(bool(value("font_bold", False)))
        font.setItalic(bool(value("font_italic", False)))
        font.setUnderline(bool(value("font_underline", False)))

        item = TextItem(
            "",
            QPointF(pos),
            font,
            self._color(value("color", "#000000"), "#000000"),
            provisional=True,
        )
        item.set_outline(
            bool(value("outline_enabled", False)),
            self._color(value("outline_color", "#FFFFFF"), "#FFFFFF"),
            value("outline_width", TextItem.DEFAULT_OUTLINE_WIDTH),
        )
        item.set_shadow(
            bool(value("shadow_enabled", False)),
            self._color(value("shadow_color", TextItem.DEFAULT_SHADOW_COLOR), TextItem.DEFAULT_SHADOW_COLOR),
        )

        # 组合标注的默认外观是"白底气泡"：即使用户从没开过文字背景，这里也打开。
        background = self._color(value("background_color", "#FFFFFF"), "#FFFFFF")
        opacity = int(value("background_opacity", 235))
        item.set_background(True, background, opacity)

        ctx.scene.addItem(item)
        return item

    @staticmethod
    def _color(raw, fallback: str) -> QColor:
        color = QColor(raw)
        return color if color.isValid() else QColor(fallback)
