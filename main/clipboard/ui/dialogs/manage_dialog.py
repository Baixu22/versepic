# -*- coding: utf-8 -*-
"""
剪贴板管理窗口 - 三列布局（独立窗口）

第1列：导航（分组管理、内容管理）
第2列：列表（分组列表/内容分组选择）
第3列：详细编辑区

这是一个独立的设置窗口，不是剪贴板窗口的子窗口。
使用单例模式确保只有一个实例存在。
"""

from dataclasses import replace as _replace_tokens
from typing import Optional

from PySide6.QtCore import (
    QCoreApplication,
    QSignalBlocker,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QColor, QCursor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid

from ui.apple_style import apple_scrollbar_qss
from ui.fluent_lite import (
    BodyLabel,
    CaptionLabel,
    ComboBox,
    FluentIcon,
    NavigationInterface,
    NavigationItemPosition,
    PushButton as FluentPushButton,
    PrimaryPushButton,
    Button,
    FluentTitleBar,
    FrostedFramelessDialog,
)
from ui.motion import cancel_motion, fade_hide, fade_show
from ui.fluent_lite.labels import PageHeader
from ui.fluent_lite.theme import (
    FONT_FAMILY, SURFACE_RADIUS, WORKSPACE_MARGIN,
    WORKSPACE_PADDING, WORKSPACE_SIDEBAR_WIDTH, WORKSPACE_HEADER_HEIGHT,
)
from ui.outline_icons import Icon
from core import safe_event
from core.ui_scale import configure_dialog_control, configure_dialog_controls
from core.ui_theme import UIThemeMode, get_ui_theme
from ..theme.themes import get_theme_manager
from ..theme.theme_styles import management_palette, readable_accent, surface_palette
from ui.dialogs import show_confirm_dialog, show_info_dialog, show_warning_dialog

from ...core import ClipboardManager, Group, GroupType
from ...services.file_payload_service import extract_first_file_path_from_content
from ...services.group_service import (
    build_delete_group_confirm_message,
    get_group_display_icon,
    get_toggled_default_group_icon,
    group_name_exists,
    make_unique_group_name,
)
from ...services.import_export_service import (
    collect_text_export_rows,
    import_text_rows,
    read_import_rows,
    write_csv_rows,
)
from ...services.manage_dialog_service import save_file_content, save_group, save_text_content
from ..forms.file_content_form import build_edit_file_content_form, build_file_content_form
from ..forms.group_form import build_edit_group_form, build_new_group_form
from ..forms.group_icon_picker import (
    first_grapheme,
    on_icon_input_changed,
    on_preset_icon_clicked,
)
from ..forms.import_export_form import build_import_export_form
from ..forms.text_content_form import build_edit_text_content_form, build_text_content_form
from ..layout_scale import (
    field_gap,
    manage_dialog_height,
    manage_dialog_min_height,
    manage_dialog_min_width,
    manage_dialog_width,
    scale_ui,
)
from ..widgets.draggable_list_widget import DraggableListWidget
from ..widgets.manage_list_delegate import GROUP_LABEL_ROLE, PREVIEW_ROLE, ManageListDelegate


_manage_window_instance: Optional["ManageDialog"] = None


def _qt_object_is_valid(obj) -> bool:
    if obj is None:
        return False
    try:
        return isValid(obj)
    except RuntimeError:
        return False


def get_manage_dialog(manager: ClipboardManager = None) -> "ManageDialog":
    """获取管理窗口的单例实例"""
    global _manage_window_instance
    if not _qt_object_is_valid(_manage_window_instance):
        _manage_window_instance = None
    if _manage_window_instance is None:
        if manager is None:
            manager = ClipboardManager()
        _manage_window_instance = ManageDialog(manager)
    return _manage_window_instance


def get_existing_manage_dialog() -> Optional["ManageDialog"]:
    """获取已存在的管理窗口实例，不主动创建。"""
    global _manage_window_instance
    if not _qt_object_is_valid(_manage_window_instance):
        _manage_window_instance = None
    return _manage_window_instance


def destroy_manage_dialog() -> bool:
    """销毁缓存的管理窗口，返回它销毁前是否可见。"""
    global _manage_window_instance
    dialog = _manage_window_instance
    _manage_window_instance = None

    if not _qt_object_is_valid(dialog):
        return False

    was_visible = dialog.isVisible()
    # closeEvent() 有意只隐藏窗口并忽略关闭，因此这里必须绕过 close()，
    # 直接安排 QObject 销毁，才能让下次打开按新的构造期参数重建。
    dialog.hide()
    dialog.deleteLater()
    return was_visible


class ManageDialog(FrostedFramelessDialog):
    """剪贴板管理窗口 - 三列布局（独立窗口）"""

    group_added = Signal()
    content_added = Signal(int)
    data_changed = Signal()

    def __init__(self, manager: ClipboardManager, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.current_mode = "group"
        self.selected_group_id = None
        self.editing_group_id = None
        self.editing_item_id = None
        self._detail_form_token = 0
        self._clean_state = None
        self._dirty = False
        # The management window retains its independently selected clipboard theme.
        self._fade_done_pending = False
        self._clipboard_theme_manager = get_theme_manager()
        self._apple = management_palette(self._clipboard_theme_manager.get_current_theme())

        self._setup_titlebar()

        self.setWindowTitle(self.tr("Clipboard Management"))
        self.setMinimumSize(manage_dialog_min_width(), manage_dialog_min_height())
        self.resize(manage_dialog_width(), manage_dialog_height())
        self.setWindowFlags(
            self.windowFlags()
            | Qt.WindowType.Window
            | Qt.WindowType.WindowCloseButtonHint
            | Qt.WindowType.WindowMinimizeButtonHint
            | Qt.WindowType.WindowMaximizeButtonHint
        )
        # setWindowFlags 会重建原生窗口，无边框库加的 WS_THICKFRAME 和阴影随之丢失，
        # 边缘就拖不动了，要重新加回去
        self.updateFrameless()
        try:
            from core.resource_manager import ResourceManager
            import os

            icon_path = ResourceManager.get_resource_path("svg/versepic.png")
            if os.path.exists(icon_path):
                from PySide6.QtGui import QIcon

                self.setWindowIcon(QIcon(icon_path))
        except Exception:
            pass
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)

        self._setup_ui()
        from ui.fluent_lite.popups import ToolTip
        ToolTip.install(self)
        # Static Fluent controls are created once.  Opt them into the
        # standalone-window scale before any dynamic detail form is built.
        configure_dialog_controls(self)
        self._apply_mode("group")
        QShortcut(QKeySequence("Ctrl+S"), self, activated=self._on_save_clicked)
        QShortcut(QKeySequence("Ctrl+N"), self, activated=self._new_entry)
        self._center_on_screen()
        self._apply_ui_theme(get_ui_theme().tokens)
        get_ui_theme().theme_changed.connect(self._apply_ui_theme)
        self._clipboard_theme_manager.theme_changed.connect(self._apply_clipboard_theme)

    def _apply_clipboard_theme(self, _theme):
        self._apply_ui_theme(get_ui_theme().tokens)

    def _refresh_theme_scope(self, tokens=None, subtree=None):
        """Reapply Fluent styles after controls have acquired this parent."""
        tokens = tokens or get_ui_theme().tokens
        for widget in (subtree or self).findChildren(QWidget):
            apply_theme = getattr(widget, "_apply_theme", None)
            if callable(apply_theme):
                apply_theme(tokens)
            else:
                # PySide6 6.9.x shadows QWidget.update() with the
                # QAbstractItemView.update(QModelIndex) overload on item views,
                # so a bare view.update() raises TypeError. Refresh the viewport
                # instead, which is a plain QWidget on every version.
                viewport = getattr(widget, "viewport", None)
                (viewport() if callable(viewport) else widget).update()

    def _apple_scope_tokens(self, tokens):
        """Map the Apple palette onto the semantic ui_theme tokens.

        Every nested Fluent-lite control resolves its colours through
        ui_tokens(), which honours ``_ui_theme_tokens_override`` on an
        ancestor — so the overrides below re-tint buttons, inputs, radios and
        combo popups without forking their stylesheets.
        """
        theme = self._clipboard_theme_manager.get_current_theme()
        dark = surface_palette(theme).dark
        apple = management_palette(theme)
        self._apple = apple
        input_border = theme.colors.border_primary
        self._input_border = input_border
        self._ui_theme_tokens_override = _replace_tokens(
            tokens,
            mode=UIThemeMode.DARK if dark else UIThemeMode.LIGHT,
            accent=theme.colors.accent_primary,
            accent_hover=apple.accent_hover,
            accent_pressed=apple.accent_pressed,
            accent_soft=theme.colors.bg_selected,
            accent_strong=readable_accent(QColor(apple.accent), QColor("#171717" if dark else "#FAFAFA")).name(),
            accent_strong_hover=readable_accent(QColor(apple.accent_hover), QColor("#171717" if dark else "#FAFAFA")).name(),
            accent_strong_pressed=readable_accent(QColor(apple.accent_pressed), QColor("#171717" if dark else "#FAFAFA")).name(),
            accent_text=apple.accent,
            window=apple.window_bg,
            window_top=apple.window_bg,
            window_bottom=apple.window_bg,
            window_border=apple.border,
            surface=apple.card_bg,
            surface_strong=apple.card_bg,
            surface_subtle=apple.sidebar_bg,
            surface_hover=apple.hover_bg,
            text=apple.text,
            text_muted=apple.text_secondary,
            text_disabled=apple.text_tertiary,
            border=input_border,
            border_hover=apple.text_tertiary,
            input_background=apple.card_bg,
            popup_background=apple.card_bg,
            popup_hover=apple.hover_bg,
            separator=apple.border,
            success=apple.success,
            danger=apple.danger,
            danger_soft=apple.danger_soft,
        )
        return apple

    def _apply_ui_theme(self, tokens):
        """Re-tint the window with the Apple palette for the current light/dark mode."""
        apple = self._apple_scope_tokens(tokens)
        self._refresh_theme_scope(tokens)
        self.setStyleSheet(f"""
            ManageDialog QWidget {{
                font-family: {FONT_FAMILY};
            }}
        """ + apple_scrollbar_qss(apple))

        self.nav_column.setStyleSheet(
            "QWidget#ManageNavColumn {"
            "background: transparent;"
            "border: none;"
            f"border-radius: {scale_ui(SURFACE_RADIUS)}px;"
            "}"
        )
        card_qss = (
            f"background: {apple.card_bg};"
            f"border: 1px solid {apple.border};"
            f"border-radius: {scale_ui(SURFACE_RADIUS)}px;"
        )
        self.list_column.setStyleSheet(
            f"QWidget#ManageListColumn {{ background: transparent; "
            f"border: none; border-right: 1px solid {apple.border}; }}"
        )
        self.content_card.setStyleSheet(f"QWidget#ManageContentCard {{{card_qss}}}")
        self.workspace_splitter.setStyleSheet(
            f"QSplitter::handle {{ background: transparent; }}"
            f"QSplitter::handle:hover {{ background: {apple.border}; border-radius: {scale_ui(2)}px; }}"
        )
        self.detail_column.setStyleSheet("QWidget#ManageDetailColumn { background: transparent; border: none; }")
        self.list_widget.setStyleSheet(f"""
            QListWidget {{
                background: transparent;
                border: none;
                outline: none;
                color: {apple.text};
                font-size: {scale_ui(13)}px;
            }}
        """)
        self.detail_title._apply_theme()
        self.detail_subtitle.setStyleSheet(
            f"color: {apple.text_secondary}; font-size: {scale_ui(13)}px; "
            "background: transparent;"
        )
        self.detail_separator.setStyleSheet(
            f"background: {apple.border}; border: none;"
        )
        self.footer_separator.setStyleSheet(self.detail_separator.styleSheet())
        self.nav_interface._apply_theme()
        nav_width = max(scale_ui(WORKSPACE_SIDEBAR_WIDTH), *(button.sizeHint().width() for button in self.nav_interface._items.values()))
        self.nav_column.setFixedWidth(nav_width)
        self.titleBar.hBoxLayout.setContentsMargins(scale_ui(12), 0, 0, 0)
        for row in range(self.list_widget.count()):
            item = self.list_widget.item(row)
            data = item.data(Qt.ItemDataRole.UserRole)
            if data and data[0] == "new":
                item.setIcon(Icon.PLUS.render_icon(apple.text_secondary))
            elif data and data[0] == "item":
                item.setIcon(Icon.FILE.render_icon(apple.text_secondary))
        self._apply_dynamic_form_theme()
        self.update()

    def _apply_action_button_theme(self):
        """Action variants resolve colours from the same local scope as every control."""
        self.delete_btn.setVariant("destructive-ghost")


    def _apply_dynamic_form_theme(self):
        """Refresh controls that are rebuilt when the selected form changes."""
        tokens = get_ui_theme().tokens
        apple = self._apple
        self._apply_action_button_theme()
        # Reapply hierarchy after dynamic forms acquire their scoped theme.
        for label in self.detail_content.findChildren(BodyLabel):
            size = label.property("headingSize") or 14
            weight = 600 if label.property("headingSize") else 500
            label.setStyleSheet(
                f"background: transparent; color: {apple.text}; "
                f"font: {weight} {scale_ui(size)}px {FONT_FAMILY};"
            )
        self.list_title.setStyleSheet(
            f"background: transparent; color: {apple.text}; "
            f"font: 500 {scale_ui(13)}px {FONT_FAMILY};"
        )
        for option in self.detail_content.findChildren(QWidget, "GroupTypeOption"):
            option._apply_theme()
        icon_button = getattr(self, "icon_picker_button", None)
        if _qt_object_is_valid(icon_button):
            icon_button._apply_theme()
        icon_input = getattr(self, "icon_input", None)
        if _qt_object_is_valid(icon_input):
            apply_theme = getattr(icon_input, "_apply_theme", None)
            if callable(apply_theme):
                apply_theme(tokens)
            icon_input.setStyleSheet(
                icon_input.styleSheet()
                + f"QLineEdit {{ font-size: {scale_ui(20)}px; padding: 0px; }}"
            )
        import_export_separator = getattr(
            self, "import_export_separator", None
        )
        if _qt_object_is_valid(import_export_separator):
            import_export_separator.setStyleSheet(
                f"background: {apple.border}; border: none;"
            )

    def _setup_titlebar(self):
        title_bar = FluentTitleBar(self)
        # Mark before _setup_ui(), which derives the content top margin from
        # titleBar.height(); an unscaled height puts the columns under the
        # caption buttons.
        configure_dialog_control(title_bar)
        self.setTitleBar(title_bar)
        title_bar.setDoubleClickEnabled(True)

    def _center_on_screen(self):
        """在鼠标所在屏幕居中显示"""
        cursor_pos = QCursor.pos()
        screen = QApplication.screenAt(cursor_pos)
        if not screen:
            screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            x = geo.x() + (geo.width() - self.width()) // 2
            y = geo.y() + (geo.height() - self.height()) // 2
            self.move(x, y)

    def show_and_activate(self):
        """显示并激活窗口（独立窗口专用方法）"""
        was_hidden = not self.isVisible() or self.isMinimized()
        if self.isMinimized():
            self.showNormal()
        else:
            self.show()
        self.raise_()
        self.activateWindow()
        if was_hidden:
            cancel_motion(self)
            fade_show(self)
        elif getattr(self, "_motion_closing", False):
            cancel_motion(self)

    def refresh_after_external_change(self, deleted_group_id: Optional[int] = None):
        """外部数据变化后同步当前管理窗口，避免显示已删除的旧数据。"""
        self.setUpdatesEnabled(False)
        try:
            if deleted_group_id is not None:
                if self.editing_group_id == deleted_group_id:
                    self.editing_group_id = None
                if self.selected_group_id == deleted_group_id:
                    self.selected_group_id = None

            if self.current_mode == "group":
                self._refresh_group_list()
                if self.editing_group_id is not None:
                    self._show_edit_group_form(self.editing_group_id)
                else:
                    self._show_new_group_form()
            elif self.current_mode == "content":
                self._refresh_group_combo()
                self._refresh_content_list()
                if self.editing_item_id is not None and self.manager.get_item(self.editing_item_id) is not None:
                    self._show_edit_content_form(self.editing_item_id)
                else:
                    self.editing_item_id = None
                    self._show_new_content_form()
        finally:
            self.setUpdatesEnabled(True)

    def open_group_editor(self, group_id: int):
        """打开并定位到指定分组的编辑界面"""
        if not self._confirm_discard():
            return
        self._dirty = False
        self.setUpdatesEnabled(False)
        if self.current_mode != "group":
            self._switch_mode("group")
        else:
            self._refresh_group_list()
        self.editing_group_id = group_id
        self._select_list_item("group", group_id)
        self._show_edit_group_form(group_id)
        self.setUpdatesEnabled(True)
        self.show_and_activate()

    def open_item_editor(self, item_id: int, group_id: Optional[int]):
        """打开并定位到指定内容的编辑界面"""
        if not self._confirm_discard():
            return
        self._dirty = False
        self.setUpdatesEnabled(False)
        if self.current_mode != "content":
            self._switch_mode("content")
        if group_id is not None:
            self._select_group_in_combo(group_id)
        self._refresh_content_list()
        self.editing_item_id = item_id
        self._select_list_item("item", item_id)
        self._show_edit_content_form(item_id)
        self.setUpdatesEnabled(True)
        self.show_and_activate()

    def done(self, result):
        """淡出后再真正结束对话框，保证 accept/reject 的返回值不变。

        QDialog.accept()/reject() 都汇集到这里：首次进入先播放 fade_hide，
        等动画结束窗口已经隐藏后再重新进入并走基类的完成逻辑。
        """
        if self.isVisible() and not self._confirm_discard():
            return
        self._discard_draft()
        if not self.isVisible() or getattr(self, "_motion_closing", False):
            super().done(result)
            return
        self._fade_done_pending = True
        fade_hide(self)

        def _finish(r=result):
            # 淡出期间窗口被重新打开时 cancel_motion 会清除 _fade_done_pending，
            # 此时不再走基类 done()，避免把刚打开的对话框关掉。
            if self._fade_done_pending:
                self._fade_done_pending = False
                super().done(r)

        # fade_hide 时长 160ms：窗口隐藏后完成基类逻辑
        QTimer.singleShot(170, _finish)

    @safe_event
    def closeEvent(self, event):
        """关闭事件 - 淡出后只隐藏窗口，不销毁"""
        event.ignore()
        if not self._confirm_discard():
            return
        self._discard_draft()
        if not self.isVisible():
            self.hide()
            return
        fade_hide(self)

    def _setup_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(scale_ui(WORKSPACE_MARGIN), self.titleBar.height() + scale_ui(WORKSPACE_MARGIN), scale_ui(WORKSPACE_MARGIN), scale_ui(WORKSPACE_MARGIN))
        main_layout.setSpacing(scale_ui(WORKSPACE_MARGIN))
        self.nav_column = self._create_nav_column()
        main_layout.addWidget(self.nav_column)
        self.content_card = QWidget()
        self.content_card.setObjectName("ManageContentCard")
        card_layout = QHBoxLayout(self.content_card)
        card_layout.setContentsMargins(1, 1, 1, 1)
        card_layout.setSpacing(0)
        self.workspace_splitter = QSplitter(Qt.Orientation.Horizontal, self.content_card)
        self.workspace_splitter.setChildrenCollapsible(False)
        self.workspace_splitter.setHandleWidth(scale_ui(5))
        self.workspace_splitter.setOpaqueResize(False)
        self.list_column = self._create_list_column()
        self.detail_column = self._create_detail_column()
        self.detail_column.setMinimumWidth(scale_ui(360))
        self.workspace_splitter.addWidget(self.list_column)
        self.workspace_splitter.addWidget(self.detail_column)
        self.workspace_splitter.setStretchFactor(0, 0)
        self.workspace_splitter.setStretchFactor(1, 1)
        self.workspace_splitter.setSizes([scale_ui(240), scale_ui(560)])
        card_layout.addWidget(self.workspace_splitter)
        main_layout.addWidget(self.content_card, 1)

    def _create_nav_column(self):
        widget = QWidget()
        widget.setObjectName("ManageNavColumn")
        widget.setFixedWidth(scale_ui(WORKSPACE_SIDEBAR_WIDTH))
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, scale_ui(6), 0, 0)
        self.nav_interface = NavigationInterface(widget)
        for key, icon, text in (("group", FluentIcon.FOLDER, "Group Management"),
                                ("content", FluentIcon.EDIT, "Content Manager"),
                                ("import_export", FluentIcon.DOWNLOAD, "Import/Export")):
            self.nav_interface.addItem(key, icon, self.tr(text), lambda checked=False, k=key: self._switch_mode(k), NavigationItemPosition.TOP)
        layout.addWidget(self.nav_interface, 1)
        return widget

    def _create_list_column(self):
        widget = QWidget()
        widget.setObjectName("ManageListColumn")
        widget.setMinimumWidth(scale_ui(208))
        widget.setMaximumWidth(scale_ui(400))
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, scale_ui(8))
        layout.setSpacing(scale_ui(8))
        self.list_header = QWidget()
        self.list_header.setFixedHeight(scale_ui(WORKSPACE_HEADER_HEIGHT))
        header = QHBoxLayout(self.list_header)
        header.setContentsMargins(scale_ui(16), 0, scale_ui(10), 0)
        self.list_title = BodyLabel(self.tr("Group List"))
        header.addWidget(self.list_title, 1)
        self.list_count = CaptionLabel("")
        self.list_count.setWordWrap(False)
        self.list_count.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Preferred)
        header.addWidget(self.list_count)
        self.new_btn = Button(parent=self.list_header, variant="ghost", size="icon-sm", icon=Icon.PLUS)
        self.new_btn.setAutoDefault(False)
        self.new_btn.clicked.connect(self._new_entry)
        header.addWidget(self.new_btn)
        layout.addWidget(self.list_header)
        self.group_combo = ComboBox()
        self.group_combo.setAccessibleName(self.tr("Group"))
        self.group_combo.currentIndexChanged.connect(self._on_group_combo_changed)
        combo_row = QHBoxLayout()
        combo_row.setContentsMargins(scale_ui(10), 0, scale_ui(10), 0)
        combo_row.addWidget(self.group_combo)
        layout.addLayout(combo_row)
        self.list_widget = DraggableListWidget()
        self.list_widget.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.list_widget.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.list_widget.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self._list_delegate = ManageListDelegate(self.list_widget)
        self.list_widget.setItemDelegate(self._list_delegate)
        self.list_widget.setMouseTracking(True)
        self.list_widget.viewport().setMouseTracking(True)
        self.list_widget.currentItemChanged.connect(self._on_current_item_changed)
        self.list_widget.model().rowsMoved.connect(self._on_list_reordered)
        layout.addWidget(self.list_widget, 1)
        self.load_more_btn = Button(self.tr("Load more"), widget, variant="ghost", size="sm")
        self.load_more_btn.setAutoDefault(False)
        self.load_more_btn.clicked.connect(self._load_more_content)
        self.load_more_btn.hide()
        layout.addWidget(self.load_more_btn)
        return widget

    def _create_detail_column(self):
        widget = QWidget()
        widget.setObjectName("ManageDetailColumn")
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(scale_ui(WORKSPACE_PADDING), 0, scale_ui(WORKSPACE_PADDING), scale_ui(16))
        layout.setSpacing(0)
        self.detail_title = PageHeader(self.tr("New Group"))
        layout.addWidget(self.detail_title)
        self.detail_separator = QFrame()
        self.detail_separator.setFixedHeight(1)
        layout.addWidget(self.detail_separator)
        # Kept as semantic metadata for the group type; descriptions live with each choice.
        self.detail_subtitle = CaptionLabel("")
        self.detail_subtitle.setWordWrap(True)
        self.detail_subtitle.setContentsMargins(0, scale_ui(14), 0, 0)
        self.detail_subtitle.hide()
        layout.addWidget(self.detail_subtitle)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self.detail_content = QWidget()
        self.detail_content.setStyleSheet("background: transparent;")
        self.detail_layout = QVBoxLayout(self.detail_content)
        self.detail_layout.setContentsMargins(0, scale_ui(20), 0, scale_ui(20))
        self.detail_layout.setSpacing(field_gap())
        scroll.setWidget(self.detail_content)
        layout.addWidget(scroll, 1)
        self.footer_separator = QFrame()
        self.footer_separator.setFixedHeight(1)
        layout.addWidget(self.footer_separator)
        self.footer = QWidget()
        self.btn_layout = QHBoxLayout(self.footer)
        self.btn_layout.setContentsMargins(0, scale_ui(12), 0, 0)
        self.btn_layout.setSpacing(scale_ui(12))
        self.delete_btn = FluentPushButton(self.tr("Delete"))
        self.delete_btn.setAutoDefault(False)
        self.delete_btn.clicked.connect(self._on_delete_clicked)
        self.btn_layout.addWidget(self.delete_btn)
        self.status_label = CaptionLabel("")
        self.btn_layout.addWidget(self.status_label, 1)
        self.discard_btn = Button(QCoreApplication.translate("SettingsDialog", "Cancel"), variant="outline")
        self.discard_btn.setAutoDefault(False)
        self.discard_btn.clicked.connect(self._discard_draft)
        self.discard_btn.hide()
        self.btn_layout.addWidget(self.discard_btn)
        self.save_btn = PrimaryPushButton(self.tr("Save"))
        self.save_btn.setAutoDefault(False)
        self.save_btn.setDefault(True)
        self.save_btn.setToolTip("Ctrl+S")
        self.save_btn.clicked.connect(self._on_save_clicked)
        for button in (self.save_btn, self.discard_btn):
            button.setMinimumWidth(scale_ui(88))
        self.btn_layout.addWidget(self.save_btn)
        layout.addWidget(self.footer)
        return widget

    def _switch_mode(self, mode):
        if mode == self.current_mode:
            self.nav_interface.setCurrentItem(mode)
            return
        if not self._confirm_discard():
            self.nav_interface.setCurrentItem(self.current_mode)
            return
        self._apply_mode(mode)

    def _apply_mode(self, mode):
        self.current_mode = mode
        self.nav_interface.setCurrentItem(mode)
        self.footer.setVisible(mode != "import_export")
        self.footer_separator.setVisible(mode != "import_export")
        self.list_column.setVisible(mode != "import_export")
        self.group_combo.setVisible(mode == "content")
        if mode == "group":
            self.new_btn.setEnabled(True)
            self.list_title.setText(self.tr("Group List"))
            self.new_btn.setToolTip(self.tr("New Group") + " (Ctrl+N)")
            self._refresh_group_list()
            self._restore_editor("group", self.editing_group_id)
        elif mode == "content":
            self.list_title.setText(self.tr("Content List"))
            self.new_btn.setToolTip(self.tr("Add Content") + " (Ctrl+N)")
            self._refresh_group_combo()
            self._refresh_content_list()
            self._restore_editor("item", self.editing_item_id)
        else:
            self._show_import_export_form()
        self.new_btn.setAccessibleName(self.new_btn.toolTip())

    def _restore_editor(self, kind, entry_id):
        for row in range(self.list_widget.count()):
            item = self.list_widget.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == (kind, entry_id):
                with QSignalBlocker(self.list_widget):
                    self.list_widget.setCurrentItem(item)
                self._on_list_item_clicked(item)
                return
        with QSignalBlocker(self.list_widget):
            self.list_widget.setCurrentRow(-1)
        if kind == "group":
            self._show_new_group_form()
        else:
            self._show_new_content_form()

    def _new_entry(self):
        if self.current_mode == "import_export" or not self._confirm_discard():
            return
        with QSignalBlocker(self.list_widget):
            self.list_widget.setCurrentRow(-1)
        if self.current_mode == "group":
            self._show_new_group_form()
            self.group_name_input.setFocus()
        else:
            self._show_new_content_form()
            if _qt_object_is_valid(getattr(self, "title_input", None)):
                self.title_input.setFocus()

    def _form_state(self):
        values = []
        for name in ("group_name_input", "icon_input", "title_input", "file_path_input", "content_edit"):
            control = getattr(self, name, None)
            if _qt_object_is_valid(control):
                values.append((name, control.document().isModified() if hasattr(control, "document") else control.text()))
        for name in ("radio_normal", "radio_file", "radio_hidden"):
            control = getattr(self, name, None)
            if _qt_object_is_valid(control):
                values.append((name, control.isChecked()))
        return tuple(values)

    def _update_dirty(self, *_):
        self._dirty = self._clean_state is not None and self._form_state() != self._clean_state
        self.status_label.setText(self.tr("Unsaved changes") if self._dirty else "")
        self.discard_btn.setVisible(self._dirty)
        editing = self.editing_group_id if self.current_mode == "group" else self.editing_item_id
        self.save_btn.setEnabled(self._dirty or editing is None)

    def _mark_saved(self):
        editor = getattr(self, "content_edit", None)
        if _qt_object_is_valid(editor):
            editor.document().setModified(False)
        self._clean_state = self._form_state()
        self._dirty = False
        self._update_dirty()
        self.status_label.setText(self.tr("Saved"))

    def _discard_draft(self):
        if not self._dirty:
            return
        if self.current_mode == "group":
            if self.editing_group_id is not None:
                self._show_edit_group_form(self.editing_group_id)
            else:
                self._show_new_group_form()
        elif self.current_mode == "content":
            if self.editing_item_id is not None:
                self._show_edit_content_form(self.editing_item_id)
            else:
                self._show_new_content_form()

    def _confirm_discard(self):
        if not self._dirty:
            return True
        return show_confirm_dialog(self, self.tr("Unsaved changes"), self.tr("Discard changes and continue?"))

    def _on_current_item_changed(self, current, previous):
        if current is None:
            return
        if not self._confirm_discard():
            with QSignalBlocker(self.list_widget):
                self.list_widget.setCurrentItem(previous)
            return
        self._on_list_item_clicked(current)

    def _select_group_in_combo(self, group_id: int):
        """在分组下拉框中选中指定分组"""
        self.group_combo.blockSignals(True)
        try:
            for i in range(self.group_combo.count()):
                if self.group_combo.itemData(i) == group_id:
                    self.group_combo.setCurrentIndex(i)
                    self.selected_group_id = group_id
                    return
        finally:
            self.group_combo.blockSignals(False)

    def _select_list_item(self, item_type: str, item_id: int):
        """在列表中选中指定类型的项"""
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            data = item.data(Qt.ItemDataRole.UserRole) if item else None
            if data and data[0] == item_type and data[1] == item_id:
                with QSignalBlocker(self.list_widget):
                    self.list_widget.setCurrentRow(i)
                self.list_widget.scrollToItem(item)
                return

    def _refresh_group_combo(self):
        """刷新分组下拉框"""
        self.group_combo.blockSignals(True)
        self.group_combo.clear()

        groups = self.manager.get_groups()
        if not groups:
            self.group_combo.addItem(self.tr("(Please create a group first)"), userData=None)
            self.selected_group_id = None
        else:
            for group in groups:
                icon = get_group_display_icon(group.icon, group.group_type == GroupType.FILE, is_hidden=(group.group_type == GroupType.HIDDEN))
                self.group_combo.addItem(f"{icon} {group.name}", userData=group.id)

            idx = 0
            if self.selected_group_id:
                for i in range(self.group_combo.count()):
                    if self.group_combo.itemData(i) == self.selected_group_id:
                        idx = i
                        break
            self.group_combo.setCurrentIndex(idx)
            self.selected_group_id = self.group_combo.currentData()

        self.group_combo.setEnabled(bool(groups))
        self.group_combo.blockSignals(False)

    def _on_group_combo_changed(self, index: int):
        """分组下拉框改变"""
        if not self._confirm_discard():
            self._select_group_in_combo(self.selected_group_id)
            return
        self.selected_group_id = self.group_combo.currentData()
        self._refresh_content_list()
        self._restore_editor("item", None)

    def _refresh_group_list(self):
        """刷新分组列表（分组管理模式）"""
        current_item = self.list_widget.currentItem()
        saved_group_id = None
        if current_item:
            data = current_item.data(Qt.ItemDataRole.UserRole)
            if data and data[0] == "group":
                saved_group_id = data[1]

        blocker = QSignalBlocker(self.list_widget)
        self.list_widget.clear()


        groups = self.manager.get_groups()
        self.load_more_btn.hide()
        self.list_count.setText(str(len(groups)))
        restored_selection = False
        for i, group in enumerate(groups):
            icon = get_group_display_icon(group.icon, group.group_type == GroupType.FILE, is_hidden=(group.group_type == GroupType.HIDDEN))
            item = QListWidgetItem(f"{icon} {group.name}")
            # 文字仍带 emoji 前缀（外部按 text() 读分组名），但 delegate 认 GROUP_LABEL_ROLE：
            # emoji 画进固定图标槽、名字画进文字槽，于是和上面 PLUS 行左边缘对齐。
            item.setData(GROUP_LABEL_ROLE, (icon, group.name))
            item.setToolTip(group.name)
            item.setData(Qt.ItemDataRole.UserRole, ("group", group.id))
            self.list_widget.addItem(item)

            if saved_group_id is not None and group.id == saved_group_id:
                self.list_widget.setCurrentRow(i)
                restored_selection = True

        if not restored_selection:
            self.list_widget.setCurrentRow(-1)
        del blocker

    def _refresh_content_list(self):
        """刷新内容列表（内容管理模式）"""
        current_item = self.list_widget.currentItem()
        saved_item_id = None
        if current_item:
            data = current_item.data(Qt.ItemDataRole.UserRole)
            if data and data[0] == "item":
                saved_item_id = data[1]

        blocker = QSignalBlocker(self.list_widget)
        self.list_widget.clear()
        self.list_count.setText("0")
        self.load_more_btn.hide()

        if self.selected_group_id is None:
            return

        items = self.manager.get_by_group(self.selected_group_id, limit=51)
        self._has_more_content = len(items) > 50
        self.load_more_btn.setVisible(self._has_more_content)
        self.list_count.setText(str(min(len(items), 50)) + ("+" if self._has_more_content else ""))
        restored_selection = False
        for i, item in enumerate(items[:50]):
            self._append_content_row(item)

            if saved_item_id is not None and item.id == saved_item_id:
                self.list_widget.setCurrentRow(i)
                restored_selection = True

        if not restored_selection:
            self.list_widget.setCurrentRow(-1)
        del blocker

    def _append_content_row(self, item):
        display = item.title or " ".join(item.content[:160].split())
        row = QListWidgetItem(display)
        row.setData(Qt.ItemDataRole.UserRole, ("item", item.id))
        row.setData(PREVIEW_ROLE, " ".join(item.content[:256].split())[:160])
        row.setToolTip(display)
        row.setIcon(Icon.FILE.render_icon(self._apple.text_secondary))
        self.list_widget.addItem(row)
        return row

    def _load_more_content(self):
        if self.current_mode != "content" or self.selected_group_id is None:
            return
        offset = self.list_widget.count()
        items = self.manager.get_by_group(self.selected_group_id, offset=offset, limit=51)
        with QSignalBlocker(self.list_widget):
            for item in items[:50]:
                self._append_content_row(item)
        self._has_more_content = len(items) > 50
        self.load_more_btn.setVisible(self._has_more_content)
        self.list_count.setText(str(self.list_widget.count()) + ("+" if self._has_more_content else ""))

    def _on_list_item_clicked(self, item: QListWidgetItem):
        """列表项点击"""
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data:
            return

        item_type, item_id = data

        if self.current_mode == "group":
            if item_type == "new":
                self.editing_group_id = None
                self._show_new_group_form()
            elif item_type == "group":
                self.editing_group_id = item_id
                self._show_edit_group_form(item_id)
        else:
            if item_type == "new":
                self.editing_item_id = None
                self._show_new_content_form()
            elif item_type == "item":
                self.editing_item_id = item_id
                self._show_edit_content_form(item_id)

    def _on_list_reordered(self, parent, start, end, destination, row):
        """列表拖拽重排序后的处理"""
        if self.current_mode == "group":
            self._handle_group_reorder(start, row)
        else:
            self._handle_item_reorder(start, row)

    def _handle_group_reorder(self, old_index: int, new_index: int):
        """处理分组拖拽排序"""
        from core.logger import T, log_debug, log_info, log_error, log_exception

        log_debug(T("old_index={old_index}, new_index={new_index}", old_index=old_index, new_index=new_index), "GroupDrag")

        groups = self.manager.get_groups()

        log_debug(T("当前有 {count} 个分组", count=len(groups)), "GroupDrag")

        if old_index < 0 or old_index >= len(groups):
            log_error(T("索引越界: old_index={old_index}", old_index=old_index), "GroupDrag")
            return

        old_pos = old_index
        new_pos = new_index

        if old_pos < 0 or old_pos >= len(groups):
            log_error(T("调整后索引越界: old_pos={old_pos}", old_pos=old_pos), "GroupDrag")
            return

        moved_group = groups[old_pos]
        log_debug(T("移动分组: ID={group_id}, name={group_name}", group_id=moved_group.id, group_name=moved_group.name), "GroupDrag")

        temp_groups = [g for i, g in enumerate(groups) if i != old_pos]
        adjusted_new_pos = new_pos if new_pos < old_pos else new_pos - 1

        before_id = None
        after_id = None

        if adjusted_new_pos > 0:
            before_id = temp_groups[adjusted_new_pos - 1].id

        if adjusted_new_pos < len(temp_groups):
            after_id = temp_groups[adjusted_new_pos].id

        log_debug(T("计算: before_id={before_id}, after_id={after_id}", before_id=before_id, after_id=after_id), "GroupDrag")

        try:
            self.manager._manager.move_group_between(moved_group.id, before_id=before_id, after_id=after_id)
            log_info(T("移动成功: ID={group_id}, before={before_id}, after={after_id}", group_id=moved_group.id, before_id=before_id, after_id=after_id), "GroupDrag")
            self._refresh_group_list()
            self.group_added.emit()
        except Exception as e:
            log_error(T("移动失败: {e}", e=e), "GroupDrag")
            log_exception(e, T("拖拽分组移动失败"))
            self._refresh_group_list()

    def _handle_item_reorder(self, old_index: int, new_index: int):
        """处理内容拖拽排序"""
        from core.logger import T, log_debug, log_info, log_error, log_exception

        log_debug(T("old_index={old_index}, new_index={new_index}", old_index=old_index, new_index=new_index), "ItemDrag")

        if self.selected_group_id is None:
            log_error(T("未选择分组"), "ItemDrag")
            return

        items = self.manager.get_by_group(self.selected_group_id, offset=0, limit=1000)

        log_debug(T("当前分组有 {count} 个内容", count=len(items)), "ItemDrag")

        if old_index < 0 or old_index >= len(items):
            log_error(T("索引越界: old_index={old_index}, items count={items_count}", old_index=old_index, items_count=len(items)), "ItemDrag")
            return

        old_pos = old_index
        new_pos = new_index

        if old_pos < 0 or old_pos >= len(items):
            log_error(T("调整后索引越界: old_pos={old_pos}", old_pos=old_pos), "ItemDrag")
            return

        moved_item = items[old_pos]
        log_debug(T("移动项: ID={item_id}, title={item_title}", item_id=moved_item.id, item_title=moved_item.title or moved_item.content[:20]), "ItemDrag")

        temp_items = [item for i, item in enumerate(items) if i != old_pos]
        adjusted_new_pos = new_pos if new_pos < old_pos else new_pos - 1

        before_id = None
        after_id = None

        if adjusted_new_pos > 0:
            before_id = temp_items[adjusted_new_pos - 1].id

        if adjusted_new_pos < len(temp_items):
            after_id = temp_items[adjusted_new_pos].id

        log_debug(T("计算: before_id={before_id}, after_id={after_id}", before_id=before_id, after_id=after_id), "ItemDrag")

        try:
            self.manager._manager.move_item_between(moved_item.id, before_id=before_id, after_id=after_id)
            log_info(T("移动成功: ID={item_id}, before={before_id}, after={after_id}", item_id=moved_item.id, before_id=before_id, after_id=after_id), "ItemDrag")
            self._refresh_content_list()
        except Exception as e:
            log_error(T("移动失败: {e}", e=e), "ItemDrag")
            log_exception(e, T("拖拽内容移动失败"))
            self._refresh_content_list()

    def _clear_detail_layout(self):
        """清空详情区域"""
        self._detail_form_token += 1
        self._clean_state = None
        self._dirty = False
        self.status_label.clear()
        popup = getattr(self, "_icon_popup", None)
        if _qt_object_is_valid(popup):
            popup.hide()
            popup.deleteLater()
        self._icon_popup = None
        type_group = getattr(self, "_group_type_btn_group", None)
        if _qt_object_is_valid(type_group):
            type_group.deleteLater()
        for attr in (
            "title_input",
            "content_edit",
            "file_path_input",
            "file_drop_zone",
            "icon_picker_button",
            "group_name_input",
            "icon_input",
            "radio_normal",
            "radio_file",
            "radio_hidden",
            "_group_type_btn_group",
        ):
            widget = getattr(self, attr, None)
            if _qt_object_is_valid(widget):
                try:
                    widget.blockSignals(True)
                except Exception:
                    pass
            setattr(self, attr, None)

        def clear_layout(layout):
            while layout.count():
                child = layout.takeAt(0)
                widget = child.widget()
                if widget:
                    widget.setParent(None)
                    widget.deleteLater()
                elif child.layout():
                    clear_layout(child.layout())

        clear_layout(self.detail_layout)

    def _finish_detail_form_setup(self):
        """Apply window scaling and theme to a freshly rebuilt detail form."""
        # 末尾收一个弹簧：表单比详情区矮时，多出来的高度会被有伸缩余量的
        # 控件（标签、输入框）平分，于是「标签-输入框」的间距被撑到和
        # 「字段组之间」一样宽，成对关系就看不出来了。让弹簧吃掉余量，
        # 表单顶部对齐、各字段保持紧凑节奏。
        self.detail_layout.addStretch()
        # Detail forms are destroyed and recreated when the selection or mode
        # changes, so the one-time setup in __init__ cannot cover these new
        # controls.  Mark only this subtree to avoid touching existing widgets
        # or compounding any geometry values.
        configure_dialog_controls(self.detail_content)
        self._refresh_theme_scope(subtree=self.detail_content)
        self._apply_dynamic_form_theme()
        for button in self.detail_content.findChildren(QPushButton):
            button.setAutoDefault(False)
        self._clean_state = self._form_state()
        self._dirty = False
        for name in ("group_name_input", "icon_input", "title_input", "file_path_input", "content_edit"):
            control = getattr(self, name, None)
            if _qt_object_is_valid(control):
                control.textChanged.connect(self._update_dirty)
        for name in ("radio_normal", "radio_file", "radio_hidden"):
            control = getattr(self, name, None)
            if _qt_object_is_valid(control):
                control.toggled.connect(self._update_dirty)
        self._update_dirty()

    def _is_current_detail_form_token(self, form_token: Optional[int]) -> bool:
        return form_token is None or form_token == self._detail_form_token

    def _show_new_group_form(self):
        """显示新建分组表单"""
        self._clear_detail_layout()
        self.delete_btn.hide()
        self.save_btn.show()
        self.save_btn.setText(self.tr("Create"))
        self.editing_group_id = None

        build_new_group_form(self)
        self._update_group_form_header()
        self._finish_detail_form_setup()

    def _on_group_type_toggled(self, checked: bool, form_token: Optional[int] = None):
        """分组类型切换时，若用户未手动修改图标则自动切换默认图标"""
        if not self._is_current_detail_form_token(form_token):
            return
        if not _qt_object_is_valid(getattr(self, "icon_input", None)):
            return
        if not checked:
            return  # 只处理选中事件，避免重复触发
        current = self.icon_input.text()
        is_file_group = _qt_object_is_valid(getattr(self, "radio_file", None)) and self.radio_file.isChecked()
        is_hidden = _qt_object_is_valid(getattr(self, "radio_hidden", None)) and self.radio_hidden.isChecked()
        self.icon_input.setText(get_toggled_default_group_icon(current, is_file_group, is_hidden=is_hidden))
        self._update_group_form_header()

    def _set_detail_subtitle(self, text: str):
        """设置详情区标题下方的小字说明。"""
        self.detail_subtitle.setText(text)
        self.detail_subtitle.setVisible(bool(text))

    def _update_group_form_header(self):
        """根据当前分组类型刷新分组表单标题和说明。"""
        if not _qt_object_is_valid(getattr(self, "radio_file", None)):
            return

        self.detail_title.setText(self.tr("New Group") if self.editing_group_id is None else self.tr("Edit Group"))
        self._set_detail_subtitle(self.tr("Name this group and choose how its contents are used."))

    def _on_icon_input_changed(self, text: str, form_token: Optional[int] = None):
        """输入框内容变化时更新预览（只保留第一个 emoji）"""
        if not self._is_current_detail_form_token(form_token):
            return
        if not _qt_object_is_valid(getattr(self, "icon_input", None)):
            return
        on_icon_input_changed(self, text)

    def _on_preset_icon_clicked(self, icon: str, form_token: Optional[int] = None):
        """点击预设图标"""
        if not self._is_current_detail_form_token(form_token):
            return
        if not _qt_object_is_valid(getattr(self, "icon_input", None)):
            return
        on_preset_icon_clicked(self, icon)

    def _show_edit_group_form(self, group_id: int):
        """显示编辑分组表单"""
        self._clear_detail_layout()
        self.delete_btn.show()
        self.save_btn.show()
        self.save_btn.setText(self.tr("Save"))
        self.editing_group_id = group_id

        groups = self.manager.get_groups()
        group = next((g for g in groups if g.id == group_id), None)
        if not group:
            return

        build_edit_group_form(self, group)
        self._update_group_form_header()
        self._finish_detail_form_setup()

    def _get_selected_group(self) -> Optional[Group]:
        """获取当前选中分组对象"""
        if self.selected_group_id is None:
            return None
        groups = self.manager.get_groups()
        return next((g for g in groups if g.id == self.selected_group_id), None)

    def _is_file_content_mode(self) -> bool:
        """判断当前内容编辑是否应走文件条目表单。
        隐藏分组的行为与普通分组相同，不走文件表单。"""
        if self.editing_item_id is not None:
            item = self.manager.get_item(self.editing_item_id)
            if item is not None:
                return item.content_type == "file"

        selected_group = self._get_selected_group()
        if selected_group is None:
            return False
        # 只有快速启动分组才走文件表单；隐藏分组和普通分组一样走文本表单
        return selected_group.group_type == GroupType.FILE

    def _extract_file_path_from_item(self, item) -> str:
        """从文件条目内容中提取首个路径，兼容旧格式原始路径文本。"""
        if item is None or item.content_type != "file":
            return ""
        return extract_first_file_path_from_content(item.content)

    def _show_new_content_form(self):
        """显示新建内容表单"""
        self._clear_detail_layout()
        self.detail_title.setText(self.tr("Add Content"))
        self._set_detail_subtitle(self.tr("Save reusable text or file paths in this group."))
        self.delete_btn.hide()
        self.save_btn.show()
        self.save_btn.setText(self.tr("Add"))
        self.editing_item_id = None
        has_group = self.selected_group_id is not None
        self.footer.setVisible(has_group)
        self.footer_separator.setVisible(has_group)
        self.new_btn.setEnabled(has_group)

        if self.selected_group_id is None:
            hint = CaptionLabel(self.tr("Please select a group above, or create a group first"))
            self.detail_layout.addWidget(hint)
            create = Button(self.tr("New Group"), variant="outline", icon=Icon.PLUS)
            create.clicked.connect(lambda: self._switch_mode("group"))
            row = QHBoxLayout()
            row.addWidget(create)
            row.addStretch()
            self.detail_layout.addLayout(row)
            self._finish_detail_form_setup()
            return

        selected_group = self._get_selected_group()
        if selected_group is not None and selected_group.group_type == GroupType.FILE:
            self._build_file_content_form()
        else:
            self._build_text_content_form()
        self._finish_detail_form_setup()

    def _build_text_content_form(self):
        """普通分组 — 文本内容输入表单"""
        build_text_content_form(self)

    def _build_file_content_form(self, add_stretch: bool = True):
        """文件分组 — 文件选择表单"""
        build_file_content_form(self, add_stretch=add_stretch)

    def _set_selected_file_path(self, path: str):
        """统一设置当前选中的文件或文件夹路径。"""
        import os

        normalized_path = os.path.normpath(path)
        self.selected_file_path = normalized_path
        if hasattr(self, "file_path_input"):
            self.file_path_input.setText(normalized_path)

    def _on_browse_file(self):
        """弹出文件选择对话框"""
        path, _ = QFileDialog.getOpenFileName(self, self.tr("Select File"), "", self.tr("All Files (*.*)"))
        if path:
            self._set_selected_file_path(path)

    def _on_browse_folder(self):
        """弹出文件夹选择对话框"""
        path = QFileDialog.getExistingDirectory(self, self.tr("Select Folder"), "")
        if path:
            self._set_selected_file_path(path)

    def _show_edit_content_form(self, item_id: int):
        """显示编辑内容表单"""
        self._clear_detail_layout()
        self.detail_title.setText(self.tr("Edit Content"))
        self._set_detail_subtitle(self.tr("Edit the content, then save your changes."))
        self.delete_btn.show()
        self.save_btn.show()
        self.save_btn.setText(self.tr("Save"))
        self.editing_item_id = item_id

        item = self.manager.get_item(item_id)
        if not item:
            return

        if item.content_type == "file":
            file_path = self._extract_file_path_from_item(item)
            build_edit_file_content_form(self, item, file_path)
        else:
            build_edit_text_content_form(self, item)

        if item.created_at:
            time_str = item.created_at.strftime("%Y-%m-%d %H:%M:%S")
            time_label = CaptionLabel(f"{self.tr('Created')}: {time_str}")
            self.detail_layout.addWidget(time_label)

        if item.content_type == "file":
            self.detail_layout.addStretch()
        self._finish_detail_form_setup()

    def _show_import_export_form(self):
        """显示导入导出表单"""
        self._clear_detail_layout()
        self.detail_title.setText(self.tr("Import/Export"))
        self._set_detail_subtitle(self.tr("Transfer saved text and file paths using CSV."))
        self.delete_btn.hide()
        self.save_btn.hide()

        build_import_export_form(self)
        self._finish_detail_form_setup()

    def _get_selected_icon(self) -> str:
        """获取选中的图标（优先从输入框获取，确保只有一个字符）"""
        if _qt_object_is_valid(getattr(self, "icon_input", None)):
            text = first_grapheme(self.icon_input.text())
            if text:
                return text
        return "📁"

    def _get_delete_group_confirm_message(self) -> str:
        return build_delete_group_confirm_message(self.tr)

    def _group_name_exists(self, name: str, exclude_group_id: Optional[int] = None) -> bool:
        return group_name_exists(self.manager.get_groups(), name, exclude_group_id=exclude_group_id)

    @staticmethod
    def _make_unique_group_name(base_name: str, used_names: set[str]) -> str:
        return make_unique_group_name(base_name, used_names)

    def _on_save_clicked(self):
        """保存按钮点击"""
        if self.current_mode == "group":
            self._save_group()
        elif self.current_mode == "content":
            self._save_content()

    def _save_group(self):
        """保存分组"""
        if not _qt_object_is_valid(getattr(self, "group_name_input", None)):
            return
        name = self.group_name_input.text().strip()
        if not name:
            show_warning_dialog(self, self.tr("Hint"), self.tr("Please enter group name"))
            return

        if self._group_name_exists(name, exclude_group_id=self.editing_group_id):
            show_warning_dialog(self, self.tr("Hint"), self.tr("A group with this name already exists"))
            return

        icon = self._get_selected_icon()
        if _qt_object_is_valid(getattr(self, "radio_hidden", None)) and self.radio_hidden.isChecked():
            group_type = GroupType.HIDDEN
        elif _qt_object_is_valid(getattr(self, "radio_file", None)) and self.radio_file.isChecked():
            group_type = GroupType.FILE
        else:
            group_type = GroupType.NORMAL

        result = save_group(self.manager, self.editing_group_id, name, icon, int(group_type))
        if not result.success:
            message = self.tr("Failed to create group") if result.error == "create_group_failed" else self.tr("Failed to update group")
            show_warning_dialog(self, self.tr("Failed"), message)
            return

        self.editing_group_id = result.entity_id
        self.group_added.emit()
        self.data_changed.emit()
        self._refresh_group_list()
        self._select_list_item("group", result.entity_id)
        self._update_group_form_header()
        self.delete_btn.show()
        self.save_btn.setText(self.tr("Save"))
        self._mark_saved()

    def _save_content(self):
        """保存内容"""
        if self.selected_group_id is None:
            show_warning_dialog(self, self.tr("Hint"), self.tr("Please select a group first"))
            return

        if self._is_file_content_mode():
            self._save_file_content()
        else:
            self._save_text_content()

    def _save_file_content(self):
        """保存文件类型内容"""
        path = getattr(self, "selected_file_path", None)
        if not path and hasattr(self, "file_path_input"):
            path = self.file_path_input.text().strip()
        if not path:
            show_warning_dialog(self, self.tr("Hint"), self.tr("Please select a file"))
            return

        title = self.title_input.text().strip() if hasattr(self, "title_input") else None
        title = title if title else None

        result = save_file_content(self.manager, self.editing_item_id, self.selected_group_id, path, title)
        if not result.success:
            error_messages = {
                "move_to_group_failed": self.tr("Failed to move to group"),
                "add_content_failed": self.tr("Failed to add content"),
                "update_content_failed": self.tr("Failed to update content"),
            }
            show_warning_dialog(self, self.tr("Failed"), error_messages.get(result.error, self.tr("Failed to update content")))
            return

        self._finish_content_save(result.entity_id)

    def _save_text_content(self):
        """保存文本类型内容（原有逻辑）"""
        content = self.content_edit.toPlainText().strip()
        if not content:
            show_warning_dialog(self, self.tr("Hint"), self.tr("Please enter content"))
            return

        title = self.title_input.text().strip() if hasattr(self, "title_input") else None
        title = title if title else None

        result = save_text_content(self.manager, self.editing_item_id, self.selected_group_id, content, title)
        if not result.success:
            error_messages = {
                "move_to_group_failed": self.tr("Failed to move to group"),
                "add_content_failed": self.tr("Failed to add content"),
                "update_content_failed": self.tr("Failed to update content"),
            }
            show_warning_dialog(self, self.tr("Failed"), error_messages.get(result.error, self.tr("Failed to update content")))
            return

        self._finish_content_save(result.entity_id)

    def _finish_content_save(self, item_id):
        self.editing_item_id = item_id
        self.content_added.emit(self.selected_group_id)
        self.data_changed.emit()
        self._refresh_content_list()
        self._select_list_item("item", item_id)
        self.detail_title.setText(self.tr("Edit Content"))
        self.delete_btn.show()
        self.save_btn.setText(self.tr("Save"))
        self._mark_saved()

    def _on_delete_clicked(self):
        """删除按钮点击"""
        if self.current_mode == "group" and self.editing_group_id:
            reply = show_confirm_dialog(self, self.tr("Confirm Delete"), self._get_delete_group_confirm_message())
            if reply:
                if self.manager.delete_group(self.editing_group_id):
                    self.editing_group_id = None
                    self.group_added.emit()
                    self.data_changed.emit()
                    self._refresh_group_list()
                    self._show_new_group_form()
                else:
                    show_warning_dialog(self, self.tr("Failed"), self.tr("Failed to delete group"))

        elif self.current_mode == "content" and self.editing_item_id:
            reply = show_confirm_dialog(self, self.tr("Confirm Delete"), self.tr("Are you sure you want to delete this item?"))
            if reply:
                if self.manager.delete_item(self.editing_item_id):
                    self.editing_item_id = None
                    self.content_added.emit(self.selected_group_id)
                    self.data_changed.emit()
                    self._refresh_content_list()
                    self._show_new_content_form()
                else:
                    show_warning_dialog(self, self.tr("Failed"), self.tr("Failed to delete item"))

    def _switch_page(self, index: int):
        """切换页面。"""
        if index == 0:
            self._switch_mode("group")
        else:
            self._switch_mode("content")

    def _export_to_csv(self):
        """导出收藏内容到 CSV 文件（仅导出纯文本内容）"""
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            self.tr("Export to CSV"),
            "clipboard_export.csv",
            "CSV Files (*.csv);;All Files (*)",
        )

        if not file_path:
            return

        try:
            rows = collect_text_export_rows(self.manager)

            encoding = "utf-8-sig"
            if hasattr(self, "export_encoding_combo"):
                encoding = self.export_encoding_combo.currentData() or "utf-8-sig"

            write_csv_rows(file_path, [self.tr("Group"), self.tr("Content"), self.tr("Title")], rows, encoding)

            show_info_dialog(
                self,
                self.tr("Export Successful"),
                self.tr("Exported {count} items to CSV file.").format(count=len(rows)),
            )
        except Exception as e:
            show_warning_dialog(self, self.tr("Export Failed"), self.tr("Failed to export: {error}").format(error=str(e)))

    def _import_from_csv(self):
        """从 CSV 文件导入内容"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            self.tr("Import from CSV"),
            "",
            "CSV Files (*.csv);;All Files (*)",
        )

        if not file_path:
            return

        try:
            rows = read_import_rows(file_path)

            if not rows:
                show_warning_dialog(self, self.tr("Import Failed"), self.tr("No valid data found in CSV file."))
                return

            imported_count = import_text_rows(self.manager, rows)

            self.group_added.emit()
            self.data_changed.emit()
            if self.current_mode == "group":
                self._refresh_group_list()
            else:
                self._refresh_content_list()

            show_info_dialog(
                self,
                self.tr("Import Successful"),
                self.tr("Imported {count} items.").format(count=imported_count),
            )
        except Exception as e:
            show_warning_dialog(self, self.tr("Import Failed"), self.tr("Failed to import: {error}").format(error=str(e)))


__all__ = [
    "ManageDialog",
    "destroy_manage_dialog",
    "get_existing_manage_dialog",
    "get_manage_dialog",
]
