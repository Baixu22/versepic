# -*- coding: utf-8 -*-
"""设置页的导出水印分组（TF-0038）：开关、参数与实时预览。

预览和导出共用 core.watermark 的同一套渲染，所以设置页看到的位置与
透明度就是成图里的样子；默认关闭，打开前不改任何既有导出行为。
"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QLabel, QWidget

from core.ui_scale import dialog_scaled
from core.watermark import options_from_mapping, preview
from ui.fluent_lite import ComboBox, FluentIcon, LineEdit, PushButton, SettingCard, SpinBox, SwitchSettingCard


def _get(dialog, key, default):
    try:
        return dialog.config_manager.get_app_setting(key, default)
    except Exception:
        return default


def add_watermark_controls(dialog, group):
    """把水印卡片加进「保存设置」分组；控件挂在 dialog 上供 apply_settings 读取。"""
    enabled = SwitchSettingCard(
        FluentIcon.EDIT,
        dialog.tr("Export Watermark"),
        dialog.tr("Adds a text or image mark to exported images. Off by default; the original image and project are never changed."),
        parent=group,
    )
    enabled.setChecked(bool(_get(dialog, "watermark_enabled", False)))
    group.addSettingCard(enabled)
    dialog.watermark_toggle = enabled

    kind_card = SettingCard(FluentIcon.EDIT, dialog.tr("Watermark Type"), "", parent=group)
    kind = ComboBox(kind_card)
    kind.addItem(dialog.tr("Text"), "text")
    kind.addItem(dialog.tr("Image"), "image")
    kind.setCurrentIndex(max(0, kind.findData(_get(dialog, "watermark_kind", "text"))))
    kind_card.addControl(kind)
    group.addSettingCard(kind_card)
    dialog.watermark_kind_combo = kind

    text_card = SettingCard(
        FluentIcon.EDIT,
        dialog.tr("Watermark Text"),
        dialog.tr("Only the text you type here is written; window titles and identities are never read."),
        parent=group,
    )
    text_edit = LineEdit(text_card)
    text_edit.setMaxLength(200)
    text_edit.setText(str(_get(dialog, "watermark_text", "")))
    text_card.addControl(text_edit)
    group.addSettingCard(text_card)
    dialog.watermark_text_edit = text_edit

    image_card = SettingCard(
        FluentIcon.FOLDER,
        dialog.tr("Watermark Image"),
        dialog.tr("PNG/JPG/BMP/WebP. Missing or oversized files are ignored."),
        parent=group,
    )
    image_row = QWidget(image_card)
    image_layout = QHBoxLayout(image_row)
    image_layout.setContentsMargins(0, 0, 0, 0)
    image_layout.setSpacing(dialog_scaled(6))
    image_edit = LineEdit(image_row)
    image_edit.setText(str(_get(dialog, "watermark_image_path", "")))
    pick = PushButton(dialog.tr("Choose…"), image_row)
    image_layout.addWidget(image_edit)
    image_layout.addWidget(pick)
    image_card.addControl(image_row)
    group.addSettingCard(image_card)
    dialog.watermark_image_edit = image_edit

    position_card = SettingCard(FluentIcon.EDIT, dialog.tr("Watermark Position"), "", parent=group)
    position = ComboBox(position_card)
    for value, label in (
        ("bottom_right", "Bottom right"),
        ("bottom_left", "Bottom left"),
        ("top_right", "Top right"),
        ("top_left", "Top left"),
        ("center", "Center"),
    ):
        position.addItem(dialog.tr(label), value)
    position.setCurrentIndex(max(0, position.findData(_get(dialog, "watermark_position", "bottom_right"))))
    position_card.addControl(position)
    group.addSettingCard(position_card)
    dialog.watermark_position_combo = position

    strength_card = SettingCard(FluentIcon.EDIT, dialog.tr("Watermark Opacity and Size"), "", parent=group)
    strength_row = QWidget(strength_card)
    strength_layout = QHBoxLayout(strength_row)
    strength_layout.setContentsMargins(0, 0, 0, 0)
    strength_layout.setSpacing(dialog_scaled(6))
    opacity = SpinBox(strength_row)
    opacity.setRange(5, 100)
    opacity.setSuffix(" %")
    opacity.setValue(int(round(float(_get(dialog, "watermark_opacity", 0.6)) * 100)))
    opacity.setToolTip(dialog.tr("Opacity"))
    scale = SpinBox(strength_row)
    scale.setRange(20, 400)
    scale.setSuffix(" %")
    scale.setValue(int(round(float(_get(dialog, "watermark_scale", 1.0)) * 100)))
    scale.setToolTip(dialog.tr("Size"))
    strength_layout.addWidget(opacity)
    strength_layout.addWidget(scale)
    strength_card.addControl(strength_row)
    group.addSettingCard(strength_card)
    dialog.watermark_opacity_spin = opacity
    dialog.watermark_scale_spin = scale

    preview_card = SettingCard(
        FluentIcon.DOCUMENT,
        dialog.tr("Watermark Preview"),
        dialog.tr("The preview uses the same renderer as export."),
        parent=group,
    )
    label = QLabel(preview_card)
    label.setMinimumSize(dialog_scaled(220), dialog_scaled(140))
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    preview_card.addControl(label)
    group.addSettingCard(preview_card)
    dialog.watermark_preview = label

    def current_options():
        return options_from_mapping({
            "enabled": True,
            "kind": kind.currentData(),
            "text": text_edit.text(),
            "image_path": image_edit.text(),
            "position": position.currentData(),
            "opacity": opacity.value() / 100.0,
            "scale": scale.value() / 100.0,
        })

    def refresh():
        sample = QImage(dialog_scaled(240), dialog_scaled(150), QImage.Format.Format_ARGB32)
        sample.fill(QColor("#3366CC"))
        label.setPixmap(QPixmap.fromImage(preview(sample, current_options())))
        active = bool(enabled.isChecked())
        for card in (kind_card, position_card, strength_card, preview_card):
            card.setEnabled(active)
        text_card.setEnabled(active and kind.currentData() == "text")
        image_card.setEnabled(active and kind.currentData() == "image")

    def choose_image():
        path, _selected = QFileDialog.getOpenFileName(
            dialog,
            dialog.tr("Watermark Image"),
            "",
            dialog.tr("Images (*.png *.jpg *.jpeg *.bmp *.webp);;All files (*)"),
        )
        if path:
            image_edit.setText(path)
            refresh()

    pick.clicked.connect(choose_image)
    enabled.checkedChanged.connect(refresh)
    kind.currentIndexChanged.connect(refresh)
    text_edit.textChanged.connect(refresh)
    image_edit.textChanged.connect(refresh)
    position.currentIndexChanged.connect(refresh)
    opacity.valueChanged.connect(refresh)
    scale.valueChanged.connect(refresh)
    refresh()
    return preview_card
