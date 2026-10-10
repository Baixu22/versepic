"""Delayed capture: cancellation, scheduling and the real MainApp entry chain."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QDialog

from main_app import MainApp
from ui.capture_countdown import CaptureCountdown


@pytest.fixture
def countdown(qtbot, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr("ui.capture_countdown.time.monotonic", lambda: clock[0])
    monkeypatch.setattr(CaptureCountdown, "_start_escape_listener", lambda self: None)
    widget = CaptureCountdown()
    qtbot.addWidget(widget)
    yield widget, clock
    widget.cancel()


@pytest.mark.parametrize("seconds", [3, 5, 10])
def test_countdown_uses_deadline_and_fires_once_after_hiding(countdown, qtbot, seconds):
    widget, clock = countdown
    states = []
    widget.finished.connect(lambda: states.append((widget.isVisible(), widget.is_pending)))
    widget.start(seconds)
    assert widget.is_pending and widget.isVisible()
    assert str(seconds) in widget.label.text()
    clock[0] += seconds + 0.4  # event-loop delays must not lengthen a countdown
    widget._tick()
    assert not widget.isVisible() and states == []
    qtbot.waitUntil(lambda: len(states) == 1)
    widget._finish()
    widget._tick()
    assert states == [(False, False)]
    assert not widget._timer.isActive() and not widget._settle.isActive()


@pytest.mark.parametrize("invalid", [0, 1, -1, 60, "3", None])
def test_invalid_delays_do_not_start(countdown, invalid):
    widget, _ = countdown
    with pytest.raises(ValueError):
        widget.start(invalid)
    assert not widget.is_pending


def test_duplicate_start_keeps_the_original_deadline(countdown):
    widget, clock = countdown
    widget.start(3)
    deadline = widget._deadline
    clock[0] += 1
    widget.start(10)
    assert widget._deadline == deadline


@pytest.mark.parametrize("cancel_by", ["button", "escape", "close", "method"])
def test_cancel_prevents_capture_and_allows_reuse(countdown, qtbot, cancel_by):
    widget, clock = countdown
    captures = []
    widget.finished.connect(lambda: captures.append(True))
    widget.start(3)
    if cancel_by == "button":
        qtbot.mouseClick(widget.cancel_button, Qt.MouseButton.LeftButton)
    elif cancel_by == "escape":
        qtbot.keyClick(widget, Qt.Key.Key_Escape)
    elif cancel_by == "close":
        widget.close()
    else:
        widget.cancel()
    clock[0] += 5
    widget._tick()
    qtbot.wait(140)
    assert captures == [] and not widget.is_pending and not widget.isVisible()
    widget.start(5)
    assert widget.is_pending and widget.isVisible()


def test_cancel_during_compositor_settle_prevents_capture(countdown, qtbot):
    widget, clock = countdown
    captures = []
    widget.finished.connect(lambda: captures.append(True))
    widget.start(3)
    clock[0] += 3
    widget._tick()
    widget.cancel()
    qtbot.wait(140)
    assert captures == []


def test_countdown_never_requests_focus(countdown):
    widget, _ = countdown
    assert widget.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    assert widget.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus


@pytest.fixture
def main(qapp, monkeypatch):
    app = MainApp.__new__(MainApp)
    QObject.__init__(app)
    app.app = qapp
    app.screenshot_window = None
    app.clipboard_window = None
    app.clipboard_manager = None
    app._capture_countdown = None
    app._quitting = False
    app._capture_thread = None
    app.tray_icon = Mock()
    app.config_manager = Mock()
    app._on_capture_ready = Mock()
    monkeypatch.setattr(CaptureCountdown, "_start_escape_listener", lambda self: None)
    yield app
    app._cancel_pending_capture()
    if app._capture_thread:
        assert app._capture_thread.wait(5000)
    if app._capture_countdown:
        app._capture_countdown.close()
        app._capture_countdown.deleteLater()
    app.deleteLater()


def test_delayed_entry_runs_production_capture_thread_once(main, monkeypatch, qtbot):
    capture = Mock(return_value=(QImage(20, 20, QImage.Format.Format_RGB32), None))
    monkeypatch.setattr("capture.capture_service.CaptureService.capture_all_screens", capture)
    main.start_delayed_screenshot(3)
    main.start_delayed_screenshot(5)
    main.start_screenshot()  # normal shortcut must not bypass the pending countdown
    assert not capture.called
    widget = main._capture_countdown
    widget._deadline = 0
    widget._tick()
    qtbot.waitUntil(lambda: main._on_capture_ready.called)
    assert capture.call_count == 1
    assert not widget.is_pending and not widget.isVisible()


def test_shutdown_cancels_delayed_callback(main, qtbot):
    main.start_delayed_screenshot(3)
    main._cancel_pending_capture()
    main._capture_countdown._finish()
    main.start_screenshot()
    assert main._capture_thread is None
    assert not main._capture_countdown.is_pending


def test_live_capture_session_does_not_start_another_countdown(main):
    main.screenshot_window = SimpleNamespace(_session_active=True)
    main.start_screenshot = Mock()
    main.start_delayed_screenshot(3)
    main.start_screenshot.assert_called_once()
    assert main._capture_countdown is None


def test_sensitive_start_cancels_pending_delayed_ordinary_capture(main, monkeypatch):
    main.start_screenshot = Mock()
    monkeypatch.setattr("core.capture_privacy.ensure_supported", lambda parent=None: True)
    main.start_delayed_screenshot(5)
    assert main._capture_countdown is not None and main._capture_countdown.is_pending
    main.start_sensitive_screenshot()
    assert not main._capture_countdown.is_pending
    main.start_screenshot.assert_called_once_with(sensitive=True)


def test_capture_in_flight_does_not_start_a_countdown(main):
    main._capture_thread = Mock(isRunning=Mock(return_value=True))
    main.start_delayed_screenshot(3)
    assert main._capture_countdown is None
    main._capture_thread = None


def test_modal_window_blocks_scheduling(main, qtbot):
    dialog = QDialog()
    qtbot.addWidget(dialog)
    dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
    dialog.show()
    assert QApplication.activeModalWidget() is dialog
    main.start_delayed_screenshot(3)
    assert main._capture_countdown is None
    dialog.close()


def test_capture_error_is_reported_and_can_be_retried(main, monkeypatch, qtbot):
    capture = Mock(side_effect=RuntimeError("synthetic capture failure"))
    monkeypatch.setattr("capture.capture_service.CaptureService.capture_all_screens", capture)
    main.start_screenshot()
    qtbot.waitUntil(lambda: main.tray_icon.showMessage.called)
    assert main._capture_thread.wait(5000)
    capture.side_effect = None
    capture.return_value = (QImage(), None)
    main.start_screenshot()
    qtbot.waitUntil(lambda: main._on_capture_ready.called)
    assert capture.call_count == 2


def test_tray_delays_retain_each_menu_value(qtbot, main):
    from ui.tray_menu import create_tray_menu
    main.open_clipboard_window = Mock()
    main.open_translator = Mock()
    main.set_global_hotkeys_disabled = Mock()
    main.open_settings = Mock()
    main.quit_app = Mock()
    main.config_manager.get_app_setting.return_value = False
    main.start_delayed_screenshot = Mock()
    menu = create_tray_menu(main)
    qtbot.addWidget(menu)
    submenu = menu.actions()[1].menu()
    assert len(submenu.actions()) == 3
    for action in submenu.actions():
        action.trigger()
    assert [call.args[0] for call in main.start_delayed_screenshot.call_args_list] == [3, 5, 10]


def test_modal_opened_during_countdown_prevents_capture(main, qtbot, monkeypatch):
    capture = Mock()
    monkeypatch.setattr("capture.capture_service.CaptureService.capture_all_screens", capture)
    main.start_delayed_screenshot(3)
    dialog = QDialog()
    qtbot.addWidget(dialog)
    dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
    dialog.show()
    main._capture_countdown._deadline = 0
    main._capture_countdown._tick()
    qtbot.waitUntil(lambda: not main._capture_countdown.is_pending)
    assert not capture.called
    dialog.close()


def test_global_listener_failure_cancels_instead_of_uncancellable_capture(countdown):
    widget, _ = countdown
    failed = []
    widget.failed.connect(lambda: failed.append(True))
    widget.start(3)
    listener = Mock(is_alive=Mock(return_value=False))
    widget._listener = listener
    widget._tick()
    assert not widget.is_pending and failed == [True]
    listener.stop.assert_called_once()
    listener.join.assert_called_once()


def test_late_capture_result_after_shutdown_never_creates_a_window(main):
    main._cancel_pending_capture()
    MainApp._on_capture_ready(main, QImage(), None)
    assert main.screenshot_window is None


@pytest.mark.parametrize("language", ["zh", "en", "ja", "ko"])
def test_compiled_countdown_and_tray_translations(qapp, language):
    from pathlib import Path
    from PySide6.QtCore import QTranslator
    translator = QTranslator()
    resource = Path(__file__).resolve().parents[1] / "translations" / f"app_{language}.qm"
    assert translator.load(str(resource))
    for context, source in [
        ("CaptureCountdown", "Screenshot in %1 s"),
        ("CaptureCountdown", "Open a menu or tooltip. Esc cancels."),
        ("CaptureCountdown", "Cancel"),
        ("SystemTray", "Delayed screenshot"),
        ("SystemTray", "After %1 seconds"),
        ("MainApp", "Screenshot failed"),
        ("MainApp", "Could not capture the screen. Please try again."),
    ]:
        assert translator.translate(context, source), (language, context, source)


def test_queued_escape_from_previous_session_cannot_cancel_new_countdown(countdown):
    widget, _ = countdown
    widget.start(3)
    old_generation = widget._generation
    widget.cancel()
    widget.start(5)
    widget.cancel_requested.emit(old_generation)
    assert widget.is_pending
    widget.cancel_requested.emit(widget._generation)
    assert not widget.is_pending


def test_reused_countdown_refreshes_language(countdown, monkeypatch):
    widget, _ = countdown
    widget.start(3)
    widget.cancel()
    monkeypatch.setattr(CaptureCountdown, "tr", lambda self, text: "new:" + text)
    widget.start(3)
    assert widget.hint.text().startswith("new:")
    assert widget.cancel_button.text() == "new:Cancel"
    assert widget.label.text().startswith("new:")
