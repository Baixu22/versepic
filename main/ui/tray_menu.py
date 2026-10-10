# -*- coding: utf-8 -*-
"""System tray context menu."""

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QFileDialog, QMenu

from core import safe_event
from core.constants import CSS_FONT_FAMILY_UI
from core.i18n import make_tr
from core.logger import log_exception
from ui.dialogs import show_warning_dialog

_tr = make_tr("SystemTray")


class CustomTrayMenu(QMenu):
    def __init__(self, *args):
        super().__init__(*args)
        from core.ui_theme import get_ui_theme
        self.aboutToShow.connect(self._apply_theme)
        get_ui_theme().theme_changed.connect(self._apply_theme)

    def _apply_theme(self, *_):
        self.setStyleSheet(_menu_style())

    @safe_event
    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            return
        super().mouseReleaseEvent(event)


def create_tray_menu(app) -> QMenu:
    """Create the system tray context menu for MainApp."""
    menu = CustomTrayMenu()
    menu.setStyleSheet(_menu_style())

    action_screenshot = QAction(_tr("Screenshot"), app)
    action_screenshot.triggered.connect(app.start_screenshot)
    menu.addAction(action_screenshot)

    delayed_menu = CustomTrayMenu(_tr("Delayed screenshot"), menu)
    menu.addMenu(delayed_menu)
    menu.delayed_capture_menu = delayed_menu
    for seconds in (3, 5, 10):
        action = delayed_menu.addAction(_tr("After %1 seconds").replace("%1", str(seconds)))
        action.triggered.connect(lambda checked=False, delay=seconds: app.start_delayed_screenshot(delay))

    from settings.tool_settings import QUICK_CAPTURE_ACTIONS
    quick_menu = CustomTrayMenu(_tr("Quick capture"), menu)
    menu.addMenu(quick_menu)
    menu.quick_capture_menu = quick_menu
    for kind, label in QUICK_CAPTURE_ACTIONS:
        action = quick_menu.addAction(_tr(label))
        action.triggered.connect(
            lambda checked=False, capture_kind=kind:
            QTimer.singleShot(100, app, lambda: app.start_quick_capture(capture_kind)))

    private_action = QAction(_tr("Sensitive screenshot (once)"), app)
    private_action.triggered.connect(lambda checked=False: QTimer.singleShot(100, app, app.start_sensitive_screenshot))
    menu.addAction(private_action)

    action_clipboard = QAction(_tr("Clipboard"), app)
    action_clipboard.triggered.connect(app.open_clipboard_window)
    menu.addAction(action_clipboard)

    editor_action = QAction(_tr("Open image editor…"), app)
    editor_action.triggered.connect(_open_image_editor)
    menu.addAction(editor_action)

    compare_action = QAction(_tr("Compare images…"), app)
    compare_action.triggered.connect(_open_image_compare)
    menu.addAction(compare_action)

    workspace_action = QAction(_tr("Pin workspaces…"), app)
    workspace_action.triggered.connect(_open_pin_workspaces)
    menu.addAction(workspace_action)

    layout_action = QAction(_tr("Image layout / PDF"), app)
    layout_action.triggered.connect(_open_image_layout)
    menu.addAction(layout_action)

    action_translate = QAction(_tr("Translation"), app)
    action_translate.triggered.connect(app.open_translator)
    menu.addAction(action_translate)

    menu.addSeparator()

    action_global_hotkeys = QAction(_tr("Disable Global Hotkeys"), app)
    action_global_hotkeys.setCheckable(True)
    action_global_hotkeys.setChecked(
        app.config_manager.get_app_setting("global_hotkeys_disabled", False)
    )
    action_global_hotkeys.triggered.connect(app.set_global_hotkeys_disabled)
    menu.addAction(action_global_hotkeys)

    menu.addSeparator()
    _add_pin_actions(menu, app)

    menu.addSeparator()

    action_settings = QAction(_tr("Settings"), app)
    action_settings.triggered.connect(app.open_settings)
    menu.addAction(action_settings)

    menu.addSeparator()

    action_quit = QAction(_tr("Exit"), app)
    action_quit.triggered.connect(app.quit_app)
    menu.addAction(action_quit)

    return menu


def _menu_style() -> str:
    from core.ui_theme import get_ui_theme

    t = get_ui_theme().tokens
    return f"""
        QMenu {{
            background-color: {t.popup_background};
            border: 1px solid {t.border};
            border-radius: 12px;
            padding: 4px;
            font-family: {CSS_FONT_FAMILY_UI};
            font-size: 9pt;
            color: {t.text};
        }}
        QMenu::item {{
            padding: 8px 16px;
            border-radius: 8px;
            color: {t.text};
            background-color: transparent;
        }}
        QMenu::item:selected {{
            background-color: {t.popup_hover};
            color: {t.text};
        }}
        QMenu::item:disabled {{
            color: {t.text_disabled};
        }}
        QMenu::separator {{
            height: 1px;
            background: {t.separator};
            margin: 4px 6px;
        }}
    """


def _add_pin_actions(menu: QMenu, app):
    from pin.pin_manager import PinManager

    pin_manager = PinManager.instance()
    pin_count = pin_manager.count()
    has_pins = pin_count > 0

    close_all_action = QAction(_tr("Close all pinned windows"), app)
    close_all_action.setEnabled(has_pins)
    close_all_action.triggered.connect(pin_manager.close_all)
    menu.addAction(close_all_action)

    pins_title = _tr("Current pinned windows: {count}").format(count=pin_count)
    if not has_pins:
        pins_action = QAction(pins_title, app)
        pins_action.setEnabled(False)
        menu.addAction(pins_action)
        return

    pins_menu = CustomTrayMenu(pins_title, menu)
    pins_menu.setStyleSheet(_menu_style())

    move_center_action = QAction(_tr("Move all pins to center"), app)
    move_center_action.triggered.connect(pin_manager.move_all_to_screen_center)
    pins_menu.addAction(move_center_action)

    thumbnail_all_action = QAction(_tr("Thumbnail all pins"), app)
    thumbnail_all_action.triggered.connect(lambda: pin_manager.set_all_thumbnail_mode(True))
    pins_menu.addAction(thumbnail_all_action)

    restore_all_action = QAction(_tr("Restore all pin thumbnails"), app)
    restore_all_action.triggered.connect(lambda: pin_manager.set_all_thumbnail_mode(False))
    pins_menu.addAction(restore_all_action)

    pins_menu.addSeparator()

    submenu_close_all_action = QAction(_tr("Close all pins"), app)
    submenu_close_all_action.triggered.connect(pin_manager.close_all)
    pins_menu.addAction(submenu_close_all_action)

    save_all_action = QAction(_tr("Save all pins as..."), app)
    save_all_action.triggered.connect(lambda: _save_all_pins_as(app, pin_manager))
    pins_menu.addAction(save_all_action)
    layout_action = pins_menu.addAction(_tr("Arrange pinned images…"))
    layout_action.triggered.connect(_arrange_pinned_images)

    menu.addMenu(pins_menu)


def _save_all_pins_as(app, pin_manager):
    directory = QFileDialog.getExistingDirectory(
        None,
        _tr("Choose folder to save pinned images"),
        str(Path.home()),
    )
    if not directory:
        return

    prefix = datetime.now().strftime("pins_%Y%m%d_%H%M%S")
    try:
        saved, failed = pin_manager.save_all_to_directory(directory, prefix=prefix)
    except Exception as e:
        log_exception(e, "Save all pins")
        show_warning_dialog(None, _tr("Save Failed"), str(e))
        return

    if failed:
        show_warning_dialog(
            None,
            _tr("Save Failed"),
            _tr("Saved {saved} pinned images, failed {failed}.").format(
                saved=saved,
                failed=failed,
            ),
        )


def _open_image_layout():
    from ui.image_layout_dialog import show_image_layout
    return show_image_layout()


def _arrange_pinned_images():
    window = _open_image_layout()
    window.add_pins()


def _open_image_editor():
    from ui.image_editor import show_image_editor
    return show_image_editor()


def _open_pin_workspaces():
    from pin.workspace_dialog import show_pin_workspaces
    return show_pin_workspaces()


def _open_image_compare():
    from ui.image_compare import show_image_compare
    return show_image_compare()
