# -*- coding: utf-8 -*-
"""TF-0044 批次验收门槛：回归 + 原生交互 + 隐私 + 资源释放。

每次运行都重新执行，不复用历史通过数：定向/全量回归、原生 DPI 与兼容性驱动、
隐私默认值矩阵、以及窗口/图元释放检查。缺条件（HDR、受保护内容、安装包）如实
记为 unverified，不阻塞核心批次。

用法：python main/tests/batch_acceptance.py --run --output <目录>
"""

from __future__ import annotations

import argparse
import gc
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / "main"
sys.path.insert(0, str(MAIN))
PY = str(ROOT / "venv312" / "Scripts" / "python.exe")

BATCH_TARGETED = [
    "main/tests/test_text_callout.py",
    "main/tests/test_number_legend.py",
    "main/tests/test_image_stamp.py",
    "main/tests/test_watermark.py",
    "main/tests/test_annotation_presets.py",
    "main/tests/test_capture_metadata.py",
    "main/tests/test_markdown_report.py",
    "main/tests/test_dpi_awareness.py",
    "main/tests/test_capture_compatibility.py",
    "main/tests/test_i18n.py",
    "main/tests/test_readme_tree.py",
]

NATIVE_DRIVERS = [
    "main/tests/native_dpi_matrix.py",
    "main/tests/native_capture_compatibility.py",
]


def run(argv, timeout=1800):
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    proc = subprocess.run(argv, cwd=str(ROOT), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=env, timeout=timeout)
    return {
        "argv": argv,
        "exit_code": proc.returncode,
        "stdout_tail": (proc.stdout or "").strip().splitlines()[-12:],
        "stderr_tail": (proc.stderr or "").strip().splitlines()[-6:],
    }


def parse_counts(text):
    for line in reversed(text.splitlines()):
        if " passed" in line or " failed" in line:
            return line.strip()
    return ""


def privacy_matrix():
    from settings.tool_settings import ToolSettingsManager

    defaults = ToolSettingsManager.APP_DEFAULT_SETTINGS
    checks = [
        {"item": "watermark_off_by_default", "passed": defaults.get("watermark_enabled") is False},
        {"item": "number_legend_off_by_default", "passed": defaults.get("number_legend_placement") == "off"},
        {"item": "capture_meta_off_by_default", "passed": all(
            defaults.get(key) in (False, "") for key in
            ("capture_meta_source_enabled", "capture_meta_time_enabled", "capture_meta_note_enabled",
             "capture_meta_source", "capture_meta_note", "capture_meta_time"))},
    ]

    from core.capture_metadata import CaptureMetadata
    checks.append({"item": "no_metadata_line_without_user_choice",
                   "passed": CaptureMetadata().build_lines() == []})

    save_src = (ROOT / "main/core/save.py").read_text(encoding="utf-8")
    clipboard_src = (ROOT / "main/clipboard/core/models.py").read_text(encoding="utf-8")
    checks.append({"item": "metadata_not_in_file_names_or_clipboard_source",
                   "passed": "capture_meta" not in save_src and "capture_meta" not in clipboard_src})

    conftest = (MAIN / "tests/conftest.py").read_text(encoding="utf-8")
    checks.append({"item": "tests_use_isolated_settings",
                   "passed": "isolated_tool_settings" in conftest and "tmp_path_factory" in conftest})

    capture_src = (ROOT / "main/capture/capture_service.py").read_text(encoding="utf-8")
    checks.append({"item": "no_protected_content_bypass",
                   "passed": all(token not in capture_src for token in
                                 ("SetWindowDisplayAffinity", "WDA_EXCLUDEFROMCAPTURE", "PrintWindow"))})
    return checks


def resource_release_check():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QCoreApplication, QEvent, QRectF
    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import QApplication

    from canvas.scene import CanvasScene
    from canvas.view import CanvasView

    app = QApplication.instance() or QApplication([])
    before = len(app.topLevelWidgets())
    for _ in range(5):
        scene = CanvasScene(QImage(160, 100, QImage.Format.Format_ARGB32), QRectF(0, 0, 160, 100), enable_mosaic=True)
        view = CanvasView(scene)
        view.show()
        app.processEvents()
        # 与生产 teardown 同款：cleanup + close + deleteLater（只 close 不会销毁顶层窗口）
        if hasattr(view, "cleanup"):
            view.cleanup()
        view.close()
        view.deleteLater()
        scene.deleteLater()
        app.processEvents()
    gc.collect()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
    after = len(app.topLevelWidgets())
    return {"item": "windows_released_after_close", "passed": after <= before,
            "detail": {"top_level_before": before, "top_level_after": after}}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if not args.run:
        parser.error("batch acceptance requires --run")

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    result = {
        "task": "TF-0044",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "batch": [
            "TF-0035 组合标注", "TF-0036 编号说明列表", "TF-0037 插图", "TF-0038 导出水印",
            "TF-0039 标注样式预设", "TF-0040 截图元信息", "TF-0041 Markdown 问题报告",
            "TF-0042 混合 DPI", "TF-0043 捕获兼容性",
        ],
        "not_delivered": [
            "TF-0030 真实监听零留存（受本机隔离环境限制）",
            "TF-0045 安装包与文档对齐（尚未执行）",
        ],
        "steps": {},
        "privacy": [],
        "resources": {},
        "unverified": [],
    }

    targeted = run([PY, "-m", "pytest", *BATCH_TARGETED, "-q"])
    targeted["summary"] = parse_counts("\n".join(targeted["stdout_tail"]))
    result["steps"]["targeted_regression"] = targeted

    full = run([PY, "-m", "pytest", "-o", "faulthandler_timeout=90", "-q"])
    full["summary"] = parse_counts("\n".join(full["stdout_tail"]))
    result["steps"]["full_regression"] = full

    for driver in NATIVE_DRIVERS:
        name = Path(driver).stem
        step = run([PY, driver, "--run", "--output", str(out_dir / name)])
        result["steps"][name] = step

    result["privacy"] = privacy_matrix()
    result["resources"] = resource_release_check()
    result["unverified"].extend([
        {"item": "TF-0030_real_listener_zero_retention", "reason": "本机无法创建独立 window station；需隔离 Windows 环境或用户授权"},
        {"item": "hdr_and_protected_content", "reason": "本机无 HDR 硬件/受保护内容样例（见 TF-0043 unverified）"},
        {"item": "installer_verification", "reason": "属于 TF-0045，本轮未执行"},
    ])

    executed_ok = all(step["exit_code"] == 0 for step in result["steps"].values())
    privacy_ok = all(item["passed"] for item in result["privacy"])
    resource_ok = bool(result["resources"].get("passed"))
    result["passed"] = bool(executed_ok and privacy_ok and resource_ok)

    (out_dir / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# TF-0044 批次验收", "",
             f"- 生成时间：{result['created_at']}",
             f"- 定向回归：{result['steps']['targeted_regression']['summary']}（exit {result['steps']['targeted_regression']['exit_code']}）",
             f"- 全量回归：{result['steps']['full_regression']['summary']}（exit {result['steps']['full_regression']['exit_code']}）"]
    for driver in NATIVE_DRIVERS:
        step = result["steps"][Path(driver).stem]
        lines.append(f"- {Path(driver).name}：exit {step['exit_code']}")
    lines.append("- 隐私：")
    for item in result["privacy"]:
        lines.append(f"  - {'PASS' if item['passed'] else 'FAIL'} {item['item']}")
    lines.append(f"- 资源释放：{'PASS' if resource_ok else 'FAIL'} {result['resources']}")
    lines.append("- 未验证：")
    for item in result["unverified"]:
        lines.append(f"  - {item['item']}：{item['reason']}")
    (out_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(json.dumps({"passed": result["passed"],
                      "targeted": result["steps"]["targeted_regression"]["summary"],
                      "full": result["steps"]["full_regression"]["summary"],
                      "privacy_ok": privacy_ok, "resource_ok": resource_ok}, ensure_ascii=False))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
