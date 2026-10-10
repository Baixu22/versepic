"""Startup must request per-monitor V2 before Qt creates any windows."""
import ctypes
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from pathlib import Path

from core import platform_utils


@pytest.mark.skipif(platform_utils.os.name != "nt", reason="Windows DPI APIs")
@pytest.mark.parametrize("v2_available", [True, False])
def test_dpi_awareness_prefers_v2_and_falls_back(monkeypatch, v2_available):
    set_v2 = Mock(return_value=1)
    set_v1 = Mock(return_value=0)
    user32 = SimpleNamespace(SetProcessDPIAware=Mock())
    if v2_available:
        user32.SetProcessDpiAwarenessContext = set_v2
    monkeypatch.setattr(ctypes, "windll", SimpleNamespace(
        user32=user32, shcore=SimpleNamespace(SetProcessDpiAwareness=set_v1)))

    platform_utils.set_dpi_awareness()

    if v2_available:
        assert set_v2.call_args.args[0].value == ctypes.c_void_p(-4).value
        set_v1.assert_not_called()
    else:
        set_v1.assert_called_once_with(2)


def test_setup_environment_disables_qt_scaling_and_sets_dpi(monkeypatch):
    """生产 pre-Qt 设置必须把 Qt 自动缩放关掉，否则逻辑坐标会和物理像素差一个比例。"""
    from core import bootstrap, platform_utils

    monkeypatch.setattr("core.crash_handler.install_crash_hooks", lambda: None)
    called = []
    monkeypatch.setattr(platform_utils, "set_dpi_awareness", lambda: called.append(True))
    monkeypatch.delenv("QT_ENABLE_HIGHDPI_SCALING", raising=False)
    monkeypatch.delenv("QT_SCALE_FACTOR", raising=False)

    bootstrap.setup_environment()

    assert platform_utils.os.environ["QT_ENABLE_HIGHDPI_SCALING"] == "0"
    assert platform_utils.os.environ["QT_SCALE_FACTOR"] == "1"
    assert called == [True], "必须按 per-monitor V2 请求 DPI 感知"


def test_native_dpi_matrix_uses_production_pre_qt_setup():
    """原生矩阵驱动要复用生产入口，才代表真实运行路径。"""
    source = (Path(__file__).with_name("native_dpi_matrix.py")).read_text(encoding="utf-8")
    assert "bootstrap.setup_environment()" in source
    assert "set_dpi_awareness()" in source
    assert source.index("bootstrap.setup_environment()") < source.index("QApplication")
    assert "QT_ENABLE_HIGHDPI_SCALING" in source


def test_capture_service_reports_physical_virtual_desktop(monkeypatch):
    """模拟对照：即使 Qt 处于 150% 逻辑坐标，采集给的仍是物理像素矩形。"""
    from PySide6.QtCore import QRectF

    from capture.capture_service import CaptureService

    class _Shot:
        width = 2560
        height = 1600
        bgra = bytes(2560 * 1600 * 4)

    class _Sct:
        monitors = [{"left": 0, "top": 0, "width": 2560, "height": 1600},
                    {"left": 0, "top": 0, "width": 2560, "height": 1600}]

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def grab(self, rect):
            return _Shot()

    monkeypatch.setattr("capture.capture_service.mss.mss", lambda: _Sct())
    image, rect = CaptureService().capture_all_screens()
    assert isinstance(rect, QRectF)
    assert (rect.x(), rect.y(), rect.width(), rect.height()) == (0.0, 0.0, 2560.0, 1600.0)
