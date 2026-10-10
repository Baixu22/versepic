# -*- coding: utf-8 -*-
r"""恢复第六批原生验收写入真实配置的测试值（TF-0019/0020/0021 遗留）。

背景见 docs/screenshot-expansion-progress.md「第六批 · 设置隔离事故」：驱动在隔离
QSettings 生效前导入了 stitch.scroll_window，导致真实注册表
HKCU\Software\Jietuba\ToolSettings 被写成测试值，且没有事前备份。

本脚本只碰那批被写入的键，并遵守两条纪律：
- 默认 --report 只读、只打印 diff；
- --apply 会先把当前值备份到 JSON，再写回应用默认值（不是"猜用户原值"）。

用法：
    python main/tests/restore_polluted_settings.py --report
    python main/tests/restore_polluted_settings.py --apply --output <备份目录>
    python main/tests/restore_polluted_settings.py --restore <备份或用户提供的 json>
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QSettings  # noqa: E402

from settings.tool_settings import ToolSettingsManager  # noqa: E402

ORG = "Jietuba"
APP = "ToolSettings"

AFFECTED = (
    ("app", "log_enabled", ToolSettingsManager.APP_DEFAULT_SETTINGS["log_enabled"]),
    ("app", "log_dir", ToolSettingsManager.APP_DEFAULT_SETTINGS["log_dir"]),
    ("app", "screenshot_save_path", ToolSettingsManager.APP_DEFAULT_SETTINGS["screenshot_save_path"]),
    ("app", "language", ToolSettingsManager.APP_DEFAULT_SETTINGS["language"]),
    ("app", "ui_scale_percent", ToolSettingsManager.APP_DEFAULT_SETTINGS["ui_scale_percent"]),
    ("app", "dialog_scale_percent", ToolSettingsManager.APP_DEFAULT_SETTINGS["dialog_scale_percent"]),
    ("screenshot", "long_stitch_ignore_top_pixels",
     ToolSettingsManager.APP_DEFAULT_SETTINGS["long_stitch_ignore_top_pixels"]),
    ("app", "long_stitch_ignore_right_pixels",
     ToolSettingsManager.APP_DEFAULT_SETTINGS["long_stitch_ignore_right_pixels"]),
    ("clipboard", "db_path", ToolSettingsManager.APP_DEFAULT_SETTINGS["clipboard_db_path"]),
)

FULL_GROUPS = ("app", "clipboard", "screenshot")


def snapshot(settings: QSettings) -> dict:
    data = {"affected": {}, "groups": {}}
    for group, key, _default in AFFECTED:
        data["affected"][f"{group}/{key}"] = settings.value(f"{group}/{key}", None)
    for group in FULL_GROUPS:
        settings.beginGroup(group)
        data["groups"][group] = {key: settings.value(key) for key in settings.childKeys()}
        settings.endGroup()
    return data


def _norm(value):
    """QSettings 把 bool/数字按注册表类型存成字符串，比较时统一归一化。"""
    if isinstance(value, str):
        text = value.strip()
        if text.lower() in ("true", "false"):
            return text.lower() == "true"
        try:
            return int(text)
        except ValueError:
            return text
    return value


def report(settings: QSettings) -> list:
    rows = []
    for group, key, default in AFFECTED:
        current = settings.value(f"{group}/{key}", None)
        rows.append({
            "key": f"{group}/{key}",
            "current": current,
            "default": default,
            "differs": _norm(current) != _norm(default),
        })
    return rows


def apply_defaults(settings: QSettings, rows) -> None:
    for row in rows:
        if not row["differs"]:
            continue
        group, key = row["key"].split("/", 1)
        settings.setValue(f"{group}/{key}", row["default"])
    settings.sync()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", action="store_true", help="只读：打印当前值与默认值的差异")
    parser.add_argument("--apply", action="store_true", help="备份当前值后写入应用默认值")
    parser.add_argument("--restore", type=Path, help="按给定 JSON 恢复")
    parser.add_argument("--output", type=Path, default=Path(".ui_review/settings-restore"))
    args = parser.parse_args()

    settings = QSettings(ORG, APP)
    rows = report(settings)

    print(json.dumps({
        "settings_file": str(Path(settings.fileName())),
        "rows": rows,
        "diff_count": sum(1 for r in rows if r["differs"]),
    }, ensure_ascii=False, indent=2))

    if args.restore:
        data = json.loads(args.restore.read_text(encoding="utf-8"))
        values = data.get("affected", data)
        for key, value in values.items():
            group, name = key.split("/", 1)
            settings.setValue(f"{group}/{name}", value)
        settings.sync()
        print("restored from", args.restore)
        return 0

    if not args.apply:
        print("(dry-run：未写任何值；加 --apply 才会恢复默认值)")
        return 0

    args.output.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = args.output / f"toolsettings-backup-{stamp}.json"
    backup.write_text(json.dumps(snapshot(settings), ensure_ascii=False, indent=2), encoding="utf-8")
    apply_defaults(settings, rows)
    after = report(settings)
    print(json.dumps({
        "backup": str(backup),
        "remaining_diff": [r for r in after if r["differs"]],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
