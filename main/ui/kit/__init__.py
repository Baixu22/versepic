"""Project-owned, neutral Qt Widgets kit.

Public imports live here; fluent_lite remains the compatibility implementation
for existing feature pages. No Qt Quick, WebEngine or external widget dependency.
"""
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QWidget

from core.ui_theme import DARK_TOKENS, LIGHT_TOKENS, get_ui_theme
from core.ui_scale import configure_dialog_controls
from ui.outline_icons import Icon
from ui.fluent_lite import (
    BodyLabel, CaptionLabel, ComboBox, DoubleSpinBox, LineEdit, NavigationInterface,
    RadioButton, SegmentedWidget, SimpleCardWidget, SpinBox, SwitchButton, TextEdit,
)
from ui.fluent_lite.button_base import Button, IconButton
from ui.fluent_lite.popups import Menu, ToolTip
from ui.fluent_lite.primitives import Badge, CheckBox, Separator
from ui.fluent_lite.theme import ui_tokens


class Theme:
    @staticmethod
    def apply(root, mode="light"):
        """Scope one window independently; mode may be light, dark or system."""
        if mode not in ("light", "dark", "system"):
            raise ValueError(f"Unknown theme: {mode}")
        root._ui_theme_tokens_override = (
            None if mode == "system" else DARK_TOKENS if mode == "dark" else LIGHT_TOKENS
        )
        root.setPalette(get_ui_theme().build_palette(ui_tokens(root)))
        for widget in [root, *root.findChildren(QWidget)]:
            apply = getattr(widget, "_apply_theme", None)
            if callable(apply):
                apply()
            widget.update()
        tip = getattr(root, "_kit_tooltip", None)
        if tip is not None:
            tip.hide()

    @staticmethod
    def setup(root, mode="system"):
        font = QFont()
        font.setFamilies(["Segoe UI Variable", "Microsoft YaHei UI", "Segoe UI"])
        font.setPixelSize(13)
        root.setFont(font)
        configure_dialog_controls(root)
        Theme.apply(root, mode)
        ToolTip.install(root)


__all__ = [
    "Button", "IconButton", "Icon", "LineEdit", "TextEdit", "ComboBox", "SpinBox",
    "DoubleSpinBox", "CheckBox", "RadioButton", "SwitchButton", "SegmentedWidget",
    "NavigationInterface", "Badge", "Separator", "Menu", "ToolTip", "BodyLabel",
    "CaptionLabel", "SimpleCardWidget", "Theme", "ui_tokens",
]
