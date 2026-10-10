# -*- coding: utf-8 -*-
"""设置页的截图元信息分组（TF-0040）：来源/时间/备注 + 导出预览。

默认全关。来源是"尽力检测 + 用户可改可删"的一行文本：检测失败或命中的是本
工具自身时留空，让用户自己填或干脆不导出。预览用与导出同一条 render_strip。
"""
from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from core.capture_metadata import (
    CaptureMetadata,
    describe_source_window,
    now_stamp,
    render_strip,
)
from core.ui_scale import dialog_scaled
from ui.fluent_lite import FluentIcon, LineEdit, PushButton, SettingCard, SwitchSettingCard


def _get(dialog, key, default):
    try:
        return dialog.config_manager.get_app_setting(key, default)
    except Exception:
        return default


def add_metadata_controls(dialog, group):
    """把元信息卡片加进「保存设置」；控件挂在 dialog 上供 apply_settings 读取。"""
    source_card = SwitchSettingCard(
        FluentIcon.EDIT,
        dialog.tr("Include Source Info"),
        dialog.tr("Only the text you keep below is exported. Window titles are never read automatically."),
        parent=group,
    )
    source_card.setChecked(bool(_get(dialog, "capture_meta_source_enabled", False)))
    group.addSettingCard(source_card)
    dialog.meta_source_toggle = source_card

    source_row_card = SettingCard(FluentIcon.FOLDER, dialog.tr("Source"), "", parent=group)
    source_row = QWidget(source_row_card)
    source_layout = QHBoxLayout(source_row)
    source_layout.setContentsMargins(0, 0, 0, 0)
    source_layout.setSpacing(dialog_scaled(6))
    source_edit = LineEdit(source_row)
    source_edit.setMaxLength(200)
    source_edit.setText(str(_get(dialog, "capture_meta_source", "")))
    detect = PushButton(dialog.tr("Detect window"), source_row)
    clear = PushButton(dialog.tr("Clear"), source_row)
    source_layout.addWidget(source_edit)
    source_layout.addWidget(detect)
    source_layout.addWidget(clear)
    source_row_card.addControl(source_row)
    group.addSettingCard(source_row_card)
    dialog.meta_source_edit = source_edit

    time_card = SwitchSettingCard(
        FluentIcon.SAVE,
        dialog.tr("Include Time"),
        dialog.tr("Writes the export time next to the image. Off by default."),
        parent=group,
    )
    time_card.setChecked(bool(_get(dialog, "capture_meta_time_enabled", False)))
    group.addSettingCard(time_card)
    dialog.meta_time_toggle = time_card

    note_card = SwitchSettingCard(
        FluentIcon.EDIT,
        dialog.tr("Include Note"),
        dialog.tr("Your own note; empty notes are not exported."),
        parent=group,
    )
    note_card.setChecked(bool(_get(dialog, "capture_meta_note_enabled", False)))
    group.addSettingCard(note_card)
    dialog.meta_note_toggle = note_card

    note_row_card = SettingCard(FluentIcon.EDIT, dialog.tr("Note"), "", parent=group)
    note_edit = LineEdit(note_row_card)
    note_edit.setMaxLength(200)
    note_edit.setText(str(_get(dialog, "capture_meta_note", "")))
    note_row_card.addControl(note_edit)
    group.addSettingCard(note_row_card)
    dialog.meta_note_edit = note_edit

    preview_card = SettingCard(
        FluentIcon.DOCUMENT,
        dialog.tr("Metadata Preview"),
        dialog.tr("Shows exactly what will be appended to the exported image."),
        parent=group,
    )
    preview = QLabel(preview_card)
    preview.setMinimumSize(dialog_scaled(220), dialog_scaled(90))
    preview_card.addControl(preview)
    group.addSettingCard(preview_card)
    dialog.meta_preview = preview

    def current_metadata():
        return CaptureMetadata(
            source_enabled=source_card.isChecked(),
            time_enabled=time_card.isChecked(),
            note_enabled=note_card.isChecked(),
            source=source_edit.text(),
            note=note_edit.text(),
            captured_at=now_stamp() if time_card.isChecked() else "",
        )

    def refresh():
        sample = QImage(dialog_scaled(240), dialog_scaled(90), QImage.Format.Format_ARGB32)
        sample.fill(QColor("#3366CC"))
        out = render_strip(sample, current_metadata().build_lines())
        preview.setPixmap(QPixmap.fromImage(out))
        active = source_card.isChecked()
        source_edit.setEnabled(active)
        detect.setEnabled(active)
        clear.setEnabled(active)
        note_edit.setEnabled(note_card.isChecked())

    def detect_source():
        info = describe_source_window()
        source_edit.setText(info.get("source", ""))
        refresh()

    detect.clicked.connect(detect_source)
    clear.clicked.connect(lambda: (source_edit.clear(), refresh()))
    source_card.checkedChanged.connect(refresh)
    time_card.checkedChanged.connect(refresh)
    note_card.checkedChanged.connect(refresh)
    source_edit.textChanged.connect(refresh)
    note_edit.textChanged.connect(refresh)
    refresh()
    return preview_card
