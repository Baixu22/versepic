# -*- coding: utf-8 -*-
"""TF-0042 真实 Windows 混合 DPI / 多显示器验收（原生驱动）。

必须在真实桌面会话里运行；每一项都记"实测值"和"是否真的具备该环境"：
没有 125%/150%/200% 或负坐标副屏时，对应行记为 unverified，而不是通过。
只保存每块屏左上角 32x32 的小裁剪作为证据，不落整屏截图。

用法：
    python main/tests/native_dpi_matrix.py --run --output <目录>
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wintypes
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

if os.name != "nt":
    raise SystemExit("native DPI matrix requires Windows")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import bootstrap, platform_utils  # noqa: E402

# 用生产同一条 pre-Qt 设置（QT_ENABLE_HIGHDPI_SCALING=0 + per-monitor V2），
# 这样 Qt 的逻辑坐标和 mss/Win32 的物理像素才会一致。
bootstrap.setup_environment()
platform_utils.set_dpi_awareness()

try:
    import mss  # noqa: E402
except Exception as exc:  # pragma: no cover - environment dependent
    raise SystemExit(f"mss unavailable: {exc}") from exc

user32 = ctypes.windll.user32
shcore = ctypes.windll.shcore

MONITORINFOF_PRIMARY = 0x1
MDT_EFFECTIVE_DPI = 0


class RECT(ctypes.Structure):
    _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG),
                ("right", wintypes.LONG), ("bottom", wintypes.LONG)]


class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", RECT), ("rcWork", RECT),
                ("dwFlags", wintypes.DWORD), ("szDevice", wintypes.WCHAR * 32)]


def enumerate_monitors():
    """返回 [(device, rect_tuple, is_primary)]，用 Win32 API 枚举。"""
    monitors = []
    MonitorEnumProc = ctypes.WINFUNCTYPE(
        ctypes.c_int, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(RECT), wintypes.LPARAM)

    def callback(hmonitor, _hdc, _rect, _data):
        info = MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(MONITORINFOEXW)
        if user32.GetMonitorInfoW(hmonitor, ctypes.byref(info)):
            rect = info.rcMonitor
            monitors.append({
                "hmon": int(hmonitor),
                "device": str(info.szDevice),
                "rect": [int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)],
                "primary": bool(info.dwFlags & MONITORINFOF_PRIMARY),
            })
        return 1

    user32.EnumDisplayMonitors(None, None, MonitorEnumProc(callback), 0)
    return monitors


def monitor_dpi(handle):
    """按 HMONITOR 拿有效 DPI；取不到就回退 96（并如实记录）。"""
    try:
        dpi_x = wintypes.UINT()
        dpi_y = wintypes.UINT()
        if shcore.GetDpiForMonitor(ctypes.c_void_p(int(handle)), MDT_EFFECTIVE_DPI,
                                   ctypes.byref(dpi_x), ctypes.byref(dpi_y)) == 0:
            return int(dpi_x.value) or 96
    except Exception:
        pass
    return 96


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="store_true", help="确实执行原生验收")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if not args.run:
        parser.error("native DPI matrix requires --run")

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    monitors = enumerate_monitors()
    for monitor in monitors:
        monitor["dpi"] = monitor_dpi(monitor["hmon"])
        monitor["scale"] = round(monitor["dpi"] / 96.0, 4)
    public_monitors = [{k: v for k, v in m.items() if k != "hmon"} for m in monitors]

    result = {
        "task": "TF-0042",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "kind": "real_desktop" if len(monitors) > 0 else "unavailable",
        "dpi_awareness": "per-monitor-v2-requested",
        "monitors": public_monitors,
        "checks": [],
        "matrix": [],
        "unverified": [],
        "note": "只保存每块屏左上角 32x32 小裁剪；整套验收在真实桌面会话执行。",
    }

    def check(name, passed, detail):
        result["checks"].append({"name": name, "passed": bool(passed), "detail": detail})
        return bool(passed)

    ok = True
    with mss.mss() as sct:
        mss_monitors = list(sct.monitors[1:])
        virtual = sct.monitors[0]
        expected = [m["rect"] for m in monitors]
        actual = [[m["left"], m["top"], m["left"] + m["width"], m["top"] + m["height"]] for m in mss_monitors]
        ok &= check("virtual_desktop_matches_win32", sorted(expected) == sorted(actual),
                    {"win32": sorted(expected), "mss": sorted(actual)})

        for index, monitor in enumerate(monitors, start=1):
            left, top, right, bottom = monitor["rect"]
            width, height = right - left, bottom - top
            match = next((m for m in mss_monitors
                          if [m["left"], m["top"], m["left"] + m["width"], m["top"] + m["height"]] == monitor["rect"]), None)
            if match is None:
                ok &= check(f"monitor_{index}_capture", False, "mss 找不到与 Win32 矩形一致的显示器")
                continue
            shot = sct.grab(match)
            size_ok = (shot.width, shot.height) == (width, height)
            ok &= check(f"monitor_{index}_physical_size", size_ok,
                        {"expected": [width, height], "actual": [shot.width, shot.height], "scale": monitor["scale"]})
            crop_path = out_dir / f"monitor-{index}-topleft.png"
            try:
                from PySide6.QtGui import QImage
                image = QImage(shot.bgra, shot.width, shot.height, shot.width * 4, QImage.Format.Format_RGB32)
                image.copy(0, 0, min(32, shot.width), min(32, shot.height)).save(str(crop_path), "PNG")
            except Exception:
                crop_path = None
            result["matrix"].append({
                "monitor": index,
                "device": monitor["device"],
                "rect": monitor["rect"],
                "dpi": monitor["dpi"],
                "scale": monitor["scale"],
                "verified": bool(size_ok),
                "crop": str(crop_path) if crop_path else None,
            })

        scale_set = {m["scale"] for m in monitors}
        for wanted in (1.0, 1.25, 1.5, 2.0):
            if wanted in scale_set:
                continue
            result["unverified"].append({
                "item": f"scale_{wanted:.2f}",
                "reason": "本机没有该缩放比例的显示器",
            })
        if any(m["rect"][0] < 0 or m["rect"][1] < 0 for m in monitors):
            result["matrix"].append({"monitor": "negative_coords", "verified": True})
        else:
            result["unverified"].append({"item": "negative_coordinate_monitor", "reason": "本机没有负坐标副屏"})

    os.environ.setdefault("QT_QPA_PLATFORM", "windows")
    try:
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([])
        primary = app.primaryScreen()
        result["qt"] = {
            "screens": [s.name() for s in app.screens()],
            "primary_dpr": float(primary.devicePixelRatio()) if primary else None,
            "primary_geometry": [primary.geometry().x(), primary.geometry().y(),
                                 primary.geometry().width(), primary.geometry().height()] if primary else None,
        }
        if primary is not None:
            ok &= check("qt_scaling_disabled_for_physical_pixels", abs(primary.devicePixelRatio() - 1.0) < 1e-6,
                        {"devicePixelRatio": float(primary.devicePixelRatio()),
                         "QT_ENABLE_HIGHDPI_SCALING": os.environ.get("QT_ENABLE_HIGHDPI_SCALING")})
            geometry = primary.geometry()
            ok &= check("qt_primary_geometry_matches_physical_monitor",
                        (geometry.x(), geometry.y(), geometry.width(), geometry.height()) == tuple(monitors[0]["rect"]),
                        {"qt": [geometry.x(), geometry.y(), geometry.width(), geometry.height()],
                         "win32": monitors[0]["rect"]})
    except Exception as exc:
        result["qt"] = {"error": str(exc)}

    result["passed"] = bool(ok) and not any(c["passed"] is False for c in result["checks"])
    result["virtual_desktop"] = [virtual["left"], virtual["top"], virtual["width"], virtual["height"]]
    (out_dir / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed": result["passed"], "monitors": len(monitors),
                      "unverified": [u["item"] for u in result["unverified"]]}, ensure_ascii=False))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
