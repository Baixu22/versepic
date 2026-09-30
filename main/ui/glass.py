# -*- coding: utf-8 -*-
"""Windows 原生毛玻璃：DWM 圆角 + 系统阴影 + Acrylic 背景模糊。

Qt 自己画不出"模糊窗口背后的桌面"，只能让 DWM 合成。做法：
- SetWindowCompositionAttribute(ACCENT_ENABLE_ACRYLICBLURBEHIND) 打开背景模糊，
  tint 色由调用方给（浅/深主题各一档），Qt 侧只再叠一层很淡的底色；
- Win11 上用 DWMWA_WINDOW_CORNER_PREFERENCE 让系统裁圆角并给出原生阴影，
  不再在 Qt 里留透明边距画假阴影（那圈半透明边就是"颗粒感"的来源之一）。
非 Windows / 调用失败时返回 False，调用方退回普通半透明底。
"""
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

_DWMWA_WINDOW_CORNER_PREFERENCE = 33
_DWMWCP_ROUND = 2
_DWMWA_BORDER_COLOR = 34
_DWMWA_COLOR_NONE = 0xFFFFFFFE
_WCA_ACCENT_POLICY = 19
_ACCENT_ENABLE_BLURBEHIND = 3
_ACCENT_ENABLE_ACRYLICBLURBEHIND = 4
_ACCENT_DISABLED = 0

# 材质模式：
# - "blur"：纯高斯模糊（ACCENT_ENABLE_BLURBEHIND），不带 Acrylic 的噪点纹理。
#   底色由 Qt 在容器上画半透明色层，DWM 按逐像素 alpha 与模糊背景合成。
#   实测 Acrylic 在平坦区相邻像素亮度差约 1.15、最大 5 级，大块浅色面上
#   就是肉眼可见的"颗粒感"；纯模糊没有这层纹理。
# - "acrylic"：旧方案，tint 交给 DWM，带噪点。保留作兼容/对比。
MODE_BLUR = "blur"
MODE_ACRYLIC = "acrylic"


class _AccentPolicy(ctypes.Structure):
    _fields_ = [
        ("AccentState", ctypes.c_uint),
        ("AccentFlags", ctypes.c_uint),
        ("GradientColor", ctypes.c_uint),
        ("AnimationId", ctypes.c_uint),
    ]


class _WinCompAttrData(ctypes.Structure):
    _fields_ = [
        ("Attribute", ctypes.c_int),
        ("Data", ctypes.c_void_p),
        ("SizeOfData", ctypes.c_size_t),
    ]


def is_supported() -> bool:
    if sys.platform != "win32":
        return False
    try:
        return sys.getwindowsversion().build >= 17763
    except Exception:
        return False


def is_win11() -> bool:
    try:
        return sys.platform == "win32" and sys.getwindowsversion().build >= 22000
    except Exception:
        return False


def enable_glass(widget, dark: bool, tint_alpha: int = 0x99, tint_rgb=None, mode: str = MODE_BLUR) -> bool:
    """给顶层窗口打开背景模糊 + 系统圆角。须在窗口 show（有 HWND）之后调用。

    mode=MODE_BLUR（默认）时 tint 参数不生效，调用方须自己在窗口里画半透明底色；
    mode=MODE_ACRYLIC 时 tint_rgb/tint_alpha 交给 DWM 着色。
    tint_rgb 为 (r, g, b)，缺省按明暗取中性灰；主题换底色时传主题的背景色。
    """
    if not is_supported():
        return False
    try:
        hwnd = int(widget.winId())
        user32 = ctypes.windll.user32
        dwm = ctypes.windll.dwmapi

        if is_win11():
            pref = ctypes.c_int(_DWMWCP_ROUND)
            dwm.DwmSetWindowAttribute(
                wintypes.HWND(hwnd), _DWMWA_WINDOW_CORNER_PREFERENCE, ctypes.byref(pref), ctypes.sizeof(pref)
            )
            # 系统默认会给 Win11 窗口描一圈强调色细边，关掉，由 Qt 画更淡的 hairline
            border = ctypes.c_uint(_DWMWA_COLOR_NONE)
            dwm.DwmSetWindowAttribute(
                wintypes.HWND(hwnd), _DWMWA_BORDER_COLOR, ctypes.byref(border), ctypes.sizeof(border)
            )

        # GradientColor 为 AABBGGRR
        r, g, b = tint_rgb if tint_rgb is not None else ((0x20, 0x20, 0x22) if dark else (0xF4, 0xF4, 0xF6))
        tint = ((tint_alpha & 0xFF) << 24) | (b << 16) | (g << 8) | r
        state = _ACCENT_ENABLE_ACRYLICBLURBEHIND if mode == MODE_ACRYLIC else _ACCENT_ENABLE_BLURBEHIND
        accent = _AccentPolicy(state, 2, tint, 0)
        data = _WinCompAttrData(_WCA_ACCENT_POLICY, ctypes.cast(ctypes.pointer(accent), ctypes.c_void_p),
                                ctypes.sizeof(accent))
        set_attr = user32.SetWindowCompositionAttribute
        set_attr.argtypes = [wintypes.HWND, ctypes.POINTER(_WinCompAttrData)]
        set_attr.restype = wintypes.BOOL
        return bool(set_attr(wintypes.HWND(hwnd), ctypes.byref(data)))
    except Exception:
        return False


def disable_glass(widget) -> None:
    if not is_supported():
        return
    try:
        accent = _AccentPolicy(_ACCENT_DISABLED, 0, 0, 0)
        data = _WinCompAttrData(_WCA_ACCENT_POLICY, ctypes.cast(ctypes.pointer(accent), ctypes.c_void_p),
                                ctypes.sizeof(accent))
        ctypes.windll.user32.SetWindowCompositionAttribute(wintypes.HWND(int(widget.winId())), ctypes.byref(data))
    except Exception:
        pass
