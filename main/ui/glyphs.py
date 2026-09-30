# -*- coding: utf-8 -*-
"""Pixel-exact UI glyphs: tinted SVG icons and a few hand-drawn strokes.

Rendering an icon large and letting Qt shrink it on paint is what makes small
icons look soft.  Everything here is rasterised at the exact pixel size it will
be drawn at (Qt's own high-DPI scaling is disabled in this app, so 1 px here is
1 physical px on screen).
"""

from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap


def _blank(size: int) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    return pixmap


@lru_cache(maxsize=256)
def svg_pixmap(name: str, size: int, color: str) -> QPixmap:
    """`svg/<name>` rendered at size×size and tinted to `color` (any QColor string)."""
    from ui.outline_icons import outline_icon

    outlines = {
        "fluent_icons/Pin.svg": "pin", "fluent_icons/Filter.svg": "filter",
        "fluent_icons/Folder.svg": "folder", "fluent_icons/Document.svg": "file",
        "fluent_icons/Camera.svg": "image", "fluent_icons/Delete.svg": "trash",
        "fluent_icons/Edit.svg": "edit", "fluent_icons/Setting.svg": "settings",
    }
    if name in outlines:
        return outline_icon(outlines[name], color).pixmap(size, size)
    from core.resource_manager import ResourceManager

    source = ResourceManager.get_icon_by_name(name, size).pixmap(size, size)
    if source.isNull():
        return _blank(size)
    tinted = _blank(size)
    painter = QPainter(tinted)
    painter.drawPixmap(0, 0, source)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(tinted.rect(), QColor(color))
    painter.end()
    return tinted


def svg_icon(name: str, size: int, color: str) -> QIcon:
    return QIcon(svg_pixmap(name, size, color))


@lru_cache(maxsize=256)
def glyph_pixmap(kind: str, size: int, color: str, stroke: float = 1.5) -> QPixmap:
    """Simple line glyphs drawn with round caps: close, plus, more, check, chevron."""
    from ui.outline_icons import outline_icon
    name = {"magnifier": "search", "chevron_down": "chevron-down"}.get(kind, kind)
    if name in {"search", "chevron-down", "close", "plus", "more", "check", "clipboard", "copy"}:
        return outline_icon(name, color).pixmap(size, size)
    pixmap = _blank(size)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    pen = QPen(QColor(color), stroke)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    s = float(size)
    if kind == "close":
        m = s * 0.3
        painter.drawLine(QPointF(m, m), QPointF(s - m, s - m))
        painter.drawLine(QPointF(s - m, m), QPointF(m, s - m))
    elif kind == "plus":
        m = s * 0.25
        painter.drawLine(QPointF(s / 2, m), QPointF(s / 2, s - m))
        painter.drawLine(QPointF(m, s / 2), QPointF(s - m, s / 2))
    elif kind == "more":
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(color))
        r = max(1.2, s * 0.085)
        for fx in (0.27, 0.5, 0.73):
            painter.drawEllipse(QPointF(s * fx, s / 2), r, r)
    elif kind == "check":
        path = QPainterPath(QPointF(s * 0.24, s * 0.53))
        path.lineTo(QPointF(s * 0.42, s * 0.70))
        path.lineTo(QPointF(s * 0.77, s * 0.32))
        painter.drawPath(path)
    elif kind == "chevron_down":
        path = QPainterPath(QPointF(s * 0.3, s * 0.42))
        path.lineTo(QPointF(s * 0.5, s * 0.62))
        path.lineTo(QPointF(s * 0.7, s * 0.42))
        painter.drawPath(path)
    elif kind == "clipboard":
        # empty-state illustration: board + clip + text lines
        board = QRectF(s * 0.22, s * 0.17, s * 0.56, s * 0.7)
        painter.drawRoundedRect(board, s * 0.1, s * 0.1)
        clip = QRectF(s * 0.37, s * 0.1, s * 0.26, s * 0.13)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(clip, s * 0.05, s * 0.05)
        for i, frac in enumerate((0.36, 0.5, 0.64)):
            right = 0.66 if i < 2 else 0.54
            painter.drawLine(QPointF(s * 0.34, s * frac + s * 0.04), QPointF(s * right, s * frac + s * 0.04))
    elif kind == "magnifier":
        r = s * 0.28
        c = QPointF(s * 0.44, s * 0.44)
        painter.drawEllipse(c, r, r)
        painter.drawLine(QPointF(s * 0.64, s * 0.64), QPointF(s * 0.8, s * 0.8))
    elif kind == "copy":
        # 两张错开的圆角纸：后一张只露出 L 形边
        back = QPainterPath()
        back.moveTo(QPointF(s * 0.30, s * 0.72))
        back.lineTo(QPointF(s * 0.26, s * 0.72))
        back.quadTo(QPointF(s * 0.16, s * 0.72), QPointF(s * 0.16, s * 0.62))
        back.lineTo(QPointF(s * 0.16, s * 0.26))
        back.quadTo(QPointF(s * 0.16, s * 0.16), QPointF(s * 0.26, s * 0.16))
        back.lineTo(QPointF(s * 0.58, s * 0.16))
        back.quadTo(QPointF(s * 0.68, s * 0.16), QPointF(s * 0.68, s * 0.26))
        back.lineTo(QPointF(s * 0.68, s * 0.30))
        painter.drawPath(back)
        painter.drawRoundedRect(QRectF(s * 0.34, s * 0.34, s * 0.5, s * 0.5), s * 0.1, s * 0.1)
    painter.end()
    return pixmap


def glyph_icon(kind: str, size: int, color: str, stroke: float = 1.5) -> QIcon:
    return QIcon(glyph_pixmap(kind, size, color, stroke))


__all__ = ["glyph_icon", "glyph_pixmap", "svg_icon", "svg_pixmap"]
