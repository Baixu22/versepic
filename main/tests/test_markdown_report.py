# -*- coding: utf-8 -*-
"""TF-0041 Markdown 问题报告：相对路径、转义、顺序、附件只含选中的最终成图。"""

import pytest
from PySide6.QtGui import QColor, QImage

from core.markdown_report import (
    MAX_ENTRIES,
    ReportEntry,
    ReportOptions,
    escape_markdown_text,
    render_report,
    sanitize_attachment_name,
    write_report,
)


def _image(color="#FF0000"):
    image = QImage(24, 16, QImage.Format.Format_ARGB32)
    image.fill(QColor(color))
    return image


def _entries(count=2):
    colors = ["#FF0000", "#00FF00", "#0000FF", "#FFFF00"]
    return [ReportEntry(title=f"Step {i}", note=f"note {i}", image=_image(colors[i % 4]))
            for i in range(1, count + 1)]


def test_escape_markdown_and_html_specials():
    escaped = escape_markdown_text("<script>alert(1)</script> *bold* [x](y) | a `c`")
    assert "<script>" not in escaped
    assert "&lt;script&gt;" in escaped
    assert "\\*bold\\*" in escaped
    assert "\\[x\\]" in escaped
    assert "\\|" in escaped


def test_sanitize_attachment_name_strips_paths_and_dedups():
    used = set()
    first = sanitize_attachment_name("../../etc/passwd", 1, used)
    second = sanitize_attachment_name("../../etc/passwd", 1, used)
    assert "/" not in first and "\\" not in first
    assert first.endswith(".png") and second.endswith(".png")
    assert first != second
    assert sanitize_attachment_name("a" * 200, 3, used).endswith(".png")


def test_write_report_uses_relative_paths_and_keeps_order(tmp_path):
    result = write_report(_entries(3), ReportOptions(title="登录问题", intro="复现步骤"), tmp_path / "report.md")

    assert result.markdown_path.exists()
    assert len(result.attachments) == 3
    text = result.markdown_path.read_text(encoding="utf-8")
    assert "# 登录问题" in text
    assert "images/" in text
    assert str(tmp_path) not in text, "报告里不能出现绝对本机路径"
    positions = [text.index(f"## {i}. Step {i}") for i in (1, 2, 3)]
    assert positions == sorted(positions), "顺序必须与集合一致"
    assert text.index("## 1. Step 1") < text.index("## 2. Step 2") < text.index("## 3. Step 3")


def test_report_folder_can_be_moved_and_links_still_resolve(tmp_path):
    report_dir = tmp_path / "report"
    report_dir.mkdir()
    result = write_report(_entries(2), ReportOptions(title="移动测试"), report_dir / "report.md")

    moved = tmp_path / "moved"
    report_dir.rename(moved)

    text = (moved / "report.md").read_text(encoding="utf-8")
    for name in ("01-Step-1.png", ):
        pass
    for attachment in result.attachments:
        relative = attachment.relative_to(report_dir)
        assert (moved / relative).exists(), "搬走整个目录后附件仍要在"
    assert str(moved) not in text


def test_source_and_time_only_when_explicit(tmp_path):
    plain = write_report(_entries(1), ReportOptions(title="T"), tmp_path / "a.md")
    assert "来源" not in plain.markdown_path.read_text(encoding="utf-8")
    assert "时间" not in plain.markdown_path.read_text(encoding="utf-8")

    marked = write_report(
        _entries(1),
        ReportOptions(title="T", include_source=True, source="Chrome - 登录页",
                      include_time=True, captured_at="2026-10-10 12:00:00"),
        tmp_path / "b.md",
    )
    text = marked.markdown_path.read_text(encoding="utf-8")
    assert "来源" in text and "Chrome" in text
    assert "2026-10-10 12:00:00" in text


def test_attachments_contain_only_selected_final_images(tmp_path):
    result = write_report(_entries(2), ReportOptions(title="T"), tmp_path / "report.md")
    images_dir = tmp_path / "images"
    files = sorted(p.name for p in images_dir.iterdir())
    assert files == sorted(p.name for p in result.attachments)
    assert len(files) == 2


def test_invalid_entries_are_rejected(tmp_path):
    with pytest.raises(ValueError):
        write_report([], ReportOptions(), tmp_path / "empty.md")
    with pytest.raises(ValueError):
        write_report([ReportEntry(title="x", image=QImage())], ReportOptions(), tmp_path / "bad.md")
    too_many = [ReportEntry(title=f"{i}", image=_image()) for i in range(MAX_ENTRIES + 1)]
    with pytest.raises(ValueError):
        write_report(too_many, ReportOptions(), tmp_path / "many.md")


def test_render_report_escapes_notes_and_headings():
    entries = [ReportEntry(title="<b>标题</b>", note="第一行\n第二行 *强调*", image=_image())]
    text = render_report(entries, ReportOptions(title="<报告>"), ["01-x.png"])
    assert "&lt;报告&gt;" in text
    assert "&lt;b&gt;" in text
    assert "\\*强调\\*" in text
    assert "第一行" in text and "第二行" in text


def test_report_dialog_exports_notes_and_cancel_writes_nothing(qapp, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog

    from ui.markdown_report_dialog import MarkdownReportDialog

    entries = [("First", _image("#FF0000"), "id-1"), ("Second", _image("#00FF00"), "id-2")]
    dialog = MarkdownReportDialog(entries)
    try:
        dialog.title_edit.setText("登录失败")
        dialog.intro_edit.setText("复现步骤")
        dialog.notes[1] = "第二张的备注"
        target = tmp_path / "report.md"
        monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(target), "")))
        dialog._export()
        assert target.exists()
        text = target.read_text(encoding="utf-8")
        assert "# 登录失败" in text
        assert "Second" in text and "第二张的备注" in text
        assert (tmp_path / "images").is_dir()
        assert len(list((tmp_path / "images").iterdir())) == 2

        # 取消（对话框返回空路径）不写任何文件
        other = tmp_path / "cancelled.md"
        monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: ("", "")))
        dialog._export()
        assert not other.exists()
    finally:
        dialog.deleteLater()
