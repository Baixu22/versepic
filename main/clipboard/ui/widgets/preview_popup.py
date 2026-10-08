# -*- coding: utf-8 -*-
"""
剪贴板悬停预览弹窗

提供 HTML 富文本和图片的悬停预览功能。
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QApplication
)
from PySide6.QtCore import Qt, QPoint, QTimer
from PySide6.QtGui import QPixmap

from core.logger import T, log_exception
from core.i18n import make_tr
from ui.fluent_lite import TextEdit
from typing import TYPE_CHECKING

_tr = make_tr("ClipboardPreview")

if TYPE_CHECKING:
    from ...core import ClipboardManager, ClipboardItem


class PreviewPopup(QWidget):
    """悬停预览弹窗 - 支持 HTML 富文本和图片预览"""
    
    _instance = None  # 单例，避免多个弹窗
    
    @classmethod
    def instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def __init__(self):
        super().__init__(None)
        # 无边框 + 工具窗口 + 置顶
        self.setWindowFlags(
            Qt.WindowType.ToolTip |
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

        # 颜色不再写死浅色：预览弹窗是独立顶层窗口，拿不到父窗口的样式，
        # 之前固定 #FAFAFA/#333，深色主题下会弹出一块刺眼的白底黑字。
        # 这里按当前剪贴板主题取色，并订阅主题变化。
        self._setup_ui()
        from ..theme.themes import get_theme_manager

        self._theme_manager = get_theme_manager()
        self._theme_manager.theme_changed.connect(self._apply_theme)
        self._apply_theme()

        self._manager = None
        self._current_item_id = None
        # 预览是无父窗口的独立顶层窗口。剪贴板窗口隐藏后，队列中仍可能有
        # 方向键或悬停事件到达，因此不能只依赖关闭时调用一次 hide()。
        self._display_enabled = False
        
        # 延迟显示定时器
        self._show_timer = QTimer()
        self._show_timer.setSingleShot(True)
        self._show_timer.timeout.connect(self._do_show)
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.setInterval(350)
        self._hide_timer.timeout.connect(self.hide_preview)
        self._pending_item = None
        self._pending_pos = None
        self._pending_prefer_side = "auto"
        self._pending_avoid_rect = None
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        
        # 来源、时间及标签，所有类型共用。
        self.title_label = QLabel()
        self.title_label.setTextFormat(Qt.TextFormat.PlainText)
        self.title_label.setWordWrap(True)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.title_label.hide()  # 默认隐藏
        layout.addWidget(self.title_label)
        
        # 内容区域 - 使用 QTextEdit 支持富文本
        self.content_widget = TextEdit(use_default_style=False)
        self.content_widget.setReadOnly(True)
        # 启用自动换行
        self.content_widget.setLineWrapMode(TextEdit.LineWrapMode.WidgetWidth)
        # 长内容可滚动阅读，避免被高度上限静默裁掉。
        self.content_widget.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.content_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # 外观（底色/描边/文字色）统一由 _apply_theme 里的预览样式给，
        # 这里不再挂一份写死颜色的样式表，否则深浅切换时它会盖住主题。
        # 设置文档边距为0，减少额外空间
        self.content_widget.document().setDocumentMargin(2)
        # 只设置最大尺寸，让内容自适应
        self.content_widget.setMaximumSize(680, 540)
        layout.addWidget(self.content_widget)
        
        # 图片预览（默认隐藏）
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.hide()
        layout.addWidget(self.image_label)

    def _apply_theme(self, _theme=None):
        """Re-tint the popup from the active clipboard theme.

        The popup is a top-level tool window, so it cannot inherit the
        clipboard window's stylesheet and must resolve its own colours.
        """
        from ..theme.theme_styles import ThemeStyleGenerator, rgba, surface_palette
        from dataclasses import replace
        from core.ui_theme import DARK_TOKENS, LIGHT_TOKENS
        from ui.fluent_lite.theme import scrollbar_qss

        theme = self._theme_manager.get_current_theme()
        palette = surface_palette(theme)
        colors = theme.colors
        self._ui_theme_tokens_override = replace(
            DARK_TOKENS if palette.dark else LIGHT_TOKENS,
            accent=palette.accent_text.name(), border_hover=palette.text_secondary.name())
        generator = ThemeStyleGenerator(theme)
        # objectName 要先设好，下面的选择器才能命中图片预览框。
        self.image_label.setObjectName("previewImage")
        # 外框 + 文本区沿用生成器里那一份，避免和剪贴板窗口内的预览样式漂移。
        self.setStyleSheet(
            generator.generate_preview_popup_style()
            + scrollbar_qss(self) + f"""
            QLabel {{
                background: transparent;
                color: {colors.text_secondary};
                font-size: 13px;
                font-weight: 400;
                padding-left: 4px;
            }}
            QLabel#previewImage {{
                background: {rgba(palette.control)};
                border: 1px solid {rgba(palette.hairline)};
                border-radius: 4px;
            }}
        """
        )
    
    def set_manager(self, manager: 'ClipboardManager'):
        """设置剪贴板管理器（用于加载图片）"""
        self._manager = manager

    def set_display_enabled(self, enabled: bool):
        """设置当前是否允许显示预览。禁用时同时清理已有及待显示内容。"""
        self._display_enabled = bool(enabled)
        if not self._display_enabled:
            self.force_cleanup()
    
    def show_preview(self, item: 'ClipboardItem', pos: QPoint, delay_ms: int = 5, prefer_side: str = "auto", avoid_rect=None):
        """
        显示预览（带延迟）
        
        Args:
            item: 剪贴板项
            pos: 显示位置
            delay_ms: 延迟毫秒数，0 表示立即显示
            prefer_side: 预览优先显示方向（"left" | "right" | "auto"）
            avoid_rect: 需要避开的矩形区域（通常为主窗口矩形）
        """
        if not self._display_enabled:
            return

        self._hide_timer.stop()

        if not item:
            self.hide_preview()
            return
        
        # 如果是同一个项目且已显示，忽略
        if self._current_item_id == item.id and self.isVisible():
            return
        
        self._pending_item = item
        self._pending_pos = pos
        self._pending_prefer_side = prefer_side
        self._pending_avoid_rect = avoid_rect
        
        if delay_ms > 0:
            self._show_timer.start(delay_ms)
        else:
            self._do_show()
    
    def _do_show(self):
        """实际执行显示"""
        # 定时器触发前窗口可能已经隐藏。这里再次检查，避免旧的延迟任务
        # 在关闭清理完成后把独立的预览窗口重新显示出来。
        if not self._display_enabled:
            self.force_cleanup()
            return

        item = self._pending_item
        pos = self._pending_pos
        
        if not item:
            return
        
        self._current_item_id = item.id
        
        # 根据内容类型显示不同预览
        if item.content_type == "image":
            self._show_image_preview(item)
        elif item.content_type == "file":
            self._show_file_preview(item)
        elif item.content_type == "text":
            # 文本类型也显示预览
            self._show_text_preview(item)
        else:
            # 其他类型不显示预览
            return

        from .item_delegate import source_app_display_name, _tr as row_tr
        name = source_app_display_name(getattr(item, "source_app", None))
        source = row_tr("Source: {name}").format(name=name) if name else row_tr("Unknown source")
        when = item.created_at.strftime("%Y-%m-%d %H:%M") if item.created_at else ""
        tags = "  ".join("#" + tag.name for tag in (getattr(item, "tags", None) or []))
        metadata = source + ("  ·  " + when if when else "") + ("\n" + tags if tags else "")
        self.title_label.setText(metadata)
        self.title_label.setToolTip(metadata)
        self.title_label.setFixedWidth(max(240, self.image_label.width() if item.content_type == "image"
                                           else self.content_widget.width()))
        self.title_label.setMaximumHeight(100)
        self.title_label.show()
        
        # 调整位置（在触发位置右侧显示）
        self.adjustSize()

        screen = QApplication.screenAt(pos) or QApplication.primaryScreen()
        screen_geo = screen.availableGeometry() if screen else QApplication.primaryScreen().availableGeometry()

        gap = 10
        x = pos.x() + 20
        y = pos.y()

        avoid_rect = self._pending_avoid_rect
        prefer_side = self._pending_prefer_side or "auto"

        if avoid_rect is not None:
            left_space = avoid_rect.left() - screen_geo.left()
            right_space = screen_geo.right() - avoid_rect.right()

            def place_left():
                return avoid_rect.left() - self.width() - gap

            def place_right():
                return avoid_rect.right() + gap

            if prefer_side == "left":
                if left_space >= self.width() + gap:
                    x = place_left()
                elif right_space >= self.width() + gap:
                    x = place_right()
                else:
                    x = place_right() if right_space >= left_space else place_left()
            elif prefer_side == "right":
                if right_space >= self.width() + gap:
                    x = place_right()
                elif left_space >= self.width() + gap:
                    x = place_left()
                else:
                    x = place_left() if left_space >= right_space else place_right()
            else:
                # auto: 优先右侧，不够再左侧
                if right_space >= self.width() + gap:
                    x = place_right()
                elif left_space >= self.width() + gap:
                    x = place_left()
                else:
                    x = place_right() if right_space >= left_space else place_left()

        # 确保不超出屏幕
        if x + self.width() > screen_geo.right():
            x = screen_geo.right() - self.width() - gap
        if x < screen_geo.left():
            x = screen_geo.left()
        if y + self.height() > screen_geo.bottom():
            y = screen_geo.bottom() - self.height() - gap
        if y < screen_geo.top():
            y = screen_geo.top()

        self.move(x, y)
        self.show()
        self.content_widget.verticalScrollBar().setValue(0)
    
    def _show_text_preview(self, item: 'ClipboardItem'):
        """显示纯文本预览 - 上面显示时间，下面显示完整内容"""
        # 显示时间标题
        if item.created_at:
            time_str = item.created_at.strftime("%Y-%m-%d %H:%M:%S")
            self.title_label.setText(time_str)
        else:
            self.title_label.setText(_tr("📝 文本"))
        self.title_label.show()
        
        # 显示完整内容（限制长度避免卡顿）
        content = item.content[:100000]
        if len(item.content) > 100000:
            content += "\n\n" + _tr("Preview shortened; copy the item for its full content.")
        
        # 先重置尺寸约束
        self.content_widget.setMinimumSize(0, 0)
        self.content_widget.setMaximumSize(680, 540)
        
        self.content_widget.setPlainText(content)
        
        # 根据内容调整大小
        self._adjust_content_size()
        
        self.content_widget.show()
        self.image_label.hide()
    
    def _show_file_preview(self, item: 'ClipboardItem'):
        """显示文件预览 - 文件名和完整路径"""
        import json
        import os
        from collections import defaultdict
        
        self.title_label.hide()  # 不显示标题
        self.image_label.hide()
        
        try:
            data = json.loads(item.content)
            files = data.get("files", [])
            
            if not files:
                self.content_widget.setPlainText("无文件信息")
                self.content_widget.show()
                return
            
            # 构建显示内容
            lines = []
            
            if len(files) == 1:
                # 单个文件
                filename = os.path.basename(files[0])
                lines.append(filename)
                lines.append("")
                lines.append(files[0])
            else:
                # 多个文件 - 按目录分组
                dir_files = defaultdict(list)
                for filepath in files:
                    dir_path = os.path.dirname(filepath)
                    filename = os.path.basename(filepath)
                    dir_files[dir_path].append(filename)
                
                if len(dir_files) == 1:
                    # 全部在同一目录
                    dir_path = list(dir_files.keys())[0]
                    filenames = dir_files[dir_path]
                    for fn in filenames:
                        lines.append(fn)
                    lines.append("")
                    lines.append(dir_path)
                else:
                    # 多个目录，按目录分组显示
                    group_num = 1
                    for dir_path, filenames in dir_files.items():
                        if len(filenames) == 1:
                            # 该目录只有一个文件
                            lines.append(f"[{group_num}] {filenames[0]}")
                            lines.append(os.path.join(dir_path, filenames[0]))
                        else:
                            # 该目录有多个文件
                            lines.append(f"[{group_num}]")
                            for fn in filenames:
                                lines.append(f"  {fn}")
                            lines.append(dir_path)
                        group_num += 1
                        lines.append("")  # 空行分隔
                    
                    # 移除最后的空行
                    if lines and lines[-1] == "":
                        lines.pop()
            
            text = "\n".join(lines)
            
            # 先重置尺寸约束
            self.content_widget.setMinimumSize(0, 0)
            self.content_widget.setMaximumSize(680, 540)
            
            self.content_widget.setPlainText(text)
            
            # 根据内容自适应大小
            self._adjust_content_size()
            self.content_widget.show()
            
        except Exception as e:
            log_exception(e, T("加载文本预览"))
            self.content_widget.setMinimumSize(0, 0)
            self.content_widget.setMaximumSize(680, 540)
            self.content_widget.setPlainText(item.content)
            self._adjust_content_size()
            self.content_widget.show()
    
    def _adjust_content_size(self):
        """根据内容调整 content_widget 大小 - 智能自适应宽度和高度"""
        self.content_widget.ensurePolished()
        doc = self.content_widget.document()
        
        # 获取字体度量
        font_metrics = self.content_widget.fontMetrics()
        line_height = font_metrics.height()
        
        # 获取纯文本内容
        text = doc.toPlainText()
        lines = text.split('\n')
        line_count = len(lines)
        
        # 计算最长行的宽度（不换行情况下的理想宽度）
        max_line_width = 0
        for line in lines:
            line_width = font_metrics.horizontalAdvance(line)
            max_line_width = max(max_line_width, line_width)
        
        # padding 计算：CSS padding 4px 上下 + 8px 左右 + 边框 2px + 文档边距 2px
        h_padding = 8 * 2 + 2 * 2 + 4  # 左右 padding + 边框 + 余量
        v_padding = 4 * 2 + 2 * 2 + 4  # 上下 padding + 边框 + 文档边距
        
        ideal_width = max_line_width + h_padding
        
        # 限制最大宽度
        max_width, max_height = self._preview_limits()
        min_width = min(420, max_width)
        
        if ideal_width <= max_width:
            # 内容不需要换行，使用理想宽度
            actual_width = max(ideal_width, min_width)
            # 不设置文档宽度限制，保持自然布局
            doc.setTextWidth(actual_width - h_padding)
            # 高度基于实际行数
            actual_height = line_count * line_height + v_padding
        else:
            # 内容需要换行，使用最大宽度
            actual_width = max_width
            # 设置文档宽度让其自动换行
            doc.setTextWidth(max_width - h_padding)
            # 重新获取文档高度（换行后）
            actual_height = int(doc.size().height()) + v_padding
        
        # 限制高度范围
        min_height = line_height + v_padding  # 至少能显示一行
        
        actual_height = min(actual_height, max_height)
        actual_height = max(actual_height, min_height)
        
        # 设置固定尺寸
        self.content_widget.setFixedSize(int(actual_width), int(actual_height))

    def _preview_limits(self):
        screen = QApplication.screenAt(self._pending_pos) if self._pending_pos is not None else None
        screen = screen or QApplication.primaryScreen()
        geometry = screen.availableGeometry()
        return min(680, max(200, geometry.width() - 48)), min(540, max(120, geometry.height() - 160))
    
    def _show_html_preview(self, item: 'ClipboardItem'):
        """显示 HTML 富文本预览"""
        self.title_label.setText(_tr("富文本预览"))
        html = item.html_content
        
        if html:
            # 限制大小，避免过大的 HTML 卡顿
            if len(html) > 50000:
                html = html[:50000] + "..."
            self.content_widget.setHtml(html)
        else:
            self.content_widget.setPlainText(item.content[:2000])
        self.content_widget.show()
        self.image_label.hide()
    
    def _show_image_preview(self, item: 'ClipboardItem'):
        """显示图片预览"""
        self.title_label.hide()  # 图片预览不显示标题
        self.content_widget.hide()
        
        # 尝试加载完整图片
        if self._manager and item.image_id:
            image_data = self._manager.get_image_data(item.image_id)
            if image_data:
                pixmap = QPixmap()
                pixmap.loadFromData(image_data)
                # 缩放到合适大小
                scaled = pixmap.scaled(
                    *self._preview_limits(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
                self.image_label.setPixmap(scaled)
                self.image_label.setFixedSize(scaled.size())
                self.image_label.show()
                return
        
        # Fallback: 使用缩略图
        if item.thumbnail:
            import base64
            try:
                if item.thumbnail.startswith("data:image"):
                    _, data = item.thumbnail.split(",", 1)
                    image_data = base64.b64decode(data)
                    pixmap = QPixmap()
                    pixmap.loadFromData(image_data)
                    scaled = pixmap.scaled(
                        *self._preview_limits(),
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation
                    )
                    self.image_label.setPixmap(scaled)
                    self.image_label.setFixedSize(scaled.size())
                    self.image_label.show()
            except Exception as e:
                log_exception(e, T("加载图片预览"))
    
    def hide_preview(self):
        """隐藏预览"""
        self._hide_timer.stop()
        self._show_timer.stop()
        self._pending_item = None
        self._pending_pos = None
        self._pending_prefer_side = "auto"
        self._pending_avoid_rect = None
        self._current_item_id = None
        self.hide()

    def schedule_hide(self):
        """Allow the pointer to cross the gap from the list into the scrollable preview."""
        self._show_timer.stop()
        self._hide_timer.start()

    def enterEvent(self, event):
        self._hide_timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.schedule_hide()
        super().leaveEvent(event)
    
    def force_cleanup(self):
        """强制清理 - 用于窗口关闭时确保预览完全停止"""
        self._hide_timer.stop()
        self._show_timer.stop()
        self._pending_item = None
        self._pending_pos = None
        self._pending_prefer_side = "auto"
        self._pending_avoid_rect = None
        self._current_item_id = None
        if self.isVisible():
            self.hide()


__all__ = ["PreviewPopup"]
 
