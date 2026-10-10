"""Validated, immutable quick-capture targets in physical desktop pixels."""
from dataclasses import dataclass
import os

from PySide6.QtCore import QRect
import win32api
import win32con
import win32gui
import win32process

from capture.window_finder import get_window_rect_no_shadow


class CaptureTargetUnavailable(ValueError):
    """The requested target cannot be captured without guessing another area."""


def rect_from_edges(edges):
    left, top, right, bottom = edges
    rect = QRect(left, top, right - left, bottom - top)
    if rect.width() < 8 or rect.height() < 8:
        raise CaptureTargetUnavailable("Empty or too-small capture target")
    return rect


@dataclass(frozen=True)
class QuickCaptureRequest:
    kind: str
    area: tuple = ()
    hwnd: int = 0
    pid: int = 0
    action: str = "edit"

    def __post_init__(self):
        if self.kind not in ("screen", "window", "last") or self.action not in ("edit", "copy"):
            raise ValueError("Invalid quick capture request")

    def resolve(self):
        if self.kind != "window":
            return rect_from_edges(self.area)
        try:
            if (not self.hwnd or not win32gui.IsWindow(self.hwnd)
                    or not win32gui.IsWindowVisible(self.hwnd) or win32gui.IsIconic(self.hwnd)):
                raise CaptureTargetUnavailable("Window is not visible")
            pid = win32process.GetWindowThreadProcessId(self.hwnd)[1]
            if not self.pid or pid != self.pid or pid == os.getpid():
                raise CaptureTargetUnavailable("Window owner changed or is this application")
            return rect_from_edges(get_window_rect_no_shadow(self.hwnd))
        except CaptureTargetUnavailable:
            raise
        except Exception as exc:
            raise CaptureTargetUnavailable("Window is no longer available") from exc

    def capture(self, service):
        before = self.resolve()
        image, desktop = service.capture_all_screens()
        if (before != self.resolve() or not desktop.contains(before)
                or image.width() != round(desktop.width()) or image.height() != round(desktop.height())):
            raise CaptureTargetUnavailable("Target moved or screen layout changed")
        return image, desktop, before


def make_quick_capture_request(kind, *, point=None, hwnd=None, last_region=None, action="edit"):
    if kind == "window":
        try:
            pid = win32process.GetWindowThreadProcessId(hwnd)[1] if hwnd else 0
        except Exception as exc:
            raise CaptureTargetUnavailable("No capture window") from exc
        request = QuickCaptureRequest(kind, hwnd=hwnd or 0, pid=pid, action=action)
    elif kind == "screen":
        try:
            monitor = win32api.MonitorFromPoint((point.x(), point.y()), win32con.MONITOR_DEFAULTTONEAREST)
            area = tuple(win32api.GetMonitorInfo(monitor)["Monitor"])
        except Exception as exc:
            raise CaptureTargetUnavailable("No capture screen") from exc
        request = QuickCaptureRequest(kind, area=area, action=action)
    elif kind == "last":
        if last_region is None or last_region.isEmpty():
            raise CaptureTargetUnavailable("No previous region")
        rect = last_region
        request = QuickCaptureRequest(kind, area=(rect.x(), rect.y(), rect.x() + rect.width(),
                                                 rect.y() + rect.height()), action=action)
    else:
        raise ValueError("Unknown quick capture kind")
    request.resolve()
    return request
