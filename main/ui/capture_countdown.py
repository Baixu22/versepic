"""A non-activating, cancellable countdown for menu and tooltip captures."""

import math
import time

from PySide6.QtCore import QEvent, QTimer, Qt, Signal
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QVBoxLayout

from core.logger import log_exception
from core.ui_scale import dialog_scaled, scale_dialog_font
from core.ui_theme import get_ui_theme
from ui.fluent_lite import BodyLabel, CaptionLabel, PushButton


class CaptureCountdown(QFrame):
    finished = Signal()
    failed = Signal()
    cancel_requested = Signal(int)

    def __init__(self):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setObjectName("CaptureCountdown")
        scale_dialog_font(self)
        self._pending = False
        self._generation = 0
        self._listener = None
        self._deadline = 0.0
        self.label = BodyLabel(self)
        self.label.setTypography(18, 600)
        self.hint = CaptionLabel(self.tr("Open a menu or tooltip. Esc cancels."), self)
        self.cancel_button = PushButton(self.tr("Cancel"), self)
        self.cancel_button.clicked.connect(self.cancel)
        self.cancel_requested.connect(self._cancel_generation)
        row = QHBoxLayout()
        row.addWidget(self.label, 1)
        row.addWidget(self.cancel_button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(*[dialog_scaled(16)] * 4)
        layout.setSpacing(dialog_scaled(8))
        layout.addLayout(row)
        layout.addWidget(self.hint)
        self.setMinimumWidth(dialog_scaled(320))
        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._tick)
        # Keep cancellation live while the hidden window leaves the compositor.
        self._settle = QTimer(self)
        self._settle.setSingleShot(True)
        self._settle.setInterval(100)
        self._settle.timeout.connect(self._finish)
        get_ui_theme().theme_changed.connect(self._apply_theme)
        self._apply_theme()

    @property
    def is_pending(self):
        return self._pending

    def _apply_theme(self, *_):
        t = get_ui_theme().tokens
        self.setStyleSheet(f"QFrame#CaptureCountdown {{ background: {t.surface}; "
                           f"border: 1px solid {t.border}; border-radius: {dialog_scaled(10)}px; }}")

    def start(self, seconds):
        if seconds not in (3, 5, 10):
            raise ValueError("Capture delay must be 3, 5 or 10 seconds")
        if self._pending:
            return
        self._pending = True
        self._generation += 1
        self.hint.setText(self.tr("Open a menu or tooltip. Esc cancels."))
        self.cancel_button.setText(self.tr("Cancel"))
        self._deadline = time.monotonic() + seconds
        QApplication.instance().installEventFilter(self)
        self._start_escape_listener()
        self._tick()
        self.adjustSize()
        screen = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        bounds = screen.availableGeometry()
        margin = dialog_scaled(24)
        self.move(max(bounds.left(), bounds.right() - self.width() - margin), bounds.top() + margin)
        if QApplication.platformName() == "windows":
            from core.platform_utils import set_window_exclude_from_capture
            set_window_exclude_from_capture(int(self.winId()), True)
        self.show()
        self._timer.start()

    def _start_escape_listener(self):
        if QApplication.platformName() != "windows":
            return
        try:
            from pynput import keyboard
            generation = self._generation

            def on_press(key):
                if key == keyboard.Key.esc:
                    self.cancel_requested.emit(generation)

            self._listener = keyboard.Listener(on_press=on_press)
            self._listener.start()
        except Exception as exc:
            # Never leave a countdown running with a broken global cancel key.
            log_exception(exc, "Capture countdown keyboard listener")
            self.cancel()
            raise

    def _tick(self):
        if not self._pending:
            return
        if self._listener is not None and not self._listener.is_alive():
            self.cancel()
            self.failed.emit()
            return
        remaining = max(0, math.ceil(self._deadline - time.monotonic()))
        self.label.setText(self.tr("Screenshot in %1 s").replace("%1", str(remaining)))
        if remaining == 0:
            self._timer.stop()
            self.hide()
            self._settle.start()

    def _stop(self):
        self._pending = False
        self._timer.stop()
        self._settle.stop()
        self.hide()
        QApplication.instance().removeEventFilter(self)
        if self._listener is not None:
            self._listener.stop()
            self._listener.join(timeout=1)
            self._listener = None

    def _cancel_generation(self, generation):
        if generation == self._generation:
            self.cancel()

    def cancel(self):
        self._stop()

    def _finish(self):
        if self._pending:
            self._stop()
            self.finished.emit()

    def eventFilter(self, obj, event):
        if self._pending and event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape:
            self.cancel()
        return False

    def closeEvent(self, event):
        self.cancel()
        super().closeEvent(event)
