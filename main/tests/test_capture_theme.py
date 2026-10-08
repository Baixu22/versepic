"""Live palette changes must preserve screenshot editing state."""
from PySide6.QtGui import QColor

from core.theme import get_theme
from core.ui_theme import get_ui_theme
from ui.toolbar import Toolbar
from ui.tray_menu import CustomTrayMenu


def test_live_capture_theme_preserves_tool_and_annotation(qtbot):
    theme = get_ui_theme()
    original_mode = theme.mode
    bar = Toolbar()
    menu = CustomTrayMenu()
    qtbot.addWidget(bar)
    qtbot.addWidget(menu)
    bar.select_tool("pen")
    original_color = bar.paint_panel.current_color.name()
    original_width = bar.paint_panel.current_size
    try:
        for mode in ("dark", "light", "dark"):
            theme.set_mode(mode, persist=False)
            assert bar._buttons["pen"].isChecked()
            assert bar.paint_panel.current_color.name() == original_color
            assert bar.paint_panel.current_size == original_width
            assert theme.tokens.surface in bar.paint_panel.styleSheet()
            assert theme.tokens.popup_hover in menu.styleSheet()
            # The actual arrow preview must change ink with the palette.
            icon = bar.arrow_panel.arrow_style_combo.itemIcon(0)
            image = icon.pixmap(80, 22).toImage()
            pixels = [image.pixelColor(x, y) for x in range(image.width())
                      for y in range(image.height())]
            solid = [p for p in pixels if p.alpha() > 240]
            assert solid
            assert abs(solid[0].lightness() - QColor(theme.tokens.text).lightness()) < 5
    finally:
        theme.set_mode(original_mode, persist=False)


def test_legacy_capture_accent_follows_palette_without_overwriting_custom_color(qapp):
    theme = get_ui_theme()
    capture = get_theme()
    original_mode, original_color = theme.mode, QColor(capture._theme_color)
    try:
        capture.set_theme_color(QColor("#40E0D0"))
        for mode in ("light", "dark"):
            theme.set_mode(mode, persist=False)
            assert capture.theme_color == QColor(theme.tokens.accent)
        capture.set_theme_color(QColor("#c45a32"))
        theme.set_mode("light", persist=False)
        assert capture.theme_color == QColor("#c45a32")
    finally:
        capture.set_theme_color(original_color)
        theme.set_mode(original_mode, persist=False)
