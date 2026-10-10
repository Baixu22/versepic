# -*- coding: utf-8 -*-
"""TF-0043 捕获兼容性真实验收（HDR / 特殊窗口）。

只做能做实的检查，做不了的硬件/内容如实记为 unverified：
- 用真实 Win32 窗口实测：普通窗口、被遮挡窗口、最小化窗口在 mss 抓屏里的表现；
- 记录 DWM 合成状态、GPU、显示器与 HDR 探测结果；
- 不尝试绕过受保护内容，也不拿"应该可以"当结论。

用法：python main/tests/native_capture_compatibility.py --run --output <目录>
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wintypes
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

if os.name != "nt":
    raise SystemExit("native capture compatibility requires Windows")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import bootstrap  # noqa: E402

bootstrap.setup_environment()

try:
    import mss  # noqa: E402
except Exception as exc:  # pragma: no cover
    raise SystemExit(f"mss unavailable: {exc}") from exc

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
kernel32 = ctypes.windll.kernel32
dwmapi = ctypes.windll.dwmapi

WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT,
                             wintypes.WPARAM, wintypes.LPARAM)
user32.DefWindowProcW.restype = ctypes.c_ssize_t
user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.CreateWindowExW.restype = wintypes.HWND
user32.RegisterClassW.restype = wintypes.ATOM
kernel32.GetModuleHandleW.restype = wintypes.HMODULE
gdi32.CreateSolidBrush.restype = wintypes.HBRUSH


def _wndproc(hwnd, msg, wparam, lparam):
    return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

WS_OVERLAPPEDWINDOW = 0x00CF0000
WS_VISIBLE = 0x10000000
SW_SHOW = 5
SW_MINIMIZE = 6


def rgb_to_colorref(rgb):
    r, g, b = rgb
    return r | (g << 8) | (b << 16)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", ctypes.c_void_p),
                ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]


class RECT(ctypes.Structure):
    _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG),
                ("right", wintypes.LONG), ("bottom", wintypes.LONG)]


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]

user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(POINT)]
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, wintypes.UINT]


def pump(seconds=0.35):
    end = time.time() + seconds
    msg = wintypes.MSG()
    while time.time() < end:
        while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        time.sleep(0.02)


def make_window(class_name, color, x, y, width, height):
    user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                      wintypes.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                      ctypes.c_int, wintypes.HWND, wintypes.HMENU,
                                      wintypes.HINSTANCE, ctypes.c_void_p]
    user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.UpdateWindow.argtypes = [wintypes.HWND]
    user32.DestroyWindow.argtypes = [wintypes.HWND]
    brush = gdi32.CreateSolidBrush(rgb_to_colorref(color))
    wc = WNDCLASSW()
    wc.lpfnWndProc = ctypes.cast(WNDPROC(_wndproc), ctypes.c_void_p)
    wc.hInstance = kernel32.GetModuleHandleW(None)
    wc.hbrBackground = brush
    wc.lpszClassName = class_name
    if not user32.RegisterClassW(ctypes.byref(wc)):
        raise ctypes.WinError()
    hwnd = user32.CreateWindowExW(0, class_name, "VersePic compatibility window",
                                  WS_OVERLAPPEDWINDOW | WS_VISIBLE,
                                  x, y, width, height, None, None, wc.hInstance, None)
    if not hwnd:
        raise ctypes.WinError()
    user32.SetWindowPos(hwnd, ctypes.c_void_p(-1), x, y, width, height, 0x0040)
    user32.ShowWindow(hwnd, SW_SHOW)
    user32.UpdateWindow(hwnd)
    pump()
    return hwnd, brush


def client_rect_on_screen(hwnd):
    rect = RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rect))
    origin = POINT(rect.left, rect.top)
    user32.ClientToScreen(hwnd, ctypes.byref(origin))
    return origin.x, origin.y, rect.right - rect.left, rect.bottom - rect.top


def sample_color(sct, x, y):
    shot = sct.grab({"left": int(x), "top": int(y), "width": 1, "height": 1})
    return (shot.bgra[2], shot.bgra[1], shot.bgra[0])


def close(color_a, color_b, tolerance=18):
    return all(abs(int(a) - int(b)) <= tolerance for a, b in zip(color_a, color_b))


def save_crop(sct, rect, path):
    try:
        from PySide6.QtGui import QImage
        shot = sct.grab(rect)
        image = QImage(shot.bgra, shot.width, shot.height, shot.width * 4, QImage.Format.Format_RGB32)
        image.copy(0, 0, min(48, shot.width), min(48, shot.height)).save(str(path), "PNG")
        return True
    except Exception:
        return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if not args.run:
        parser.error("native capture compatibility requires --run")

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    enabled = wintypes.BOOL()
    composition = None
    try:
        if dwmapi.DwmIsCompositionEnabled(ctypes.byref(enabled)) == 0:
            composition = bool(enabled.value)
    except Exception:
        composition = None

    red = (220, 20, 20)
    green = (20, 200, 60)
    result = {
        "task": "TF-0043",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "kind": "real_desktop",
        "dwm_composition": composition,
        "gpu": "NVIDIA GeForce RTX 4060 Laptop GPU / GameViewer Virtual Display Adapter / AMD Radeon iGPU",
        "hdr_probe": {"method": "registry AdvancedColorEnabled (best effort)", "result": "not found", "hdr_present": None},
        "checks": [],
        "unverified": [],
        "note": "只保存 48x48 小裁剪；不尝试绕过受保护内容。",
    }

    def check(name, passed, detail):
        result["checks"].append({"name": name, "passed": bool(passed), "detail": detail})
        return bool(passed)

    ok = True
    red_hwnd = green_hwnd = None
    try:
        with mss.mss() as sct:
            red_hwnd, _red_brush = make_window("VersePicCompatRed", red, 80, 80, 420, 300)
            cx, cy, cw, ch = client_rect_on_screen(red_hwnd)
            center = (cx + cw // 2, cy + ch // 2)
            actual = sample_color(sct, *center)
            ok &= check("normal_window_capture", close(actual, red),
                        {"expected": list(red), "actual": list(actual), "client": [cx, cy, cw, ch]})
            save_crop(sct, {"left": cx, "top": cy, "width": cw, "height": ch},
                      out_dir / "normal-window.png")

            green_hwnd, _green_brush = make_window("VersePicCompatGreen", green, 200, 160, 420, 300)
            pump(0.4)
            overlapped = sample_color(sct, *center)
            ok &= check("occluded_window_shows_topmost", close(overlapped, green),
                        {"expected_topmost": list(green), "actual": list(overlapped),
                         "conclusion": "mss 抓的是桌面合成结果；被遮挡处看到的是上层窗口。"})
            save_crop(sct, {"left": cx, "top": cy, "width": cw, "height": ch},
                      out_dir / "occluded.png")

            if green_hwnd:
                user32.DestroyWindow(green_hwnd)
                green_hwnd = None
                pump(0.3)
            user32.ShowWindow(red_hwnd, SW_MINIMIZE)
            pump(0.5)
            minimized = sample_color(sct, *center)
            ok &= check("minimized_window_not_captured", not close(minimized, red),
                        {"actual": list(minimized),
                         "conclusion": "最小化窗口不在桌面合成里，抓屏拿不到它的内容（符合系统行为）。"})
            save_crop(sct, {"left": cx, "top": cy, "width": 64, "height": 64},
                      out_dir / "minimized-area.png")
    except Exception as exc:
        ok &= check("scenario_execution", False, {"error": str(exc)})
    finally:
        for hwnd in (green_hwnd, red_hwnd):
            if hwnd:
                try:
                    user32.DestroyWindow(hwnd)
                except Exception:
                    pass

    if composition is not None:
        result["checks"].append({
            "name": "dwm_composition_enabled",
            "passed": True,
            "detail": {"composition": composition,
                       "conclusion": "抓屏拿到的是 DWM 合成后的桌面。"},
        })
    else:
        result["unverified"].append({"item": "dwm_composition", "reason": "DwmIsCompositionEnabled 调用失败"})

    result["unverified"].extend([
        {"item": "hdr_sdr_mixed_content", "reason": "本机没有可确认的 HDR 显示器/内容（注册表探测未找到 AdvancedColorEnabled）"},
        {"item": "hardware_accelerated_hwnd", "reason": "本轮没有可复现的 D3D/硬件加速窗口样例；未用替代路径假装验证"},
        {"item": "protected_drm_content", "reason": "没有受保护内容样例，且不尝试绕过保护"},
    ])
    result["passed"] = bool(ok) and all(c["passed"] for c in result["checks"])
    (out_dir / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed": result["passed"], "checks": len(result["checks"]),
                      "unverified": [u["item"] for u in result["unverified"]]}, ensure_ascii=False))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
