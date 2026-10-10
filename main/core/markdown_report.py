# -*- coding: utf-8 -*-
"""多张截图的 Markdown 问题报告（TF-0041）。

把用户已经选好、排好序的最终成图写成本地 Markdown + images/ 附件：
- 只用相对路径，整个报告目录可以整体搬走；
- 标题/步骤/备注都做 Markdown 转义，文件名做净化与去重；
- 不写绝对本机路径，不附带原始工程、底图或任何默认隐私信息；
- 来源/时间只有调用方显式传入时才出现（复用 TF-0040 的用户选择）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtGui import QImage

MAX_TITLE_CHARS = 200
MAX_NOTE_CHARS = 2000
MAX_ENTRIES = 64
MAX_ATTACHMENT_NAME = 60

_MD_SPECIALS = "\\`*_[]()|"


@dataclass
class ReportEntry:
    title: str = ""
    note: str = ""
    image: object = None


@dataclass
class ReportOptions:
    title: str = "Issue Report"
    intro: str = ""
    include_source: bool = False
    include_time: bool = False
    source: str = ""
    captured_at: str = ""
    attachments_dir: str = "images"


@dataclass
class ReportResult:
    markdown_path: Path
    attachments: list = field(default_factory=list)


def escape_markdown_text(value) -> str:
    """转义 Markdown/HTML 里会改变结构的字符，避免标题里的内容破坏报告。"""
    text = "" if value is None else str(value)
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    out = []
    for char in text:
        if char in _MD_SPECIALS:
            out.append("\\" + char)
        else:
            out.append(char)
    return "".join(out)


def sanitize_attachment_name(name, index: int, used=None) -> str:
    """净化附件名：去掉路径与非法字符，去重并强制 .png，绝不带目录。"""
    used = used if used is not None else set()
    raw = str(name or "").replace("\\", "/").split("/")[-1]
    raw = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff._-]+", "-", raw).strip("-._")
    stem = raw.rsplit(".", 1)[0] if "." in raw else raw
    stem = stem[:MAX_ATTACHMENT_NAME] or f"image-{index:02d}"
    candidate = f"{index:02d}-{stem}.png"
    suffix = 2
    while candidate.lower() in used:
        candidate = f"{index:02d}-{stem}-{suffix}.png"
        suffix += 1
    used.add(candidate.lower())
    return candidate


def _metadata_line(options: ReportOptions) -> str:
    parts = []
    if options.include_source and str(options.source or "").strip():
        parts.append("来源：" + escape_markdown_text(options.source))
    if options.include_time and str(options.captured_at or "").strip():
        parts.append("时间：" + escape_markdown_text(options.captured_at))
    return " · ".join(parts)


def render_report(entries, options: ReportOptions, attachment_names=None) -> str:
    """生成 Markdown 文本；attachment_names 与 entries 一一对应。"""
    attachment_names = list(attachment_names or [])
    lines = ["# " + escape_markdown_text(options.title)[:MAX_TITLE_CHARS], ""]
    if str(options.intro or "").strip():
        lines.extend([escape_markdown_text(options.intro)[:MAX_NOTE_CHARS], ""])
    meta = _metadata_line(options)
    if meta:
        lines.extend(["> " + meta, ""])
    for index, entry in enumerate(entries, start=1):
        heading = escape_markdown_text(entry.title)[:MAX_TITLE_CHARS] or f"Step {index}"
        lines.append(f"## {index}. {heading}")
        lines.append("")
        name = attachment_names[index - 1] if index - 1 < len(attachment_names) else ""
        if name:
            lines.append(f"![{escape_markdown_text(entry.title) or heading}]({options.attachments_dir}/{name})")
            lines.append("")
        note = escape_markdown_text(entry.note)[:MAX_NOTE_CHARS]
        if note.strip():
            lines.append(note.replace("\n", "  \n"))
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_report(entries, options: ReportOptions, target_path) -> ReportResult:
    """写 report.md 与 images/ 附件；只写用户传入的这些最终成图。"""
    entries = [entry for entry in (entries or []) if isinstance(entry, ReportEntry)]
    if not entries:
        raise ValueError("report needs at least one image")
    if len(entries) > MAX_ENTRIES:
        raise ValueError("too many images for one report")
    for entry in entries:
        image = entry.image
        if not isinstance(image, QImage) or image.isNull():
            raise ValueError("report entry has no valid image")

    target = Path(target_path)
    base_dir = target.parent
    attachments_dir = base_dir / options.attachments_dir
    attachments_dir.mkdir(parents=True, exist_ok=True)

    used = set()
    names = []
    attachments = []
    for index, entry in enumerate(entries, start=1):
        name = sanitize_attachment_name(entry.title, index, used)
        path = attachments_dir / name
        if not entry.image.save(str(path), "PNG"):
            raise ValueError("failed to write report attachment")
        names.append(name)
        attachments.append(path)

    markdown = render_report(entries, options, names)
    target.write_text(markdown, encoding="utf-8")
    return ReportResult(markdown_path=target, attachments=attachments)
