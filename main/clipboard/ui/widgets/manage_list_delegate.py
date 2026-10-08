"""Compact management rows with separate icon and text slots."""
from PySide6.QtCore import QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPen
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem

from ui.fluent_lite.theme import CONTROL_RADIUS, ui_tokens
from ..layout_scale import scale_ui


GROUP_LABEL_ROLE = Qt.ItemDataRole.UserRole + 1
PREVIEW_ROLE = Qt.ItemDataRole.UserRole + 2


class ManageListDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index):
        return QSize(0, scale_ui(60 if index.data(PREVIEW_ROLE) is not None else 40))

    def paint(self, painter, option, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        tokens = ui_tokens(self.parent())
        selected = bool(opt.state & QStyle.StateFlag.State_Selected)
        hovered = bool(opt.state & QStyle.StateFlag.State_MouseOver)
        rect = opt.rect.adjusted(scale_ui(6), scale_ui(2), -scale_ui(6), -scale_ui(2))
        painter.save()
        painter.setRenderHint(painter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        if selected or hovered:
            painter.setBrush(QColor(tokens.accent_soft if selected else tokens.surface_hover))
            painter.drawRoundedRect(QRectF(rect), scale_ui(CONTROL_RADIUS), scale_ui(CONTROL_RADIUS))
        if selected and opt.state & QStyle.StateFlag.State_HasFocus:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(tokens.ring), 1))
            painter.drawRoundedRect(QRectF(rect).adjusted(.5, .5, -.5, -.5), scale_ui(CONTROL_RADIUS), scale_ui(CONTROL_RADIUS))
        side = scale_ui(18)
        icon_rect = QRect(rect.x() + scale_ui(10), rect.y() + (rect.height() - side) // 2, side, side)
        text_rect = rect.adjusted(scale_ui(10) + side + scale_ui(8), 0, -scale_ui(10), 0)
        icon_rect = QStyle.visualRect(opt.direction, rect, icon_rect)
        text_rect = QStyle.visualRect(opt.direction, rect, text_rect)
        group_label = index.data(GROUP_LABEL_ROLE)
        text = opt.text
        if group_label:
            glyph, text = group_label
            font = QFont(opt.font)
            font.setPixelSize(scale_ui(16))
            painter.setFont(font)
            painter.setPen(QColor(tokens.text))
            painter.drawText(icon_rect, Qt.AlignmentFlag.AlignCenter, glyph)
        elif not opt.icon.isNull():
            opt.icon.paint(painter, icon_rect, Qt.AlignmentFlag.AlignCenter, QIcon.Mode.Normal)
        font = QFont(opt.font)
        font.setWeight(QFont.Weight.Normal)
        font.setPixelSize(scale_ui(14))
        preview = index.data(PREVIEW_ROLE)
        if preview is not None:
            text_rect.setTop(rect.top() + scale_ui(7))
            text_rect.setHeight(scale_ui(22))
        painter.setFont(font)
        painter.setPen(QColor(tokens.text))
        text = painter.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, text_rect.width())
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeading, text)
        if preview is not None:
            font.setPixelSize(scale_ui(12))
            painter.setFont(font)
            painter.setPen(QColor(tokens.text_muted))
            preview_rect = text_rect.translated(0, scale_ui(22))
            preview_text = painter.fontMetrics().elidedText(preview, Qt.TextElideMode.ElideRight, preview_rect.width())
            painter.drawText(preview_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeading, preview_text)
        painter.restore()
