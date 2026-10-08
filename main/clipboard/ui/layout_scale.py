# -*- coding: utf-8 -*-

"""Shared size metrics for the clipboard management dialog."""

from core.ui_scale import get_dialog_scale

MANAGE_DIALOG_BASE_WIDTH = 1020
MANAGE_DIALOG_BASE_HEIGHT = 600

MANAGE_DIALOG_MIN_WIDTH_BASE = 820
MANAGE_DIALOG_MIN_HEIGHT_BASE = 580

# 900x600 是设计稿基准，+20/+120 是实际窗口比设计稿多出的外框留白；
# 二者的比值是固定的"设计稿 -> 实际窗口"换算比例，和用户的窗口缩放设置无关。
_CHROME_SCALE_X = (MANAGE_DIALOG_BASE_WIDTH + 20) / MANAGE_DIALOG_BASE_WIDTH
_CHROME_SCALE_Y = (MANAGE_DIALOG_BASE_HEIGHT + 120) / MANAGE_DIALOG_BASE_HEIGHT


def _dialog_factor() -> float:
    """实时读取设置里的窗口缩放比例。取成函数而不是模块级常量，
    是因为常量只在模块第一次被 import 时算一次，之后用户改设置也不会再变。"""
    return get_dialog_scale().factor


def _scale(value: int, factor: float) -> int:
    if value == 0:
        return 0
    return max(1, round(value * factor))


def manage_dialog_width() -> int:
    return round(MANAGE_DIALOG_BASE_WIDTH * _CHROME_SCALE_X * _dialog_factor())


def manage_dialog_height() -> int:
    return round(MANAGE_DIALOG_BASE_HEIGHT * _CHROME_SCALE_Y * _dialog_factor())


def manage_dialog_min_width() -> int:
    return round(MANAGE_DIALOG_MIN_WIDTH_BASE * _dialog_factor())


def manage_dialog_min_height() -> int:
    return round(MANAGE_DIALOG_MIN_HEIGHT_BASE * _dialog_factor())


def scale_x(value: int) -> int:
    return _scale(value, _CHROME_SCALE_X * _dialog_factor())


def scale_y(value: int) -> int:
    return _scale(value, _CHROME_SCALE_Y * _dialog_factor())


def scale_ui(value: int) -> int:
    """字号、圆角、内边距。不乘设计稿换算比例：那是窗口外框的留白，
    乘上去字会比其他窗口大一圈。"""
    return _scale(value, _dialog_factor())


def field_gap() -> int:
    """字段内间距：label 和它自己的控件之间。详情区布局的统一 spacing。"""
    return scale_ui(6)


def field_group_gap() -> int:
    """字段组之间额外插入的间距。

    叠加上下两道 spacing 后，组间约为组内的三倍，label 才会明显贴住自己的
    控件、而不是悬在两组中间。用布局 spacer 而不是 label 的 margin-top：
    详情区换肤时会整句重写 label 的样式表，margin 会被一起抹掉。
    """
    return scale_ui(10)
