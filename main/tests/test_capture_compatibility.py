# -*- coding: utf-8 -*-
"""TF-0043 捕获兼容性契约：不伪造成果、不绕过保护、走桌面合成抓屏。

真实硬件结论在 native_capture_compatibility.py 的 result.json 里；这里只锁住
"没做过的不要写成通过"和"不去碰受保护内容"这两条基本纪律。
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "native_capture_compatibility.py"
CAPTURE = ROOT / "capture" / "capture_service.py"


def test_compatibility_driver_records_unverified_rows_and_never_fakes_them():
    source = HARNESS.read_text(encoding="utf-8")
    for item in ("hdr_sdr_mixed_content", "hardware_accelerated_hwnd", "protected_drm_content"):
        assert item in source, f"{item} 必须作为 unverified 记录"
    assert '"unverified"' in source
    assert "not close(minimized, red)" in source, "最小化窗口要按实际抓到的内容判断，不能想当然"
    assert "result[\"passed\"] = bool(ok) and all(c[\"passed\"] for c in result[\"checks\"])" in source, \
        "通过与否只能取决于真正执行过的检查"


def test_capture_path_does_not_try_to_bypass_protection_or_use_window_print():
    source = CAPTURE.read_text(encoding="utf-8")
    assert "mss" in source
    for forbidden in ("SetWindowDisplayAffinity", "WDA_EXCLUDEFROMCAPTURE", "PrintWindow"):
        assert forbidden not in source, f"采集路径不应使用 {forbidden}（受保护/离屏内容不被宣传为支持）"
