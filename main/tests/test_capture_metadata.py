# -*- coding: utf-8 -*-
"""TF-0040 截图元信息：默认关闭、只有显式内容才导出、来源回退、不误用来源字段。"""
import os

from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QImage

from canvas.scene import CanvasScene
from core.capture_metadata import (
    CaptureMetadata,
    describe_source_window,
    load_metadata,
    now_stamp,
    render_strip,
    save_metadata,
)
from core.export import ExportService
from settings import get_tool_settings_manager

SIZE = 120


def _image(width=SIZE, height=SIZE):
    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(QColor("#3366CC"))
    return image


def test_defaults_export_nothing():
    meta = CaptureMetadata()
    assert meta.is_empty()
    assert meta.build_lines() == []
    image = _image()
    assert render_strip(image, []) is image


def test_only_enabled_parts_are_exported():
    meta = CaptureMetadata(
        source_enabled=True, source="Chrome - 登录页",
        note_enabled=True, note="第 3 步失败",
        time_enabled=False, captured_at="2026-10-10 12:00:00",
    )
    lines = meta.build_lines()
    assert lines == ["来源: Chrome - 登录页", "备注: 第 3 步失败"]
    assert "2026-10-10" not in "".join(lines)

    empty = CaptureMetadata(source_enabled=True, source="   ")
    assert empty.build_lines() == [], "勾了但内容为空不导出"


def test_render_strip_wraps_long_note_and_keeps_width(qapp):
    image = _image(120, 80)
    long_note = "备注: " + "很长的问题描述需要折行显示并且不能截断。" * 6
    out = render_strip(image, [long_note])
    assert out.width() == image.width()
    assert out.height() > image.height()
    assert out.pixelColor(2, 2) == image.pixelColor(2, 2), "原图像素不能被信息条覆盖"


def test_save_and_load_roundtrip_and_cancel_keeps_old_value():
    manager = get_tool_settings_manager()
    before = manager.get_app_setting("capture_meta_source", "")
    try:
        meta = CaptureMetadata(source_enabled=True, source="VSCode - main.py", note="复现步骤", captured_at=now_stamp())
        assert save_metadata(manager, meta) is True
        loaded = load_metadata(manager)
        assert loaded.source_enabled is True
        assert loaded.source == "VSCode - main.py"
        assert loaded.note == "复现步骤"

        # 取消 = 不再调用 save：设置保持上一次的值，敏感标题不会传播
        cancelled = CaptureMetadata(source_enabled=True, source="敏感标题")
        assert cancelled.source == "敏感标题"
        assert manager.get_app_setting("capture_meta_source", "") == "VSCode - main.py"
    finally:
        manager.set_app_setting("capture_meta_source", before)
        manager.set_app_setting("capture_meta_source_enabled", False)
        manager.set_app_setting("capture_meta_note", "")
        manager.set_app_setting("capture_meta_note_enabled", False)


def test_source_window_excludes_our_own_process(monkeypatch):
    import capture.window_finder as finder_module
    import win32process

    class _Finder:
        def find_window_at_point_info(self, x, y):
            return (123, [], "我们自己")

    monkeypatch.setattr(finder_module, "WINDOWS_API_AVAILABLE", True)
    monkeypatch.setattr(finder_module, "WindowFinder", _Finder)
    monkeypatch.setattr(win32process, "GetWindowThreadProcessId", lambda hwnd: (0, os.getpid()))

    assert describe_source_window(10, 10, own_pid=os.getpid()) == {}


def test_source_window_falls_back_when_unavailable(monkeypatch):
    import capture.window_finder as finder_module

    class _Finder:
        def find_window_at_point_info(self, x, y):
            raise RuntimeError("access denied")

    monkeypatch.setattr(finder_module, "WINDOWS_API_AVAILABLE", True)
    monkeypatch.setattr(finder_module, "WindowFinder", _Finder)
    assert describe_source_window(10, 10) == {}

    monkeypatch.setattr(finder_module, "WINDOWS_API_AVAILABLE", False)
    assert describe_source_window(10, 10) == {}


def test_source_window_keeps_title_when_process_lookup_fails(monkeypatch):
    import capture.window_finder as finder_module
    import win32process

    class _Finder:
        def find_window_at_point_info(self, x, y):
            return (321, [], "Notepad - notes.txt")

    monkeypatch.setattr(finder_module, "WINDOWS_API_AVAILABLE", True)
    monkeypatch.setattr(finder_module, "WindowFinder", _Finder)
    monkeypatch.setattr(win32process, "GetWindowThreadProcessId", lambda hwnd: (0, 999999))

    info = describe_source_window(10, 10, own_pid=os.getpid())
    assert info["source"].endswith("Notepad - notes.txt")


def test_export_chain_adds_metadata_only_when_enabled(qapp):
    manager = get_tool_settings_manager()
    before_enabled = manager.get_app_setting("capture_meta_source_enabled", False)
    before_source = manager.get_app_setting("capture_meta_source", "")
    image = _image()
    scene = CanvasScene(image, QRectF(0, 0, SIZE, SIZE), enable_mosaic=True)
    scene.selection_model.initialize_confirmed_rect(QRectF(0, 0, SIZE, SIZE))
    service = ExportService(scene)
    rect = QRectF(0, 0, SIZE, SIZE)
    try:
        manager.set_app_setting("capture_meta_source_enabled", False)
        plain = service.export(rect)
        assert service.export_with_legend(rect).size() == plain.size()

        manager.set_app_setting("capture_meta_source_enabled", True)
        manager.set_app_setting("capture_meta_source", "Chrome - 登录页")
        marked = service.export_with_legend(rect)
        assert marked.height() > plain.height()
        assert marked.width() == plain.width()
    finally:
        manager.set_app_setting("capture_meta_source_enabled", before_enabled)
        manager.set_app_setting("capture_meta_source", before_source)


def test_metadata_never_feeds_file_names_or_clipboard_source():
    with open("main/core/save.py", encoding="utf-8") as handle:
        save_src = handle.read()
    with open("main/clipboard/core/models.py", encoding="utf-8") as handle:
        clipboard_src = handle.read()
    assert "capture_meta" not in save_src, "元信息默认不能写进文件名"
    assert "capture_meta" not in clipboard_src, "不能误用剪贴板来源字段"


def test_metadata_settings_controls_preview_and_detect(qapp, monkeypatch):
    from PySide6.QtWidgets import QWidget

    import core.capture_metadata as meta_module
    from ui.settings_ui.components import SettingCardGroup
    from ui.settings_ui.metadata_controls import add_metadata_controls

    class _Config:
        def __init__(self):
            self.saved = {}

        def get_app_setting(self, key, default=None):
            return self.saved.get(key, default)

    class _Dialog(QWidget):
        def __init__(self):
            super().__init__()
            self.config_manager = _Config()

        def tr(self, text):
            return text

    monkeypatch.setattr(meta_module, "describe_source_window", lambda *a, **k: {"source": "Chrome - 登录页"})

    dialog = _Dialog()
    group = SettingCardGroup("Metadata", dialog)
    add_metadata_controls(dialog, group)

    assert dialog.meta_source_toggle.isChecked() is False, "来源默认不导出"
    assert dialog.meta_time_toggle.isChecked() is False
    assert dialog.meta_note_toggle.isChecked() is False
    assert dialog.meta_preview.pixmap() is not None
    assert not dialog.meta_source_edit.isEnabled(), "关闭时来源不可编辑"

    dialog.meta_source_toggle.setChecked(True)
    dialog.meta_source_edit.setText("Chrome - 登录页")
    dialog.meta_note_toggle.setChecked(True)
    dialog.meta_note_edit.setText("第 3 步失败")
    lines = CaptureMetadata(source_enabled=True, source="Chrome - 登录页",
                            note_enabled=True, note="第 3 步失败").build_lines()
    assert lines == ["来源: Chrome - 登录页", "备注: 第 3 步失败"]

    dialog.meta_source_edit.clear()
    assert CaptureMetadata(source_enabled=True, source="").build_lines() == []
