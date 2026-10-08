"""Menu hover must respect the clipboard theme independently of the app theme."""
import pytest
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QMenu

from clipboard.ui.theme.themes import THEME_DARK, THEME_LIGHT
from clipboard.ui.theme.theme_styles import ThemeStyleGenerator
from core.ui_theme import get_ui_theme


@pytest.mark.parametrize("theme,app_mode,dark", [
    (THEME_DARK, "light", True), (THEME_LIGHT, "dark", False),
])
@pytest.mark.parametrize("checked", [False, True])
def test_menu_hover_uses_local_theme(qtbot, theme, app_mode, dark, checked):
    manager = get_ui_theme()
    original = manager.mode
    menu = QMenu()
    qtbot.addWidget(menu)
    try:
        manager.set_mode(app_mode, persist=False)
        menu.setStyleSheet(ThemeStyleGenerator(theme).generate_menu_style())
        action = menu.addAction("Keep clipboard open")
        action.setCheckable(True)
        action.setChecked(checked)
        menu.popup(QPoint(20, 20))
        assert menu.font().pixelSize() == 15
        menu.setActiveAction(action)
        qtbot.wait(20)
        rect = menu.actionGeometry(action)
        pixel = menu.grab().toImage().pixelColor(rect.right() - 12, rect.center().y())
        assert (pixel.lightness() < 100) if dark else (pixel.lightness() > 180)
        assert action.isChecked() == checked
    finally:
        menu.close()
        manager.set_mode(original, persist=False)
