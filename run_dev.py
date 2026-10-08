# -*- coding: utf-8 -*-
"""开发版启动器：跳过欢迎向导、静默托盘、打开剪贴板历史窗。

用法:
    venv312\\Scripts\\python.exe run_dev.py
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
MAIN = os.path.join(ROOT, "main")
sys.path.insert(0, MAIN)
os.chdir(MAIN)


def seed_dev_config() -> None:
    """开发环境预置：非首次运行、显示剪贴板、OCR 懒加载。"""
    from settings import get_tool_settings_manager

    cfg = get_tool_settings_manager()
    if hasattr(cfg, "mark_as_run"):
        cfg.mark_as_run()
    cfg.set_app_setting("preload_ocr", False)
    cfg.set_app_setting("preload_settings", True)
    cfg.set_app_setting("preload_clipboard", True)
    # 列表显示来源/时间/标签行；窗口不透明，便于验收
    if hasattr(cfg, "set_clipboard_show_metadata"):
        cfg.set_clipboard_show_metadata(True)
    else:
        cfg.set_app_setting("clipboard_show_metadata", True)
    if hasattr(cfg, "set_clipboard_theme"):
        cfg.set_clipboard_theme("auto")
    if hasattr(cfg, "set_clipboard_enabled"):
        cfg.set_clipboard_enabled(True)
    # 启动时不弹设置窗（托盘静默），剪贴板窗由钩子打开
    if hasattr(cfg, "set_show_main_window"):
        cfg.set_show_main_window(False)
    else:
        cfg.set_app_setting("show_main_window", False)


def main() -> None:
    seed_dev_config()

    # 启动完成后自动弹出剪贴板历史窗，方便立刻试
    from core import bootstrap

    original = bootstrap.PreloadManager._show_main_window_on_start

    def _show_and_open_clipboard(self):
        original(self)
        try:
            from PySide6.QtCore import QTimer

            def _open():
                self.app.open_clipboard_window()

            QTimer.singleShot(600, _open)
        except Exception:
            pass

    bootstrap.PreloadManager._show_main_window_on_start = _show_and_open_clipboard
    bootstrap.run()


if __name__ == "__main__":
    main()
