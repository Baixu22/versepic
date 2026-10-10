"""Opt-in Windows native acceptance with a separate, synthetic target process.

Run: python main/tests/native_delayed_capture.py --run --output <directory>
Only synthetic window crops are saved; no clipboard/history or personal settings.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def target(directory):
    from PySide6.QtCore import QTimer, QPoint
    from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel, QPushButton, QMenu, QToolTip
    app = QApplication([])
    win = QWidget()
    win.setWindowTitle("VersePic isolated capture acceptance")
    win.setStyleSheet("QWidget { background: #f7f7f7; color: #171717; font-size: 18px; }")
    layout = QVBoxLayout(win)
    layout.addWidget(QLabel("Synthetic screenshot target — no personal data"))
    button = QPushButton("Menu and tooltip capture sample")
    layout.addWidget(button)
    layout.addStretch()
    win.setGeometry(80, 100, 720, 440)
    menu = QMenu(win)
    menu.setStyleSheet("QMenu { background: #2ec46d; color: black; padding: 12px; }"
                      "QMenu::item { padding: 10px 30px; }")
    menu.addAction("Synthetic menu item")
    menu.addAction("Delayed capture should keep this visible")
    win.show()
    win.raise_()
    win.activateWindow()
    state = {"sequence": -1}

    def report():
        rect = win.frameGeometry()
        result = {"hwnd": int(win.winId()), "pid": os.getpid(),
                  "rect": [rect.x(), rect.y(), rect.width(), rect.height()], "sequence": state["sequence"]}
        if menu.isVisible():
            r = menu.frameGeometry()
            result["sample"] = [r.x() + r.width() - 16, r.y() + 16]
            result["kind"] = "menu"
        for widget in QApplication.topLevelWidgets():
            if widget.inherits("QTipLabel") and widget.isVisible():
                r = widget.frameGeometry()
                result["sample"] = [r.x() + r.width() - 10, r.y() + 5]
                result["kind"] = "tooltip"
        temp = directory / "target.tmp"
        temp.write_text(json.dumps(result), encoding="utf-8")
        os.replace(temp, directory / "target.json")

    def poll():
        try:
            command = json.loads((directory / "command.json").read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return
        if command["sequence"] == state["sequence"]:
            return
        state["sequence"] = command["sequence"]
        menu.hide()
        QToolTip.hideText()
        if command["kind"] == "quit":
            app.quit()
            return
        if command["kind"] == "menu":
            menu.popup(win.mapToGlobal(QPoint(45, 190)))
        elif command["kind"] == "tooltip":
            QToolTip.showText(win.mapToGlobal(QPoint(55, 260)), "Synthetic tooltip for delayed screenshot", win,
                              msecShowTime=10000)
        QTimer.singleShot(180, report)

    timer = QTimer(win)
    timer.timeout.connect(poll)
    timer.start(30)
    QTimer.singleShot(200, report)
    app.exec()


def verify(directory):
    os.environ["QT_QPA_PLATFORM"] = "windows"
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from PySide6.QtCore import QObject, QSettings, QTranslator
    from PySide6.QtWidgets import QApplication
    import win32gui
    import win32process
    from pynput.keyboard import Controller, Key
    from settings import get_tool_settings_manager
    from core.ui_theme import get_ui_theme
    from main_app import MainApp

    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    config = get_tool_settings_manager(QSettings(str(directory / "settings.ini"), QSettings.Format.IniFormat))
    config.set_clipboard_db_path(str(directory / "unused-clipboard.db"))
    theme = get_ui_theme().init(config, app)
    translator = QTranslator()
    assert translator.load(str(Path(__file__).resolve().parents[1] / "translations/app_zh.qm"))
    app.installTranslator(translator)
    controller = MainApp.__new__(MainApp)
    QObject.__init__(controller)
    controller.app = app
    controller.config_manager = config
    controller.screenshot_window = None
    controller.clipboard_window = None
    controller._capture_thread = None
    controller._capture_countdown = None
    controller._quitting = False
    controller.tray_icon = None
    captures = []
    controller._on_capture_ready = lambda image, rect: captures.append((image, rect, time.monotonic()))
    (directory / "target.json").write_text("{}", encoding="utf-8")
    (directory / "command.json").write_text(
        json.dumps({"sequence": 0, "kind": "idle"}), encoding="utf-8")
    process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--target", "--output", str(directory)],
                               creationflags=subprocess.CREATE_NO_WINDOW)
    sequence = 0
    original_foreground = win32gui.GetForegroundWindow()

    def wait(predicate, seconds=8):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            app.processEvents()
            if predicate():
                return
            time.sleep(0.01)
        raise AssertionError("Native acceptance condition timed out")

    def pause(seconds):
        start = time.monotonic()
        wait(lambda: time.monotonic() - start >= seconds, seconds + 1)

    def state():
        try:
            return json.loads((directory / "target.json").read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def command(kind):
        nonlocal sequence
        sequence += 1
        (directory / "command.json").write_text(json.dumps({"sequence": sequence, "kind": kind}), encoding="utf-8")
        wait(lambda: state().get("sequence") == sequence and state().get("kind") == kind)
        return state()

    def target_is_foreground():
        return win32process.GetWindowThreadProcessId(win32gui.GetForegroundWindow())[1] == state().get("pid")

    def focus_target():
        keyboard = Controller()
        keyboard.press(Key.alt)
        keyboard.release(Key.alt)
        win32gui.SetForegroundWindow(state()["hwnd"])
        wait(target_is_foreground)
        pause(0.25)

    results = []
    try:
        wait(lambda: bool(state().get("hwnd")))
        for mode, kind in [("light", "menu"), ("dark", "tooltip")]:
            theme.set_mode(mode, persist=False)
            focus_target()
            info = command(kind)
            wait(target_is_foreground)
            before = len(captures)
            started = time.monotonic()
            controller.start_delayed_screenshot(3)
            countdown = controller._capture_countdown
            pause(0.2)
            assert target_is_foreground(), "Countdown stole foreground focus"
            assert countdown._listener is not None and countdown._listener.is_alive()
            assert countdown.grab().save(str(directory / f"countdown-{mode}.png"))
            # Move the excluded overlay over our own synthetic target, not personal content.
            x, y, width, height = info["rect"]
            countdown.move(x + width - countdown.width() - 15, y + 65)
            wait(lambda previous=before: len(captures) > previous)
            image, desktop, captured_at = captures[-1]
            elapsed = captured_at - started
            assert 3 <= elapsed < 6, elapsed
            crop = image.copy(x - int(desktop.x()), y - int(desktop.y()), width, height)
            assert crop.save(str(directory / f"captured-{kind}.png"))
            # Ensure the overlay has disappeared and the requested external menu/tip remains.
            assert not countdown.isVisible() and not countdown.is_pending
            assert state()["kind"] == kind
            sx, sy = info["sample"]
            color = image.pixelColor(sx - int(desktop.x()), sy - int(desktop.y()))
            if kind == "menu":
                assert color.name() == "#2ec46d", color.name()
            else:
                assert color.name() != "#f7f7f7", "Tooltip pixels were not captured"
            results.append({"check": kind + " capture", "elapsed_seconds": round(elapsed, 3),
                            "foreground_pid": info["pid"], "sample_color": color.name(), "passed": True})
            image = crop = None
            captures.clear()  # Do not retain the full virtual desktop after validating the crop.

        focus_target()
        command("menu")
        wait(target_is_foreground)
        controller.start_delayed_screenshot(3)
        pause(0.15)
        assert target_is_foreground()
        keyboard = Controller()
        keyboard.press(Key.esc)
        pause(0.08)
        keyboard.release(Key.esc)
        wait(lambda: not controller._capture_countdown.is_pending)
        pause(3.2)
        assert captures == []
        assert controller._capture_countdown._listener is None
        results.append({"check": "Esc from separate foreground process cancels capture", "passed": True})
        (directory / "result.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(results, ensure_ascii=False, indent=2))
    finally:
        controller._cancel_pending_capture()
        if controller._capture_thread:
            assert controller._capture_thread.wait(5000)
        if controller._capture_countdown:
            controller._capture_countdown.close()
        captures.clear()
        (directory / "command.json").write_text(
            json.dumps({"sequence": sequence + 1, "kind": "quit"}), encoding="utf-8")
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.terminate()
            process.wait(timeout=5)
        if win32gui.IsWindow(original_foreground):
            try:
                win32gui.SetForegroundWindow(original_foreground)
            except Exception:
                pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="store_true", help="Explicitly allow temporary native test windows")
    parser.add_argument("--target", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    os.environ["QT_QPA_PLATFORM"] = "windows"
    os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "0"
    os.environ["QT_SCALE_FACTOR"] = "1"
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from core.platform_utils import set_dpi_awareness
    set_dpi_awareness()
    if args.target:
        target(args.output)
    elif args.run:
        verify(args.output)
    else:
        parser.error("Native acceptance requires --run")
