# -*- coding: utf-8 -*-
"""列表行视觉冒烟：把 delegate 画到 QPixmap 并落盘，肉眼验收用。

用法:
    venv312\\Scripts\\python.exe main\\tests\\smoke_paint_list_row.py
产物:
    assets/clipboard_row_preview.png
"""
from __future__ import annotations

import os
import sys
from datetime import datetime

os.environ.pop("QT_QPA_PLATFORM", None)  # offscreen 无系统字库，中文会变方块

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtGui import QColor, QFontDatabase, QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from clipboard.core.models import ClipboardItem, Tag  # noqa: E402
from clipboard.ui.theme.themes import get_theme_manager  # noqa: E402
from clipboard.ui.widgets.item_delegate import (  # noqa: E402
    ROLE_ITEM_DATA,
    ROLE_ITEM_ID,
    ClipboardItemDelegate,
)
from PySide6.QtCore import QRect  # noqa: E402
from PySide6.QtWidgets import QStyleOptionViewItem  # noqa: E402


def ensure_cjk_font() -> None:
    """确保字库里有微软雅黑；极简环境可手动加载系统 ttc。"""
    _app = QApplication.instance() or QApplication([])  # Keep the Qt application alive while using its fonts.
    if "Microsoft YaHei UI" in QFontDatabase.families() or "Microsoft YaHei" in QFontDatabase.families():
        return
    for path in (
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\msyhbd.ttc",
        r"C:\Windows\Fonts\simhei.ttf",
    ):
        if os.path.exists(path):
            QFontDatabase.addApplicationFont(path)


class _FakeIndex:
    def __init__(self, data: dict):
        self._data = data

    def data(self, role):
        return self._data.get(role)

    def row(self):
        return self._data.get("row", 0)


def build_samples() -> list[ClipboardItem]:
    now = datetime(2026, 4, 5, 10, 21)
    pinned = ClipboardItem(
        id=1,
        content="SELECT * FROM users WHERE id = ?",
        content_type="text",
        is_pinned=True,
        source_app=r"C:\Users\me\AppData\Local\Programs\Microsoft VS Code\Code.exe",
        created_at=now,
    )
    pinned.tags = [
        Tag(id=1, name="代码", color="#5B8DB8"),
        Tag(id=2, name="工作", color="#C4922A"),
        Tag(id=3, name="项目A", color="#8B7BB8"),
        Tag(id=4, name="紧急", color="#C47A6A"),
        Tag(id=5, name="后端", color="#4A9B8E"),
    ]

    normal = ClipboardItem(
        id=2,
        content="[1920x1080]",
        content_type="image",
        source_app=r"C:\Tools\Snipaste\Snipaste.exe",
        created_at=datetime(2026, 4, 5, 10, 18),
        image_id="demo",
        thumbnail=None,
    )
    normal.tags = [Tag(id=6, name="素材", color="#4A9B8E")]

    text2 = ClipboardItem(
        id=3,
        content="https://github.com/1003129155/jietuba",
        content_type="text",
        source_app=r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        created_at=datetime(2026, 4, 5, 9, 55),
    )
    return [pinned, normal, text2]


def paint_preview(out_path: str) -> None:
    _app = QApplication.instance() or QApplication([])  # Own the application through rendering.
    ensure_cjk_font()
    theme = get_theme_manager().get_current_theme()
    delegate = ClipboardItemDelegate(theme=theme, display_lines=15, show_metadata=True)

    width, row_h = 560, 56
    samples = build_samples()
    height = row_h * len(samples) + 16
    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(QColor(theme.colors.bg_primary))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    for i, item in enumerate(samples):
        option = QStyleOptionViewItem()
        option.rect = QRect(8, 8 + i * row_h, width - 16, row_h - 4)
        index = _FakeIndex({ROLE_ITEM_DATA: item, ROLE_ITEM_ID: item.id, "row": i})
        delegate.set_highlighted_id(item.id if item.is_pinned else None)
        delegate.paint(painter, option, index)

    painter.end()
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    if not image.save(out_path):
        raise RuntimeError(f"save failed: {out_path}")
    print("PAINT_OK", out_path)


if __name__ == "__main__":
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    out = os.path.join(root, "assets", "clipboard_row_preview.png")
    paint_preview(out)
