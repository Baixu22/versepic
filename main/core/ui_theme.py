# -*- coding: utf-8 -*-
"""Application-wide light/dark appearance management.

This module intentionally does not manage screenshot accent and mask colours;
those remain in :mod:`core.theme`.  UIThemeManager owns only semantic colours
used by application windows and native Qt widgets.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication


class UIThemeMode(str, Enum):
    SYSTEM = "system"
    LIGHT = "light"
    DARK = "dark"

    @classmethod
    def coerce(cls, value) -> "UIThemeMode":
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value).lower())
        except ValueError:
            return cls.SYSTEM


@dataclass(frozen=True)
class UIThemeTokens:
    mode: UIThemeMode
    accent: str
    accent_hover: str
    accent_pressed: str
    accent_soft: str
    window: str
    window_top: str
    window_bottom: str
    surface: str
    surface_strong: str
    surface_subtle: str
    surface_hover: str
    text: str
    text_muted: str
    text_disabled: str
    border: str
    border_hover: str
    window_border: str
    input_background: str
    popup_background: str
    popup_hover: str
    separator: str
    switch_off: str
    # 白字压在 accent 上只有 3.4:1，不够正文对比度；实心按钮这类要承载白字
    # 的填充改用深一档的 accent_strong（4.9:1），开关、指示条仍用 accent。
    accent_strong: str
    accent_strong_hover: str
    accent_strong_pressed: str
    # 浅强调底（accent_soft）上的文字和图标，比如导航与标签页的选中项。
    accent_text: str
    success: str
    danger: str
    danger_soft: str
    status_idle: str
    selected_text: str = "#FFFFFF"

    @property
    def primary_foreground(self) -> str:
        return "#171717" if self.is_dark else "#FAFAFA"

    @property
    def ring(self) -> str:
        return "#A3A3A3" if self.is_dark else "#737373"

    @property
    def is_dark(self) -> bool:
        return self.mode is UIThemeMode.DARK


# Neutral UI chrome. Screenshot annotation colours remain in core.theme.
LIGHT_TOKENS = UIThemeTokens(
    mode=UIThemeMode.LIGHT,
    accent="#171717", accent_hover="#3D3D3D", accent_pressed="#525252",
    accent_strong="#171717", accent_strong_hover="#3D3D3D", accent_strong_pressed="#525252",
    accent_soft="#F1F1F1", accent_text="#171717",
    window="#FAFAFA", window_top="#FAFAFA", window_bottom="#FAFAFA",
    surface="#FFFFFF", surface_strong="#FFFFFF", surface_subtle="#F1F1F1", surface_hover="#F1F1F1",
    text="#171717", text_muted="#737373", text_disabled="#A3A3A3",
    border="#E7E7E7", border_hover="#A3A3A3", window_border="#D4D4D4",
    input_background="#F1F1F1", popup_background="#FFFFFF", popup_hover="#F1F1F1",
    separator="#E7E7E7", switch_off="#D4D4D4",
    success="#16803C", danger="#B91C1C", danger_soft="#FEF2F2", status_idle="#A3A3A3",
    selected_text="#FAFAFA",
)

DARK_TOKENS = UIThemeTokens(
    mode=UIThemeMode.DARK,
    accent="#E5E5E5", accent_hover="#E7E7E7", accent_pressed="#D4D4D4",
    accent_strong="#E5E5E5", accent_strong_hover="#E7E7E7", accent_strong_pressed="#D4D4D4",
    accent_soft="#262626", accent_text="#FAFAFA",
    window="#0A0A0A", window_top="#0A0A0A", window_bottom="#0A0A0A",
    surface="#171717", surface_strong="#202020", surface_subtle="#262626", surface_hover="#3D3D3D",
    text="#FAFAFA", text_muted="#A3A3A3", text_disabled="#737373",
    border="#2E2E2E", border_hover="#737373", window_border="#525252",
    input_background="#262626", popup_background="#202020", popup_hover="#3D3D3D",
    separator="#2E2E2E", switch_off="#525252",
    success="#4ADE80", danger="#F87171", danger_soft="#3B2020", status_idle="#737373",
    selected_text="#171717",
)


class UIThemeManager(QObject):
    """Resolve, persist and apply the effective application appearance."""

    theme_changed = Signal(object)
    mode_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._config = None
        self._application: Optional[QApplication] = None
        self._mode = UIThemeMode.SYSTEM
        self._effective_mode = UIThemeMode.LIGHT
        self._system_signal_connected = False

    def init(self, config_manager=None, application=None):
        self._config = config_manager
        app = application or QApplication.instance()
        self._application = app if isinstance(app, QApplication) else None
        saved = (
            config_manager.get_app_setting("ui_theme_mode", "system")
            if config_manager is not None
            else "system"
        )
        self._mode = UIThemeMode.coerce(saved)
        self._connect_system_theme()
        self.apply(force=True)
        return self

    @property
    def mode(self) -> UIThemeMode:
        return self._mode

    @property
    def effective_mode(self) -> UIThemeMode:
        return self._effective_mode

    @property
    def is_dark(self) -> bool:
        return self._effective_mode is UIThemeMode.DARK

    @property
    def tokens(self) -> UIThemeTokens:
        return DARK_TOKENS if self.is_dark else LIGHT_TOKENS

    def set_mode(self, mode, persist: bool = True):
        normalized = UIThemeMode.coerce(mode)
        changed = normalized is not self._mode
        self._mode = normalized
        if persist and self._config is not None:
            self._config.set_app_setting("ui_theme_mode", normalized.value)
        self.apply(force=changed)
        if changed:
            self.mode_changed.emit(normalized.value)

    def apply(self, force: bool = False):
        effective = self._resolve_effective_mode()
        changed = effective is not self._effective_mode
        self._effective_mode = effective
        if not (force or changed):
            return

        if self._application is not None:
            self._application.setProperty("uiTheme", effective.value)
            self._application.setPalette(self.build_palette(self.tokens))
            self._application.setStyleSheet(
                self._build_global_stylesheet(self.tokens)
            )

        self.theme_changed.emit(self.tokens)

    def _resolve_effective_mode(self) -> UIThemeMode:
        if self._mode is not UIThemeMode.SYSTEM:
            return self._mode
        hints = QGuiApplication.styleHints()
        if hints is not None and hasattr(hints, "colorScheme"):
            scheme = hints.colorScheme()
            if scheme == Qt.ColorScheme.Dark:
                return UIThemeMode.DARK
            if scheme == Qt.ColorScheme.Light:
                return UIThemeMode.LIGHT

        # Some remote-desktop and older platform plugins report Unknown.
        app = self._application or QApplication.instance()
        if app is not None:
            window = app.palette().color(QPalette.ColorRole.Window)
            return (
                UIThemeMode.DARK
                if window.lightness() < 128
                else UIThemeMode.LIGHT
            )
        return UIThemeMode.LIGHT

    def _connect_system_theme(self):
        if self._system_signal_connected:
            return
        hints = QGuiApplication.styleHints()
        signal = getattr(hints, "colorSchemeChanged", None) if hints else None
        if signal is not None:
            signal.connect(self._on_system_theme_changed)
            self._system_signal_connected = True

    def _on_system_theme_changed(self, _scheme):
        if self._mode is UIThemeMode.SYSTEM:
            self.apply()

    @staticmethod
    def build_palette(t: UIThemeTokens) -> QPalette:
        palette = QPalette()
        normal = QPalette.ColorGroup.Normal
        inactive = QPalette.ColorGroup.Inactive

        roles = {
            QPalette.ColorRole.Window: t.window,
            QPalette.ColorRole.WindowText: t.text,
            QPalette.ColorRole.Base: t.input_background,
            QPalette.ColorRole.AlternateBase: t.surface_subtle,
            QPalette.ColorRole.ToolTipBase: t.popup_background,
            QPalette.ColorRole.ToolTipText: t.text,
            QPalette.ColorRole.Text: t.text,
            QPalette.ColorRole.Button: t.surface_strong,
            QPalette.ColorRole.ButtonText: t.text,
            QPalette.ColorRole.BrightText: "#FFFFFF",
            QPalette.ColorRole.Link: t.accent,
            QPalette.ColorRole.Highlight: t.accent,
            QPalette.ColorRole.HighlightedText: t.selected_text,
            QPalette.ColorRole.PlaceholderText: t.text_muted,
            QPalette.ColorRole.Mid: t.border_hover,
            QPalette.ColorRole.Dark: t.window_border,
        }
        for group in (normal, inactive):
            for role, value in roles.items():
                palette.setColor(group, role, QColor(value))

        disabled = QPalette.ColorGroup.Disabled
        for role, value in roles.items():
            palette.setColor(disabled, role, QColor(value))
        for role in (
            QPalette.ColorRole.WindowText,
            QPalette.ColorRole.Text,
            QPalette.ColorRole.ButtonText,
            QPalette.ColorRole.PlaceholderText,
        ):
            palette.setColor(disabled, role, QColor(t.text_disabled))
        return palette

    @staticmethod
    def _build_global_stylesheet(t: UIThemeTokens) -> str:
        # Keep this intentionally small.  Feature windows with their own theme
        # (for example Clipboard) remain free to override it locally.
        return f"""
            QToolTip {{
                color: {t.text};
                background-color: {t.popup_background};
                border: 1px solid {t.border_hover};
                padding: 4px 7px;
            }}
            QMenu {{
                color: {t.text};
                background-color: {t.popup_background};
                border: 1px solid {t.border};
                border-radius: 6px;
                padding: 4px;
            }}
            QMenu::item {{
                color: {t.text};
                background-color: transparent;
                padding: 6px 28px 6px 26px;
                margin: 1px 0;
            }}
            QMenu::item:selected {{
                color: {t.text};
                background-color: {t.popup_hover};
            }}
            QMenu::item:disabled {{
                color: {t.text_disabled};
                background-color: transparent;
            }}
            QMenu::separator {{
                height: 1px;
                background: {t.separator};
                margin: 4px 7px;
            }}
        """


_manager: Optional[UIThemeManager] = None


def get_ui_theme() -> UIThemeManager:
    global _manager
    if _manager is None:
        _manager = UIThemeManager()
    return _manager
