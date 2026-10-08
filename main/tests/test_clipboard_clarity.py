"""Readable metadata and stable, paginated history ordering."""
from datetime import datetime
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QPoint, QPointF, QRect
from PySide6.QtGui import QEnterEvent
from PySide6.QtWidgets import QStyleOptionViewItem

from clipboard.core import ClipboardItem, Tag
from clipboard.core.models import TAG_CHIP_COLORS
from clipboard.core.manager import ClipboardManager
from clipboard.controllers.clipboard_controller import ClipboardController
from clipboard.ui.theme.themes import PRESET_THEMES
from clipboard.ui.theme.theme_styles import surface_palette, tag_chip_palette
from clipboard.ui.widgets.item_delegate import ClipboardItemDelegate, ROLE_ITEM_DATA
from .test_clipboard_light_resources import _contrast


def test_ordering_applies_before_pagination_and_keeps_pins_first(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(ClipboardManager, "_instance", None)
    manager = ClipboardManager(str(tmp_path / "history.db"))
    assert manager.is_available
    try:
        ids = [manager.add_item(f"example {i}", "text") for i in range(6)]
        store = manager.image_text_store
        with store.connect() as db:
            for i, item_id in enumerate(ids):
                db.execute("UPDATE clipboard SET created_at=?, item_order=?, paste_count=?, is_pinned=? WHERE id=?",
                           (100 + i, 10 - i, i % 3, int(i in (1, 4)), item_id))
        expected = {"default": [1, 4, 0, 2, 3, 5], "newest": [4, 1, 5, 3, 2, 0],
                    "oldest": [1, 4, 0, 2, 3, 5], "frequent": [4, 1, 5, 2, 3, 0]}
        for order, indices in expected.items():
            for search in (None, "example"):
                actual = [item.id for offset in (0, 2, 4)
                          for item in manager.get_history(offset, 2, search=search, sort_order=order)]
                assert actual == [ids[i] for i in indices]
        manager.toggle_pin(ids[5])
        assert manager.get_history(limit=1, sort_order="newest")[0].id == ids[5]
        manager.toggle_pin(ids[5])
        assert manager.get_history(limit=1, sort_order="newest")[0].id == ids[4]
    finally:
        manager.release_storage()


def test_filtered_history_advances_by_raw_page_and_disables_fast_insert(monkeypatch):
    items = [ClipboardItem(i, "example", "text", source_app="Code.exe" if i == 4 else "other.exe")
             for i in range(6)]
    manager = SimpleNamespace(get_history=lambda offset, limit, **kw: items[offset:offset + limit])
    monkeypatch.setattr(ClipboardController, "_load_settings", lambda self: None)
    ctrl = ClipboardController(manager)
    ctrl._source_filter = "Code"
    ctrl._get_page_size = lambda: 3
    ctrl.load_history()
    assert ctrl._current_offset == 3 and ctrl.has_more_items()
    ctrl.load_more_if_needed()
    assert [item.id for item in ctrl.current_items] == [4]
    assert not ctrl.insert_item(items[0])
    ctrl._source_filter = None
    ctrl.sort_order = "oldest"
    assert not ctrl.insert_item(ClipboardItem(100, "new", "text"))


@pytest.mark.parametrize("theme", list(PRESET_THEMES.values()), ids=list(PRESET_THEMES))
def test_tag_ink_has_readable_contrast_on_normal_and_pinned_rows(theme):
    palette = surface_palette(theme)
    for background in (palette.tint, palette.accent_soft):
        for color in TAG_CHIP_COLORS:
            fill, ink = tag_chip_palette(color, background)
            assert fill.alpha() == 255
            assert _contrast(fill, ink) >= 4.5


def test_tags_keep_their_own_space_and_report_every_hidden_label(qapp):
    delegate = ClipboardItemDelegate(theme=PRESET_THEMES["apple"], display_lines=17)
    tags = [Tag(i, "这是一条很长的标签名称" + str(i)) for i in range(6)]
    for width in (170, 300, 480):
        layout = delegate._tag_layout(tags, width)
        assert sum(size for _, size, _ in layout) + (len(layout) - 1) * 6 <= width
        shown = sum(color is not None for _, _, color in layout)
        assert layout[-1][0] == f"+{len(tags) - shown}"
    option = QStyleOptionViewItem()
    option.rect = QRect(0, 0, 560, 100)
    item = ClipboardItem(1, "example", "text", tags=tags)
    index = SimpleNamespace(data=lambda role: item if role == ROLE_ITEM_DATA else None)
    delegate.set_show_metadata(False)
    tagged_height = delegate.sizeHint(option, index).height()
    item.tags = []
    assert tagged_height - delegate.sizeHint(option, index).height() >= delegate._chip_h


def test_preview_shows_source_tags_and_scrollable_long_content(qapp):
    from clipboard.ui.widgets.preview_popup import PreviewPopup
    popup = PreviewPopup()
    item = ClipboardItem(1, "A long paragraph. " * 1000, "text", source_app="Code.exe",
                         created_at=datetime(2026, 10, 7), tags=[Tag(1, "工作")])
    popup.set_display_enabled(True)
    popup.show_preview(item, QPoint(20, 20), delay_ms=0)
    qapp.processEvents()
    assert "Code" in popup.title_label.text() and "#工作" in popup.title_label.text()
    assert popup.content_widget.toPlainText() == item.content
    assert popup.content_widget.width() > 500
    assert popup.content_widget.verticalScrollBar().maximum() > 0
    assert popup.content_widget.verticalScrollBar().value() == 0
    popup.schedule_hide()
    assert popup._hide_timer.isActive()
    popup.enterEvent(QEnterEvent(QPointF(), QPointF(), QPointF()))
    assert not popup._hide_timer.isActive() and popup.isVisible()
    popup.schedule_hide()
    popup.set_display_enabled(False)
    assert not popup._hide_timer.isActive() and not popup.isVisible()
    popup.deleteLater()
