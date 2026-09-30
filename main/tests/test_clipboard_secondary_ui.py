# -*- coding: utf-8 -*-
"""二次开发 UI 辅助：来源短名、标签 Chip 色板、统一置顶语义。"""

from clipboard.core import TAG_CHIP_COLORS, Tag, source_app_short_name
from clipboard.core.models import ClipboardItem


def test_source_app_short_name_strips_path_and_exe():
    assert source_app_short_name(r"C:\Users\me\AppData\Local\Programs\Code.exe") == "Code"
    assert source_app_short_name("D:/soft/WeChat/WeChat.exe") == "WeChat"
    assert source_app_short_name("chrome.exe") == "Chrome" or source_app_short_name("chrome.exe") == "chrome"
    assert source_app_short_name(None) == ""
    assert source_app_short_name("") == ""


def test_source_app_short_name_truncates_long_names():
    long_path = "C:\\Program Files\\" + ("VeryLongApplicationName" * 3) + ".exe"
    assert len(source_app_short_name(long_path)) <= 16


def test_tag_chip_color_stable_and_from_palette():
    tag = Tag(id=1, name="工作", color=None)
    assert tag.chip_color in TAG_CHIP_COLORS
    assert Tag(id=2, name="工作", color=None).chip_color == tag.chip_color
    assert Tag(id=3, name="x", color="#5B8DB8").chip_color == "#5B8DB8"
    assert Tag(id=4, name="x", color="#FF0000").chip_color in TAG_CHIP_COLORS


def test_clipboard_item_defaults_and_source_label():
    item = ClipboardItem(id=1, content="hi", content_type="text")
    assert item.tags == []
    assert item.source_label == ""
    item2 = ClipboardItem(
        id=2,
        content="hi",
        content_type="text",
        source_app=r"C:\Dev\Code.exe",
    )
    assert item2.source_label == "Code"


def test_context_menu_gives_all_items_history_pin(monkeypatch):
    from clipboard.controllers.clipboard_controller import ClipboardController

    class DummyManager:
        def get_groups(self):
            return []

        def get_item(self, item_id):
            return ClipboardItem(
                id=item_id,
                content="img",
                content_type="image",
                image_id="x",
                source_app=r"C:\a\Paint.exe",
            )

        def list_tags(self):
            return []

    monkeypatch.setattr(ClipboardController, "_load_settings", lambda self: None)
    controller = ClipboardController(DummyManager())
    ctx = controller.build_context_menu_data(9)
    keys = [a.key for a in ctx.actions if not a.is_separator]
    assert "toggle_pin" in keys
    assert "tags_menu" in keys
    assert "filter_by_source" in keys
    assert "pin_image" in keys
