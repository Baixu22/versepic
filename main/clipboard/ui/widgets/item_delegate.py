# -*- coding: utf-8 -*-
"""
ClipboardItemDelegate — 剪贴板列表项绘制代理

一行的结构（内容、出处/时间、独立标签 + 左侧图形 + 右侧按键提示）：

    [图标]  [已置顶] 内容标题（单行，超出省略）              1
            来源：Code · 3 分钟前
            (代码) (工作) (+2)

- 置顶行用浅底、侧边指示条和常驻文字标记；标签有独立的高对比度底色；
- 高亮（鼠标或键盘选中）是一块内缩的圆角底，在行之间平滑淡入淡出；
- 左侧图形：文本用来源应用图标，图片用裁成方形的缩略图，文件用系统文件图标；
- 右侧是直选按键（1–9、A–Z），悬停时让位给行尾快捷按钮。

使用 QStyledItemDelegate + QPainter 直接绘制，不为每行创建 QWidget。
所有位图都按实际显示尺寸渲染，避免缩放造成的发虚和颗粒感。
"""

import base64
import json
import os
from collections import OrderedDict
from datetime import datetime
from time import perf_counter
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import QCoreApplication, QDate, QFileInfo, QLocale, QModelIndex, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QFileIconProvider, QListWidget, QStyledItemDelegate, QStyleOptionViewItem

from core.logger import T, log_error
from ui.glyphs import svg_pixmap

from ...core import ClipboardItem, source_app_short_name
from ..theme.theme_styles import SurfacePalette, surface_palette, readable_accent, tag_chip_palette
from ..theme.themes import Theme


# QListWidgetItem 自定义数据角色
ROLE_ITEM_DATA = Qt.ItemDataRole.UserRole + 1      # ClipboardItem 对象
ROLE_ITEM_ID = Qt.ItemDataRole.UserRole             # item.id（保持兼容）

# 前 35 项的直选按键：1–9，A–Z（与 ClipboardShortcutHandler 一致）
SHORTCUT_KEYS = [str(i) for i in range(1, 10)] + [chr(c) for c in range(ord("A"), ord("Z") + 1)]

UI_FAMILIES = ["Microsoft YaHei UI", "Segoe UI Variable Text", "Segoe UI"]

# 几何（以内容字号 17px 为基准，按字号等比缩放）
_BASE_FONT = 17
_ROW_INSET_X = 6        # 高亮底距视口左右边
_ROW_INSET_Y = 3
_ROW_RADIUS = 8
_PAD_X = 10             # 高亮底内的左右留白
_LEAD_W = 36            # 左侧图形列宽
_LEAD_GAP = 10
_THUMB = 36
_ICON = 24
_HINT_W = 22
_TAG_MAX = 3

# 行悬停过渡时长（秒）
_HOVER_SECONDS = 0.15

_ICON_MISSING = object()
_CTX = "ClipboardWindow"


def _tr(text: str) -> str:
    return QCoreApplication.translate(_CTX, text)


def _current_locale() -> QLocale:
    try:
        from core.i18n import I18nManager

        code = I18nManager.get_current_language()
    except Exception:
        code = "zh"
    return {
        "en": QLocale(QLocale.Language.English, QLocale.Country.UnitedStates),
        "ja": QLocale(QLocale.Language.Japanese, QLocale.Country.Japan),
        "ko": QLocale(QLocale.Language.Korean, QLocale.Country.SouthKorea),
    }.get(code, QLocale(QLocale.Language.Chinese, QLocale.Country.China))


def format_relative_time(created: Optional[datetime], now: Optional[datetime] = None) -> str:
    """刚刚 / N 分钟前 / 今天 HH:MM / 昨天 HH:MM / M月d日 / yyyy年M月d日。"""
    if created is None:
        return ""
    now = now or datetime.now()
    seconds = (now - created).total_seconds()
    if seconds < 60:
        return _tr("Just now")
    if seconds < 3600:
        return _tr("{n} min ago").format(n=int(seconds // 60))
    clock = created.strftime("%H:%M")
    day_delta = (now.date() - created.date()).days
    if day_delta == 0:
        return clock
    if day_delta == 1:
        return f"{_tr('Yesterday')} {clock}"
    qdate = QDate(created.year, created.month, created.day)
    fmt = _tr("MMM d") if created.year == now.year else _tr("MMM d, yyyy")
    return _current_locale().toString(qdate, fmt)


_APP_NAME_CACHE: Dict[str, str] = {}
_APP_NAME_MAX = 20


def source_app_display_name(source_app: Optional[str]) -> str:
    """来源应用的可读名称：优先取 exe 版本信息里的 FileDescription。

    `msedge.exe` → `Microsoft Edge`，`explorer.exe` → `Windows 资源管理器`（随系统语言）。
    取不到（非 Windows、文件不存在、无版本信息）时退回 exe 主名，首字母大写。
    结果按路径缓存，同一应用只读一次版本信息。
    """
    if not source_app:
        return ""
    cached = _APP_NAME_CACHE.get(source_app)
    if cached is not None:
        return cached
    name = ""
    if os.name == "nt" and os.path.isfile(source_app):
        try:
            import win32api

            lang, codepage = win32api.GetFileVersionInfo(source_app, "\\VarFileInfo\\Translation")[0]
            key = "\\StringFileInfo\\%04x%04x\\FileDescription" % (lang, codepage)
            name = (win32api.GetFileVersionInfo(source_app, key) or "").strip()
        except Exception:
            name = ""
    if not name:
        short = source_app_short_name(source_app)
        name = short[:1].upper() + short[1:] if short else ""
    if len(name) > _APP_NAME_MAX:
        name = name[: _APP_NAME_MAX - 1] + "…"
    if len(_APP_NAME_CACHE) > 256:
        _APP_NAME_CACHE.clear()
    _APP_NAME_CACHE[source_app] = name
    return name


def file_paths_of(item: ClipboardItem) -> List[str]:
    if item.content_type != "file":
        return []
    try:
        return list(json.loads(item.content).get("files", []))
    except Exception:
        return []


class ClipboardItemDelegate(QStyledItemDelegate):
    """高性能列表项绘制代理：所有视觉效果通过 QPainter 直接绘制。"""

    # 解码后的缩略图 (data_url -> QPixmap)，以及裁好圆角的方块 ((data_url, px) -> QPixmap)
    _thumb_cache: Dict[str, Optional[QPixmap]] = {}
    _tile_cache: "OrderedDict[Tuple[str, int], QPixmap]" = OrderedDict()
    _THUMB_CACHE_MAX = 120
    _TILE_CACHE_MAX = 240

    # 来源应用 / 文件图标 ((路径, px) -> QPixmap)。LRU，取不到也缓存，避免反复探盘。
    _icon_cache: "OrderedDict[Tuple[str, int], Optional[QPixmap]]" = OrderedDict()
    _ICON_CACHE_MAX = 128

    def __init__(
        self,
        parent: QListWidget = None,
        theme: Theme = None,
        display_lines: int = 1,
        window_opacity: int = 0,
        show_metadata: bool = True,
        line_height_padding: int = 8,
        show_shortcuts: bool = True,
    ):
        super().__init__(parent)
        self._theme: Optional[Theme] = theme
        self._palette: Optional[SurfacePalette] = surface_palette(theme) if theme else None
        self._display_lines = display_lines
        self._window_opacity = window_opacity
        self._show_metadata = show_metadata
        self._line_height_padding = line_height_padding
        self._show_shortcuts = show_shortcuts
        self._highlighted_id: Optional[int] = None

        # 行悬停过渡：row -> (t0, from, to)，进度在 paint 里按时间推算
        self._hover_row = -1
        self._hover_states: Dict[int, Tuple[float, float, float]] = {}

        # 行尾快捷按钮占用的宽度（仅对该行生效，文字给按钮让位）
        self._reserve_row = -1
        self._reserve_width = 0

        self._fonts: Dict[str, QFont] = {}
        self._metrics: Dict[str, QFontMetrics] = {}
        self._rebuild_font_cache()

    # ========== 配置更新 ==========

    def set_theme(self, theme: Theme):
        self._theme = theme
        self._palette = surface_palette(theme)

    def set_display_lines(self, lines: int):
        self._display_lines = lines
        self._rebuild_font_cache()

    def set_window_opacity(self, opacity: int):
        self._window_opacity = opacity

    def set_show_metadata(self, show: bool):
        self._show_metadata = show

    def set_show_shortcuts(self, show: bool):
        self._show_shortcuts = show

    def set_highlighted_id(self, item_id: Optional[int]):
        self._highlighted_id = item_id

    def set_action_reserve(self, row: int, width: int):
        """悬停行尾按钮出现时，让该行文字在 width 像素之前省略。"""
        self._reserve_row = row
        self._reserve_width = max(0, width)

    def set_hovered_row(self, row: int):
        """设置当前鼠标悬停行（-1 表示无）；高亮按 150ms OutCubic 过渡。"""
        if row == self._hover_row:
            return
        now = perf_counter()
        old = self._hover_row
        if old >= 0:
            cur = self._hover_progress(old, now)
            if cur > 0.01:
                self._hover_states[old] = (now, cur, 0.0)
            else:
                self._hover_states.pop(old, None)
        if row >= 0:
            start_from = self._hover_progress(row, now) if row in self._hover_states else 0.0
            if start_from < 0.99:
                self._hover_states[row] = (now, start_from, 1.0)
        self._hover_row = row

    def reset_hover(self):
        """列表重建时清空悬停状态。"""
        self._hover_row = -1
        self._hover_states.clear()
        self._reserve_row = -1

    def _hover_progress(self, row: int, now: Optional[float] = None) -> float:
        state = self._hover_states.get(row)
        if state is None:
            return 1.0 if row == self._hover_row and row >= 0 else 0.0
        t0, from_value, to_value = state
        if now is None:
            now = perf_counter()
        p = min(1.0, max(0.0, (now - t0) / _HOVER_SECONDS))
        eased = 1.0 - (1.0 - p) ** 3
        if p >= 1.0:
            if to_value <= 0.0:
                self._hover_states.pop(row, None)
            return to_value
        return from_value + (to_value - from_value) * eased

    def is_animating(self) -> bool:
        return bool(self._hover_states)

    @classmethod
    def clear_thumb_cache(cls):
        cls._thumb_cache.clear()
        cls._tile_cache.clear()

    # ========== 度量 ==========

    def _font_size(self) -> int:
        return self._display_lines if self._display_lines >= 10 else 15

    def _s(self, base: float) -> int:
        return max(1, round(base * self._font_size() / _BASE_FONT))

    def _rebuild_font_cache(self):
        size = self._font_size()

        def make(px: int, weight=QFont.Weight.Normal) -> QFont:
            font = QFont()
            font.setFamilies(UI_FAMILIES)
            font.setPixelSize(px)
            font.setWeight(weight)
            font.setHintingPreference(QFont.HintingPreference.PreferFullHinting)
            return font

        meta_px = max(12, round(size * 0.76))
        self._fonts = {
            "title": make(size),
            "meta": make(meta_px),
            "chip": make(meta_px, QFont.Weight.Medium),
            "hint": make(max(11, round(size * 0.7)), QFont.Weight.Medium),
        }
        self._metrics = {key: QFontMetrics(font) for key, font in self._fonts.items()}
        self._title_h = round(size * 1.45)
        self._meta_h = round(meta_px * 1.5)
        self._chip_h = max(22, self._meta_h + 4)

    def _pad_y(self) -> int:
        return self._s(max(10, self._line_height_padding))

    def _block_height(self, item):
        return (self._title_h + (self._meta_h + 4 if self._show_metadata else 0)
                + (self._chip_h + 6 if item.tags else 0))

    # ========== 核心绘制 ==========

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex):
        item: ClipboardItem = index.data(ROLE_ITEM_DATA)
        if not item or self._palette is None:
            return
        pal = self._palette
        row = index.row()
        rect = option.rect

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.setClipRect(rect)

        box = QRectF(rect).adjusted(_ROW_INSET_X, _ROW_INSET_Y, -_ROW_INSET_X, -_ROW_INSET_Y)
        path = QPainterPath()
        path.addRoundedRect(box, _ROW_RADIUS, _ROW_RADIUS)
        background = pal.accent_soft if item.is_pinned else pal.tint
        if item.is_pinned:
            painter.fillPath(path, background)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(pal.accent_text)
            painter.drawRoundedRect(QRectF(box.left() + 2, box.top() + 9, 3, box.height() - 18), 1.5, 1.5)

        # ---- 高亮底（选中 / 悬停，同一块圆角底，靠进度淡入淡出） ----
        highlighted = self._highlighted_id is not None and index.data(ROLE_ITEM_ID) == self._highlighted_id
        strength = self._hover_progress(row)
        if highlighted and row != self._hover_row:
            strength = 1.0
        if strength > 0.0:
            fill = QColor(pal.selected)
            fill.setAlphaF(pal.selected.alphaF() * strength)
            painter.fillPath(path, fill)
        if highlighted:
            painter.setPen(QPen(pal.accent_text, 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(box.adjusted(.5, .5, -.5, -.5), _ROW_RADIUS, _ROW_RADIUS)

        # ---- 水平分区 ----
        left = rect.left() + _ROW_INSET_X + _PAD_X
        right = rect.right() - _ROW_INSET_X - _PAD_X
        lead_w = self._s(_LEAD_W)
        text_left = left + lead_w + self._s(_LEAD_GAP)
        hint_w = self._s(_HINT_W) if self._show_shortcuts else 0
        reserve = self._reserve_width if row == self._reserve_row else 0
        text_right = right - max(hint_w + (self._s(8) if hint_w else 0), reserve)

        # ---- 垂直分区 ----
        block_h = self._block_height(item)
        top = rect.top() + (rect.height() - block_h) // 2
        title_rect = QRect(text_left, top, max(0, text_right - text_left), self._title_h)
        meta_top = top + self._title_h + 4

        # ---- 左侧图形 ----
        self._paint_leading(painter, item, QRect(left, rect.top(), lead_w, rect.height()))

        # Pin stays in the title slot even while the trailing action buttons are visible.
        if item.is_pinned:
            pin_size = self._s(14)
            label = _tr("Pinned")
            pin_width = pin_size + 5 + self._metrics["chip"].horizontalAdvance(label)
            painter.setPen(readable_accent(pal.accent, background))
            painter.setFont(self._fonts["chip"])
            painter.drawPixmap(text_left, top + (self._title_h - pin_size) // 2,
                               svg_pixmap("fluent_icons/Pin.svg", pin_size, painter.pen().color().name()))
            painter.drawText(QRect(text_left + pin_size + 5, top, pin_width - pin_size - 5, self._title_h),
                             Qt.AlignmentFlag.AlignVCenter, label)
            title_rect.setLeft(text_left + pin_width + self._s(10))

        # ---- 标题 ----
        painter.setFont(self._fonts["title"])
        painter.setPen(pal.text)
        title = self._metrics["title"].elidedText(item.display_text, Qt.TextElideMode.ElideRight, title_rect.width())
        painter.drawText(title_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, title)

        # ---- 元数据行：来源 · 时间 · 标签 ----
        if self._show_metadata:
            self._paint_meta(painter, item, text_left, text_right, meta_top)
        if item.tags:
            tag_top = meta_top + self._meta_h + 6 if self._show_metadata else top + self._title_h + 6
            self._paint_tags(painter, item.tags, text_left, text_right, tag_top, background)

        # ---- 右侧：直选按键 / 置顶标记（悬停时让位给快捷按钮） ----
        if not reserve:
            if self._show_shortcuts and row < len(SHORTCUT_KEYS):
                painter.setFont(self._fonts["hint"])
                painter.setPen(pal.text_tertiary)
                hint_rect = QRect(right - hint_w, top, hint_w, self._title_h)
                painter.drawText(hint_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, SHORTCUT_KEYS[row])

        painter.restore()

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        item: ClipboardItem = index.data(ROLE_ITEM_DATA)
        height = (self._block_height(item) if item else self._title_h) + self._pad_y() * 2
        if item and item.content_type == "image" and item.thumbnail:
            height = max(height, self._s(_THUMB) + self._s(10))
        width = option.rect.width() if option.rect.width() > 0 else 300
        return QSize(width, height)

    # ========== 左侧图形 ==========

    def _paint_leading(self, painter: QPainter, item: ClipboardItem, column: QRect):
        pal = self._palette
        if item.content_type == "image" and item.thumbnail:
            size = self._s(_THUMB)
            tile = self._thumbnail_tile(item.thumbnail, size)
            if tile is not None:
                x = column.left() + (column.width() - size) // 2
                y = column.top() + (column.height() - size) // 2
                painter.drawPixmap(x, y, tile)
                return

        size = self._s(_ICON)
        pixmap: Optional[QPixmap] = None
        if item.content_type == "file":
            paths = file_paths_of(item)
            if paths:
                pixmap = self._system_icon(paths[0], size)
            if pixmap is None:
                pixmap = svg_pixmap("fluent_icons/Folder.svg", self._s(20), pal.text_secondary.name())
        else:
            if item.source_app:
                pixmap = self._system_icon(item.source_app, size)
            if pixmap is None:
                glyph = "fluent_icons/Camera.svg" if item.content_type == "image" else "fluent_icons/Document.svg"
                pixmap = svg_pixmap(glyph, self._s(20), pal.text_tertiary.name())
        logical_size = pixmap.deviceIndependentSize().toSize()
        x = column.left() + (column.width() - logical_size.width()) // 2
        y = column.top() + (column.height() - logical_size.height()) // 2
        painter.drawPixmap(x, y, pixmap)

    @classmethod
    def _system_icon(cls, path: str, size: int) -> Optional[QPixmap]:
        """exe / 文件的系统图标，从 2 倍尺寸平滑缩到 size，缓存结果。"""
        key = (path, size)
        cached = cls._icon_cache.get(key, _ICON_MISSING)
        if cached is not _ICON_MISSING:
            cls._icon_cache.move_to_end(key)
            return cached
        pixmap: Optional[QPixmap] = None
        try:
            info = QFileInfo(path)
            if info.exists():
                icon: QIcon = QFileIconProvider().icon(info)
                if not icon.isNull():
                    source = icon.pixmap(QSize(size * 2, size * 2))
                    if not source.isNull():
                        pixmap = source.scaled(
                            size * 2, size * 2,
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation,
                        )
                        pixmap.setDevicePixelRatio(2.0)
        except Exception:
            pixmap = None
        if len(cls._icon_cache) >= cls._ICON_CACHE_MAX:
            cls._icon_cache.popitem(last=False)
        cls._icon_cache[key] = pixmap
        return pixmap

    # 兼容旧调用名
    @classmethod
    def _get_app_icon(cls, source_app: str) -> Optional[QPixmap]:
        return cls._system_icon(source_app, 24) if source_app else None

    def _decode_thumbnail(self, data_url: str) -> Optional[QPixmap]:
        if data_url in self._thumb_cache:
            return self._thumb_cache[data_url]
        pixmap: Optional[QPixmap] = None
        try:
            if data_url.startswith("data:image"):
                _, data = data_url.split(",", 1)
                candidate = QPixmap()
                if candidate.loadFromData(base64.b64decode(data)):
                    pixmap = candidate
        except Exception as e:
            log_error(T("加载缩略图失败: {e}", e=e), "Clipboard")
        if len(self._thumb_cache) >= self._THUMB_CACHE_MAX:
            for key in list(self._thumb_cache.keys())[: self._THUMB_CACHE_MAX // 2]:
                self._thumb_cache.pop(key, None)
        self._thumb_cache[data_url] = pixmap
        return pixmap

    def _thumbnail_tile(self, data_url: str, size: int) -> Optional[QPixmap]:
        """缩略图裁成居中方块（等比铺满），圆角 + 细描边，按显示尺寸缓存。"""
        key = (data_url, size)
        tile = self._tile_cache.get(key)
        if tile is not None:
            self._tile_cache.move_to_end(key)
            return tile
        source = self._decode_thumbnail(data_url)
        if source is None or source.isNull():
            return None
        scaled = source.scaled(
            size, size,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        tile = QPixmap(size, size)
        tile.fill(Qt.GlobalColor.transparent)
        p = QPainter(tile)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        radius = max(4, round(size * 0.17))
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(0, 0, size, size), radius, radius)
        p.setClipPath(clip)
        p.drawPixmap((size - scaled.width()) // 2, (size - scaled.height()) // 2, scaled)
        p.setClipping(False)
        edge = QColor(255, 255, 255, 40) if self._palette and self._palette.dark else QColor(0, 0, 0, 26)
        p.setPen(QPen(edge, 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(0.5, 0.5, size - 1, size - 1), radius - 0.5, radius - 0.5)
        p.end()
        if len(self._tile_cache) >= self._TILE_CACHE_MAX:
            self._tile_cache.popitem(last=False)
        self._tile_cache[key] = tile
        return tile

    # ========== 元数据行 ==========

    def _paint_meta(self, painter: QPainter, item: ClipboardItem, left: int, right: int, top: int):
        pal = self._palette
        fm = self._metrics["meta"]
        painter.setFont(self._fonts["meta"])
        baseline = top + (self._meta_h + fm.ascent() - fm.descent()) // 2
        x = left

        def draw(text: str, color: QColor) -> bool:
            nonlocal x
            if not text:
                return True
            room = right - x
            if room <= fm.horizontalAdvance("…"):
                return False
            shown = fm.elidedText(text, Qt.TextElideMode.ElideRight, room)
            painter.setPen(color)
            painter.drawText(x, baseline, shown)
            x += fm.horizontalAdvance(shown)
            return shown == text

        name = source_app_display_name(item.source_app)
        source = _tr("Source: {name}").format(name=name) if name else _tr("Unknown source")
        if item.content_type == "image":
            from ...core.image_text import INDEX_LABELS
            source = _tr(INDEX_LABELS.get(item.ocr_status, INDEX_LABELS["pending"])) + "  ·  " + source
        when = format_relative_time(item.created_at)
        suffix = f"  ·  {when}" if when else ""
        room = max(0, right - left - fm.horizontalAdvance(suffix))
        background = pal.accent_soft if item.is_pinned else pal.tint
        ink = readable_accent(pal.text_secondary, background)
        draw(fm.elidedText(source, Qt.TextElideMode.ElideRight, room), ink)
        draw(suffix, ink)

    def _tag_layout(self, tags, width):
        """Reserve the overflow count before laying out labels, including at narrow widths."""
        fm = self._metrics["chip"]
        gap, padding = 6, 16
        result = []
        remaining = width
        for i, tag in enumerate(tags[:_TAG_MAX]):
            count = len(tags) - i - 1
            reserve = fm.horizontalAdvance(f"+{count}") + padding + gap if count else 0
            available = min(self._s(145), remaining - reserve)
            if available < fm.horizontalAdvance("…") + padding:
                break
            label = fm.elidedText(tag.name, Qt.TextElideMode.ElideRight, available - padding)
            size = fm.horizontalAdvance(label) + padding
            result.append((label, size, tag.chip_color))
            remaining -= size + gap
        hidden = len(tags) - len(result)
        if hidden:
            label = f"+{hidden}"
            size = fm.horizontalAdvance(label) + padding
            if size <= remaining:
                result.append((label, size, None))
        return result

    def _paint_tags(self, painter, tags, left, right, top, background):
        painter.setFont(self._fonts["chip"])
        for label, width, color in self._tag_layout(tags, right - left):
            fill, ink = tag_chip_palette(color or self._palette.text_secondary.name(), background)
            box = QRectF(left, top, width, self._chip_h)
            edge = QColor(ink)
            edge.setAlphaF(.45)
            painter.setPen(QPen(edge, 1))
            painter.setBrush(fill)
            painter.drawRoundedRect(box, 8, 8)
            painter.setPen(ink)
            painter.drawText(box, Qt.AlignmentFlag.AlignCenter, label)
            left += width + 6


__all__ = [
    "ClipboardItemDelegate",
    "ROLE_ITEM_DATA",
    "ROLE_ITEM_ID",
    "SHORTCUT_KEYS",
    "UI_FAMILIES",
    "file_paths_of",
    "format_relative_time",
]
