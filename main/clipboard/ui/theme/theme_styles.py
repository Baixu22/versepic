# -*- coding: utf-8 -*-
"""
主题样式生成器

将主题颜色转换为 Qt StyleSheet，并为玻璃材质界面派生一套统一的表面配色
（SurfacePalette）：列表行、工具栏、分组标签页都从这里取色，不再各算各的。
"""

from dataclasses import dataclass

from PySide6.QtGui import QColor

from core.ui_theme import RADIUS_LG, RADIUS_MD, RADIUS_XL

from .themes import Theme


def rgba(color: QColor) -> str:
    """QColor → QSS 的 rgba() 写法。"""
    return f"rgba({color.red()}, {color.green()}, {color.blue()}, {color.alphaF():.3f})"


def _with_alpha(color: QColor, alpha: float) -> QColor:
    c = QColor(color)
    c.setAlphaF(max(0.0, min(1.0, alpha)))
    return c


@dataclass(frozen=True)
class SurfacePalette:
    """玻璃面板上的语义色。叠加色一律是半透明黑/白，不用不透明灰块。"""

    dark: bool
    tint: QColor            # 毛玻璃底色（主题 bg_primary）
    text: QColor
    text_secondary: QColor
    text_tertiary: QColor
    accent: QColor
    accent_text: QColor     # 压在 accent 软底上的文字/图标
    accent_soft: QColor     # 选中标签、激活筛选的软底
    hover: QColor           # 行悬停
    selected: QColor        # 行选中
    control: QColor         # 搜索框、按钮的静止底
    control_hover: QColor
    control_pressed: QColor
    hairline: QColor
    danger: QColor
    popup: QColor           # 菜单、预览等不透明浮层


def readable_accent(color: QColor, background: QColor, minimum: float = 4.5) -> QColor:
    """保留主题色相，同时保证文字或白字按钮的 WCAG 对比度。"""
    def luminance(value):
        channels = [value.redF(), value.greenF(), value.blueF()]
        linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
        return sum(c * w for c, w in zip(linear, (0.2126, 0.7152, 0.0722)))

    result = QColor(color)
    bg = luminance(background)
    for _ in range(40):
        fg = luminance(result)
        if (max(fg, bg) + 0.05) / (min(fg, bg) + 0.05) >= minimum:
            break
        # 0.179 is where black and white have equal contrast, in linear luminance.
        result = result.darker(108) if bg > 0.179 else result.lighter(108)
    return result


def surface_palette(theme: Theme) -> SurfacePalette:
    c = theme.colors
    text = QColor(c.text_primary)
    dark = text.lightness() > 128
    accent = QColor(c.accent_primary)
    ink = QColor(255, 255, 255) if dark else QColor(0, 0, 0)
    return SurfacePalette(
        dark=dark,
        tint=QColor(c.bg_primary),
        text=text,
        text_secondary=QColor(c.text_secondary),
        text_tertiary=QColor(c.text_tertiary),
        accent=accent,
        accent_text=readable_accent(accent, QColor(c.bg_primary)),
        accent_soft=QColor(c.bg_selected),
        hover=_with_alpha(ink, 0.055 if dark else 0.03),
        selected=_with_alpha(ink, 0.10 if dark else 0.065),
        control=QColor(c.bg_tertiary),
        control_hover=_with_alpha(ink, 0.12 if dark else 0.08),
        control_pressed=_with_alpha(ink, 0.16 if dark else 0.11),
        hairline=_with_alpha(ink, 0.12 if dark else 0.09),
        danger=QColor(c.error),
        popup=QColor(c.bg_secondary) if not dark else QColor(c.bg_secondary).lighter(108),
    )


def tag_chip_palette(color: str, background: QColor):
    """Opaque chip fill and readable ink, including pale user-selected tag colours."""
    tint = QColor(color)
    fill = QColor(*[round(a * .16 + b * .84) for a, b in zip(
        tint.getRgb()[:3], background.getRgb()[:3])])
    return fill, readable_accent(tint, fill)


def management_palette(theme: Theme):
    """管理页保留三列布局，颜色与剪贴板共用同一主题和表面语义。"""
    from dataclasses import replace
    from ui.apple_style import apple_tokens

    p = surface_palette(theme)
    c = theme.colors
    return replace(
        apple_tokens(p.dark),
        accent=p.accent_text.name(),
        accent_hover=c.accent_hover,
        accent_pressed=QColor(c.accent_hover).darker(110).name(),
        accent_soft=c.bg_selected,
        window_bg=c.bg_primary,
        surface_bg=c.bg_secondary,
        sidebar_bg=c.bg_tertiary,
        card_bg=c.bg_secondary,
        hover_bg=c.bg_hover,
        text=c.text_primary,
        text_secondary=c.text_secondary,
        text_tertiary=c.text_tertiary,
        border=c.border_primary,
        danger=c.error,
        danger_soft=c.error_bg,
        success=c.success,
    )


def glass_tint_alpha(dark: bool, opacity: int = 0, *, native_glass: bool = False) -> float:
    """返回玻璃前景 tint 的 alpha。

    ``native_glass`` 使用 Windows 任务栏式的更透底色，让 DWM 的模糊结果和
    窗口后的桌面颜色能够透进来；非原生/测试路径继续保留原来的高对比度底色。
    opacity 仍沿用设置语义：0=默认，100=最透明。
    """
    opacity = max(0, min(100, int(opacity or 0)))
    if native_glass:
        # 约 20%~34% 的背景色可见；足够吸收桌面色，又不会让文字漂浮。
        base, floor = (0.70, 0.54) if dark else (0.80, 0.68)
    else:
        base, floor = (0.66, 0.42) if dark else (1.0, 0.82)
    return max(floor, base - opacity * ((base - floor) / 100))


class ThemeStyleGenerator:
    """主题样式生成器"""

    def __init__(self, theme: Theme, glass: bool = False):
        self.theme = theme
        self.colors = theme.colors
        # glass=True：窗口背后由 DWM 原生模糊，Qt 侧面板一律透明
        self.glass = glass
        self.palette = surface_palette(theme)

    def generate_window_style(self, opacity: int = 0) -> str:
        """
        生成主窗口样式

        Args:
            opacity: 透明度 (0-100, 0=不透明)
        """
        p = self.palette
        opacity_alpha = (255 - int(opacity * 2.55)) / 255
        radius = RADIUS_XL
        if self.glass:
            import sys
            # DWM 只做纯高斯模糊（无噪点），底色层由这里画：主题底色 + 按「透明度」调的 alpha
            tint = _with_alpha(p.tint, glass_tint_alpha(p.dark, opacity, native_glass=True))
            background = rgba(tint)
            # Windows 11 让 DWM 自己画窗口圆角，Qt 侧只描边，半径跟着系统走，
            # 否则自绘的圆角会和系统裁切错开、四角露出底下的桌面。
            radius = RADIUS_MD if sys.getwindowsversion().build >= 22000 else RADIUS_XL
        else:
            alpha = max(0.0, min(1.0, opacity_alpha))
            background = f"rgba({self._hex_to_rgb(self.colors.bg_primary)}, {alpha:.3f})"

        return f"""
            QFrame#mainContainer {{
                background: {background};
                border: 1px solid {rgba(p.hairline)};
                border-radius: {radius}px;
            }}
            QToolTip {{
                background: {rgba(p.popup)};
                color: {self.colors.text_primary};
                border: 1px solid {rgba(p.hairline)};
                border-radius: {RADIUS_MD}px;
                padding: 4px 8px;
                font-size: 12px;
            }}
        """

    def generate_list_widget_style(self, opacity: int = 0) -> str:
        """生成列表控件样式：行由 delegate 自绘，控件本身透明，滚动条细而淡。"""
        p = self.palette
        bg = "transparent"  # The parent paints alpha once; stacking fills cancels transparency.
        handle = _with_alpha(p.text, 0.22 if p.dark else 0.18)
        handle_hover = _with_alpha(p.text, 0.36 if p.dark else 0.32)
        return f"""
            QListWidget {{
                background: {bg};
                border: none;
                outline: none;
                color: {self.colors.text_primary};
            }}
            QListWidget::item {{
                padding: 0px;
                border: none;
                background: transparent;
            }}
            QListWidget::item:selected {{
                background: transparent;
            }}
            QListWidget::item:hover {{
                background: transparent;
            }}
            QScrollBar:vertical {{ width: 10px; margin: 4px 2px 4px 0px; background: transparent; }}
            QScrollBar::handle:vertical {{ min-height: 36px; background: {rgba(handle)}; border-radius: 3px;
                margin: 0px 2px; }}
            QScrollBar::handle:vertical:hover {{ background: {rgba(handle_hover)}; }}
            QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
            QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
        """

    def generate_search_bar_style(self, opacity: int = 0, corner_radius: str = "") -> str:
        """生成顶部工具栏 / 侧栏容器样式；corner_radius 给出窗口圆角处的补充圆角 QSS。"""
        alpha = 255 - int(opacity * 2.55)
        if self.glass:
            return """
            QWidget {
                background: transparent;
                border-top: 1px solid transparent;
            }
        """

        return f"""
            QWidget {{
                background: rgba({self._hex_to_rgb(self.colors.bg_secondary)}, {alpha / 255});
                border-top: 1px solid {self._hex_to_rgba(self.colors.border_primary, 0.6)};
                {corner_radius}
            }}
        """

    def generate_time_filter_bar_style(self, opacity: int = 0) -> str:
        """筛选面板容器：玻璃上透明，只有底部一条细线。"""
        _ = opacity
        # 分隔线由外层工具栏统一画在底部，这里不再重复一条
        return """
            QWidget#filterPanel {
                background: transparent;
                border: none;
            }
        """

    def generate_button_style(self, button_type: str = "normal") -> str:
        """
        生成按钮样式

        Args:
            button_type: 按钮类型 (normal, primary, danger)
        """
        if button_type == "primary":
            return f"""
                QPushButton {{
                    background: {self.colors.accent_primary};
                    color: white;
                    border: none;
                    border-radius: {RADIUS_MD}px;
                    padding: 7px 18px;
                    font-size: 13px;
                    font-weight: 500;
                }}
                QPushButton:hover {{
                    background: {self.colors.accent_hover};
                }}
                QPushButton:pressed {{
                    background: {self.colors.accent_hover};
                }}
            """
        elif button_type == "danger":
            return f"""
                QPushButton {{
                    background: transparent;
                    color: {self.colors.error};
                    border: none;
                    border-radius: {RADIUS_MD}px;
                    padding: 7px 18px;
                    font-size: 13px;
                }}
                QPushButton:hover {{
                    background: {self._hex_to_rgba(self.colors.error, 0.10)};
                }}
            """
        else:  # normal
            return f"""
                QPushButton {{
                    background: {self.colors.bg_secondary};
                    color: {self.colors.text_primary};
                    border: 1px solid {self.colors.border_primary};
                    border-radius: {RADIUS_MD}px;
                    padding: 6px 16px;
                    font-size: 13px;
                }}
                QPushButton:hover {{
                    background: {self.colors.bg_hover};
                }}
            """

    def generate_input_style(self) -> str:
        """生成输入框样式"""
        return f"""
            QLineEdit {{
                border: 1px solid {self.colors.border_primary};
                border-radius: {RADIUS_MD}px;
                padding: 7px 11px;
                font-size: 13px;
                background: {self.colors.bg_secondary};
                color: {self.colors.text_primary};
            }}
            QLineEdit:focus {{
                border-color: {self.colors.border_accent};
            }}
            QTextEdit {{
                border: 1px solid {self.colors.border_primary};
                border-radius: {RADIUS_MD}px;
                padding: 8px;
                font-size: 13px;
                background: {self.colors.bg_secondary};
                color: {self.colors.text_primary};
            }}
            QTextEdit:focus {{
                border-color: {self.colors.border_accent};
            }}
        """

    def generate_combobox_style(self) -> str:
        """生成下拉框样式"""
        return f"""
            QComboBox {{
                border: 1px solid {self.colors.border_primary};
                border-radius: {RADIUS_MD}px;
                padding: 6px 10px;
                font-size: 12px;
                background: {self.colors.bg_secondary};
                color: {self.colors.text_primary};
            }}
            QComboBox QAbstractItemView {{
                background: {self.colors.bg_secondary};
                color: {self.colors.text_primary};
                selection-background-color: {self.colors.bg_selected};
                selection-color: {self.colors.text_accent};
            }}
        """

    def generate_dialog_style(self) -> str:
        """生成对话框样式"""
        return f"""
            QDialog {{
                background: {self.colors.bg_primary};
            }}
        """

    def generate_manage_dialog_style(self) -> str:
        """生成管理对话框完整样式"""
        return f"""
            QDialog {{ background: {self.colors.bg_primary}; }}

            /* 输入框样式 */
            {self.generate_input_style()}

            /* 导航列样式 */
            QWidget#navColumn {{
                background: {self.colors.bg_tertiary};
                border-right: 1px solid {self.colors.border_secondary};
            }}

            /* 列表列样式 */
            QWidget#listColumn {{
                background: {self.colors.bg_secondary};
                border-right: 1px solid {self.colors.border_secondary};
            }}

            QListWidget {{
                background: transparent;
                border: none;
                outline: none;
                color: {self.colors.text_primary};
            }}
            QListWidget::item {{
                padding: 0px 12px;
                border-bottom: 1px solid {self.colors.bg_hover};
                color: {self.colors.text_primary};
            }}
            QListWidget::item:selected {{
                background: {self.colors.bg_selected};
                color: {self.colors.text_accent};
            }}
            QListWidget::item:hover {{
                background: {self.colors.bg_hover};
            }}

            /* 详情列样式 */
            QWidget#detailColumn {{
                background: {self.colors.bg_primary};
            }}
        """

    def generate_preview_popup_style(self) -> str:
        """生成预览弹窗样式"""
        p = self.palette
        return f"""
            PreviewPopup {{
                background: {rgba(p.popup)};
                border: 1px solid {rgba(p.hairline)};
                border-radius: {RADIUS_LG}px;
            }}
            QTextEdit {{
                background: transparent;
                border: none;
                padding: 2px 4px;
                font-size: 15px;
                color: {self.colors.text_primary};
                selection-background-color: {rgba(p.selected)};
            }}
            QLabel#previewMeta {{
                background: transparent;
                color: {self.colors.text_tertiary};
                font-size: 12px;
                padding: 0px 6px;
            }}
            QLabel#previewImage {{
                background: transparent;
                border: none;
            }}
        """

    def generate_menu_style(self, font_size: int = 15) -> str:
        """Use the shared menu geometry with this clipboard window's palette."""
        from dataclasses import replace
        from core.ui_theme import DARK_TOKENS, LIGHT_TOKENS
        from ui.fluent_lite.theme import menu_qss
        p, c = self.palette, self.colors
        tokens = replace(
            DARK_TOKENS if p.dark else LIGHT_TOKENS,
            text=c.text_primary, text_disabled=c.text_disabled,
            popup_background=rgba(p.popup), popup_hover=c.bg_hover,
            border=rgba(p.hairline), separator=rgba(p.hairline),
        )
        return menu_qss(tokens=tokens, font_size=font_size)

    def generate_toolbar_button_style(self) -> str:
        """工具栏图标按钮：静止无底，悬停浅底，激活为强调色软底。"""
        p = self.palette
        return f"""
            QToolButton {{
                background: transparent;
                border: none;
                border-radius: {RADIUS_MD}px;
                padding: 0px;
            }}
            QToolButton:hover {{
                background: {rgba(p.control_hover)};
            }}
            QToolButton:pressed {{
                background: {rgba(p.control_pressed)};
            }}
            QToolButton:checked {{
                background: {rgba(p.accent_soft)};
            }}
        """

    def generate_search_input_style(self, has_text: bool = False) -> str:
        """搜索框：玻璃上的浅色胶囊，聚焦时描强调色细边。"""
        p = self.palette
        bg = p.control_hover if has_text else p.control
        return f"""
            QLineEdit {{
                background: {rgba(bg)};
                border: 1px solid transparent;
                border-radius: {RADIUS_MD}px;
                color: {self.colors.text_primary};
                font-size: 16px;
                padding: 0px 6px 0px 4px;
                selection-background-color: {self.colors.accent_primary};
                selection-color: white;
            }}
            QLineEdit:hover {{
                background: {rgba(p.control_hover)};
            }}
            QLineEdit:focus {{
                border: 1px solid {rgba(_with_alpha(p.accent, 0.75))};
                background: {rgba(p.control_hover)};
            }}
        """

    def generate_clear_search_btn_style(self) -> str:
        """生成清除搜索按钮样式"""
        return self.generate_toolbar_button_style()

    def generate_filter_toggle_btn_style(self) -> str:
        """筛选开关按钮：同工具栏按钮。"""
        return self.generate_toolbar_button_style()

    def generate_segment_style(self) -> str:
        """类型筛选的分段按钮（同一组内互斥）。"""
        p = self.palette
        return f"""
            QToolButton {{
                background: transparent;
                color: {self.colors.text_secondary};
                border: none;
                border-radius: {RADIUS_MD}px;
                padding: 0px 10px;
                font-size: 15px;
            }}
            QToolButton:hover {{
                background: {rgba(p.control_hover)};
                color: {self.colors.text_primary};
            }}
            QToolButton:checked {{
                background: {rgba(p.accent_soft)};
                color: {rgba(p.accent_text)};
                font-weight: 600;
            }}
        """

    def generate_time_filter_date_edit_style(self) -> str:
        """日期区间输入：与搜索框同一族的浅底胶囊。"""
        p = self.palette
        return f"""
            QDateEdit {{
                background: {rgba(p.control)};
                color: {self.colors.text_primary};
                border: 1px solid transparent;
                border-radius: {RADIUS_MD}px;
                padding: 2px 6px;
                font-size: 13px;
            }}
            QDateEdit:hover {{
                background: {rgba(p.control_hover)};
            }}
            QDateEdit:focus {{
                border: 1px solid {rgba(_with_alpha(p.accent, 0.75))};
            }}
            QDateEdit[hasError="true"] {{
                border: 1px solid {self.colors.error};
            }}
            QDateEdit::drop-down {{
                subcontrol-origin: padding;
                subcontrol-position: center right;
                width: 16px;
                border: none;
                background: transparent;
            }}
            QDateEdit::down-arrow {{
                image: none;
                width: 0px;
                height: 0px;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 5px solid {self.colors.text_tertiary};
            }}
        """

    def generate_time_filter_calendar_style(self) -> str:
        """日期弹出日历：不透明浮层卡片。"""
        p = self.palette
        return f"""
            QCalendarWidget {{
                background: {rgba(p.popup)};
                color: {self.colors.text_primary};
                border: 1px solid {rgba(p.hairline)};
            }}
            QCalendarWidget QWidget {{
                background: {rgba(p.popup)};
                color: {self.colors.text_primary};
                alternate-background-color: {rgba(p.popup)};
            }}
            QCalendarWidget QWidget#qt_calendar_navigationbar {{
                background: {rgba(p.popup)};
            }}
            QCalendarWidget QToolButton {{
                background: transparent;
                color: {self.colors.text_primary};
                border: none;
                border-radius: {RADIUS_MD}px;
                padding: 4px 6px;
                font-weight: 600;
            }}
            QCalendarWidget QToolButton:hover {{
                background: {rgba(p.control_hover)};
            }}
            QCalendarWidget QMenu {{
                background: {rgba(p.popup)};
                color: {self.colors.text_primary};
                border: 1px solid {rgba(p.hairline)};
            }}
            QCalendarWidget QMenu::item:selected {{
                background: {self.colors.accent_primary};
                color: #FFFFFF;
            }}
            QCalendarWidget QSpinBox {{
                background: {rgba(p.control)};
                color: {self.colors.text_primary};
                border: none;
                border-radius: {RADIUS_MD}px;
                padding: 2px 4px;
            }}
            QCalendarWidget QAbstractItemView {{
                background: {rgba(p.popup)};
                color: {self.colors.text_primary};
                selection-background-color: {self.colors.accent_primary};
                selection-color: white;
                outline: none;
            }}
            QCalendarWidget QAbstractItemView:disabled {{
                color: {self.colors.text_disabled};
            }}
        """

    def generate_time_filter_action_btn_style(self, primary: bool = False) -> str:
        """筛选面板里的文字按钮（重置）。"""
        p = self.palette
        fg = rgba(p.accent_text) if primary else self.colors.text_secondary
        return f"""
            QToolButton {{
                background: transparent;
                color: {fg};
                border: none;
                border-radius: {RADIUS_MD}px;
                padding: 0px 8px;
                font-size: 13px;
            }}
            QToolButton:hover {{
                background: {rgba(p.control_hover)};
                color: {self.colors.text_primary};
            }}
        """

    def generate_time_filter_combo_style(self) -> str:
        """Generate the compact content-type filter combo style."""
        return f"""
            QComboBox {{
                background: {self.colors.bg_primary};
                color: {self.colors.text_primary};
                border: 1px solid {self.colors.border_primary};
                border-radius: {RADIUS_MD}px;
                padding: 3px 12px 3px 8px;
                font-size: 12px;
            }}
            QComboBox QAbstractItemView {{
                background: {self.colors.bg_primary};
                color: {self.colors.text_primary};
                border: 1px solid {self.colors.border_primary};
                selection-background-color: {self.colors.accent_primary};
                selection-color: white;
                outline: none;
            }}
        """

    def generate_time_filter_type_btn_style(self) -> str:
        """兼容保留：类型筛选改成分段按钮后仍可能被外部调用。"""
        return self.generate_segment_style()

    def generate_menu_btn_style(self) -> str:
        """「更多」按钮：同工具栏按钮。"""
        return self.generate_toolbar_button_style()

    def is_dark(self) -> bool:
        return self.palette.dark

    def _hairline(self) -> str:
        """玻璃上的分隔线：按明暗取黑/白极低透明，不用灰色实线。"""
        return rgba(self.palette.hairline)

    def _fill(self, strength: float = 1.0) -> str:
        """玻璃上的控件底：半透明黑/白叠加，而不是不透明灰块。"""
        return rgba(_with_alpha(self.palette.control, self.palette.control.alphaF() * strength))

    def _accent_soft(self) -> str:
        """强调色软底（macOS 选中胶囊底）。"""
        return rgba(self.palette.accent_soft)

    def _hex_to_rgba(self, hex_color: str, alpha: float) -> str:
        """十六进制颜色转 rgba() 字符串。"""
        return f"rgba({self._hex_to_rgb(hex_color)}, {alpha})"

    @staticmethod
    def _hex_to_rgb(hex_color: str) -> str:
        """
        将十六进制颜色转换为 RGB 字符串

        Args:
            hex_color: 十六进制颜色，如 "#FFFFFF"

        Returns:
            RGB 字符串，如 "255, 255, 255"
        """
        hex_color = hex_color.lstrip('#')
        if len(hex_color) == 3:
            hex_color = ''.join([c*2 for c in hex_color])

        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)

        return f"{r}, {g}, {b}"


def generate_all_styles(theme: Theme, opacity: int = 0) -> dict:
    """
    生成所有样式

    Args:
        theme: 主题对象
        opacity: 透明度 (0-100)

    Returns:
        包含所有样式的字典
    """
    generator = ThemeStyleGenerator(theme)

    return {
        "window": generator.generate_window_style(opacity),
        "list_widget": generator.generate_list_widget_style(opacity),
        "search_bar": generator.generate_search_bar_style(opacity),
        "button_normal": generator.generate_button_style("normal"),
        "button_primary": generator.generate_button_style("primary"),
        "button_danger": generator.generate_button_style("danger"),
        "input": generator.generate_input_style(),
        "combobox": generator.generate_combobox_style(),
        "dialog": generator.generate_dialog_style(),
        "manage_dialog": generator.generate_manage_dialog_style(),
        "preview_popup": generator.generate_preview_popup_style(),
    }
