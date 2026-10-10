"""Bounded, opt-in scrolling addressed to a verified native window, never global mouse input."""
from dataclasses import dataclass
import math
import os
import threading
import time

from PySide6.QtCore import QObject, QTimer, Signal
import win32api
import win32con
import win32gui
import win32process

from capture.window_finder import get_window_rect_no_shadow

WM_MOUSEHWHEEL = 0x020E  # Not exported by every supported pywin32 build.


@dataclass(frozen=True)
class AutoScrollOptions:
    direction: str = "down"
    wheel_steps: int = 1
    interval_ms: int = 600
    max_steps: int = 40
    timeout_seconds: int = 60
    max_length: int = 20000

    def validate(self):
        if self.direction not in ("up", "down"):
            raise ValueError("Invalid scrolling direction")
        for value, lower, upper in ((self.wheel_steps,1,5), (self.interval_ms,250,3000),
                                    (self.max_steps,1,200), (self.timeout_seconds,5,180),
                                    (self.max_length,1000,100000)):
            if type(value) is not int or not lower <= value <= upper:
                raise ValueError("Invalid automatic scroll limits")


@dataclass(frozen=True)
class ScrollTarget:
    hwnd: int
    root: int
    pid: int
    point: tuple
    frame: tuple

    @classmethod
    def bind(cls, region):
        point = win32api.GetCursorPos()
        if not region.contains(*point):
            raise ValueError("Pointer is outside the capture region")
        hwnd = win32gui.WindowFromPoint(point)
        root = win32gui.GetAncestor(hwnd, win32con.GA_ROOT)
        pid = win32process.GetWindowThreadProcessId(root)[1]
        target = cls(hwnd, root, pid, point, tuple(get_window_rect_no_shadow(root)))
        target.validate(region)
        return target

    def validate(self, region):
        from PySide6.QtCore import QRect
        if not self.hwnd or not self.root or self.pid == os.getpid():
            raise ValueError("An external target window is required")
        if (not win32gui.IsWindow(self.hwnd) or not win32gui.IsWindow(self.root)
                or not win32gui.IsWindowVisible(self.root) or win32gui.IsIconic(self.root)):
            raise ValueError("Target window closed or hidden")
        if (win32process.GetWindowThreadProcessId(self.hwnd)[1] != self.pid
                or win32process.GetWindowThreadProcessId(self.root)[1] != self.pid
                or win32gui.GetAncestor(self.hwnd, win32con.GA_ROOT) != self.root):
            raise ValueError("Target window identity changed")
        if win32gui.GetAncestor(win32gui.GetForegroundWindow(), win32con.GA_ROOT) != self.root:
            raise ValueError("Target is no longer foreground")
        if tuple(get_window_rect_no_shadow(self.root)) != self.frame:
            raise ValueError("Target window moved")
        if win32gui.WindowFromPoint(self.point) != self.hwnd:
            raise ValueError("Scroll point was obscured or replaced")
        left, top, right, bottom = self.frame
        if not QRect(left,top,right-left,bottom-top).contains(region):
            raise ValueError("Capture region extends outside the selected window")
        # WM_MOUSEWHEEL screen coordinates are signed 16-bit values. Reject truncation.
        if any(not -32768 <= value <= 32767 for value in self.point):
            raise ValueError("Scroll point exceeds the native message coordinate range")

    def scroll(self, region, axis, direction, steps):
        self.validate(region)  # Revalidate immediately before the bounded, addressed message.
        delta = steps * 120 * (1 if direction == "down" else -1)
        if axis == "vertical":
            delta = -delta
        message = win32con.WM_MOUSEWHEEL if axis == "vertical" else WM_MOUSEHWHEEL
        wparam = (delta & 0xffff) << 16
        lparam = (self.point[0] & 0xffff) | ((self.point[1] & 0xffff) << 16)
        # An ignored/denied message results in an unchanged frame and stops, never retries globally.
        win32gui.SendMessageTimeout(self.hwnd, message, wparam, lparam,
                                   win32con.SMTO_ABORTIFHUNG | win32con.SMTO_BLOCK, 100)


class AutoScrollController(QObject):
    changed = Signal(bool, str)

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.active = False
        self.phase = "idle"
        self.target = None
        self.options = None
        self.steps = 0
        self._listener = None
        self._cancel = threading.Event()
        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._tick)
        self._next = self._deadline = 0.0
        self._last_countdown = None

    def _start_cancel_listener(self):
        from pynput import keyboard
        token = self._cancel
        def pressed(key):
            if key == keyboard.Key.esc:
                token.set()
        self._listener = keyboard.Listener(on_press=pressed)
        self._listener.start()

    def start(self, options):
        options.validate()
        if self.window._closing:
            raise ValueError("Capture session is closed")
        if self.active:
            return False
        state = self.window._stitch_session.state
        if state.result is None or state.direction not in (None, options.direction):
            raise ValueError("Capture a starting frame and use its current direction")
        self.options, self.steps, self.target = options, 0, None
        self._cancel = threading.Event()
        self.phase, self.active = "arming", True
        self._next = time.monotonic() + 3
        self._deadline = self._next + options.timeout_seconds
        self._last_countdown = None
        self.window.capture_timer.stop()
        self.window.scroll_check_timer.stop()
        self.window._stop_keyboard_listener()
        try:
            self._start_cancel_listener()
        except Exception:
            self.stop("Automatic scrolling could not start: the cancel key is unavailable.")
            raise
        self.changed.emit(True, "Activate the target and put the pointer inside the capture region within 3 seconds. Esc stops.")
        self._timer.start()
        return True

    def stop(self, reason="Automatic scrolling stopped. Existing content was kept."):
        if not self.active and self._listener is None:
            return
        was_active = self.active
        self.active, self.phase = False, "idle"
        self._cancel.set()
        self._timer.stop()
        self.target = None
        if self._listener is not None:
            self._listener.stop()
            self._listener.join(timeout=1)
            self._listener = None
        if was_active:
            self.changed.emit(False, reason)

    def _limit(self, now):
        state = self.window._stitch_session.state
        if now >= self._deadline:
            return "Automatic scrolling reached the time limit."
        if self.steps >= self.options.max_steps:
            return "Automatic scrolling reached the frame limit."
        length = state.result.height if self.window.scroll_direction == "vertical" else state.result.width
        if length >= self.options.max_length:
            return "Automatic scrolling reached the image length limit."
        return None

    def _tick(self):
        if not self.active:
            return
        if self._cancel.is_set():
            self.stop()
            return
        if self.window._closing or self.window._adjustment_dialog is not None:
            self.stop()
            return
        if self._listener is not None and not self._listener.is_alive():
            self.stop("Automatic scrolling stopped because the cancel key became unavailable.")
            return
        now = time.monotonic()
        try:
            if self.phase == "arming":
                if now < self._next:
                    remaining = math.ceil(self._next-now)
                    if remaining != self._last_countdown:
                        self._last_countdown = remaining
                        self.changed.emit(True, "Activate the target and put the pointer inside the capture region within 3 seconds. Esc stops.")
                    return
                self.target = ScrollTarget.bind(self.window.capture_rect)
                # Refresh the baseline if the page changed during setup, without discarding prior content.
                outcome = self.window._do_capture()
                if outcome not in ("added", "duplicate"):
                    self.stop("Automatic scrolling stopped: the starting frame did not match the preview.")
                    return
                self.phase = "scroll"
            self.target.validate(self.window.capture_rect)
            if self._cancel.is_set():
                self.stop()
                return
            if now >= self._deadline:
                self.stop("Automatic scrolling reached the time limit.")
                return
            if time.monotonic() < self._next:
                return
            if self.phase == "capture":
                outcome = self.window._do_capture()
                if self._cancel.is_set():
                    self.stop()
                    return
                if outcome == "duplicate":
                    self.stop("Automatic scrolling stopped: the frame did not change (end of page or unsupported target).")
                    return
                if outcome != "added":
                    self.stop("Automatic scrolling stopped: overlap failed. Review or repair the last seam.")
                    return
                self.phase = "scroll"
            reason = self._limit(time.monotonic())
            if reason:
                self.stop(reason)
                return
            if self._cancel.is_set():
                self.stop()
                return
            self.target.scroll(self.window.capture_rect, self.window.scroll_direction,
                               self.options.direction, self.options.wheel_steps)
            self.steps += 1
            self.phase = "capture"
            self._next = time.monotonic() + max(self.options.interval_ms/1000, self.window.scroll_cooldown)
            self.changed.emit(True, "Automatic scrolling is running. Esc or Stop ends it without discarding images.")
        except Exception:
            self.stop("Automatic scrolling stopped: target focus, position, or input access changed.")
