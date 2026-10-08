"""Shared icon/text geometry for native buttons and sidebar rows."""
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QIcon, QPalette
from PySide6.QtWidgets import QStyle

from core.ui_scale import widget_scaled


def icon_text_rects(bounds, icon_size, text_width, gap, direction, *, centered=True):
    """Lay out one label as a unit; the gap scales rather than using Qt's 4px."""
    width = min(max(0, text_width), max(0, bounds.width() - icon_size.width() - gap))
    total = icon_size.width() + gap + width
    x = bounds.x() + (max(0, bounds.width() - total) // 2 if centered else 0)
    icon = QRect(x, bounds.y() + (bounds.height() - icon_size.height()) // 2,
                 icon_size.width(), icon_size.height())
    text = QRect(x + icon.width() + gap, bounds.y(), width, bounds.height())
    return (QStyle.visualRect(direction, bounds, icon),
            QStyle.visualRect(direction, bounds, text))


def draw_button_label(widget, painter, option, *, centered=True):
    """Keep native icon states, mnemonics and RTL, with a deliberate 8px gap."""
    style = widget.style()
    if option.icon.isNull() or not option.text:
        style.drawControl(QStyle.ControlElement.CE_PushButtonLabel, option, painter, widget)
        return
    bounds = style.subElementRect(QStyle.SubElement.SE_PushButtonContents, option, widget)
    metrics = painter.fontMetrics()
    flags = Qt.TextFlag.TextShowMnemonic
    width = metrics.size(flags, option.text).width()
    icon_rect, text_rect = icon_text_rects(
        bounds, option.iconSize, width, widget_scaled(widget, 8),
        option.direction, centered=centered,
    )
    enabled = bool(option.state & QStyle.StateFlag.State_Enabled)
    mode = QIcon.Mode.Normal if enabled else QIcon.Mode.Disabled
    state = QIcon.State.On if option.state & QStyle.StateFlag.State_On else QIcon.State.Off
    option.icon.paint(painter, icon_rect, Qt.AlignmentFlag.AlignCenter, mode, state)
    if not style.styleHint(QStyle.StyleHint.SH_UnderlineShortcut, option, widget):
        flags |= Qt.TextFlag.TextHideMnemonic
    text = metrics.elidedText(option.text, Qt.TextElideMode.ElideRight, text_rect.width(), flags)
    style.drawItemText(painter, text_rect, Qt.AlignmentFlag.AlignCenter | flags,
                       option.palette, enabled, text, QPalette.ColorRole.ButtonText)
