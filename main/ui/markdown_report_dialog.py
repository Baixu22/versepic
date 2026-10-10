# -*- coding: utf-8 -*-
"""Markdown 问题报告对话框（TF-0041）。

复用多图集合的顺序与最终成图：填标题/步骤/每张图的备注，可选用户已批准的
来源与时间，导出 report.md + images/ 相对路径附件。取消不写任何文件。
"""
from PySide6.QtWidgets import QDialog, QFileDialog, QHBoxLayout, QLabel, QVBoxLayout

from core.capture_metadata import load_metadata, now_stamp
from core.markdown_report import ReportEntry, ReportOptions, write_report
from ui.fluent_lite import BodyLabel, ComboBox, LineEdit, PrimaryPushButton, PushButton


class MarkdownReportDialog(QDialog):
    def __init__(self, entries, parent=None):
        super().__init__(parent)
        self.entries = list(entries or [])
        self.notes = {}
        self.setWindowTitle(self.tr("Markdown report"))
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        title_row = QHBoxLayout()
        title_row.addWidget(BodyLabel(self.tr("Report title"), self))
        self.title_edit = LineEdit(self)
        self.title_edit.setText(self.tr("Issue report"))
        self.title_edit.setMaxLength(200)
        title_row.addWidget(self.title_edit, 1)
        layout.addLayout(title_row)

        intro_row = QHBoxLayout()
        intro_row.addWidget(BodyLabel(self.tr("Steps / description"), self))
        self.intro_edit = LineEdit(self)
        self.intro_edit.setMaxLength(2000)
        intro_row.addWidget(self.intro_edit, 1)
        layout.addLayout(intro_row)

        meta = load_metadata()
        self.include_source = PushButton(self.tr("Include approved source"), self)
        self.include_source.setCheckable(True)
        self.include_source.setChecked(bool(meta.source_enabled and meta.source))
        self.include_time = PushButton(self.tr("Include time"), self)
        self.include_time.setCheckable(True)
        self.include_time.setChecked(bool(meta.time_enabled))
        meta_row = QHBoxLayout()
        meta_row.addWidget(self.include_source)
        meta_row.addWidget(self.include_time)
        meta_row.addStretch(1)
        layout.addLayout(meta_row)

        note_row = QHBoxLayout()
        note_row.addWidget(BodyLabel(self.tr("Note for"), self))
        self.entry_combo = ComboBox(self)
        for index, entry in enumerate(self.entries, start=1):
            title = entry[0] if entry else ""
            self.entry_combo.addItem(f"{index}. {title}", index - 1)
        note_row.addWidget(self.entry_combo)
        self.note_edit = LineEdit(self)
        self.note_edit.setMaxLength(2000)
        note_row.addWidget(self.note_edit, 1)
        layout.addLayout(note_row)

        self.hint = QLabel(
            self.tr("Writes report.md plus an images/ folder next to it. Only the images in this collection are attached."),
            self,
        )
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)

        buttons = QHBoxLayout()
        self.export_button = PrimaryPushButton(self.tr("Export report"), self)
        self.cancel_button = PushButton(self.tr("Cancel"), self)
        buttons.addStretch(1)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.export_button)
        layout.addLayout(buttons)

        self.status = QLabel("", self)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        self.entry_combo.currentIndexChanged.connect(self._load_note)
        self.note_edit.textChanged.connect(self._store_note)
        self.cancel_button.clicked.connect(self.reject)
        self.export_button.clicked.connect(self._export)

    def _current_index(self) -> int:
        data = self.entry_combo.currentData()
        return int(data) if data is not None else 0

    def _load_note(self, *_args):
        index = self._current_index()
        self.note_edit.blockSignals(True)
        self.note_edit.setText(self.notes.get(index, ""))
        self.note_edit.blockSignals(False)

    def _store_note(self, text):
        self.notes[self._current_index()] = str(text)

    def build_entries(self):
        from PySide6.QtGui import QImage

        built = []
        for index, entry in enumerate(self.entries):
            title = str(entry[0] if entry else "")
            image = entry[1] if len(entry) > 1 else None
            if not isinstance(image, QImage) or image.isNull():
                continue
            built.append(ReportEntry(title=title, note=self.notes.get(index, ""), image=image))
        return built

    def _export(self):
        target, _selected = QFileDialog.getSaveFileName(
            self, self.tr("Export Markdown report"), "report.md", "Markdown (*.md)")
        if not target:
            return
        meta = load_metadata()
        options = ReportOptions(
            title=self.title_edit.text() or self.tr("Issue report"),
            intro=self.intro_edit.text(),
            include_source=bool(self.include_source.isChecked()),
            include_time=bool(self.include_time.isChecked()),
            source=meta.source,
            captured_at=now_stamp() if self.include_time.isChecked() else "",
        )
        try:
            result = write_report(self.build_entries(), options, target)
        except ValueError:
            self.status.setText(self.tr("Could not write the report. Check the target folder and that images are still loaded."))
            return
        self.status.setText(self.tr("Report written:") + " " + str(result.markdown_path))
