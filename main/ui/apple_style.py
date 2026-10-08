# -*- coding: utf-8 -*-
"""Apple (macOS-inspired) design tokens and QSS helpers shared by UI pages."""

from __future__ import annotations

from dataclasses import dataclass

from core.ui_theme import RADIUS_LG, RADIUS_MD, RADIUS_SM, RADIUS_XL

APPLE_FONT_FAMILY = '"SF Pro Text", "PingFang SC", "Microsoft YaHei UI", "Segoe UI Variable", sans-serif'


@dataclass(frozen=True)
class AppleTokens:
    accent: str
    accent_hover: str
    accent_pressed: str
    accent_soft: str
    window_bg: str
    surface_bg: str
    sidebar_bg: str
    card_bg: str
    hover_bg: str
    text: str
    text_secondary: str
    text_tertiary: str
    border: str
    danger: str
    danger_soft: str
    success: str
    # 圆角统一读 core.ui_theme 的 shadcn 刻度，不再自带一套 6/10/12，
    # 否则内容管理窗的按钮、卡片会比设置页同位置控件更方正。
    window_radius: int = RADIUS_XL
    card_radius: int = RADIUS_LG
    chip_radius: int = RADIUS_SM
    control_radius: int = RADIUS_MD
    input_radius: int = RADIUS_MD
    font_family: str = APPLE_FONT_FAMILY


LIGHT_APPLE = AppleTokens(
    accent="#007AFF",
    accent_hover="#1A84FF",
    accent_pressed="#0063D1",
    accent_soft="rgba(0, 122, 255, 0.14)",
    window_bg="#F5F5F7",
    surface_bg="rgba(255, 255, 255, 0.85)",
    sidebar_bg="rgba(246, 246, 248, 0.84)",
    card_bg="#FFFFFF",
    hover_bg="rgba(0, 0, 0, 0.05)",
    text="#1D1D1F",
    text_secondary="#6E6E73",
    text_tertiary="#86868B",
    border="rgba(0, 0, 0, 0.10)",
    danger="#FF3B30",
    danger_soft="rgba(255, 59, 48, 0.12)",
    success="#34C759",
)

DARK_APPLE = AppleTokens(
    accent="#0A84FF",
    accent_hover="#2E96FF",
    accent_pressed="#0A79E8",
    accent_soft="rgba(10, 132, 255, 0.18)",
    window_bg="#1E1E1E",
    surface_bg="rgba(44, 44, 46, 0.85)",
    sidebar_bg="rgba(36, 36, 38, 0.84)",
    card_bg="#2C2C2E",
    hover_bg="rgba(255, 255, 255, 0.08)",
    text="#F5F5F7",
    text_secondary="#98989D",
    text_tertiary="#636366",
    border="rgba(255, 255, 255, 0.12)",
    danger="#FF453A",
    danger_soft="rgba(255, 69, 58, 0.16)",
    success="#30D158",
)


def apple_tokens(dark: bool) -> AppleTokens:
    return DARK_APPLE if dark else LIGHT_APPLE


def current_apple_tokens() -> AppleTokens:
    """Resolve Apple tokens from the app-wide theme, falling back to palette lightness."""
    try:
        from core.ui_theme import get_ui_theme

        return apple_tokens(get_ui_theme().is_dark)
    except Exception:
        pass
    try:
        from PySide6.QtGui import QPalette
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is not None:
            window = app.palette().color(QPalette.ColorRole.Window)
            return apple_tokens(window.lightness() < 128)
    except Exception:
        pass
    return LIGHT_APPLE


def apple_scrollbar_qss(tokens: AppleTokens) -> str:
    return f"""
    QScrollBar:vertical {{ width: 8px; margin: 4px 0; background: transparent; }}
    QScrollBar:horizontal {{ height: 8px; margin: 0 4px; background: transparent; }}
    QScrollBar::handle:vertical {{ min-height: 32px; background: {tokens.border}; border-radius: 4px; }}
    QScrollBar::handle:horizontal {{ min-width: 32px; background: {tokens.border}; border-radius: 4px; }}
    QScrollBar::handle:hover {{ background: {tokens.text_tertiary}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
    """


def apple_button_qss(tokens: AppleTokens, primary: bool = False) -> str:
    if primary:
        return f"""
        QPushButton {{
            color: #FFFFFF;
            background-color: {tokens.accent};
            border: none;
            border-radius: {tokens.control_radius}px;
            padding: 5px 14px;
            font-family: {tokens.font_family};
        }}
        QPushButton:hover {{ background-color: {tokens.accent_hover}; }}
        QPushButton:pressed {{ background-color: {tokens.accent_pressed}; }}
        QPushButton:disabled {{ background-color: {tokens.accent_soft}; color: {tokens.text_tertiary}; }}
        """
    return f"""
    QPushButton {{
        color: {tokens.text};
        background-color: {tokens.card_bg};
        border: 1px solid {tokens.border};
        border-radius: {tokens.control_radius}px;
        padding: 5px 14px;
        font-family: {tokens.font_family};
    }}
    QPushButton:hover {{ background-color: {tokens.hover_bg}; }}
    QPushButton:pressed {{ background-color: {tokens.accent_soft}; }}
    QPushButton:disabled {{ color: {tokens.text_tertiary}; background-color: {tokens.hover_bg}; }}
    """


def apple_input_qss(tokens: AppleTokens) -> str:
    return f"""
    QLineEdit {{
        color: {tokens.text};
        background-color: {tokens.hover_bg};
        border: 1px solid {tokens.border};
        border-radius: {tokens.input_radius}px;
        padding: 4px 10px;
        selection-background-color: {tokens.accent};
        selection-color: #FFFFFF;
        font-family: {tokens.font_family};
    }}
    QLineEdit:focus {{ border: 1px solid {tokens.accent}; background-color: {tokens.card_bg}; }}
    QLineEdit:disabled {{ color: {tokens.text_tertiary}; }}
    """


def apple_pill_qss(tokens: AppleTokens) -> str:
    return f"""
    QPushButton {{
        color: {tokens.text_secondary};
        background-color: transparent;
        border: none;
        border-radius: {tokens.chip_radius}px;
        padding: 4px 12px;
        font-family: {tokens.font_family};
    }}
    QPushButton:hover {{ background-color: {tokens.hover_bg}; color: {tokens.text}; }}
    QPushButton:checked {{
        color: {tokens.accent};
        background-color: {tokens.accent_soft};
    }}
    QPushButton:disabled {{ color: {tokens.text_tertiary}; }}
    """
