"""截图来源信息 / 时间 / 备注（TF-0040）。

只有用户显式勾选并保留的内容才会随导出分享：默认全关，不自动把窗口标题写进
文件名或图片，也不动剪贴板自己的来源字段。来源窗口探测是尽力而为：取不到进程、
窗口已消失、权限不足或命中的是本工具自身时一律回退成"没有来源"，绝不猜。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter

from core.number_legend import wrap_caption

DEFAULT_MARGIN = 14
DEFAULT_FONT_SIZE = 13
MAX_TEXT_CHARS = 200

_LABEL_SOURCE = "来源"
_LABEL_TIME = "时间"
_LABEL_NOTE = "备注"


@dataclass(frozen=True)
class CaptureMetadata:
    source_enabled: bool = False
    time_enabled: bool = False
    note_enabled: bool = False
    source: str = ""
    note: str = ""
    captured_at: str = ""

    def sanitized(self) -> "CaptureMetadata":
        return replace(
            self,
            source=str(self.source or "").strip()[:MAX_TEXT_CHARS],
            note=str(self.note or "").strip()[:MAX_TEXT_CHARS],
            captured_at=str(self.captured_at or "").strip()[:64],
        )

    def is_empty(self) -> bool:
        return not self.build_lines()

    def build_lines(self) -> list:
        """返回真正会被导出的行；没勾选或内容为空的部分不出现。"""
        meta = self.sanitized()
        lines = []
        if meta.source_enabled and meta.source:
            lines.append(f"{_LABEL_SOURCE}: {meta.source}")
        if meta.time_enabled and meta.captured_at:
            lines.append(f"{_LABEL_TIME}: {meta.captured_at}")
        if meta.note_enabled and meta.note:
            lines.append(f"{_LABEL_NOTE}: {meta.note}")
        return lines


def now_stamp(moment: datetime = None) -> str:
    moment = moment or datetime.now()
    return moment.strftime("%Y-%m-%d %H:%M:%S")


def describe_source_window(x=None, y=None, own_pid=None) -> dict:
    """尽力描述光标/选区所在的来源窗口；失败或命中自身时返回空 dict。"""
    import os

    own = os.getpid() if own_pid is None else own_pid
    try:
        from capture.window_finder import WINDOWS_API_AVAILABLE, WindowFinder

        if not WINDOWS_API_AVAILABLE:
            return {}
        finder = WindowFinder()
        if x is None or y is None:
            from PySide6.QtGui import QCursor

            point = QCursor.pos()
            x, y = point.x(), point.y()
        info = finder.find_window_at_point_info(int(x), int(y))
    except Exception:
        return {}
    if not info:
        return {}
    handle = info[0]
    title = info[2] if len(info) > 2 else ""
    pid = None
    try:
        import win32process

        _thread_id, pid = win32process.GetWindowThreadProcessId(handle)
    except Exception:
        pid = None
    if pid is not None and int(pid) == int(own):
        return {}
    app = ""
    if pid:
        try:
            import win32api
            import win32process

            process = win32api.OpenProcess(0x1000, False, int(pid))
            try:
                path = win32process.GetModuleFileNameEx(process, 0)
            finally:
                win32api.CloseHandle(process)
            app = str(path).rsplit("\\", 1)[-1]
        except Exception:
            app = ""
    name = " - ".join(part for part in (app, str(title or "").strip()) if part)
    return {"source": name} if name else {}


def options_from_mapping(raw) -> CaptureMetadata:
    data = raw if isinstance(raw, dict) else {}
    return CaptureMetadata(
        source_enabled=bool(data.get("source_enabled", False)),
        time_enabled=bool(data.get("time_enabled", False)),
        note_enabled=bool(data.get("note_enabled", False)),
        source=data.get("source", ""),
        note=data.get("note", ""),
        captured_at=data.get("captured_at", ""),
    ).sanitized()


def load_metadata(manager=None) -> CaptureMetadata:
    if manager is None:
        try:
            from settings import get_tool_settings_manager

            manager = get_tool_settings_manager()
        except Exception:
            manager = None
    if manager is None:
        return CaptureMetadata()
    keys = {
        "source_enabled": ("capture_meta_source_enabled", False),
        "time_enabled": ("capture_meta_time_enabled", False),
        "note_enabled": ("capture_meta_note_enabled", False),
        "source": ("capture_meta_source", ""),
        "note": ("capture_meta_note", ""),
        "captured_at": ("capture_meta_time", ""),
    }
    data = {}
    for field, (key, default) in keys.items():
        try:
            data[field] = manager.get_app_setting(key, default)
        except Exception:
            data[field] = default
    return options_from_mapping(data)


def save_metadata(manager, metadata) -> bool:
    """保存用户确认后的元信息（取消时调用方不要调用这里）。"""
    if manager is None:
        return False
    meta = metadata.sanitized()
    values = {
        "capture_meta_source_enabled": bool(meta.source_enabled),
        "capture_meta_time_enabled": bool(meta.time_enabled),
        "capture_meta_note_enabled": bool(meta.note_enabled),
        "capture_meta_source": meta.source,
        "capture_meta_note": meta.note,
        "capture_meta_time": meta.captured_at,
    }
    try:
        for key, value in values.items():
            manager.set_app_setting(key, value)
    except Exception:
        return False
    return True


def _font(size: int) -> QFont:
    font = QFont()
    font.setPointSize(max(6, int(size)))
    return font


def render_strip(image: QImage, lines, *, font_size: int = DEFAULT_FONT_SIZE, margin: int = DEFAULT_MARGIN) -> QImage:
    """把元信息排成成图下方的信息条；没有内容或空图时原样返回。"""
    if image is None or image.isNull() or not lines:
        return image
    text_lines = []
    metrics = QFontMetricsF(_font(font_size))
    max_width = max(32.0, image.width() - margin * 2.0)
    for line in lines:
        text_lines.extend(wrap_caption(line, metrics, max_width))
    line_h = metrics.height()
    height = margin * 2 + len(text_lines) * line_h
    out = QImage(image.width(), image.height() + int(height), QImage.Format.Format_ARGB32_Premultiplied)
    out.fill(QColor("#FFFFFF"))
    painter = QPainter(out)
    try:
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        painter.drawImage(0, 0, image)
        painter.setFont(_font(font_size))
        painter.setPen(QColor("#202020"))
        y = image.height() + margin
        for line in text_lines:
            painter.drawText(QRectF(margin, y, max_width, line_h), int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), line)
            y += line_h
    finally:
        painter.end()
    return out
