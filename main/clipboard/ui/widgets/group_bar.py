# -*- coding: utf-8 -*-
"""
分组栏组件

- 顶部模式：一排文字标签（历史 / 各分组 / ＋），选中项为强调色软底；
- 左右模式：一列图标按钮（分组图标 + 名称提示）；
- 侧栏键盘导航状态机、分组管理回调（增删改排序）。
"""

from typing import List, Optional, Tuple

from PySide6.QtCore import QPoint, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QCursor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QBoxLayout, QHBoxLayout, QMenu, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from ui.glyphs import glyph_pixmap, svg_pixmap
from ui.motion import HoverAnimator

from ...controllers import ClipboardController
from ...core import ClipboardManager, Group, GroupType
from ..menus.group_context_menu import ClipboardGroupContextMenu
from ..theme.theme_styles import SurfacePalette, ThemeStyleGenerator, surface_palette
from ..theme.themes import Theme
from .item_delegate import UI_FAMILIES

_TAB_H = 28
_TAB_PAD_X = 11
_TAB_GAP = 4
_TAB_RADIUS = 7
_STRIP_MARGIN_X = 10
_RAIL_W = 46
_RAIL_BTN = 34


def _ui_font(px: int, weight=QFont.Weight.Normal) -> QFont:
    font = QFont()
    font.setFamilies(UI_FAMILIES)
    font.setPixelSize(px)
    font.setWeight(weight)
    return font


_LABEL_FONT = None
_EMOJI_FONT = None


def tab_width(label: str, icon_text: str = "") -> int:
    """顶部文字标签的宽度（按选中时的粗体量，切换选中不跳动）。"""
    global _LABEL_FONT, _EMOJI_FONT
    if _LABEL_FONT is None:
        _LABEL_FONT = QFontMetrics(_ui_font(13, QFont.Weight.DemiBold))
        _EMOJI_FONT = QFontMetrics(_ui_font(13))
    width = _TAB_PAD_X * 2 + _LABEL_FONT.horizontalAdvance(label)
    if icon_text:
        width += _EMOJI_FONT.horizontalAdvance(icon_text) + (5 if label else 0)
    return max(_TAB_H, width)


class _GroupButton(QPushButton):
    """自绘分组按钮：文字标签（顶部）或图标按钮（侧栏）。

    悬停 150ms 过渡；选中为强调色软底；键盘侧栏导航时画一圈静态焦点环。
    """

    def __init__(self, label: str = "", icon_text: str = "", svg: str = "", compact: bool = False,
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._label = label
        self._icon_text = icon_text
        self._svg = svg
        self._compact = compact
        self._hover = HoverAnimator(self, duration=150)
        self._palette: Optional[SurfacePalette] = None
        self._font = _ui_font(13)
        self._font_bold = _ui_font(13, QFont.Weight.DemiBold)
        self._emoji_font = _ui_font(15 if compact else 13)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFlat(True)
        if not compact:
            self.setFixedHeight(_TAB_H)
            self.setFixedWidth(self.ideal_width())
        else:
            self.setFixedSize(_RAIL_BTN, _RAIL_BTN)

    def ideal_width(self) -> int:
        if self._svg and not self._label:
            return _TAB_H
        return tab_width(self._label, self._icon_text)

    def set_palette(self, palette: SurfacePalette):
        self._palette = palette
        self.update()

    def enterEvent(self, event):
        self._hover.enter()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover.leave()
        super().leaveEvent(event)

    def paintEvent(self, _event):
        pal = self._palette
        if pal is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = 8 if self._compact else _TAB_RADIUS
        checked = self.isCheckable() and self.isChecked()
        progress = self._hover.value()

        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        if checked:
            painter.fillPath(path, pal.accent_soft)
        elif progress > 0.0:
            hover = QColor(pal.control_hover)
            hover.setAlphaF(hover.alphaF() * progress)
            painter.fillPath(path, hover)
        if self.property("sidebar_focus"):
            painter.setPen(QPen(pal.accent, 1.5))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect.adjusted(0.75, 0.75, -0.75, -0.75), radius, radius)

        color = pal.accent_text if checked else (pal.text if progress > 0.5 else pal.text_secondary)
        if self._svg:
            size = 18 if self._compact else 16
            pm = svg_pixmap(self._svg, size, color.name())
            if self._label:
                x = _TAB_PAD_X
            else:
                x = (self.width() - size) // 2
            painter.drawPixmap(int(x), (self.height() - size) // 2, pm)
            if not self._label:
                painter.end()
                return
        x = _TAB_PAD_X if not self._compact else 0
        if self._icon_text:
            painter.setFont(self._emoji_font)
            painter.setPen(color)
            if self._compact:
                painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._icon_text)
                painter.end()
                return
            fm = QFontMetrics(self._emoji_font)
            painter.drawText(QRectF(x, 0, fm.horizontalAdvance(self._icon_text) + 2, self.height()),
                             Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self._icon_text)
            x += fm.horizontalAdvance(self._icon_text) + 5
        painter.setFont(self._font_bold if checked else self._font)
        painter.setPen(color)
        painter.drawText(QRectF(x, 0, self.width() - x - _TAB_PAD_X + 2, self.height()),
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self._label)
        painter.end()


class _PlusButton(QPushButton):
    """＋：新建分组。静止时只有一个淡色加号，悬停出浅底。"""

    def __init__(self, parent: Optional[QWidget] = None, compact: bool = False):
        super().__init__(parent)
        self._hover = HoverAnimator(self, duration=150)
        self._palette: Optional[SurfacePalette] = None
        self._compact = compact
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.set_compact(compact)

    def set_compact(self, compact: bool):
        self._compact = compact
        if compact:
            self.setFixedSize(_RAIL_BTN, _RAIL_BTN)
        else:
            self.setFixedSize(_TAB_H, _TAB_H)

    def set_palette(self, palette: SurfacePalette):
        self._palette = palette
        self.update()

    def enterEvent(self, event):
        self._hover.enter()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover.leave()
        super().leaveEvent(event)

    def paintEvent(self, _event):
        pal = self._palette
        if pal is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        progress = self._hover.value()
        if progress > 0.0:
            hover = QColor(pal.control_hover)
            hover.setAlphaF(hover.alphaF() * progress)
            path = QPainterPath()
            path.addRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), _TAB_RADIUS, _TAB_RADIUS)
            painter.fillPath(path, hover)
        color = pal.text if progress > 0.5 else pal.text_tertiary
        size = 16
        pm = glyph_pixmap("plus", size, color.name(QColor.NameFormat.HexArgb), 1.5)
        painter.drawPixmap((self.width() - size) // 2, (self.height() - size) // 2, pm)
        painter.end()


class _GroupMenuButton(QPushButton):
    """顶部模式的分组入口：「当前分组名 ⌄」，点开是分组菜单。

    不画底色，只在悬停时出浅底；切到非默认分组时文字变强调色，
    与左侧类型分段（实心软底）区分开：一个是「筛选」，一个是「位置」。
    """

    _CHEVRON = 12
    _GAP = 3

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._hover = HoverAnimator(self, duration=150)
        self._palette: Optional[SurfacePalette] = None
        self._label = ""
        self._icon_text = ""
        self._active = False
        self._font = _ui_font(13)
        self._font_active = _ui_font(13, QFont.Weight.Medium)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFlat(True)
        self.setFixedHeight(_TAB_H)

    def set_palette(self, palette: SurfacePalette):
        self._palette = palette
        self.update()

    def set_group(self, label: str, icon_text: str = "", active: bool = False):
        self._label, self._icon_text, self._active = label, icon_text, active
        text = f"{icon_text} {label}" if icon_text else label
        width = _TAB_PAD_X * 2 - 3 + QFontMetrics(self._font_active).horizontalAdvance(text) + self._GAP + self._CHEVRON
        self.setFixedWidth(max(_TAB_H, width))
        self.setAccessibleName(text)
        self.update()

    def enterEvent(self, event):
        self._hover.enter()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover.leave()
        super().leaveEvent(event)

    def paintEvent(self, _event):
        pal = self._palette
        if pal is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        progress = self._hover.value()
        if progress > 0.0 or self.isDown():
            hover = QColor(pal.control_pressed if self.isDown() else pal.control_hover)
            hover.setAlphaF(hover.alphaF() * (1.0 if self.isDown() else progress))
            path = QPainterPath()
            path.addRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), _TAB_RADIUS, _TAB_RADIUS)
            painter.fillPath(path, hover)
        if self._active:
            color = pal.accent_text
        else:
            color = pal.text if progress > 0.5 else pal.text_secondary
        text = f"{self._icon_text} {self._label}" if self._icon_text else self._label
        painter.setFont(self._font_active if self._active else self._font)
        painter.setPen(color)
        text_w = self.width() - _TAB_PAD_X - (_TAB_PAD_X - 3) - self._GAP - self._CHEVRON
        painter.drawText(QRectF(_TAB_PAD_X, 0, text_w, self.height()),
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)
        chevron = glyph_pixmap("chevron_down", self._CHEVRON, color.name(), 1.4)
        painter.drawPixmap(self.width() - (_TAB_PAD_X - 3) - self._CHEVRON,
                           (self.height() - self._CHEVRON) // 2 + 1, chevron)
        painter.end()


class GroupBar(QWidget):
    """
    分组栏组件 — 管理分组按钮布局和侧栏交互状态机。

    信号:
        group_switched(group_id)  — 用户切换了分组（None 表示历史）
        sidebar_entered()         — 进入侧栏导航模式（window 需清空列表选中）
        sidebar_exited(prev_id)   — 退出侧栏导航模式（window 可恢复之前选中）
        manage_groups_requested() — 请求打开分组管理对话框
        manage_items_requested()  — 请求打开内容管理对话框
    """

    group_switched = Signal(object)          # Optional[int]
    sidebar_entered = Signal()
    sidebar_exited = Signal(object)          # Optional[int] — prev_item_id
    manage_groups_requested = Signal()
    manage_items_requested = Signal()

    def __init__(
        self,
        controller: ClipboardController,
        manager: ClipboardManager,
        theme: Theme,
        position: str = "right",
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setObjectName("groupBar")
        self.controller = controller
        self.manager = manager
        self.current_theme = theme
        self._palette = surface_palette(theme)
        self.position = position  # "right" / "left" / "top"

        self.group_buttons: List[_GroupButton] = []
        self._overflow_btn: Optional[_GroupButton] = None

        self._sidebar_mode = False
        self._sidebar_index = 0
        self._sidebar_prev_item_id: Optional[int] = None

        self.bar_widget: QWidget = self
        self.bar_layout: Optional[QBoxLayout] = None
        self.clipboard_btn: _GroupButton = self._create_clipboard_btn(self._compact())
        self.add_group_btn = _PlusButton(self)
        self.add_group_btn.setToolTip(self.tr("New Group"))
        self.add_group_btn.clicked.connect(self.manage_groups_requested.emit)

        self.group_buttons_widget = QWidget(self)
        self.group_buttons_widget.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.group_buttons_widget.setStyleSheet("background: transparent;")
        self.group_buttons_layout: Optional[QBoxLayout] = None
        self._top_index = 0

        # 顶部模式的下拉入口；只有窗口提供了 top_host（筛选行里的槽位）时启用
        self.menu_btn = _GroupMenuButton(self)
        self.menu_btn.setToolTip(self.tr("Switch group"))
        self.menu_btn.clicked.connect(self._show_group_menu)
        self.menu_btn.set_palette(self._palette)
        self.menu_btn.hide()
        self._top_host: Optional[QBoxLayout] = None

    # ================================================================
    #  公共 API
    # ================================================================

    @property
    def sidebar_mode(self) -> bool:
        return self._sidebar_mode

    def build(self, content_layout: QHBoxLayout, left_widget: QWidget, left_layout: QVBoxLayout,
              top_index: int = 0, top_host: Optional[QBoxLayout] = None):
        """首次构建分组栏并插入布局。

        top_index 为旧式顶部标签条插入到列表列的位置；给了 top_host 时，
        顶部模式改为一个「分组 ⌄」下拉按钮，放进 top_host（通常是筛选行右侧），
        不再单独占一整行。
        """
        self._content_layout = content_layout
        self._left_widget = left_widget
        self._left_layout = left_layout
        self._top_index = top_index
        self._top_host = top_host
        self._build_bar()
        QTimer.singleShot(0, self.refresh_buttons)

    @property
    def menu_mode(self) -> bool:
        """顶部模式且窗口提供了宿主槽位：分组以下拉菜单呈现。"""
        return self.position == "top" and self._top_host is not None

    def set_position(self, position: str):
        """切换分组栏位置（right/left/top）"""
        if position == self.position:
            return
        self.position = position
        self._build_bar()
        QTimer.singleShot(0, self.refresh_buttons)

    def set_theme(self, theme: Theme):
        self.current_theme = theme
        self._palette = surface_palette(theme)
        for btn in self._all_buttons():
            try:
                btn.set_palette(self._palette)
            except RuntimeError:
                pass
        self.menu_btn.set_palette(self._palette)
        self._apply_bar_style()

    def refresh_buttons(self):
        """刷新分组按钮；放不下时折叠进「更多」菜单"""
        if self.menu_mode:
            self._clear_group_buttons_layout()
            self.group_buttons_layout.addWidget(self.add_group_btn)
            self._update_menu_label()
            return
        self._clear_group_buttons_layout()
        self._rebuild_clipboard_btn()
        self.clipboard_btn.setChecked(self.controller.current_group_id is None)

        groups = [g for g in self.controller.get_groups() if g.group_type != GroupType.HIDDEN]
        visible, hidden = self._split_groups(groups)

        for group in visible:
            btn = self._make_group_btn(group)
            self.group_buttons_layout.addWidget(btn)
            self.group_buttons.append(btn)

        if hidden:
            overflow = self._make_button(label="" if self._compact() else self.tr("More"),
                                         icon_text="···" if self._compact() else "")
            overflow.setCheckable(False)
            overflow.setToolTip(self.tr("More groups ({n})").format(n=len(hidden)))
            overflow.clicked.connect(lambda _checked=False, hg=hidden: self._show_overflow_group_menu(hg))
            self._overflow_btn = overflow
            self.group_buttons_layout.addWidget(overflow)
        else:
            self._overflow_btn = None

        self.add_group_btn.set_compact(self._compact())
        self.add_group_btn.set_palette(self._palette)
        self.group_buttons_layout.addWidget(self.add_group_btn)

    def enter_sidebar_mode(self, prev_item_id: Optional[int] = None):
        buttons = self._get_sidebar_buttons()
        if not buttons:
            return
        self._sidebar_mode = True
        self._sidebar_prev_item_id = prev_item_id
        self.sidebar_entered.emit()
        self._sync_sidebar_index()
        self._set_sidebar_focus_button(buttons[self._sidebar_index])

    def exit_sidebar_mode(self):
        self._sidebar_mode = False
        self._set_sidebar_focus_button(None)
        prev = self._sidebar_prev_item_id
        self._sidebar_prev_item_id = None
        self.sidebar_exited.emit(prev)

    def move_sidebar_selection(self, delta: int):
        buttons = self._get_sidebar_buttons()
        if not buttons:
            return
        self._sidebar_index = (self._sidebar_index + delta) % len(buttons)
        target = buttons[self._sidebar_index]
        self._set_sidebar_focus_button(target)
        target.click()

    def handle_top_group_switch(self, delta: int):
        """顶部模式左右键直接切换分组，不进入侧栏模式"""
        if self.menu_mode:
            order = [None] + [g.id for g in self._visible_groups()]
            current = self.controller.current_group_id
            index = order.index(current) if current in order else 0
            new_index = (index + delta) % len(order)
            if new_index != index:
                self.group_switched.emit(order[new_index])
            return
        self._sync_sidebar_index()
        buttons = self._get_sidebar_buttons()
        if not buttons:
            return
        new_index = (self._sidebar_index + delta) % len(buttons)
        if new_index == self._sidebar_index:
            return
        self._sidebar_index = new_index
        buttons[self._sidebar_index].click()

    def clear_sidebar_focus(self):
        if not self._sidebar_mode:
            self._set_sidebar_focus_button(None)

    def switch_to_group(self, group_id: Optional[int]):
        self.controller.switch_to_group(group_id)
        self.clipboard_btn.setChecked(group_id is None)
        for btn in self.group_buttons:
            btn.setChecked(btn.property("group_id") == group_id)
        self._sync_sidebar_index()
        if self.menu_mode:
            self._update_menu_label()

    # ================================================================
    #  顶部下拉菜单
    # ================================================================

    def _visible_groups(self) -> List[Group]:
        return [g for g in self.controller.get_groups() if g.group_type != GroupType.HIDDEN]

    def _update_menu_label(self):
        current = self.controller.current_group_id
        group = next((g for g in self._visible_groups() if g.id == current), None) if current is not None else None
        if group is None:
            self.menu_btn.set_group(self.tr("All History"))
        else:
            self.menu_btn.set_group(self._short_name(group.name, 10), group.icon or "", active=True)

    def _show_group_menu(self):
        menu = QMenu(self)
        menu.setStyleSheet(self._get_menu_style())
        current = self.controller.current_group_id

        def add(label: str, group_id: Optional[int]):
            action = QAction(label, menu)
            action.setCheckable(True)
            action.setChecked(current == group_id)
            action.triggered.connect(lambda _checked=False, gid=group_id: self.group_switched.emit(gid))
            menu.addAction(action)

        add(self.tr("All History"), None)
        groups = self._visible_groups()
        if groups:
            menu.addSeparator()
            for group in groups:
                add(f"{group.icon}  {group.name}" if group.icon else group.name, group.id)
        menu.addSeparator()
        manage = QAction(self.tr("Manage Groups…"), menu)
        manage.triggered.connect(self.manage_groups_requested.emit)
        menu.addAction(manage)
        # 菜单右缘对齐按钮右缘，从按钮下方展开
        below = self.menu_btn.mapToGlobal(self.menu_btn.rect().bottomRight())
        menu.exec(QPoint(below.x() - menu.sizeHint().width() + 1, below.y() + 4))

    # ================================================================
    #  按钮
    # ================================================================

    def _compact(self) -> bool:
        return self.position != "top"

    def _make_button(self, label: str = "", icon_text: str = "", svg: str = "") -> _GroupButton:
        btn = _GroupButton(label=label, icon_text=icon_text, svg=svg, compact=self._compact(),
                           parent=self.group_buttons_widget)
        btn.set_palette(self._palette)
        return btn

    def _create_clipboard_btn(self, compact: bool) -> _GroupButton:
        """历史按钮随模式换形态：顶部是文字，侧栏是时钟图标。"""
        btn = _GroupButton(
            label="" if compact else self.tr("History"),
            svg="fluent_icons/History.svg" if compact else "",
            compact=compact,
            parent=self,
        )
        btn.setToolTip(self.tr("Clipboard History"))
        btn.setCheckable(True)
        btn.clicked.connect(lambda _checked=False, b=btn: self._on_sidebar_button_clicked(b, None))
        btn.set_palette(self._palette)
        return btn

    def _rebuild_clipboard_btn(self):
        compact = self._compact()
        old = self.clipboard_btn
        if old._compact == compact:
            old.set_palette(self._palette)
            return
        btn = self._create_clipboard_btn(compact)
        btn.setChecked(old.isChecked())
        index = self.bar_layout.indexOf(old) if self.bar_layout is not None else -1
        if index >= 0:
            self.bar_layout.insertWidget(index, btn)
            self.bar_layout.removeWidget(old)
        old.hide()
        old.deleteLater()
        self.clipboard_btn = btn

    def _make_group_btn(self, group: Group) -> _GroupButton:
        icon = group.icon or ""
        if self._compact():
            btn = self._make_button(icon_text=icon or group.name[:1])
        else:
            btn = self._make_button(label=self._short_name(group.name), icon_text=icon)
        btn.setToolTip(group.name)
        btn.setCheckable(True)
        btn.setChecked(self.controller.current_group_id == group.id)
        btn.setProperty("group_id", group.id)
        btn.clicked.connect(lambda _checked=False, b=btn, gid=group.id: self._on_sidebar_button_clicked(b, gid))
        btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        btn.customContextMenuRequested.connect(
            lambda pos, b=btn, gid=group.id: self._show_group_context_menu(b, gid, pos)
        )
        return btn

    @staticmethod
    def _short_name(name: str, limit: int = 8) -> str:
        return name if len(name) <= limit else name[: limit - 1] + "…"

    def _all_buttons(self) -> List[QPushButton]:
        buttons: List[QPushButton] = [self.clipboard_btn, self.add_group_btn] + list(self.group_buttons)
        if self._overflow_btn is not None:
            buttons.append(self._overflow_btn)
        return buttons

    # ================================================================
    #  布局
    # ================================================================

    def _split_groups(self, groups: List[Group]) -> Tuple[List[Group], List[Group]]:
        """按实际可用空间决定哪些分组直接露出、哪些收进「更多」。"""
        if not groups:
            return [], []
        if self._compact():
            available = self.height() - 8 - _RAIL_BTN - 4 - (_RAIL_BTN + 4) * 2
            if self.height() <= 0:
                return list(groups), []
            capacity = max(0, available // (_RAIL_BTN + 4))
        else:
            if self.width() <= 0:
                return list(groups), []
            available = (self.width() - _STRIP_MARGIN_X * 2 - self.clipboard_btn.ideal_width()
                         - _TAB_GAP - _TAB_H - _TAB_GAP)
            more_w = tab_width(self.tr("More")) + _TAB_GAP
            capacity, used = 0, 0
            for index, group in enumerate(groups):
                need = tab_width(self._short_name(group.name), group.icon or "") + _TAB_GAP
                rest = len(groups) - index - 1
                if used + need + (more_w if rest else 0) > available:
                    break
                used += need
                capacity += 1
        if len(groups) <= capacity:
            return list(groups), []
        visible, hidden = list(groups[:capacity]), list(groups[capacity:])
        current = self.controller.current_group_id
        if current is not None and visible and current not in {g.id for g in visible}:
            selected = next((g for g in hidden if g.id == current), None)
            if selected is not None:
                hidden.remove(selected)
                hidden.insert(0, visible[-1])
                visible[-1] = selected
        return visible, hidden

    def _clear_bar_layout(self):
        if self.bar_layout is None:
            return
        keep = {self.clipboard_btn, self.add_group_btn, self.group_buttons_widget, self.menu_btn}
        while self.bar_layout.count():
            item = self.bar_layout.takeAt(0)
            widget = item.widget()
            if widget is not None and widget not in keep:
                widget.deleteLater()

    def _remove_from_host_layouts(self):
        self._content_layout.removeWidget(self)
        self._left_layout.removeWidget(self)
        if self._top_host is not None:
            self._top_host.removeWidget(self)

    def _apply_bar_style(self):
        hairline = ThemeStyleGenerator(self.current_theme)._hairline()
        if self.menu_mode:
            self.setStyleSheet("QWidget#groupBar { background: transparent; border: none; }")
            return
        if self.position == "top":
            border = f"border-bottom: 1px solid {hairline};"
        elif self.position == "left":
            border = f"border-right: 1px solid {hairline};"
        else:
            border = f"border-left: 1px solid {hairline};"
        self.setStyleSheet(f"QWidget#groupBar {{ background: transparent; {border} }}")

    def _build_bar(self):
        pos = self.position
        is_top = pos == "top"
        self._remove_from_host_layouts()

        direction = QBoxLayout.Direction.LeftToRight if is_top else QBoxLayout.Direction.TopToBottom
        if self.bar_layout is None:
            self.bar_layout = QBoxLayout(direction, self)
        else:
            self._clear_bar_layout()
            self.bar_layout.setDirection(direction)

        if self.group_buttons_layout is None:
            self.group_buttons_layout = QBoxLayout(direction, self.group_buttons_widget)
            self.group_buttons_layout.setContentsMargins(0, 0, 0, 0)
            self.group_buttons_layout.setSpacing(_TAB_GAP)
        else:
            self.group_buttons_layout.setDirection(direction)

        if self.menu_mode:
            # 下拉模式：整条栏只剩一个按钮，嵌进窗口筛选行
            self.setFixedHeight(_TAB_H)
            self.setMinimumWidth(0)
            self.setMaximumWidth(16777215)
            self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
            self.bar_layout.setContentsMargins(0, 0, 0, 0)
            self.bar_layout.setSpacing(0)
            for widget in (self.clipboard_btn, self.group_buttons_widget):
                widget.hide()
            self.bar_layout.addWidget(self.menu_btn)
            self.menu_btn.show()
            self._update_menu_label()
            self._apply_bar_style()
            # 插在宿主行的最后一个控件（筛选按钮）之前
            self._top_host.insertWidget(max(0, self._top_host.count() - 1), self)
            return
        self.menu_btn.hide()
        self.clipboard_btn.show()
        self.group_buttons_widget.show()
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        if is_top:
            self.setFixedHeight(_TAB_H + 10)
            self.setMinimumWidth(0)
            self.setMaximumWidth(16777215)
            self.bar_layout.setContentsMargins(_STRIP_MARGIN_X, 2, _STRIP_MARGIN_X, 8)
        else:
            self.setFixedWidth(_RAIL_W)
            self.setMinimumHeight(0)
            self.setMaximumHeight(16777215)
            self.bar_layout.setContentsMargins((_RAIL_W - _RAIL_BTN) // 2, 8, (_RAIL_W - _RAIL_BTN) // 2, 8)
        self.bar_layout.setSpacing(_TAB_GAP)

        self._rebuild_clipboard_btn()
        self.bar_layout.addWidget(self.clipboard_btn)
        self.bar_layout.addWidget(self.group_buttons_widget)
        self.group_buttons_layout.addWidget(self.add_group_btn)
        self.bar_layout.addStretch()
        self._apply_bar_style()

        if pos == "left":
            self._content_layout.insertWidget(0, self)
        elif is_top:
            self._content_layout.removeWidget(self._left_widget)
            self._left_layout.insertWidget(self._top_index, self)
            self._content_layout.addWidget(self._left_widget, 1)
        else:
            self._content_layout.addWidget(self)

    def _get_menu_style(self) -> str:
        return ThemeStyleGenerator(self.current_theme).generate_menu_style()

    # ================================================================
    #  侧栏导航状态机
    # ================================================================

    def _get_sidebar_buttons(self) -> List[QPushButton]:
        return [self.clipboard_btn] + self.group_buttons

    def _on_sidebar_button_clicked(self, target: QPushButton, group_id: Optional[int]):
        if not self._sidebar_mode:
            self.sidebar_entered.emit()
        self._sidebar_mode = True
        buttons = self._get_sidebar_buttons()
        if target in buttons:
            self._sidebar_index = buttons.index(target)
        self._set_sidebar_focus_button(target)
        self.group_switched.emit(group_id)

    def _sync_sidebar_index(self):
        if self.controller.current_group_id is None:
            self._sidebar_index = 0
            return
        for i, btn in enumerate(self.group_buttons, start=1):
            if btn.property("group_id") == self.controller.current_group_id:
                self._sidebar_index = i
                return
        self._sidebar_index = 0

    def _set_sidebar_focus_button(self, target: Optional[QPushButton]):
        show_ring = target is not None and self._sidebar_mode and self.position != "top"
        for btn in self._get_sidebar_buttons():
            btn.setProperty("sidebar_focus", show_ring and btn is target)
            btn.update()

    # ================================================================
    #  溢出菜单
    # ================================================================

    def _show_overflow_group_menu(self, hidden_groups: list):
        if not hidden_groups:
            return
        menu = QMenu(self)
        menu.setStyleSheet(self._get_menu_style())
        for group in hidden_groups:
            label = f"{group.icon}  {group.name}" if group.icon else group.name
            action = QAction(label, self)
            action.setCheckable(True)
            action.setChecked(group.id == self.controller.current_group_id)
            action.triggered.connect(lambda _checked=False, gid=group.id: self.group_switched.emit(gid))
            menu.addAction(action)
        menu.exec(QCursor.pos())

    def _clear_group_buttons_layout(self):
        while self.group_buttons_layout.count():
            item = self.group_buttons_layout.takeAt(0)
            widget = item.widget()
            if widget and widget is not self.add_group_btn:
                widget.deleteLater()
        self.group_buttons.clear()

    # ================================================================
    #  分组右键菜单 + 管理操作
    # ================================================================

    def _show_group_context_menu(self, btn, group_id: int, pos):
        actions_data = self.controller.build_group_context_menu_data(group_id)
        ClipboardGroupContextMenu(
            parent=self,
            menu_style=self._get_menu_style(),
            translate=self.tr,
            action_handlers=self._get_group_context_menu_handlers(group_id),
        ).show(btn, pos, actions_data)

    def _get_group_context_menu_handlers(self, group_id: int):
        return {
            "edit_group": lambda: self._edit_group(group_id),
            "move_group_up": lambda: self._move_group_order(group_id, -1),
            "move_group_down": lambda: self._move_group_order(group_id, 1),
            "delete_group": lambda: self._delete_group(group_id),
        }

    def _delete_group(self, group_id: int):
        if self.controller.delete_group(group_id, parent_widget=self):
            self.refresh_buttons()

    def _move_group_order(self, group_id: int, direction: int):
        if self.controller.move_group_order(group_id, direction):
            self.refresh_buttons()

    def _edit_group(self, group_id: int):
        self.controller.open_manage_dialog_for_group(
            group_id,
            group_added_callback=self.refresh_buttons,
            data_changed_callback=self._on_manage_data_changed,
        )

    def _on_manage_data_changed(self):
        parent = self.parent()
        if parent and hasattr(parent, '_on_manage_data_changed'):
            parent._on_manage_data_changed()


__all__ = ["GroupBar"]
