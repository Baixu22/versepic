"""Startup must request per-monitor V2 before Qt creates any windows."""
import ctypes
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

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
