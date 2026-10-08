from PySide6.QtCore import QSettings

from core.ui_theme import get_ui_theme
from settings.tool_settings import ToolSettingsManager
from ui.settings_ui.dialog import SettingsDialog


def test_apply_theme_keeps_window_open_and_footer_equal(qtbot, tmp_path, monkeypatch):
    manager = ToolSettingsManager(QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat))
    manager.set_log_dir(str(tmp_path))
    monkeypatch.setattr("core.shortcut_manager.HotkeySystem.check_hotkey_availability", lambda *_: True)
    theme = get_ui_theme()
    previous = theme.mode
    dialog = SettingsDialog(manager)
    qtbot.addWidget(dialog)
    # OS startup/logging are unrelated to applying an appearance preference.
    for name in ("autostart_toggle", "log_toggle", "language_combo"):
        if hasattr(dialog, name):
            delattr(dialog, name)
    applied, accepted = [], []
    dialog.settings_applied.connect(lambda: applied.append(True))
    dialog.accepted.connect(lambda: accepted.append(True))
    try:
        dialog.show()
        dialog._ui_theme_combo.setCurrentIndex(dialog._ui_theme_combo.findData("dark"))
        dialog.apply_settings()
        assert applied == [True]
        assert accepted == []
        assert dialog.isVisible()
        assert theme.tokens.is_dark
        assert dialog._footer_ok_btn.width() == dialog._footer_cancel_btn.width()
        assert theme.tokens.primary_foreground in dialog._footer_ok_btn.styleSheet()
        assert not dialog._has_unsaved_changes()
    finally:
        dialog._skip_unsaved_close_prompt = True
        dialog.hide()
        theme.set_mode(previous, persist=False)
