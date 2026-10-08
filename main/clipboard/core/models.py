"""clipboard core 数据模型。

定义剪贴板模块共享的数据对象，主要包括：
- `ClipboardItem`：单条剪贴板记录及其展示相关属性
- `Group`：分组名称、图标、类型等基础信息

这些模型尽量保持 UI 无关，供 core、controller 和 UI 层共同使用。
"""

import json
import zlib
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, TYPE_CHECKING

from core.logger import T, log_exception

from .enums import GroupType

if TYPE_CHECKING:
    # 仅供类型注解使用：pyclipboard 是自制 Rust 扩展，运行环境未安装时
    # core.manager 会降级处理，所以这里不能在运行时导入。
    # 别名保留 Py 前缀：本模块自己有同名的 ClipboardItem / Group 数据类。
    from pyclipboard import ClipboardItem as PyClipboardItem, Group as PyGroup


def source_app_short_name(source_app: Optional[str]) -> str:
    """来源应用显示名：完整路径 → exe 主名。

    `C:\\...\\Code.exe` → `Code`；空/None → `""`。
    只取文件名、去扩展名，避免完整路径把元数据行撑爆。
    """
    if not source_app:
        return ""
    name = source_app.replace("\\", "/").rsplit("/", 1)[-1]
    if name.lower().endswith(".exe"):
        name = name[:-4]
    return name[:16]


# 标签 Chip 色板（见 DESIGN_CLIPBOARD.md）。只允许这 8 色。
TAG_CHIP_COLORS = (
    "#6B7C8F",  # slate
    "#5B8DB8",  # blue
    "#4A9B8E",  # teal
    "#6A9F5A",  # green
    "#C4922A",  # amber
    "#C47A6A",  # coral
    "#8B7BB8",  # violet
    "#B86B8B",  # rose
)


@dataclass
class Tag:
    """标签数据类。"""

    id: int
    name: str
    color: Optional[str] = None  # 取值必须来自 TAG_CHIP_COLORS

    @property
    def chip_color(self) -> str:
        if self.color in TAG_CHIP_COLORS:
            return self.color
        # 稳定映射：同名标签始终同色
        return TAG_CHIP_COLORS[zlib.crc32(self.name.encode("utf-8")) % len(TAG_CHIP_COLORS)]


@dataclass
class ClipboardItem:
    """剪贴板项数据类。"""

    id: int
    content: str
    content_type: str
    title: Optional[str] = None
    html_content: Optional[str] = None
    image_id: Optional[str] = None
    thumbnail: Optional[str] = None
    is_pinned: bool = False
    paste_count: int = 0
    source_app: Optional[str] = None
    created_at: datetime = None
    updated_at: datetime = None
    tags: list = None  # List[Tag]，UI 只读展示
    ocr_text: str = ""  # 本地检索元数据，不替代图片内容或粘贴格式。

    def __post_init__(self):
        if self.tags is None:
            self.tags = []

    @classmethod
    def from_py_item(cls, item: "PyClipboardItem") -> "ClipboardItem":
        return cls(
            id=item.id,
            content=item.content,
            content_type=item.content_type,
            title=item.title,
            html_content=item.html_content,
            image_id=item.image_id,
            thumbnail=item.thumbnail,
            is_pinned=item.is_pinned,
            paste_count=item.paste_count,
            source_app=item.source_app,
            created_at=datetime.fromtimestamp(item.created_at) if item.created_at else None,
            updated_at=datetime.fromtimestamp(item.updated_at) if item.updated_at else None,
            tags=[],
        )

    @property
    def source_label(self) -> str:
        """元数据行用的来源短名。"""
        return source_app_short_name(self.source_app)

    @property
    def display_text(self) -> str:
        if self.title:
            return self.title

        if self.content_type == "text":
            text = self.content.replace("\n", " ").strip()
            return text[:100] + "..." if len(text) > 100 else text
        if self.content_type == "image":
            if self.ocr_text:
                text = self.ocr_text.replace("\n", " ").strip()
                return text[:100] + "…" if len(text) > 100 else text
            return self.content.strip("[]")
        if self.content_type == "file":
            try:
                import os

                data = json.loads(self.content)
                files = data.get("files", [])
                if len(files) == 1:
                    return os.path.basename(files[0])
                if len(files) > 1:
                    return ", ".join(os.path.basename(file_path) for file_path in files)
                return "文件"
            except Exception as e:
                log_exception(e, T("解析文件类型显示文本"))
                return "文件"
        return self.content[:50]

    @property
    def icon(self) -> str:
        if self.content_type == "file":
            return "📁"
        if self.content_type == "image":
            return "📷"
        return ""


@dataclass
class Group:
    """分组数据类。"""

    id: int
    name: str
    color: Optional[str] = None
    icon: Optional[str] = None
    group_type: int = GroupType.NORMAL

    @classmethod
    def from_py_group(cls, group: "PyGroup") -> "Group":
        return cls(
            id=group.id,
            name=group.name,
            color=group.color,
            icon=group.icon,
            group_type=group.group_type,
        )


__all__ = ["ClipboardItem", "Group", "Tag", "TAG_CHIP_COLORS", "source_app_short_name"]
