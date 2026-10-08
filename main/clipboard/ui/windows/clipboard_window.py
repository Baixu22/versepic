# -*- coding: utf-8 -*-
"""
剪贴板历史窗口

提供的剪贴板历史管理界面。
"""

import os
import re
from time import perf_counter
from typing import List, Optional

from PySide6.QtCore import (
    QDate, QEasingCurve, QEvent, QLocale, QPoint, QSettings, QSize, QTimer, Qt, Signal,
    QVariantAnimation,
)
from PySide6.QtGui import QColor, QCursor, QFont, QFontMetrics, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCalendarWidget,
    QDateEdit,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from core import safe_event
from core.logger import T, log_debug, log_exception
from core.shortcut_manager import ShortcutHandler, ShortcutManager
from core.ui_theme import RADIUS_MD, RADIUS_XL
from ui.dialogs import show_confirm_dialog
from ui.fluent_lite import LineEdit
from ui import glass
from ui.glyphs import glyph_icon, svg_icon
from ui.motion import apply_frost, fade_hide, fade_show, reset_opacity

from ...controllers import ClipboardController, SelectionManager
from ...core import ClipboardItem, ClipboardManager, GroupType
from ..theme.theme_styles import ThemeStyleGenerator, rgba, surface_palette
from ..theme.themes import Theme, get_theme_manager
from ..mixins.frameless_mixin import FramelessMixin
from ..dialogs.manage_dialog import ManageDialog, get_manage_dialog
from ..menus.item_context_menu import ClipboardItemContextMenu
from ..widgets.group_bar import GroupBar
from ..widgets.item_delegate import ClipboardItemDelegate, ROLE_ITEM_DATA, ROLE_ITEM_ID, UI_FAMILIES
from ..widgets.preview_popup import PreviewPopup


# 数字/字母直选条目只认裸按键。带 Ctrl 的组合必须放行：本应用自己模拟的
# Ctrl+V 在窗口常驻时会回到这里，被当成"粘贴第 31 条"就会自激成死循环。
_DIRECT_PICK_BLOCKERS = (
    Qt.KeyboardModifier.ControlModifier
    | Qt.KeyboardModifier.AltModifier
    | Qt.KeyboardModifier.MetaModifier
)

# Windows 上交给 DWM 做毛玻璃、圆角和阴影；Win11 系统圆角是 8px，Qt 侧跟随。
# 其他平台退回 Qt 自绘：圆角用共享刻度里的窗口档，外侧留白给软阴影环。
_NATIVE_GLASS = glass.is_supported()
_WINDOW_RADIUS = RADIUS_MD if glass.is_win11() else RADIUS_XL
_SHADOW_MARGIN = 0 if _NATIVE_GLASS else 10
# (外扩 px, alpha) 从外到内三层低透明描边近似投影
_SHADOW_RINGS = ((5, 14), (3, 22), (1, 42))

# 顶部工具栏：搜索行 + 筛选行。字号：15（搜索、正文、控件）、12（底栏）
_EDGE_X = 12            # 头部/底栏左右留白
_SEARCH_H = 44
_SEGMENT_H = 38
_TOOL_BTN = 40
_TOOL_ICON = 22
# 工具按钮圆角跟着共享刻度走，不再单写 16：16px 在 34px 的按钮上接近胶囊，
# 和内容管理、设置页里同尺寸的图标按钮放在一起会明显更圆。
_CONTROL_RADIUS = RADIUS_MD

# 行尾快捷操作按钮几何
_QUICK_BTN_SIZE = 36
_QUICK_BTN_GAP = 2
_QUICK_BTN_ICON_SIZE = 20
_QUICK_BAR_RIGHT_MARGIN = 12

# 悬停过渡驱动定时器参数（delegate 按时间推算进度）
_HOVER_ANIM_MS = 230

# 类型筛选：索引与 controller.set_content_type_filter 一致
_TYPE_FILTERS = ("All", "Text", "Image", "File")
# 时间筛选预设：(key, 天数)；None 表示不限时间
_DATE_PRESETS = (("any", None), ("today", 0), ("7d", 6), ("30d", 29))


class ClipboardShortcutHandler(ShortcutHandler):
    """剪贴板窗口快捷键处理器 (priority=60)"""

    def __init__(self, window: "ClipboardWindow"):
        self._window = window

    @property
    def priority(self) -> int:
        return 60

    @property
    def handler_name(self) -> str:
        return "ClipboardWindow"

    def is_active(self) -> bool:
        w = self._window
        try:
            if w is None or not w.isVisible():
                return False
            # 可见不等于有焦点：窗口设成粘贴后常驻时会一直挂在画面上。分发器按
            # 优先级问一遍谁 active，这里只看可见的话，钉图、画布等真正获焦的界面
            # 会被抢走按键（例如 Esc）。
            return w.isActiveWindow()
        except RuntimeError:
            return False

    def handle_key(self, event) -> bool:
        w = self._window
        key = event.key()
        modifiers = event.modifiers()
        focus = QApplication.focusWidget()
        if isinstance(focus, QLineEdit) and key not in (Qt.Key.Key_Escape,):
            return False

        if key == Qt.Key.Key_Space and focus is w.list_widget:
            popup = PreviewPopup.instance()
            if popup.isVisible():
                popup.hide_preview()
            else:
                item = w.list_widget.currentItem()
                if item is not None:
                    w.selection_manager._show_preview_for_item(item)
            return True

        if key == Qt.Key.Key_Escape:
            if focus is w.search_input:
                w.search_input.clear()
                w._collapse_search()
                w.list_widget.setFocus()
                return True
            if hasattr(w, "selection_manager") and w.selection_manager._selected_index >= 0:
                w.selection_manager.reset()
                return True
            w.close()
            return True

        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            w._paste_selected()
            return True

        if key == Qt.Key.Key_Delete:
            # 删除仅通过右键菜单执行，避免误按 Enter 旁边的 Delete 键。
            return True

        if key == Qt.Key.Key_F and modifiers == Qt.KeyboardModifier.ControlModifier:
            w._expand_search()
            return True

        if modifiers & _DIRECT_PICK_BLOCKERS:
            return False

        if Qt.Key.Key_1 <= key <= Qt.Key.Key_9:
            focus_widget = w.search_input
            from PySide6.QtWidgets import QApplication as _App

            if _App.focusWidget() is not focus_widget:
                index = key - Qt.Key.Key_1
                items = w.controller.current_items
                if index < len(items):
                    w._on_paste_item(items[index].id)
                    return True
            return False

        if Qt.Key.Key_A <= key <= Qt.Key.Key_Z:
            focus_widget = w.search_input
            from PySide6.QtWidgets import QApplication as _App

            if _App.focusWidget() is not focus_widget:
                index = 9 + (key - Qt.Key.Key_A)
                items = w.controller.current_items
                if index < len(items):
                    w._on_paste_item(items[index].id)
                    return True
            return False

        return False


class ClipboardWindow(QWidget, FramelessMixin):
    """剪贴板历史窗口。"""

    item_pasted = Signal(int)
    closed = Signal()
    new_item_received = Signal(object)
    _offscreen_warmup_done = False

    def __init__(self, parent=None):
        super().__init__(parent)
        self.manager = ClipboardManager()
        self.controller = ClipboardController(self.manager)
        self.controller.data_loaded.connect(self._on_data_loaded)
        self.controller.loading_state_changed.connect(self._on_loading_changed)
        self.controller.reload_required.connect(self._on_reload_required)
        self.controller.load_completed.connect(self._on_load_completed)
        self.controller.item_inserted.connect(self._on_item_inserted)
        self.controller.item_moved_to_top.connect(self._on_item_moved_to_top)
        self._image_indexer = None
        self._image_indexing = False

        self.selected_item_id: Optional[int] = None
        self._is_loading = False
        self._ignore_manage_refresh_when_hidden = True
        self._auto_fill_max_pages = 3
        self._auto_fill_remaining = self._auto_fill_max_pages
        self._offscreen_warmup_in_progress = False

        self.new_item_received.connect(self._on_new_item)
        self._init_frameless(edge_margin=8)
        self._qsettings = QSettings("Jietuba", "ClipboardWindow")

        self.theme_manager = get_theme_manager()
        self.current_theme = self.theme_manager.get_current_theme()
        self.theme_manager.theme_changed.connect(self._on_theme_changed)
        self.theme_manager.font_size_changed.connect(self._on_font_size_changed)
        self.theme_manager.opacity_changed.connect(self._on_opacity_changed)
        try:
            from core.i18n import I18nManager

            I18nManager.instance().language_changed.connect(self._on_language_changed)
        except Exception as e:
            log_debug(T("连接剪贴板语言切换信号失败: {e}", e=e), "I18n")

        self._load_settings()
        self._load_window_geometry()
        self._setup_ui()
        from ui.fluent_lite.popups import ToolTip
        ToolTip.install(self)
        self._apply_opacity()
        self._setup_shortcuts()

        self.controller.set_paste_target_exclusion(self._is_paste_picker_surface)
        PreviewPopup.instance().set_manager(self.manager)
        self._warmup_offscreen_once()

    def _on_data_loaded(self, items: List[ClipboardItem], is_first_page: bool):
        if is_first_page:
            self._auto_fill_remaining = self._auto_fill_max_pages
            if items or self.controller.current_items:
                self._refresh_list()
            else:
                self.list_widget.clear()
        else:
            self._append_items(items)
        self._update_empty_state()
        self._update_scope_bar()

    def _on_item_inserted(self, item: ClipboardItem, row: int):
        """单条新内容插进列表：不重建、不滚动、不动选中项和预览。"""
        list_item = QListWidgetItem()
        list_item.setData(ROLE_ITEM_ID, item.id)
        list_item.setData(ROLE_ITEM_DATA, item)
        self.list_widget.insertItem(row, list_item)
        self.selection_manager.shift_selection_after_insert(row)
        self._update_scope_bar()

    def _on_item_moved_to_top(self, item_id: int, row: int):
        """条目移到最前：搬动已有的行，不重建列表。"""
        for index in range(self.list_widget.count()):
            if self.list_widget.item(index).data(ROLE_ITEM_ID) != item_id:
                continue
            if index == row:
                return
            self.list_widget.insertItem(row, self.list_widget.takeItem(index))
            self.selection_manager.shift_selection_after_move(index, row)
            return

    def _on_loading_changed(self, is_loading: bool):
        self._is_loading = is_loading

    def _on_reload_required(self):
        self.controller.load_history()
        self.group_bar.refresh_buttons()

    def request_data_refresh(self, reason: str = ""):
        if self._ignore_manage_refresh_when_hidden and not self.isVisible():
            reason_text = reason or "Clipboard data"
            log_debug(T("{reason_text} 当前窗口不可见，跳过刷新界面", reason_text=reason_text), "Clipboard")
            return
        self._load_history()

    def _on_manage_data_changed(self):
        self.request_data_refresh("Manage dialog data")

    def _on_theme_changed(self, theme: Theme):
        self.current_theme = theme
        self._apply_theme()

    def _on_language_changed(self, _lang_code: str):
        self._apply_date_filter_locale()
        self._retranslate_ui()

    def _apply_theme(self):
        if hasattr(self, "_item_delegate"):
            self._item_delegate.set_theme(self.current_theme)
            self._item_delegate.set_window_opacity(self.window_opacity)
        self._apply_opacity()
        if self.isVisible():
            self._apply_glass()
        self.group_bar.set_theme(self.current_theme)
        if hasattr(self, "search_input"):
            self._apply_toolbar_styles()
            self._apply_time_filter_styles()
        self._refresh_quick_action_styles()
        self._refresh_list()
        self._update_empty_state()
        log_debug(T("主题已切换到: {theme_name}", theme_name=self.current_theme.display_name), "Clipboard")

    def _load_settings(self):
        from settings import get_tool_settings_manager

        self.config = get_tool_settings_manager()
        self.window_opacity = self.config.get_clipboard_window_opacity()
        self.display_lines = self.config.get_clipboard_font_size()
        self.group_bar_position = self.config.get_clipboard_group_bar_position()

    def _current_date_locale(self) -> QLocale:
        try:
            from core.i18n import I18nManager

            lang_code = I18nManager.get_current_language()
        except Exception:
            lang_code = "zh"

        locale_map = {
            "zh": QLocale(QLocale.Language.Chinese, QLocale.Country.China),
            "ja": QLocale(QLocale.Language.Japanese, QLocale.Country.Japan),
            "ko": QLocale(QLocale.Language.Korean, QLocale.Country.SouthKorea),
            "en": QLocale(QLocale.Language.English, QLocale.Country.UnitedStates),
        }
        return locale_map.get(lang_code, locale_map["zh"])

    def _apply_date_filter_locale(self):
        if not hasattr(self, "start_date_edit"):
            return

        locale = self._current_date_locale()
        for date_edit in (self.start_date_edit, self.end_date_edit):
            date_edit.setLocale(locale)
            calendar = date_edit.calendarWidget()
            if calendar is not None:
                calendar.setLocale(locale)

    def _retranslate_ui(self):
        if not hasattr(self, "search_input"):
            return

        self.setWindowTitle(self.tr("Clipboard History"))
        self.title_label.setText(self.tr("Clipboard History"))
        self.start_date_edit.setToolTip(self.tr("Start date"))
        self.end_date_edit.setToolTip(self.tr("End date"))
        self.filter_btn.setToolTip(self.tr("More filters"))
        self.menu_btn.setToolTip(self.tr("Settings"))
        self.close_btn.setToolTip(self.tr("Close (Esc)"))
        self.keep_open_btn.setToolTip(
            self.tr("Stays open after pasting") if self.keep_open_btn.isChecked()
            else self.tr("Closes after pasting. Click to keep it open"))
        self.search_input.setPlaceholderText(self.tr("Search clipboard"))
        self.search_input.setAccessibleName(self.tr("Search clipboard"))
        self._clear_search_action.setToolTip(self.tr("Clear search"))
        self.reset_filter_btn.setText(self.tr("Reset filters"))
        self.apply_time_filter_btn.setText(self.tr("Apply"))
        self.time_filter_separator.setText(self.tr("to"))
        action = self.tr("Paste") if self.config.get_clipboard_auto_paste() else self.tr("Copy")
        self.keyboard_hint.setText(self.tr("↑↓ Select · Enter {action} · Space Preview").format(action=action))
        if hasattr(self, "_quick_action_buttons"):
            self._quick_action_buttons["copy"].setToolTip(self.tr("Copy"))
            self._quick_action_buttons["more"].setToolTip(self.tr("More"))

        self.type_filter_labels = [self.tr(label) for label in _TYPE_FILTERS]
        # 选中时字重变粗：按粗体量好宽度再固定，切换选中不跳动
        bold = QFont(self.font())
        bold.setPixelSize(15)
        bold.setWeight(QFont.Weight.Medium)
        metrics = QFontMetrics(bold)
        for index, button in enumerate(self.type_filter_buttons):
            button.setText(self.type_filter_labels[index])
            button.setFixedWidth(max(40, metrics.horizontalAdvance(button.text()) + 22))
        self._update_date_menu_label()
        self._update_scope_bar()
        self._update_empty_state()
        self._layout_search()
        if hasattr(self, "group_bar"):
            self.group_bar.refresh_buttons()

    def _is_dark_theme(self) -> bool:
        return surface_palette(self.current_theme).dark

    def _apply_glass(self):
        # Qt owns the alpha surface. DWM blur on a layered/animated window
        # can composite differently during a move and after it settles.
        if _NATIVE_GLASS and not self._offscreen_warmup_in_progress:
            glass.disable_glass(self)

    def _apply_opacity(self):
        generator = ThemeStyleGenerator(self.current_theme, glass=False)

        if hasattr(self, "container"):
            self.container.setStyleSheet(generator.generate_window_style(self.window_opacity))

        if hasattr(self, "list_widget"):
            self.list_widget.setStyleSheet(generator.generate_list_widget_style(self.window_opacity))

        if hasattr(self, "time_filter_bar"):
            self.time_filter_bar.setStyleSheet(generator.generate_time_filter_bar_style(self.window_opacity))

    def _load_window_geometry(self):
        try:
            from settings import get_tool_settings_manager

            config = get_tool_settings_manager()
            default_width = config.get_app_setting("clipboard_window_width", 600)
            default_height = config.get_app_setting("clipboard_window_height", 720)
        except Exception as e:
            log_exception(e, T("加载剪贴板窗口几何设置"))
            default_width = 600
            default_height = 720

        self._saved_x = self._qsettings.value("window/x", None)
        self._saved_y = self._qsettings.value("window/y", None)
        self._saved_width = self._qsettings.value("window/width", default_width, type=int)
        self._saved_height = self._qsettings.value("window/height", default_height, type=int)

        if self._saved_x is not None:
            self._saved_x = int(self._saved_x)
        if self._saved_y is not None:
            self._saved_y = int(self._saved_y)

    def _save_window_geometry(self):
        self._qsettings.setValue("window/x", self.x())
        self._qsettings.setValue("window/y", self.y())
        self._qsettings.setValue("window/width", self.width())
        self._qsettings.setValue("window/height", self.height())
        self._qsettings.sync()

    def _setup_ui(self):
        self.setWindowTitle(self.tr("Clipboard History"))
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        apply_frost(self)
        self.setMinimumSize(560, 480)
        self.resize(self._saved_width, self._saved_height)

        self.container = QFrame(self)
        self.container.setObjectName("mainContainer")

        main_layout = QVBoxLayout(self)
        m = _SHADOW_MARGIN
        main_layout.setContentsMargins(m, m, m, m)
        main_layout.addWidget(self.container)

        self.content_layout = QHBoxLayout(self.container)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(0)

        self.left_widget = QWidget()
        self.left_widget.setStyleSheet("background: transparent;")
        self.left_layout = QVBoxLayout(self.left_widget)
        self.left_layout.setContentsMargins(0, 0, 0, 0)
        self.left_layout.setSpacing(0)
        self._build_toolbar()

        self.list_widget = QListWidget()
        self.list_widget.setStyleSheet(
            """
            QListWidget {
                background: #FFFFFF;
                border: none;
                outline: none;
                color: #333333;
            }
            QListWidget::item {
                padding: 0px;
                border: none;
                background: transparent;
            }
            QListWidget::item:selected {
                background: transparent;
            }
            QListWidget::item:hover {
                background: transparent;
            }
        """
        )
        self.list_widget.setSpacing(0)
        self.list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list_widget.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.list_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list_widget.customContextMenuRequested.connect(self._show_context_menu)

        show_metadata = self.config.get_clipboard_show_metadata()
        try:
            line_height_padding = self.config.get_clipboard_line_height_padding()
        except Exception as e:
            log_exception(e, T("获取行高填充设置"))
            line_height_padding = 8
        self._item_delegate = ClipboardItemDelegate(
            parent=self.list_widget,
            theme=self.current_theme,
            display_lines=self.display_lines,
            window_opacity=self.window_opacity,
            show_metadata=show_metadata,
            line_height_padding=line_height_padding,
        )
        self.list_widget.setItemDelegate(self._item_delegate)
        self.list_widget.setMouseTracking(True)
        self.list_widget.viewport().setMouseTracking(True)
        self.list_widget.itemEntered.connect(self._on_delegate_item_entered)
        self.list_widget.viewport().installEventFilter(self)

        # 行悬停过渡驱动：delegate 按时间推算进度，这里只定时刷帧
        self._hover_anim_timer = QTimer(self)
        self._hover_anim_timer.setInterval(16)
        self._hover_anim_timer.timeout.connect(self.list_widget.viewport().update)

        list_model = self.list_widget.model()
        list_model.rowsInserted.connect(self._update_empty_state)
        list_model.rowsRemoved.connect(self._update_empty_state)
        list_model.modelReset.connect(self._update_empty_state)

        self.selection_manager = SelectionManager(self.list_widget, self._get_item_data)
        self.selection_manager.group_bar_position = self.group_bar_position
        self.selection_manager.item_activated.connect(self._on_paste_item)
        self.selection_manager.request_sidebar_focus.connect(self._enter_sidebar_mode)
        self.selection_manager.request_group_switch.connect(self._on_top_group_switch)

        self.list_widget.itemSelectionChanged.connect(self._on_selection_changed)

        scrollbar = self.list_widget.verticalScrollBar()
        scrollbar.valueChanged.connect(self._on_scroll)
        scrollbar.rangeChanged.connect(self._on_scrollbar_range_changed)

        self.left_layout.addWidget(self.list_widget, 1)

        self.selection_manager.set_search_input(self.search_input)
        self.bottom_bar = QWidget()
        self.bottom_bar.setObjectName("keyboardBar")
        bottom_layout = QHBoxLayout(self.bottom_bar)
        bottom_layout.setContentsMargins(_EDGE_X + 4, 7, _EDGE_X + 4, 8)
        self.keyboard_hint = QLabel()
        self.keyboard_hint.setObjectName("keyboardHint")
        bottom_layout.addWidget(self.keyboard_hint)
        bottom_layout.addStretch()
        self.status_label = QLabel()
        self.status_label.setObjectName("statusLabel")
        bottom_layout.addWidget(self.status_label)
        self._feedback_timer = QTimer(self)
        self._feedback_timer.setSingleShot(True)
        self._feedback_timer.timeout.connect(self._update_scope_bar)
        self.left_layout.addWidget(self.bottom_bar)
        self.content_layout.addWidget(self.left_widget, 1)

        self.group_bar = GroupBar(
            controller=self.controller,
            manager=self.manager,
            theme=self.current_theme,
            position=self.group_bar_position,
            parent=self,
        )
        self.group_bar.group_switched.connect(self._on_group_switched)
        self.group_bar.sidebar_entered.connect(self._on_sidebar_entered)
        self.group_bar.sidebar_exited.connect(self._on_sidebar_exited)
        self.group_bar.manage_groups_requested.connect(self._on_add_group_clicked)
        self.group_bar.manage_items_requested.connect(self._on_add_item_clicked)
        self.group_bar.build(self.content_layout, self.left_widget, self.left_layout, top_index=1,
                             top_host=self.scope_row)
        self._apply_toolbar_styles()

        self._create_quick_action_buttons()
        self._create_empty_state()
        self._update_empty_state()

        self._setup_mouse_tracking_recursive(self)

    def _build_toolbar(self):
        """头部两行：

            [🔍 搜索剪贴板 ……………………]  📌  ···  ✕     ← 搜索即标题，空白处可拖动
            全部  文本  图片  文件          分组 ⌄   ⚲     ← 类型分段 + 分组下拉 + 更多筛选
        """
        self.toolbar = QWidget()
        self.toolbar.setObjectName("toolbar")
        layout = QVBoxLayout(self.toolbar)
        layout.setContentsMargins(_EDGE_X, 12, _EDGE_X - 4, 8)
        layout.setSpacing(8)
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(2)
        self.search_host = QWidget(self.toolbar)
        self.search_host.setFixedHeight(max(_SEARCH_H, _TOOL_BTN))
        self.search_host.installEventFilter(self)
        header.addWidget(self.search_host, 1)
        self.title_label = QLabel(self.search_host)
        self.title_label.setObjectName("clipboardTitle")
        self.title_label.setTextFormat(Qt.TextFormat.PlainText)
        self.title_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.search_input = LineEdit(self.search_host, use_default_style=False)
        self.search_input.setObjectName("recordSearch")
        self.search_input.setFixedHeight(_SEARCH_H)
        self.search_input.hide()
        self.search_input.installEventFilter(self)
        self.search_btn = QToolButton(self.search_host)
        self.search_btn.clicked.connect(self._expand_search)
        self.search_btn.setObjectName("chromeButton")
        self.search_btn.setFixedSize(_TOOL_BTN, _TOOL_BTN)
        self.search_btn.setIconSize(QSize(_TOOL_ICON, _TOOL_ICON))
        self.search_btn.setToolTip(self.tr("Search clipboard"))
        self.search_btn.installEventFilter(self)
        self._search_progress = 0.0
        self._search_animation = QVariantAnimation(self)
        self._search_animation.setDuration(200)
        self._search_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._search_animation.valueChanged.connect(self._layout_search)
        self._search_animation.finished.connect(self._finish_search_animation)
        self._search_hover_timer = QTimer(self)
        self._search_hover_timer.setSingleShot(True)
        self._search_hover_timer.setInterval(450)
        self._search_hover_timer.timeout.connect(lambda: self._expand_search(focus=False))
        self._search_idle_timer = QTimer(self)
        self._search_idle_timer.setSingleShot(True)
        self._search_idle_timer.setInterval(5000)
        self._search_idle_timer.timeout.connect(self._collapse_search)
        self.search_input.textChanged.connect(self._on_search_changed)
        self.search_input.textChanged.connect(self._update_search_background)
        self.search_input.textChanged.connect(lambda _text: self._search_idle_timer.start())
        self._search_action = self.search_input.addAction(QIcon(), QLineEdit.ActionPosition.LeadingPosition)
        self._clear_search_action = self.search_input.addAction(QIcon(), QLineEdit.ActionPosition.TrailingPosition)
        self._clear_search_action.triggered.connect(self._clear_search)
        self._clear_search_action.setVisible(False)
        header.addSpacing(6)
        self.keep_open_btn = QToolButton()
        self.keep_open_btn.setCheckable(True)
        self.keep_open_btn.setChecked(not self.config.get_clipboard_close_after_paste())
        self.keep_open_btn.clicked.connect(lambda checked: self._toggle_close_after_paste(not checked))
        self.menu_btn = QToolButton()
        self.menu_btn.clicked.connect(self._show_main_menu)
        self.close_btn = QToolButton()
        self.close_btn.clicked.connect(self.close)
        for button in (self.keep_open_btn, self.menu_btn, self.close_btn):
            button.setObjectName("chromeButton")
            button.setFixedSize(_TOOL_BTN, _TOOL_BTN)
            button.setIconSize(QSize(_TOOL_ICON, _TOOL_ICON))
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            header.addWidget(button)
        layout.addLayout(header)
        types = QHBoxLayout()
        types.setContentsMargins(0, 0, 0, 0)
        types.setSpacing(2)
        self.scope_row = types
        self.type_filter_rail = QWidget(self.toolbar)
        self.type_filter_rail.setObjectName("typeFilterRail")
        self.type_filter_rail.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        segments = QHBoxLayout(self.type_filter_rail)
        segments.setContentsMargins(3, 3, 3, 3)
        segments.setSpacing(2)
        types.addWidget(self.type_filter_rail)
        self.type_filter_group = QButtonGroup(self)
        self.type_filter_index = 0
        self.type_filter_labels = [self.tr(label) for label in _TYPE_FILTERS]
        self.type_filter_buttons = []
        for index, label in enumerate(self.type_filter_labels):
            button = QToolButton()
            button.setObjectName("typeFilter")
            button.setText(label)
            button.setCheckable(True)
            button.setChecked(index == 0)
            button.setFixedHeight(_SEGMENT_H - 6)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            self.type_filter_group.addButton(button, index)
            self.type_filter_buttons.append(button)
            segments.addWidget(button)
        self.type_filter_group.idClicked.connect(self._set_type_filter)
        types.addStretch()
        self.sort_btn = QToolButton()
        self.sort_btn.setObjectName("sortButton")
        self.sort_btn.setFixedHeight(_SEGMENT_H)
        self.sort_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.sort_btn.clicked.connect(self._show_sort_menu)
        types.addWidget(self.sort_btn)
        self.filter_btn = QToolButton()
        self.filter_btn.setObjectName("chromeButton")
        self.filter_btn.setCheckable(True)
        self.filter_btn.setFixedSize(_TOOL_BTN, _SEGMENT_H)
        self.filter_btn.setIconSize(QSize(_TOOL_ICON, _TOOL_ICON))
        self.filter_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.filter_btn.clicked.connect(self._toggle_time_filter_bar)
        # 分组下拉（GroupBar 顶部模式）会插在这个按钮之前
        types.addWidget(self.filter_btn)
        layout.addLayout(types)

        self.time_filter_bar = QWidget()
        self.time_filter_bar.setObjectName("filterPanel")
        filter_layout = QVBoxLayout(self.time_filter_bar)
        filter_layout.setContentsMargins(0, 0, 0, 6)
        filter_layout.setSpacing(8)
        presets = QHBoxLayout()
        self.date_filter_btn = QToolButton()
        self.date_filter_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.date_menu = QMenu(self.date_filter_btn)
        self.date_filter_btn.setMenu(self.date_menu)
        self._date_preset = "any"
        self._date_actions = []
        for key, days in _DATE_PRESETS:
            action = self.date_menu.addAction("")
            action.setCheckable(True)
            action.triggered.connect(lambda _checked=False, k=key, d=days: self._set_date_preset(k, d))
            self._date_actions.append(action)
        presets.addWidget(self.date_filter_btn)
        presets.addStretch()
        self.reset_filter_btn = QToolButton()
        self.reset_filter_btn.clicked.connect(self._reset_filters)
        presets.addWidget(self.reset_filter_btn)
        filter_layout.addLayout(presets)
        dates = QHBoxLayout()
        dates.setSpacing(6)
        today = QDate.currentDate()
        self.start_date_edit = QDateEdit(today.addDays(-7))
        self.end_date_edit = QDateEdit(today)
        for edit in (self.start_date_edit, self.end_date_edit):
            edit.setCalendarPopup(True)
            edit.setDisplayFormat("yyyy/MM/dd")
            edit.setMinimumWidth(108)
            edit.setFixedHeight(28)
            edit.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        dates.addWidget(self.start_date_edit, 1)
        self.time_filter_separator = QLabel(self.tr("to"))
        dates.addWidget(self.time_filter_separator)
        dates.addWidget(self.end_date_edit, 1)
        self.apply_time_filter_btn = QToolButton()
        self.apply_time_filter_btn.setMinimumHeight(28)
        self.apply_time_filter_btn.clicked.connect(self._apply_time_range_filter)
        dates.addWidget(self.apply_time_filter_btn)
        filter_layout.addLayout(dates)
        self.filter_error = QLabel()
        self.filter_error.setWordWrap(True)
        self.filter_error.hide()
        filter_layout.addWidget(self.filter_error)
        self.time_filter_bar.hide()
        layout.addWidget(self.time_filter_bar)
        self._apply_date_filter_locale()
        self.left_layout.addWidget(self.toolbar)

    def _apply_toolbar_styles(self):
        """头部与底栏的统一样式。

        类型筛选与公共 SegmentedWidget 共用浅底轨道、实体选中项的视觉层级。
        窗口级按钮（固定/更多/关闭/筛选）不用软底表示开关，只给图标上强调色，
        避免与类型分段的「选中」混淆。
        """
        p = surface_palette(self.current_theme)
        font = QFont()
        font.setFamilies(UI_FAMILIES)
        font.setPixelSize(15)
        font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias | QFont.StyleStrategy.PreferOutline)
        font.setHintingPreference(QFont.HintingPreference.PreferFullHinting)
        self.setFont(font)
        r = _CONTROL_RADIUS
        self.toolbar.setStyleSheet(f"""
            QWidget#toolbar {{ background: transparent; border: none; border-bottom: 1px solid {rgba(p.hairline)}; }}
            QLabel {{ background: transparent; color: {rgba(p.text_secondary)}; font-size: 15px; }}
            QLabel#clipboardTitle {{ color: {rgba(p.text)}; font-size: 16px; font-weight: 500; }}
            QWidget#typeFilterRail {{ background: {rgba(p.control)}; border: none; border-radius: {r + 2}px; }}
            QToolButton {{ background: transparent; color: {rgba(p.text_secondary)}; font-size: 15px;
                border: 1px solid transparent; border-radius: {r}px; padding: 0 10px; }}
            QToolButton:hover {{ background: {rgba(p.control_hover)}; color: {rgba(p.text)}; }}
            QToolButton:pressed {{ background: {rgba(p.control_pressed)}; }}
            QToolButton#typeFilter {{ border-radius: {r - 2}px; }}
            QToolButton#typeFilter:checked {{ background: {self.current_theme.colors.bg_secondary}; color: {rgba(p.text)};
                border-color: {rgba(p.hairline)}; font-weight: 500; }}
            QToolButton#chromeButton {{ padding: 0; }}
            QToolButton#chromeButton:checked {{ background: transparent; }}
            QToolButton#chromeButton:checked:hover {{ background: {rgba(p.control_hover)}; }}
            QToolButton:focus {{ border-color: {rgba(p.accent)}; }}
            QToolButton::menu-indicator {{ image: none; }}
        """)
        self._apply_search_input_style()
        self._search_action.setIcon(glyph_icon("magnifier", _TOOL_ICON, p.text_tertiary.name()))
        self.search_btn.setIcon(glyph_icon("magnifier", _TOOL_ICON, p.text_secondary.name()))
        self._clear_search_action.setIcon(glyph_icon("close", 14, p.text_tertiary.name()))
        self.menu_btn.setIcon(glyph_icon("more", _TOOL_ICON, p.text_secondary.name()))
        self.close_btn.setIcon(glyph_icon("close", _TOOL_ICON, p.text_secondary.name()))
        self.keep_open_btn.setIcon(svg_icon(
            "fluent_icons/Pin.svg", _TOOL_ICON, p.accent.name() if self.keep_open_btn.isChecked() else p.text_secondary.name()))
        self.filter_btn.setIcon(svg_icon("fluent_icons/Filter.svg", _TOOL_ICON, p.text_secondary.name()))
        self.bottom_bar.setStyleSheet(f"""
            QWidget#keyboardBar {{ background: transparent; border-top: 1px solid {rgba(p.hairline)}; }}
            QLabel {{ color: {rgba(p.text_tertiary)}; background: transparent; border: none; font-size: 12px; }}
        """)
        self.date_menu.setStyleSheet(self._get_menu_style())
        self._apply_time_filter_styles()
        self._retranslate_ui()

    def _set_date_preset(self, key, days):
        self._date_preset = key
        today = QDate.currentDate()
        if days is None:
            self.controller.set_time_range_text("")
        else:
            self.start_date_edit.setDate(today.addDays(-days))
            self.end_date_edit.setDate(today)
            self._apply_time_range_filter()
            self._date_preset = key
        self._update_date_menu_label()
        self._update_scope_bar()

    def _update_date_menu_label(self):
        labels = [self.tr("Any time"), self.tr("Today"), self.tr("Last 7 days"), self.tr("Last 30 days")]
        for (key, _), action, label in zip(_DATE_PRESETS, self._date_actions, labels):
            action.setText(label)
            action.setChecked(self._date_preset == key)
        label = next((labels[i] for i, (key, _) in enumerate(_DATE_PRESETS) if key == self._date_preset), self.tr("Custom dates"))
        self.date_filter_btn.setText(label)

    def _update_scope_bar(self):
        if not hasattr(self, "status_label"):
            return
        count = self.list_widget.count()
        in_history = self.controller.current_group_id is None
        sort_labels = {"default": self.tr("Default order"), "newest": self.tr("Newest first"),
                       "oldest": self.tr("Oldest first"), "frequent": self.tr("Most used")}
        self.sort_btn.setText(sort_labels[self.controller.sort_order] + " ▾" if in_history else self.tr("Manual order"))
        self.sort_btn.setEnabled(in_history)
        self.sort_btn.setToolTip(self.tr("Pinned items always come first") if in_history
                                 else self.tr("Use Move Up / Move Down in the context menu"))
        filters = bool(self.search_input.text().strip() or self.type_filter_index or self._date_preset != "any"
                       or self.controller.source_filter or self.controller.tag_filter_id)
        # 空列表不报「0 条」；有筛选时说「找到」，否则说「共」
        if count == 0:
            self.status_label.setText("")
        elif filters:
            self.status_label.setText(self.tr("{n} found").format(n=count))
        else:
            self.status_label.setText(self.tr("{n} items").format(n=count))
        # 空状态里键盘提示没有意义，整条底栏收起
        if getattr(self, "_image_indexing", False):
            prefix = self.status_label.text()
            self.status_label.setText((prefix + " · " if prefix else "") + self.tr("Indexing image text…"))
        self.bottom_bar.setVisible(count > 0)
        self.reset_filter_btn.setEnabled(filters)
        p = surface_palette(self.current_theme)
        self.filter_btn.setIcon(svg_icon("fluent_icons/Filter.svg", 16, p.accent.name() if filters else p.text_secondary.name()))
        source = self.controller.source_filter
        self.filter_btn.setToolTip(self.tr("Source: {name}").format(name=source) if source else self.tr("Filter"))
        self._update_empty_state()

    def _show_sort_menu(self):
        menu = QMenu(self)
        menu.setStyleSheet(self._get_menu_style())
        for key, label in (("default", self.tr("Default order")), ("newest", self.tr("Newest first")),
                           ("oldest", self.tr("Oldest first")), ("frequent", self.tr("Most used"))):
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(self.controller.sort_order == key)
            action.triggered.connect(lambda _checked=False, order=key: self.controller.set_sort_order(order))
        menu.addSeparator()
        menu.addAction(self.tr("Pinned items always come first")).setEnabled(False)
        menu.exec(self.sort_btn.mapToGlobal(QPoint(0, self.sort_btn.height())))

    def _reset_filters(self):
        if hasattr(self, "_search_timer"):
            self._search_timer.stop()
        self.search_input.blockSignals(True)
        self.search_input.clear()
        self.search_input.blockSignals(False)
        self._clear_search_action.setVisible(False)
        self._date_preset = "any"
        self._update_type_filter_button(0)
        self.filter_error.hide()
        self.controller.clear_all_filters()
        self._update_date_menu_label()
        self._update_scope_bar()

    def _get_menu_style(self):
        return ThemeStyleGenerator(self.current_theme).generate_menu_style()

    def _show_main_menu(self):
        if hasattr(self, "_settings_menu") and self._settings_menu is not None and self._settings_menu.isVisible():
            self._settings_menu.close()
            self._settings_menu = None
            return

        if hasattr(self, "_menu_close_time") and (perf_counter() - self._menu_close_time) < 0.3:
            return

        from ..panels.setting_panel import show_setting_menu

        self._settings_menu = show_setting_menu(
            parent=self,
            menu_style=self._get_menu_style(),
            tr=self.tr,
            paste_with_html=self.controller.paste_with_html,
            auto_paste=self.config.get_clipboard_auto_paste(),
            close_after_paste=self.config.get_clipboard_close_after_paste(),
            move_to_top=self.config.get_clipboard_move_to_top_on_paste(),
            show_metadata=self.config.get_clipboard_show_metadata(),
            preserve_search=self.config.get_clipboard_preserve_search(),
            window_opacity=self.window_opacity,
            current_font_size=self.config.get_clipboard_font_size(),
            current_theme_name=self.theme_manager.get_current_theme().name,
            current_group_bar_position=self.group_bar_position,
            opacity_options=self.config.get_clipboard_window_opacity_options(),
            font_size_options=self.config.get_clipboard_font_size_options(),
            on_toggle_paste_html=self._toggle_paste_with_html,
            on_toggle_auto_paste=self._toggle_auto_paste,
            on_toggle_close_after_paste=self._toggle_close_after_paste,
            on_toggle_move_to_top=self._toggle_move_to_top_on_paste,
            on_toggle_show_metadata=self._toggle_show_metadata,
            on_toggle_preserve_search=self._toggle_preserve_search,
            on_set_opacity=self._set_window_opacity,
            on_set_font_size=self._set_font_size,
            on_set_theme=self._set_theme,
            on_add_item=self._on_add_item_clicked,
            on_set_group_bar_position=self._set_group_bar_position,
            anchor_pos=self.menu_btn.mapToGlobal(QPoint(0, 0)),
        )

        def _on_menu_hide():
            self._menu_close_time = perf_counter()
            self._settings_menu = None

        self._settings_menu.aboutToHide.connect(_on_menu_hide)

    def _toggle_time_filter_bar(self, checked: bool):
        PreviewPopup.instance().hide_preview()
        self.time_filter_bar.setVisible(checked)
        self.filter_btn.setChecked(checked)

    def _apply_time_range_filter(self):
        start_text = self.start_date_edit.date().toString("yyyy/MM/dd")
        end_text = self.end_date_edit.date().toString("yyyy/MM/dd")
        range_text = f"{start_text}-{end_text}"
        ok = self.controller.set_time_range_text(range_text)
        self.start_date_edit.setProperty("hasError", not ok)
        self.end_date_edit.setProperty("hasError", not ok)
        self.start_date_edit.style().unpolish(self.start_date_edit)
        self.start_date_edit.style().polish(self.start_date_edit)
        self.end_date_edit.style().unpolish(self.end_date_edit)
        self.end_date_edit.style().polish(self.end_date_edit)
        self._apply_time_filter_styles()
        self.filter_error.setText(self.tr("End date must be on or after start date."))
        self.filter_error.setVisible(not ok)
        if ok:
            self._date_preset = "custom"
            self._update_date_menu_label()
            self._update_scope_bar()

    def _close_time_filter_bar(self):
        self._toggle_time_filter_bar(False)

    def _clear_time_and_type_filters(self):
        today = QDate.currentDate()
        self.start_date_edit.setDate(today.addDays(-7))
        self.end_date_edit.setDate(today)
        self.start_date_edit.setProperty("hasError", False)
        self.end_date_edit.setProperty("hasError", False)
        self._update_type_filter_button(0)
        self._date_preset = "any"
        self.filter_error.hide()
        self.controller.clear_time_and_type_filters()
        self._update_date_menu_label()
        self._update_scope_bar()

    def _toggle_paste_with_html(self, checked: bool):
        self.controller.set_paste_with_html(checked)

    def _toggle_auto_paste(self, checked: bool):
        self.controller.set_auto_paste(checked)
        self._retranslate_ui()

    def _toggle_close_after_paste(self, checked: bool):
        self.config.set_clipboard_close_after_paste(checked)
        self.keep_open_btn.setChecked(not checked)
        self._apply_toolbar_styles()

    def _toggle_move_to_top_on_paste(self, checked: bool):
        self.controller.set_move_to_top_on_paste(checked)

    def _toggle_show_metadata(self, checked: bool):
        self.config.set_clipboard_show_metadata(checked)
        if hasattr(self, "_item_delegate"):
            self._item_delegate.set_show_metadata(checked)
        self.controller.load_history()

    def _toggle_preserve_search(self, checked: bool):
        self.config.set_clipboard_preserve_search(checked)

    def _set_window_opacity(self, percent: int):
        self.window_opacity = percent
        self.config.set_clipboard_window_opacity(percent)
        if hasattr(self, "_item_delegate"):
            self._item_delegate.set_window_opacity(percent)
        self._apply_opacity()
        self._refresh_list()

    def _set_font_size(self, size: int):
        self.display_lines = size
        self.config.set_clipboard_font_size(size)
        if hasattr(self, "_item_delegate"):
            self._item_delegate.set_display_lines(size)
        self._refresh_list()

    def _set_theme(self, theme_name: str):
        get_theme_manager().set_theme(theme_name)

    def _on_font_size_changed(self, size: int):
        self.display_lines = size
        if hasattr(self, "_item_delegate"):
            self._item_delegate.set_display_lines(size)
        self._refresh_list()

    def _on_opacity_changed(self, percent: int):
        self.window_opacity = percent
        if hasattr(self, "_item_delegate"):
            self._item_delegate.set_window_opacity(percent)
        self._apply_opacity()
        self._refresh_list()

    def _setup_shortcuts(self):
        self._shortcut_handler = ClipboardShortcutHandler(self)

    def _load_history(self):
        self.controller.load_history()

    def _load_more_items(self):
        self.controller._load_more_items()

    def _refresh_list(self):
        PreviewPopup.instance().hide_preview()
        self.selection_manager.reset()
        self._item_delegate.reset_hover()
        self._hide_quick_actions()

        self.list_widget.setUpdatesEnabled(False)
        self.list_widget.clear()

        show_metadata = self.config.get_clipboard_show_metadata()
        self._item_delegate.set_show_metadata(show_metadata)
        self._item_delegate.set_display_lines(self.display_lines)
        self._item_delegate.set_window_opacity(self.window_opacity)
        self._item_delegate.set_theme(self.current_theme)
        self._item_delegate.set_highlighted_id(None)

        for item in self.controller.current_items:
            list_item = QListWidgetItem()
            list_item.setData(ROLE_ITEM_ID, item.id)
            list_item.setData(ROLE_ITEM_DATA, item)
            self.list_widget.addItem(list_item)

        self.list_widget.setUpdatesEnabled(True)
        self.list_widget.scrollToTop()
        self.list_widget.viewport().update()

    def _on_load_completed(self):
        QTimer.singleShot(0, self._check_and_load_more_if_needed)

    def _check_and_load_more_if_needed(self):
        scrollbar = self.list_widget.verticalScrollBar()
        is_visible = scrollbar.isVisible()
        maximum = scrollbar.maximum()
        has_more = self.controller.has_more_items()

        if (not is_visible or maximum == 0) and has_more:
            if self._auto_fill_remaining <= 0:
                return
            self._auto_fill_remaining -= 1
            self.controller._load_more_items()

    def _append_items(self, items: List[ClipboardItem]):
        log_debug(T("📝 _append_items 被调用，准备追加 {count} 条数据", count=len(items)), "Clipboard")

        self.list_widget.setUpdatesEnabled(False)

        for item in items:
            list_item = QListWidgetItem()
            list_item.setData(ROLE_ITEM_ID, item.id)
            list_item.setData(ROLE_ITEM_DATA, item)
            self.list_widget.addItem(list_item)

        self.list_widget.setUpdatesEnabled(True)
        self.list_widget.viewport().update()

    def _on_scroll(self, value: int):
        scrollbar = self.list_widget.verticalScrollBar()
        maximum = scrollbar.maximum()
        self.controller.check_scroll_load(value, maximum)
        self._reposition_quick_actions()

    def _on_scrollbar_range_changed(self, min_val: int, max_val: int):
        _ = (min_val, max_val)
        self.list_widget.viewport().update()

    def _on_search_changed(self, text: str):
        _ = text
        if hasattr(self, "_search_timer"):
            self._search_timer.stop()
        else:
            self._search_timer = QTimer(self)
            self._search_timer.setSingleShot(True)
            self._search_timer.timeout.connect(lambda: self.controller.set_search_text(self.search_input.text()))

        self._search_timer.start(300)

    def _on_selection_changed(self):
        selected_items = self.list_widget.selectedItems()
        if selected_items:
            selected_id = selected_items[0].data(Qt.ItemDataRole.UserRole)
            self._set_highlighted_item(selected_id)
        else:
            self._set_highlighted_item(None)

    def _on_delegate_item_entered(self, list_item: QListWidgetItem):
        item_id = list_item.data(ROLE_ITEM_ID)
        if item_id is None:
            return
        self._set_highlighted_item(item_id)

        row = self.list_widget.row(list_item)
        if row >= 0:
            self.selection_manager.set_hovered_index(row)
            self._item_delegate.set_hovered_row(row)
            if not self._hover_anim_timer.isActive():
                self._hover_anim_timer.start()
                QTimer.singleShot(_HOVER_ANIM_MS, self._hover_anim_timer.stop)
            self._show_quick_actions_for_row(row)

        item_data = list_item.data(ROLE_ITEM_DATA)
        if item_data:
            popup = PreviewPopup.instance()
            pos = QCursor.pos()
            if self.search_input.hasFocus() or QApplication.activePopupWidget() is not None:
                return
            popup.show_preview(item_data, pos, delay_ms=450, avoid_rect=self.frameGeometry())

    def _set_highlighted_item(self, item_id: Optional[int]):
        if self._item_delegate._highlighted_id != item_id:
            self._item_delegate.set_highlighted_id(item_id)
            self.list_widget.viewport().update()

    def _layout_search(self, progress=None):
        if progress is not None:
            self._search_progress = float(progress)
        width = round(_TOOL_BTN + (self.search_host.width() - _TOOL_BTN) * self._search_progress)
        self.search_input.setGeometry(0, (self.search_host.height() - _SEARCH_H) // 2, width, _SEARCH_H)
        self.search_btn.move(0, (self.search_host.height() - _TOOL_BTN) // 2)
        title_width = max(0, self.search_host.width() - _TOOL_BTN - 12)
        self.title_label.setGeometry(_TOOL_BTN + 8, 0, title_width, self.search_host.height())
        title = (self.tr("Search: {query}").format(query=self.search_input.text())
                 if self.search_input.text() else self.tr("Clipboard History"))
        self.title_label.setText(self.title_label.fontMetrics().elidedText(title, Qt.TextElideMode.ElideRight, title_width))
        self.title_label.setVisible(self._search_progress == 0)

    def _finish_search_animation(self):
        if self._search_progress == 0:
            self.search_input.hide()
            self.search_btn.show()

    def _expand_search(self, _checked=False, *, focus=True):
        self._search_hover_timer.stop()
        self._search_animation.stop()
        self.title_label.hide()
        self.search_btn.hide()
        self.search_input.show()
        self._search_animation.setStartValue(self._search_progress)
        self._search_animation.setEndValue(1.0)
        self._search_animation.start()
        self._search_idle_timer.start()
        if focus:
            self.search_input.setFocus()

    def _collapse_search(self):
        # Keep the query/filter intact; reopening restores the same text.
        if getattr(self, "_search_composing", False):
            self._search_idle_timer.start()
            return
        self._search_hover_timer.stop()
        self._search_hover_blocked = True
        self._search_idle_timer.stop()
        self._search_animation.stop()
        self.search_input.clearFocus()
        self._search_animation.setStartValue(self._search_progress)
        self._search_animation.setEndValue(0.0)
        self._search_animation.start()

    def _update_search_background(self, text: str):
        self._clear_search_action.setVisible(bool(text))
        PreviewPopup.instance().hide_preview()
        self._update_scope_bar()
        self._layout_search()

    def _apply_search_input_style(self, has_text: bool = False):
        p = surface_palette(self.current_theme)
        fill = self.current_theme.colors.bg_secondary
        fill_focus = fill
        self.search_input.setStyleSheet(f"""
            QLineEdit {{ background: {fill}; color: {rgba(p.text)};
                border: 1px solid {rgba(p.hairline)}; border-radius: {_CONTROL_RADIUS}px; padding: 0 10px;
                font-size: 15px; selection-background-color: {rgba(p.accent)}; selection-color: {self.current_theme.colors.bg_primary}; }}
            QLineEdit:focus {{ background: {fill_focus}; border-color: {rgba(p.accent)}; }}
        """)

    def _set_menu_btn_icon(self, hovered: bool):
        c = self.current_theme.colors
        self.menu_btn.setIcon(glyph_icon("more", 16, c.text_primary if hovered else c.text_secondary))

    def _apply_time_filter_styles(self):
        generator = ThemeStyleGenerator(self.current_theme)
        date_style = generator.generate_time_filter_date_edit_style()
        calendar_style = generator.generate_time_filter_calendar_style()
        for edit in (self.start_date_edit, self.end_date_edit):
            edit.setStyleSheet(date_style)
            edit.calendarWidget().setStyleSheet(calendar_style)
        self.filter_error.setStyleSheet(f"color: {self.current_theme.colors.error}; font-size: 12px;")

    # ========== 行尾快捷操作（复制 / 置顶 / 删除） ==========

    def _create_quick_action_buttons(self):
        self.quick_actions_bar = QWidget(self.list_widget.viewport())
        layout = QHBoxLayout(self.quick_actions_bar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(_QUICK_BTN_GAP)
        self._quick_action_buttons = {}
        self._quick_action_icons = {"copy": "fluent_icons/Copy.svg", "pin": "fluent_icons/Pin.svg"}
        for key in ("copy", "pin", "more"):
            btn = QToolButton(self.quick_actions_bar)
            btn.setFixedSize(_QUICK_BTN_SIZE, _QUICK_BTN_SIZE)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setIconSize(QSize(_QUICK_BTN_ICON_SIZE, _QUICK_BTN_ICON_SIZE))
            btn.clicked.connect(lambda _checked=False, k=key: self._on_quick_action(k))
            layout.addWidget(btn)
            self._quick_action_buttons[key] = btn
        self.quick_actions_bar.adjustSize()
        self._quick_opacity_effect = QGraphicsOpacityEffect(self.quick_actions_bar)
        self._quick_opacity_effect.setOpacity(0.0)
        self.quick_actions_bar.setGraphicsEffect(self._quick_opacity_effect)
        self._quick_action_row = -1
        self._quick_action_item_id: Optional[int] = None
        self._quick_fade = QVariantAnimation(self)
        self._quick_fade.setDuration(140)
        self._quick_fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._quick_fade.valueChanged.connect(lambda v: self._quick_opacity_effect.setOpacity(float(v)))
        self._quick_fade.finished.connect(self._on_quick_fade_finished)
        self.quick_actions_bar.hide()
        self._refresh_quick_action_styles()

    def _refresh_quick_action_styles(self):
        if not hasattr(self, "_quick_action_buttons"):
            return
        c = self.current_theme.colors
        generator = ThemeStyleGenerator(self.current_theme)
        is_dark = QColor(c.text_primary).value() >= 128
        # 半透明磁贴：行内容半透地透出来但又有足够对比托住图标
        tile_bg = "rgba(24, 24, 27, 0.96)" if is_dark else "rgba(255, 255, 255, 0.92)"
        border = generator._hex_to_rgba(c.border_primary, 0.9)
        qss = f"""
            QToolButton {{
                background: {tile_bg};
                border: 1px solid {border};
                border-radius: 8px;
            }}
            QToolButton:hover {{
                background: {c.bg_hover};
            }}
            QToolButton:pressed {{
                background: {c.bg_selected};
            }}
        """
        self._quick_action_buttons["copy"].setToolTip(self.tr("Copy"))
        self._quick_action_buttons["more"].setToolTip(self.tr("More"))
        for key, btn in self._quick_action_buttons.items():
            btn.setStyleSheet(qss)
            if key in ("copy", "more"):
                btn.setIcon(glyph_icon(key, _QUICK_BTN_ICON_SIZE, c.text_secondary))
            else:
                btn.setIcon(svg_icon(self._quick_action_icons[key], _QUICK_BTN_ICON_SIZE, c.text_secondary))

    def _tinted_icon(self, svg_name: str, tint: str) -> QIcon:
        try:
            from core.resource_manager import ResourceManager

            icon = ResourceManager.get_icon_by_name(svg_name)
            source = icon.pixmap(26, 26)
            if source.isNull():
                return icon
            tinted = QPixmap(source.size())
            tinted.fill(Qt.GlobalColor.transparent)
            painter = QPainter(tinted)
            painter.drawPixmap(0, 0, source)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
            painter.fillRect(tinted.rect(), QColor(tint))
            painter.end()
            return QIcon(tinted)
        except Exception as e:
            log_exception(e, T("加载快捷操作图标"))
            return QIcon()

    def _on_quick_action(self, key: str):
        item_id = self._quick_action_item_id
        if item_id is None:
            return
        if key == "copy":
            copied = self.manager.paste_item(item_id, self.controller.paste_with_html, False)
            if copied and self.controller.current_group_id is None and self.controller.sort_order == "frequent":
                self.controller.load_history()
            self.status_label.setText(self.tr("Copied") if copied else self.tr("Copy failed"))
            self._feedback_timer.start(1600)
        elif key == "pin":
            self._toggle_pin(item_id)
        elif key == "more":
            row = self.list_widget.item(self._quick_action_row)
            if row is not None:
                self._show_context_menu(self.list_widget.visualItemRect(row).center())

    def _show_quick_actions_for_row(self, row: int):
        if not hasattr(self, "quick_actions_bar"):
            return
        if row < 0 or row >= self.list_widget.count():
            self._hide_quick_actions()
            return
        item = self.list_widget.item(row)
        rect = self.list_widget.visualItemRect(item) if item is not None else None
        if item is None or rect is None or not rect.isValid():
            self._hide_quick_actions()
            return
        item_data = item.data(ROLE_ITEM_DATA)
        if not item_data:
            self._hide_quick_actions()
            return

        self._quick_action_row = row
        self._quick_action_item_id = item.data(ROLE_ITEM_ID)
        pin_btn = self._quick_action_buttons["pin"]
        pin_btn.setToolTip(self.tr("Unpin from Top") if item_data.is_pinned else self.tr("Pin to Top"))
        pin_btn.setIcon(self._tinted_icon(
            "fluent_icons/Pin.svg", self.current_theme.colors.accent_primary if item_data.is_pinned else self.current_theme.colors.text_secondary))

        bar = self.quick_actions_bar
        x = max(0, rect.right() + 1 - _QUICK_BAR_RIGHT_MARGIN - bar.width())
        y = rect.top() + (rect.height() - bar.height()) // 2
        self._item_delegate.set_action_reserve(row, bar.width() + 8)
        self.list_widget.viewport().update()
        bar.move(x, y)
        if not bar.isVisible():
            bar.show()
        bar.raise_()
        self._start_quick_fade(1.0)

    def _start_quick_fade(self, target: float):
        self._quick_fade.stop()
        self._quick_fade.setStartValue(self._quick_opacity_effect.opacity())
        self._quick_fade.setEndValue(target)
        self._quick_fade.start()

    def _on_quick_fade_finished(self):
        if self._quick_opacity_effect.opacity() <= 0.01:
            self.quick_actions_bar.hide()

    def _hide_quick_actions(self):
        self._item_delegate.set_action_reserve(-1, 0)
        self.list_widget.viewport().update()
        if not hasattr(self, "quick_actions_bar") or not self.quick_actions_bar.isVisible():
            self._quick_action_row = -1
            self._quick_action_item_id = None
            return
        self._quick_action_row = -1
        self._quick_action_item_id = None
        self._start_quick_fade(0.0)

    def _hide_quick_actions_if_cursor_outside(self):
        bar = getattr(self, "quick_actions_bar", None)
        if bar is None or not bar.isVisible():
            return
        pos = self.list_widget.viewport().mapFromGlobal(QCursor.pos())
        if not self.list_widget.viewport().rect().contains(pos):
            self._hide_quick_actions()
        elif not bar.geometry().adjusted(-4, -4, 4, 4).contains(pos):
            self._hide_quick_actions()

    def _reposition_quick_actions(self):
        if getattr(self, "_quick_action_row", -1) >= 0:
            row = self._quick_action_row
            self._quick_action_row = -1
            self._show_quick_actions_for_row(row)

    # ========== 空态 ==========

    def _create_empty_state(self):
        self.empty_state = QWidget(self.list_widget.viewport())
        self.empty_state.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.empty_state.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(self.empty_state)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        self.empty_state_icon = QLabel()
        self.empty_state_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_state_label = QLabel()
        self.empty_state_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_state_label.setText(self.tr("No records yet"))
        self.empty_state_detail = QLabel()
        self.empty_state_detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_state_detail.setWordWrap(True)
        layout.addWidget(self.empty_state_icon)
        layout.addWidget(self.empty_state_label)
        layout.addWidget(self.empty_state_detail)
        self.empty_state.hide()

    def _empty_state_pixmap(self) -> QPixmap:
        size, dpr = 64, 2
        pixmap = QPixmap(size * dpr, size * dpr)
        pixmap.setDevicePixelRatio(dpr)
        pixmap.fill(Qt.GlobalColor.transparent)
        color = QColor(self.current_theme.colors.text_tertiary)
        color.setAlpha(110)
        pen = QPen(color, 3)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(14, 12, 36, 42, 8, 8)   # 剪贴板板身
        painter.drawRoundedRect(24, 8, 16, 8, 4, 4)     # 顶部夹子
        painter.drawLine(21, 26, 43, 26)
        painter.drawLine(21, 34, 43, 34)
        painter.drawLine(21, 42, 36, 42)
        painter.end()
        return pixmap

    def _update_empty_state(self):
        if not hasattr(self, "empty_state"):
            return
        if self.list_widget.count() > 0 or not self.isVisible():
            self.empty_state.hide()
            return
        c = self.current_theme.colors
        self.empty_state_icon.setPixmap(self._empty_state_pixmap())
        self.empty_state_label.setStyleSheet(
            f"background: transparent; color: {c.text_primary}; font-size: 15px; font-weight: 500;"
        )
        self.empty_state_detail.setStyleSheet(
            f"background: transparent; color: {c.text_secondary}; font-size: 15px;"
        )
        keyword = self.search_input.text().strip()
        filtered = bool(keyword or self.type_filter_index or self._date_preset != "any"
                        or self.controller.source_filter or self.controller.tag_filter_id)
        if keyword:
            shown = keyword if len(keyword) <= 12 else keyword[:11] + "…"
            title = self.tr("No results for “{q}”").format(q=shown)
            detail = self.tr("Try a different keyword, or clear the filters.")
        elif filtered:
            title, detail = self.tr("Nothing matches these filters"), self.tr("Try a different keyword, or clear the filters.")
        elif self.controller.current_group_id is not None:
            title = self.tr("This group is empty")
            detail = self.tr("Right-click any item and choose “Move to Group” to add it here.")
        else:
            title = self.tr("Nothing here yet")
            detail = self.tr("Text, images and files you copy will show up here.")
        if keyword and getattr(self, "_image_indexing", False):
            title = self.tr("Indexing image text…")
        self.empty_state_label.setText(title)
        self.empty_state_detail.setText(detail)
        viewport = self.list_widget.viewport()
        w, h = min(280, viewport.width() - 32), 150
        x = max(0, (viewport.width() - w) // 2)
        y = max(16, (viewport.height() - h) // 2 - 24)
        self.empty_state.setGeometry(x, y, w, h)
        self.empty_state.raise_()
        self.empty_state.show()

    def _clear_search(self):
        self.search_input.clear()
        self.search_input.setFocus()

    def _update_type_filter_button(self, index: int):
        self.type_filter_index = index
        self.type_filter_buttons[index].setChecked(True)

    def _set_type_filter(self, index: int):
        self._update_type_filter_button(index)
        self.controller.set_content_type_filter(index)
        self._update_scope_bar()

    def _on_group_switched(self, group_id):
        self.group_bar.switch_to_group(group_id)
        self._update_scope_bar()

    def _on_sidebar_entered(self):
        self.selection_manager.clear_selection()
        self._set_highlighted_item(None)
        self.list_widget.setFocus()

    def _on_sidebar_exited(self, prev_item_id):
        self.list_widget.setFocus()
        if prev_item_id is not None:
            self.selection_manager.select_item_id(prev_item_id)
        else:
            self.selection_manager._move_selection(1)

    def _enter_sidebar_mode(self):
        prev_id = self.selection_manager.get_current_item_id()
        self.group_bar.enter_sidebar_mode(prev_id)

    def _on_top_group_switch(self, delta: int):
        self.group_bar.handle_top_group_switch(delta)

    def _on_add_group_clicked(self):
        dialog = get_manage_dialog(self.manager)
        self._connect_manage_dialog(dialog)
        dialog.show_and_activate()

    def _on_add_item_clicked(self):
        dialog = get_manage_dialog(self.manager)
        self._connect_manage_dialog(dialog)
        dialog._switch_page(1)
        dialog.show_and_activate()

    def _connect_manage_dialog(self, dialog: ManageDialog):
        for sig, slot in [
            (dialog.group_added, self.group_bar.refresh_buttons),
            (dialog.data_changed, self._on_manage_data_changed),
        ]:
            sig.connect(slot, Qt.ConnectionType.UniqueConnection)

    def _set_group_bar_position(self, position: str):
        self.group_bar_position = position
        self.selection_manager.group_bar_position = position
        self.group_bar.set_position(position)
        self.config.set_clipboard_group_bar_position(position)
        self._apply_opacity()

    def _is_paste_picker_surface(self, hwnd: int) -> bool:
        """hwnd 是不是这个拾取窗口本身。

        只认它一个。内容编辑窗口、截图标注、翻译窗口同属本进程，但都是用户
        真会往里粘的地方，按进程排除会把它们一起挡掉。
        """
        widget = QWidget.find(hwnd)
        return widget is not None and widget.window() is self

    def _paste_close_callback(self):
        """粘贴后关闭窗口的回调；开关关掉时返回 None，窗口常驻可连续粘贴。"""
        if not self.config.get_clipboard_close_after_paste():
            return None
        return self.close

    def _get_item_data(self, item_id: int) -> Optional[ClipboardItem]:
        for item in self.controller.current_items:
            if item.id == item_id:
                return item
        return None

    def _on_paste_item(self, item_id: int):
        if self.controller.current_group_id is not None:
            groups = self.controller.manager.get_groups()
            current_group = next((group for group in groups if group.id == self.controller.current_group_id), None)
            if current_group is not None and current_group.group_type == GroupType.FILE:
                self._open_file_item(item_id)
                return
        if self.controller.paste_item(item_id, on_close_callback=self._paste_close_callback()):
            self.item_pasted.emit(item_id)

    def _paste_selected(self):
        item_id = self.selection_manager.get_current_item_id()
        if item_id:
            self._on_paste_item(item_id)

    def _show_context_menu(self, pos):
        item = self.list_widget.itemAt(pos)
        if not item:
            return
        item_id = item.data(Qt.ItemDataRole.UserRole)
        if not item_id:
            return

        ctx = self.controller.build_context_menu_data(item_id)
        if ctx is None:
            return

        ClipboardItemContextMenu(
            parent=self,
            menu_style=self._get_menu_style(),
            translate=self.tr,
            action_handlers=self._get_item_context_menu_handlers(item_id),
            dynamic_handler_resolvers=(lambda action_key: self._resolve_item_context_menu_handler(item_id, action_key),),
        ).show(self.list_widget, pos, ctx)

    def _get_item_context_menu_handlers(self, item_id: int):
        return {
            "paste": lambda: self._paste_item_to_clipboard(item_id),
            "pin_image": lambda: self._create_pin_window(item_id),
            "save_image_as": lambda: self._save_image_as(item_id),
            "recognize_image": lambda: self._process_image(item_id),
            "redact_image": lambda: self._process_image(item_id, redact=True),
            "toggle_pin": lambda: self._toggle_pin(item_id),
            "filter_by_source": lambda: self._filter_by_source(item_id),
            "open_file_location": lambda: self._open_file_location(item_id),
            "edit_item": lambda: self._edit_item(item_id),
            "move_item_up": lambda: self._move_item_order(item_id, -1),
            "move_item_down": lambda: self._move_item_order(item_id, 1),
            "delete_item": lambda: self._delete_item(item_id),
        }

    def _start_image_indexing(self):
        indexer = self.manager.start_image_indexing()
        if indexer is not self._image_indexer:
            self._image_indexer = indexer
            if indexer is not None:
                indexer.updated.connect(self._on_image_text_indexed)
                indexer.state_changed.connect(self._on_index_state_changed)
        self._image_indexing = bool(indexer is not None and indexer.busy)

    def _on_index_state_changed(self, busy):
        self._image_indexing = busy
        self._update_scope_bar()
        self._update_empty_state()

    def _on_image_text_indexed(self, _item_id):
        # Refresh a visible search without interrupting an unfiltered clipboard list.
        if self.isVisible() and self.search_input.text().strip():
            self.controller.load_history()

    def _process_image(self, item_id, redact=False):
        from PySide6.QtGui import QImage
        item = self.manager.get_item(item_id)
        if item is None or not item.image_id:
            return
        data = self.manager.get_image_data(item.image_id)
        image = QImage.fromData(data) if data else QImage()
        if image.isNull():
            from ui.dialogs import show_warning_dialog
            show_warning_dialog(self, self.tr("Error"), self.tr("Unable to load image"))
            return
        if redact:
            from text_recognition.redaction_window import show_redaction
            show_redaction(image)
        else:
            from text_recognition import show_text_recognition
            show_text_recognition(image, initial_result=self.manager.image_text_store.get_result(item_id),
                                  query=self.search_input.text().strip())

    def _resolve_item_context_menu_handler(self, item_id: int, action_key: str):
        # "移出分组"
        if action_key == "remove_from_group":
            return lambda: self._move_item_to_group(item_id, None)

        # "移动到分组 xxx"
        prefix = "move_to_group_"
        if action_key.startswith(prefix):
            try:
                group_id = int(action_key[len(prefix):])
            except ValueError:
                return None
            return lambda: self._move_item_to_group(item_id, group_id)

        # "特殊粘贴" 子菜单项
        if action_key.startswith("special_paste_") or action_key.startswith("transform_"):
            return lambda: self._special_paste(item_id, action_key)

        # 文件项特殊粘贴子菜单项
        if action_key.startswith("file_paste_"):
            return lambda: self._file_special_paste(item_id, action_key)

        # 标签勾选
        if action_key.startswith("toggle_tag_"):
            try:
                tag_id = int(action_key[len("toggle_tag_"):])
            except ValueError:
                return None
            return lambda: self.controller.toggle_item_tag(item_id, tag_id)

        if action_key == "new_tag":
            return lambda: self._new_tag_for_item(item_id)
        if action_key == "manage_tags":
            return self._open_tag_manager

        return None

    def _special_paste(self, item_id: int, action_key: str):
        """执行特殊粘贴。"""
        self.controller.paste_transformed_text(
            item_id, action_key, on_close_callback=self._paste_close_callback(), explicit=True
        )
        self.item_pasted.emit(item_id)

    def _file_special_paste(self, item_id: int, action_key: str):
        """执行文件项特殊粘贴。"""
        self.controller.paste_file_text(
            item_id, action_key, on_close_callback=self._paste_close_callback(), explicit=True
        )
        self.item_pasted.emit(item_id)

    def _move_item_to_group(self, item_id: int, group_id: Optional[int]):
        self.controller.move_to_group(item_id, group_id)

    def _move_item_order(self, item_id: int, direction: int):
        self.controller.move_item_order(item_id, self.controller.current_group_id, direction)

    def _edit_item(self, item_id: int):
        self.controller.open_manage_dialog_for_item(
            item_id,
            self.controller.current_group_id,
            group_added_callback=self.group_bar.refresh_buttons,
            data_changed_callback=self._on_manage_data_changed,
        )

    def _toggle_pin(self, item_id: int):
        self.controller.toggle_pin(item_id)
        self.selection_manager.select_item_id(item_id)

    def _new_tag_for_item(self, item_id: int):
        from PySide6.QtWidgets import QInputDialog
        from clipboard.core.models import TAG_CHIP_COLORS

        name, ok = QInputDialog.getText(self, self.tr("New Tag"), self.tr("Tag name:"))
        if ok and name.strip():
            self.controller.create_and_toggle_tag(
                item_id, name.strip(), TAG_CHIP_COLORS[hash(name.strip()) % len(TAG_CHIP_COLORS)]
            )

    def _open_tag_manager(self):
        tags = self.controller.list_tags()
        from PySide6.QtWidgets import QInputDialog
        names = [t.name for t in tags] or [self.tr("(no tags yet)")]
        name, ok = QInputDialog.getItem(
            self, self.tr("Manage Tags"), self.tr("Delete tag:"), names, 0, False
        )
        if ok and name and name != self.tr("(no tags yet)"):
            tag = next((t for t in tags if t.name == name), None)
            if tag is not None:
                self.controller.delete_tag(tag.id)

    def _filter_by_source(self, item_id: int):
        """按来源应用筛选历史。"""
        item = self.controller.get_item(item_id)
        if item is None:
            return
        source = item.source_label or item.source_app
        if not source:
            return
        self.controller.set_source_filter(source)
        self.search_input.setText("")
        self._load_history()

    def _create_pin_window(self, item_id: int):
        from .pin_window import create_pin_from_clipboard_item

        create_pin_from_clipboard_item(item_id, self.controller, self)

    def _delete_item(self, item_id: int):
        confirmed = show_confirm_dialog(
            self,
            self.tr("Confirm Delete"),
            self.tr("Are you sure you want to delete this item?"),
        )
        if confirmed:
            self.controller.delete_item(item_id)

    def _open_file_item(self, item_id: int):
        import json
        import os
        from PySide6.QtCore import QTimer

        clipboard_item = self.controller.get_item(item_id)
        if clipboard_item is None or clipboard_item.content_type != "file":
            return
        try:
            data = json.loads(clipboard_item.content)
            files = data.get("files", [])
            if not files:
                return
            file_path = os.path.normpath(files[0])
            if os.path.exists(file_path):
                QTimer.singleShot(0, lambda p=file_path: os.startfile(p))
                QTimer.singleShot(50, self.hide)
        except Exception as e:
            from core.logger import T, log_warning

            log_warning(T("打开文件失败: {e}", e=e), "Clipboard")

    def _paste_item_to_clipboard(self, item_id: int):
        """右键菜单的"粘贴"：用户点这一下就是要粘一次，explicit=True 跳过自动粘贴开关。"""
        if self.controller.paste_item(
            item_id, on_close_callback=self._paste_close_callback(), explicit=True
        ):
            self.item_pasted.emit(item_id)

    def _save_image_as(self, item_id: int):
        import os

        from PySide6.QtGui import QImage
        from PySide6.QtWidgets import QFileDialog
        from ui.dialogs import show_warning_dialog
        from core.save import SaveService

        clipboard_item = self.controller.get_item(item_id)
        if clipboard_item is None or clipboard_item.content_type != "image" or not clipboard_item.image_id:
            return

        image_data = self.manager.get_image_data(clipboard_item.image_id)
        if not image_data:
            show_warning_dialog(self, self.tr("Save Failed"), self.tr("Image data is unavailable."))
            return

        image = QImage()
        if not image.loadFromData(image_data):
            show_warning_dialog(self, self.tr("Save Failed"), self.tr("Failed to load image data."))
            return

        if clipboard_item.created_at:
            default_name = f"clipboard_image_{clipboard_item.created_at.strftime('%Y%m%d_%H%M%S')}.png"
        else:
            default_name = f"clipboard_image_{clipboard_item.id}.png"

        file_path, selected_filter = QFileDialog.getSaveFileName(
            self,
            self.tr("Save as"),
            default_name,
            self.tr("PNG Image (*.png);;JPEG Image (*.jpg *.jpeg);;Bitmap Image (*.bmp);;WebP Image (*.webp);;PDF (*.pdf)"),
        )
        if not file_path:
            return

        image_format = self._format_from_save_filter(file_path, selected_filter)
        if not os.path.splitext(file_path)[1]:
            file_path = f"{file_path}.{image_format.lower()}"

        save_service = SaveService()
        if not save_service.save_qimage_to_path(image, file_path, image_format=image_format):
            show_warning_dialog(self, self.tr("Save Failed"), self.tr("Failed to save image."))

    @staticmethod
    def _format_from_save_filter(file_path: str, selected_filter: str) -> str:
        ext = os.path.splitext(file_path)[1].lstrip(".")
        if ext:
            return ext.upper()
        # 从过滤器字符串中提取第一个扩展名，如 "JPEG (*.jpg *.jpeg)" → "jpg"
        match = re.search(r'\*\.(\w+)', selected_filter)
        if match:
            return match.group(1).upper()
        return "PNG"

    def _open_file_location(self, item_id: int):
        import json
        import os
        import subprocess
        from PySide6.QtCore import QTimer

        clipboard_item = self.controller.get_item(item_id)
        if clipboard_item is None or clipboard_item.content_type != "file":
            return
        try:
            data = json.loads(clipboard_item.content)
            files = data.get("files", [])
            if not files:
                return
            file_path = os.path.normpath(files[0])
            if os.path.isdir(file_path):
                QTimer.singleShot(0, lambda p=file_path: subprocess.Popen(["explorer", p]))
            elif os.path.exists(file_path):
                QTimer.singleShot(0, lambda p=file_path: subprocess.Popen(["explorer", "/select,", p]))
            elif os.path.exists(os.path.dirname(file_path)):
                QTimer.singleShot(0, lambda p=os.path.dirname(file_path): subprocess.Popen(["explorer", p]))
        except Exception as e:
            from core.logger import T, log_warning

            log_warning(T("打开文件位置失败: {e}", e=e), "Clipboard")

    def _on_clear_clicked(self):
        self.controller.clear_history(parent_widget=self)

    def _on_new_item(self, item=None):
        self.controller.on_new_content(self.isVisible(), item)

    def notify_new_content(self, item=None):
        self.new_item_received.emit(item)

    def _warmup_offscreen_once(self):
        if ClipboardWindow._offscreen_warmup_done:
            return
        ClipboardWindow._offscreen_warmup_done = True

        screen = QApplication.primaryScreen()
        if screen is None:
            return

        self._offscreen_warmup_in_progress = True
        old_pos = self.pos()
        old_opacity = self.windowOpacity()
        try:
            geo = screen.availableGeometry()
            self.setWindowOpacity(0)
            self.move(geo.right() + 20000, geo.bottom() + 20000)
            self.show()
            QApplication.processEvents()
            self.hide()
            log_debug(T("剪贴板窗口离屏预热完成"), "Clipboard")
        except Exception as e:
            log_debug(T("剪贴板窗口离屏预热异常: {e}", e=e), "Clipboard")
        finally:
            self.move(old_pos)
            self.setWindowOpacity(old_opacity)
            self._offscreen_warmup_in_progress = False

    @safe_event
    def showEvent(self, event):
        if self._offscreen_warmup_in_progress:
            super().showEvent(event)
            return

        PreviewPopup.instance().set_display_enabled(True)
        # 隐藏动画可能还在收尾：先停掉，重置透明度和标志位再淡入
        self._cancel_motion()
        reset_opacity(self)
        self.setWindowOpacity(0)

        if hasattr(self, "_shortcut_handler") and self._shortcut_handler:
            ShortcutManager.instance().register(self._shortcut_handler)

        self._fl_reset()
        self.selection_manager.reset()
        self._start_image_indexing()
        self.controller.on_window_show()

        t_show_start = perf_counter()
        super().showEvent(event)
        self._apply_glass()

        self.list_widget.setFocus()
        self._position_at_cursor()
        QTimer.singleShot(0, self.group_bar.refresh_buttons)
        QTimer.singleShot(0, self._reveal_window)
        t_show_end = perf_counter()
        log_debug(T("⏱️ 打开窗口耗时: {elapsed_ms:.1f} ms", elapsed_ms=(t_show_end - t_show_start) * 1000), "Clipboard")

    def _reveal_window(self):
        fade_show(self)
        self._update_empty_state()

    def _position_at_cursor(self):
        cursor_pos = QCursor.pos()
        screen = QApplication.screenAt(cursor_pos)
        if screen:
            screen_geo = screen.availableGeometry()

            x = cursor_pos.x() + 10
            y = cursor_pos.y() + 10

            if x + self.width() > screen_geo.right():
                x = cursor_pos.x() - self.width() - 10

            if y + self.height() > screen_geo.bottom():
                y = cursor_pos.y() - self.height() - 10

            if x < screen_geo.left():
                x = screen_geo.left()
            if y < screen_geo.top():
                y = screen_geo.top()

            self.move(x, y)

    @safe_event
    def hideEvent(self, event):
        self._search_hover_timer.stop()
        self._search_idle_timer.stop()
        self._search_animation.stop()
        self._layout_search(0.0)
        self._finish_search_animation()
        if self._offscreen_warmup_in_progress:
            super().hideEvent(event)
            return

        # 先关闭预览入口。这样即使后续清理抛出异常，或队列中还有迟到的
        # 键盘/悬停事件，也不能在主窗口隐藏后重新拉起预览。
        PreviewPopup.instance().set_display_enabled(False)
        # 浮层按钮随窗口一起收起，避免下次打开时残留在旧行上
        if hasattr(self, "quick_actions_bar"):
            self._quick_fade.stop()
            self.quick_actions_bar.hide()
            self._quick_opacity_effect.setOpacity(0.0)
            self._quick_action_row = -1
            self._quick_action_item_id = None
        if hasattr(self, "_hover_anim_timer"):
            self._hover_anim_timer.stop()
        self._fl_reset()
        self.controller.on_window_hide()

        if not self.config.get_clipboard_preserve_search() and self.search_input.text():
            self.search_input.clear()
        self._search_idle_timer.stop()

        super().hideEvent(event)
        self._save_window_geometry()
        active_popup = QApplication.activePopupWidget()
        if active_popup is not None:
            active_popup.close()
        # 隐藏后裁剪工作集 + 清缩略图缓存，静默待机更省
        try:
            if hasattr(self, "_item_delegate"):
                self._item_delegate.clear_thumb_cache()
            from core.platform_utils import request_trim_working_set
            request_trim_working_set(400)
        except Exception:
            pass

    @safe_event
    def closeEvent(self, event):
        # 淡出动画进行中再次关闭：不重复清理，也不打断收尾
        if getattr(self, "_motion_closing", False):
            event.ignore()
            return
        # closeEvent 后通常还会收到 hideEvent，但这里必须先禁用，覆盖关闭
        # 过程中保存设置等操作异常、导致后续语句未执行的情况。
        PreviewPopup.instance().set_display_enabled(False)
        if hasattr(self, "_shortcut_handler") and self._shortcut_handler:
            ShortcutManager.instance().unregister(self._shortcut_handler)
        self._save_window_geometry()
        active_popup = QApplication.activePopupWidget()
        if active_popup is not None:
            active_popup.close()
        self.closed.emit()
        # ignore 掉关闭事件：accepted 的顶层窗口会被框架立即隐藏，淡出就来不及播。
        # 本窗口 close 语义等同隐藏（可复用的常驻 Tool 窗），收尾由 hide() 的
        # 淡出动画完成，hideEvent 里的清理逻辑照旧执行。
        event.ignore()
        self.hide()
        try:
            from core.platform_utils import request_trim_working_set
            request_trim_working_set(200)
        except Exception:
            pass

    @safe_event
    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.ActivationChange and not self.isActiveWindow():
            QTimer.singleShot(100, self._check_and_hide)

    def _cancel_motion(self):
        """停掉进行中的入场/出场动画；阻断 finished，避免收尾逻辑误触发隐藏。"""
        for anim in list(getattr(self, "_motion_anims", None) or []):
            try:
                anim.blockSignals(True)
                anim.stop()
            except RuntimeError:
                pass
        self._motion_anims = []
        self._motion_opening = False
        self._motion_closing = False

    def show(self):
        """淡出动画途中再次显示：取消收尾并恢复不透明。

        窗口淡出期间 isVisible() 仍为 True，Qt 的 show() 是空操作、不会再触发
        showEvent，必须由这里拦住取消，否则收尾动画会把刚"唤回"的窗口藏掉。
        """
        if self.isVisible() and getattr(self, "_motion_closing", False):
            self._cancel_motion()
            reset_opacity(self)
        super().show()

    def hide(self):
        """常规隐藏路由到淡出动画；动画收尾的 hide 走原生路径。"""
        if self._offscreen_warmup_in_progress or not self.isVisible():
            super().hide()
            return
        if getattr(self, "_motion_closing", False):
            super().hide()
            return
        self._cancel_motion()
        fade_hide(self)
        if not getattr(self, "_motion_closing", False):
            super().hide()

    @safe_event
    def paintEvent(self, event):
        # 容器外侧的三层低透明描边，近似 macOS 浮层投影
        if _SHADOW_MARGIN and not self._offscreen_warmup_in_progress and hasattr(self, "container"):
            m = _SHADOW_MARGIN
            target = self.rect().adjusted(m, m, -m, -m)
            if target.width() > 0 and target.height() > 0:
                painter = QPainter(self)
                painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                for spread, alpha in _SHADOW_RINGS:
                    ring = target.adjusted(-spread, -spread, spread, spread)
                    painter.setPen(QPen(QColor(0, 0, 0, alpha), 1))
                    radius = _WINDOW_RADIUS + spread
                    painter.drawRoundedRect(ring, radius, radius)
                painter.end()
        super().paintEvent(event)

    def _owns_window(self, window: Optional[QWidget]) -> bool:
        """Return whether *window* belongs to this clipboard window."""
        current = window
        while current is not None:
            if current is self:
                return True
            current = current.parentWidget()
        return False

    def _check_and_hide(self):
        if self.isActiveWindow():
            return

        # 常驻模式靠用户主动关闭。粘贴本身就会把焦点交给目标窗口，
        # 这里按失焦隐藏处理的话，关掉开关等于没有生效。
        if not self.config.get_clipboard_close_after_paste():
            return

        # A modal confirmation dialog (for example the item-delete prompt) and
        # a QMenu both activate their own top-level window.  They still belong
        # to the clipboard window and must not make their owner disappear.
        active_surfaces = (
            QApplication.activeWindow(),
            QApplication.activeModalWidget(),
            QApplication.activePopupWidget(),
        )
        if any(self._owns_window(surface) for surface in active_surfaces):
            return

        self.hide()

    def _is_draggable_area(self, widget, local_pos: QPoint) -> bool:
        _ = local_pos
        if widget is self.toolbar or widget is self.title_label or widget is getattr(self, "search_host", None):
            return True
        bar = getattr(self, "group_bar", None)
        if bar and bar.bar_widget is not None and widget is bar.bar_widget:
            return True
        return False

    def _is_date_filter_widget(self, obj) -> bool:
        date_widgets = (
            getattr(self, "start_date_edit", None),
            getattr(self, "end_date_edit", None),
        )
        for widget in date_widgets:
            if widget is not None and (obj is widget or widget.isAncestorOf(obj)):
                return True
            if widget is not None:
                calendar = widget.calendarWidget()
                if calendar is not None and (obj is calendar or calendar.isAncestorOf(obj)):
                    return True
        return isinstance(obj, QCalendarWidget)

    @safe_event
    def eventFilter(self, obj, event):
        event_type = event.type()

        if obj is getattr(self, "search_host", None) and event_type == QEvent.Type.Resize:
            if hasattr(self, "_search_progress"):
                self._layout_search()
        if obj is getattr(self, "search_btn", None):
            if event_type == QEvent.Type.Enter:
                if not getattr(self, "_search_hover_blocked", False):
                    self._search_hover_timer.start()
            elif event_type == QEvent.Type.Leave:
                self._search_hover_timer.stop()
                self._search_hover_blocked = False

        if obj is getattr(self, "search_input", None):
            if event_type == QEvent.Type.InputMethod:
                self._search_composing = bool(event.preeditString())
            if event_type in (QEvent.Type.KeyPress, QEvent.Type.MouseMove, QEvent.Type.MouseButtonPress, QEvent.Type.InputMethod):
                self._search_idle_timer.start()
            if event_type == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape:
                self.search_input.clear()
                self._collapse_search()
                self.list_widget.setFocus()
                return True

        if event_type == QEvent.Type.Leave and obj is self.list_widget.viewport():
            self.selection_manager.clear_hovered_index()
            self._item_delegate.set_hovered_row(-1)
            if not self._hover_anim_timer.isActive():
                self._hover_anim_timer.start()
                QTimer.singleShot(_HOVER_ANIM_MS, self._hover_anim_timer.stop)
            QTimer.singleShot(150, self._hide_quick_actions_if_cursor_outside)
            PreviewPopup.instance().schedule_hide()
            selected_items = self.list_widget.selectedItems()
            if selected_items:
                selected_id = selected_items[0].data(Qt.ItemDataRole.UserRole)
                self._set_highlighted_item(selected_id)
            else:
                self._set_highlighted_item(None)

        if event_type == QEvent.Type.Resize and obj is self.list_widget.viewport():
            self._update_empty_state()
            QTimer.singleShot(0, self._reposition_quick_actions)

        if event_type in (QEvent.Type.HoverEnter, QEvent.Type.HoverLeave) and obj is self.menu_btn:
            self._set_menu_btn_icon(hovered=event_type == QEvent.Type.HoverEnter)

        if event_type == QEvent.Type.FocusIn and obj is self.list_widget:
            if not self.group_bar.sidebar_mode:
                self.group_bar.clear_sidebar_focus()

        if event_type == QEvent.Type.KeyPress:
            key = event.key()
            pos = getattr(self, "group_bar_position", "right")

            if pos != "top":
                if pos == "right":
                    k_enter, k_exit = Qt.Key.Key_Right, Qt.Key.Key_Left
                else:
                    k_enter, k_exit = Qt.Key.Key_Left, Qt.Key.Key_Right
                k_prev, k_next = Qt.Key.Key_Up, Qt.Key.Key_Down

                if self.group_bar.sidebar_mode:
                    if key == k_exit:
                        self.group_bar.exit_sidebar_mode()
                        return True
                    if key == k_prev:
                        self.group_bar.move_sidebar_selection(-1)
                        return True
                    if key == k_next:
                        self.group_bar.move_sidebar_selection(1)
                        return True
                    if key == k_enter:
                        return True
                elif key == k_enter:
                    focus_widget = QApplication.focusWidget()
                    if focus_widget is self.list_widget or self.list_widget.isAncestorOf(focus_widget):
                        self._enter_sidebar_mode()
                        return True

        if event_type in (
            QEvent.Type.MouseButtonPress,
            QEvent.Type.MouseButtonRelease,
            QEvent.Type.MouseMove,
        ) and self._is_date_filter_widget(obj):
            return super().eventFilter(obj, event)

        if self._fl_handle_event(obj, event):
            return True

        return super().eventFilter(obj, event)

    @safe_event
    def leaveEvent(self, event):
        if not self._fl_is_dragging and not self._fl_resize_edge:
            self.unsetCursor()
        super().leaveEvent(event)

    @safe_event
    def keyPressEvent(self, event):
        key = event.key()

        if key in (Qt.Key.Key_Up, Qt.Key.Key_Down) and not self.group_bar.sidebar_mode:
            focus_widget = QApplication.focusWidget()
            if focus_widget is None or focus_widget is self.search_input or not (
                focus_widget is self.list_widget or self.list_widget.isAncestorOf(focus_widget)
            ):
                self.list_widget.setFocus()
                self.selection_manager._move_selection(-1 if key == Qt.Key.Key_Up else 1)
                return

        super().keyPressEvent(event)

    @safe_event
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.list_widget.viewport().update()
        if hasattr(self, "group_bar") and self.group_bar.bar_widget is not None:
            self.group_bar.refresh_buttons()


__all__ = ["ClipboardShortcutHandler", "ClipboardWindow"]

__all__ = ["ClipboardWindow"]
