# -*- coding: utf-8 -*-
"""打包产物自检（TF-0045）：在真实安装包里跑一遍本批新增能力的核心链路。

只做无 GUI 的逻辑检查：导入新模块，并跑水印 / 编号说明 / 元信息 / Markdown 报告 /
标注预设 / 组合标注 / 插图 的最小链路；输出 JSON，任一失败返回非 0。
它证明"包内确实带着这些能力"，不替代 GUI 交互验收，也不读写用户的真实配置。
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path


def _check(results, name, func):
    try:
        detail = func()
        results.append({"name": name, "passed": True, "detail": detail})
    except Exception as exc:  # pragma: no cover - reported as failure
        results.append({"name": name, "passed": False, "detail": f"{type(exc).__name__}: {exc}"})


def _output_path() -> Path:
    """--self-check-out <path> 或 --self-check-out=<path>；默认写到临时目录。"""
    for index, arg in enumerate(sys.argv):
        if arg == "--self-check-out" and index + 1 < len(sys.argv):
            return Path(sys.argv[index + 1])
        if arg.startswith("--self-check-out="):
            return Path(arg.split("=", 1)[1])
    return Path(tempfile.gettempdir()) / "versepic-self-check.json"


def run_self_check() -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    results: list = []

    def imports():
        import canvas.items.image_stamp_item  # noqa: F401
        import canvas.items.callout_link  # noqa: F401
        import core.annotation_presets  # noqa: F401
        import core.capture_metadata  # noqa: F401
        import core.markdown_report  # noqa: F401
        import core.number_legend  # noqa: F401
        import core.watermark  # noqa: F401
        import ui.markdown_report_dialog  # noqa: F401
        import ui.preset_dialog  # noqa: F401
        import ui.settings_ui.metadata_controls  # noqa: F401
        import ui.settings_ui.watermark_controls  # noqa: F401
        return "11 modules imported"

    _check(results, "imports", imports)

    from PySide6.QtGui import QColor, QImage
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])

    def watermark():
        from core.watermark import WatermarkOptions, render

        image = QImage(120, 80, QImage.Format.Format_ARGB32)
        image.fill(QColor("#3366CC"))
        marked = render(image, WatermarkOptions(enabled=True, text="self-check"))
        assert marked.size() == image.size()
        assert marked.pixelColor(1, 1) == image.pixelColor(1, 1)
        assert marked != image
        return "watermark rendered"

    _check(results, "watermark", watermark)

    def number_legend():
        from core.number_legend import LegendEntry, LegendOptions, PLACEMENT_BOTTOM, render

        image = QImage(120, 80, QImage.Format.Format_ARGB32)
        image.fill(QColor("#FFFFFF"))
        out = render(image, [LegendEntry(1, "说明文字", "#FF0000")],
                     LegendOptions(placement=PLACEMENT_BOTTOM))
        assert out.height() > image.height() and out.width() == image.width()
        return "legend strip appended"

    _check(results, "number_legend", number_legend)

    def metadata():
        from core.capture_metadata import CaptureMetadata, render_strip

        lines = CaptureMetadata(source_enabled=True, source="Chrome").build_lines()
        assert lines == ["来源: Chrome"]
        assert CaptureMetadata().build_lines() == []
        image = QImage(120, 80, QImage.Format.Format_ARGB32)
        image.fill(QColor("#FFFFFF"))
        assert render_strip(image, lines).height() > image.height()
        return "metadata strip appended"

    _check(results, "capture_metadata", metadata)

    def markdown_report():
        from core.markdown_report import ReportEntry, ReportOptions, write_report

        with tempfile.TemporaryDirectory() as tmp:
            image = QImage(64, 48, QImage.Format.Format_ARGB32)
            image.fill(QColor("#FF0000"))
            result = write_report([ReportEntry(title="Step 1", note="note", image=image)],
                                  ReportOptions(title="Self check"), Path(tmp) / "report.md")
            assert result.markdown_path.exists()
            assert len(list((Path(tmp) / "images").iterdir())) == 1
            assert str(tmp) not in result.markdown_path.read_text(encoding="utf-8")
            return "report.md + images/ written"

    _check(results, "markdown_report", markdown_report)

    def presets():
        from core.annotation_presets import load_presets, sanitize_values, upsert_preset

        values = sanitize_values("arrow", {"color": "#FF0000", "stroke_width": 8, "bogus": 1})
        assert values == {"color": "#ff0000", "stroke_width": 8.0}

        class _Manager:
            def __init__(self):
                self.data = {}

            def get_app_setting(self, key, default=None):
                return self.data.get(key, default)

            def set_app_setting(self, key, value):
                self.data[key] = value

        manager = _Manager()
        assert upsert_preset(manager, "红箭头", "arrow", values) is not None
        assert [p.name for p in load_presets(manager)] == ["红箭头"]
        return "preset roundtrip"

    _check(results, "annotation_presets", presets)

    def image_stamp():
        from PySide6.QtCore import QRectF

        from canvas.items import ImageStampItem

        image = QImage(80, 40, QImage.Format.Format_ARGB32)
        image.fill(QColor("#00FF00"))
        item = ImageStampItem(image)
        item.setRect(QRectF(0, 0, 80, 10))
        assert item.rect().width() == 80.0
        assert abs(item.rect().height() - 40.0) < 1e-6
        assert ImageStampItem.validate_image(image) is image
        return "stamp aspect preserved"

    _check(results, "image_stamp", image_stamp)

    def callout():
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QFont, QPen

        from canvas.items import ArrowItem, TextItem
        from canvas.items.callout_link import callout_target, link_callout, partner_of

        arrow = ArrowItem(QPointF(0, 0), QPointF(40, 40), QPen(QColor("#FF0000"), 2), "single")
        bubble = TextItem("说明", QPointF(0, 0), QFont("Arial", 10), QColor("#000000"))
        link_callout(arrow, bubble, QPointF(40, 40))
        assert partner_of(bubble) is arrow
        assert callout_target(bubble) == QPointF(40, 40)
        return "callout linked"

    _check(results, "text_callout", callout)

    del app
    failed = [r for r in results if not r["passed"]]
    payload = {
        "task": "TF-0045",
        "kind": "packaged_self_check",
        "python": sys.version.split()[0],
        "frozen": bool(getattr(sys, "frozen", False)),
        "results": results,
        "passed": not failed,
    }
    # windowed 打包没有 stdout：把结果写到文件，控制台模式下也顺带打印一份。
    out_path = _output_path()
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        payload["output_path"] = str(out_path)
    except Exception as exc:
        payload["output_error"] = f"{type(exc).__name__}: {exc}"
    try:
        print(json.dumps(payload, ensure_ascii=False))
    except Exception:
        pass
    return 0 if not failed else 1
