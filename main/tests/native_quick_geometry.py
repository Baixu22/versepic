"""Opt-in native quick capture and precise-region acceptance, using a separate demo process."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def run(directory):
    from PySide6.QtCore import QObject, QPoint, QRect, QSettings, QTimer, Qt, QTranslator
    from PySide6.QtGui import QBrush, QColor, QPen
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    import win32api
    import win32gui
    import win32con
    import win32process
    from pynput.keyboard import Controller, Key
    from capture.quick_capture import make_quick_capture_request
    from clipboard.controllers.foreground_tracker import ForegroundWindowTracker, get_window_pid
    from core import clipboard_utils
    from core.last_capture_region import set_last_region
    from core.shortcut_manager import HotkeySystem
    from core.ui_theme import get_ui_theme
    from main_app import MainApp
    from settings import get_tool_settings_manager

    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    config = get_tool_settings_manager(QSettings(str(directory / "settings.ini"), QSettings.Format.IniFormat))
    config.set_clipboard_db_path(str(directory / "unused-clipboard.db"))
    config.set_clipboard_enabled(False)
    config.set_screenshot_save_enabled(False)
    config.set_smart_selection(False)
    config.set_hotkey("")
    config.set_hotkey_2("")
    config.set_app_setting("quick_capture_result", "copy")
    config.set_app_setting("quick_window_hotkey", "ctrl+alt+shift+f11")
    theme = get_ui_theme().init(config, app)
    translator = QTranslator()
    assert translator.load(str(Path(__file__).resolve().parents[1] / "translations/app_zh.qm"))
    app.installTranslator(translator)
    main = MainApp.__new__(MainApp)
    QObject.__init__(main)
    main.app = app
    main.config_manager = config
    main.screenshot_window = None
    main.clipboard_window = None
    main._capture_thread = None
    main._capture_countdown = None
    main._quitting = False
    main._capture_busy = False
    main.tray_icon = None
    main.hotkey_system = HotkeySystem()
    main._capture_foreground_tracker = ForegroundWindowTracker()
    main._capture_foreground_tracker.set_excluded(lambda hwnd: get_window_pid(hwnd) == os.getpid())
    main._capture_foreground_tracker.start()
    outputs = []
    original_delivery = clipboard_utils.deliver_image_async
    clipboard_utils.deliver_image_async = lambda image, **kwargs: outputs.append(image.copy())
    keyboard = Controller()
    previous_foreground = win32gui.GetForegroundWindow()
    previous_cursor = win32api.GetCursorPos()
    (directory / "target.json").write_text("{}", encoding="utf-8")
    (directory / "command.json").write_text(json.dumps({"sequence": 0, "kind": "idle"}), encoding="utf-8")
    target = subprocess.Popen([sys.executable, str(Path(__file__).with_name("native_delayed_capture.py")),
                               "--target", "--output", str(directory)], creationflags=subprocess.CREATE_NO_WINDOW)
    results = []

    def state():
        try:
            return json.loads((directory / "target.json").read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def wait(predicate, seconds=10):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            app.processEvents()
            if predicate():
                return
            time.sleep(0.01)
        raise AssertionError("Native quick-capture condition timed out")

    def pause(seconds):
        started = time.monotonic()
        wait(lambda: time.monotonic() - started >= seconds, seconds + 1)

    def focus_target():
        keyboard.press(Key.alt)
        keyboard.release(Key.alt)
        win32gui.SetForegroundWindow(state()["hwnd"])
        wait(lambda: win32process.GetWindowThreadProcessId(win32gui.GetForegroundWindow())[1] == state()["pid"])
        pause(0.25)
        main._capture_foreground_tracker.sample()

    def copy(kind):
        before = len(outputs)
        main.start_quick_capture(kind)
        wait(lambda: len(outputs) == before + 1)
        assert main._capture_thread.wait(5000)
        return outputs[-1]

    try:
        wait(lambda: bool(state().get("hwnd")))
        focus_target()
        info = state()
        request = make_quick_capture_request("window", hwnd=info["hwnd"])
        expected = request.resolve()
        main.update_hotkey()
        assert main.hotkey_system.has_registered_hotkeys(), "Test hotkey was unavailable"
        for key in (Key.ctrl, Key.alt, Key.shift, Key.f11):
            keyboard.press(key)
        for key in (Key.f11, Key.shift, Key.alt, Key.ctrl):
            keyboard.release(key)
        wait(lambda: len(outputs) == 1)
        assert outputs[-1].size() == expected.size()
        assert outputs[-1].save(str(directory / "quick-window.png"))
        results.append({"check": "registered native hotkey captures external active window",
                        "size": [expected.width(), expected.height()], "passed": True})

        from ui.tray_menu import create_tray_menu
        menu = create_tray_menu(main)
        quick_menu = menu.quick_capture_menu
        before = len(outputs)
        quick_menu.popup(QPoint(expected.right() + 20, expected.top() + 40))
        pause(0.15)
        assert quick_menu.grab().save(str(directory / "quick-menu.png"))
        QTest.mouseClick(quick_menu, Qt.MouseButton.LeftButton, pos=quick_menu.actionGeometry(quick_menu.actions()[1]).center())
        wait(lambda: len(outputs) == before + 1)
        assert outputs[-1].size() == expected.size()
        menu.close()
        menu.deleteLater()
        results.append({"check": "native tray menu preserves external target and captures after closing", "passed": True})

        before = len(outputs)
        frozen_target = make_quick_capture_request("window", hwnd=info["hwnd"], action="copy")
        win32gui.ShowWindow(info["hwnd"], win32con.SW_MINIMIZE)
        pause(0.15)
        main.start_screenshot(request=frozen_target)
        pause(0.2)
        assert len(outputs) == before and not main._capture_busy
        win32gui.ShowWindow(info["hwnd"], win32con.SW_RESTORE)
        focus_target()
        results.append({"check": "minimized target is rejected rather than replaced by another area", "passed": True})

        selected = QRect(expected.x() + 80, expected.y() + 170, 240, 160)
        set_last_region(selected)
        last = copy("last")
        assert (last.width(), last.height()) == (240, 160)
        assert last.save(str(directory / "quick-last-region.png"))
        results.append({"check": "last-region copy dimensions", "size": [240, 160], "passed": True})

        win32api.SetCursorPos((expected.x() + 100, expected.y() + 300))
        screen_request = make_quick_capture_request("screen", point=QPoint(*win32api.GetCursorPos()))
        screen = copy("screen")
        assert screen.size() == screen_request.resolve().size()
        results.append({"check": "screen capture matches physical monitor size", "passed": True})
        outputs.clear()  # Never write the full desktop capture to disk.
        screen = None

        set_last_region(expected)
        config.set_app_setting("quick_capture_result", "edit")
        main.start_quick_capture("last")
        wait(lambda: main.screenshot_window is not None and main.screenshot_window._session_active)
        window = main.screenshot_window
        assert window.scene.selection_model.rect().toAlignedRect() == expected
        results.append({"check": "quick capture opens actual editor with correct preselection", "passed": True})
        controller = window.info_controller
        annotation = window.scene.addRect(
            expected.x() + 100, expected.y() + 210, 25, 25,
            QPen(Qt.PenStyle.NoPen), QBrush(QColor("red")))
        old_annotation = annotation.rect()
        errors = []
        for mode, width, height in (("light", 237, 119), ("dark", 320, 180)):
            theme.set_mode(mode, persist=False)

            def edit(w=width, h=height, theme_mode=mode):
                dialog = controller._geometry_dialog
                try:
                    assert dialog is not None and QApplication.activeModalWidget() is dialog
                    values = {"x": expected.x() + 80, "y": expected.y() + 190, "width": w, "height": h}
                    for name, value in values.items():
                        field = dialog.fields[name]
                        field.setFocus()
                        field.selectAll()
                        QTest.keyClicks(field, str(value))
                        QTest.keyClick(field, Qt.Key.Key_Tab)
                    if theme_mode == "dark":
                        dialog.ratio_combo.setCurrentIndex(3)
                    assert dialog.grab().save(str(directory / f"exact-region-{theme_mode}.png"))
                    assert dialog.apply_button.isEnabled()
                    QTest.mouseClick(dialog.apply_button, Qt.MouseButton.LeftButton)
                except Exception as exc:
                    errors.append(str(exc))
                    dialog.reject()

            QTimer.singleShot(150, edit)
            assert not window.info_panel.btn_geometry.icon().isNull()
            window.info_panel.btn_geometry.click()
            assert not errors, errors
            rect = window.scene.selection_model.rect()
            assert (rect.width(), rect.height()) == (width, height)
            assert annotation.rect() == old_annotation
            output = window.action_handler.export_service.export(rect)
            assert output.width() == width and output.height() == height
            assert output.pixelColor(25, 25).name() == "#ff0000"
            assert output.save(str(directory / f"exact-output-{mode}.png"))
            results.append({"check": f"{mode} native numeric input, annotation retention and exact output",
                            "size": [width, height], "passed": True})
        assert controller._lock_ratio.ratio == 16 / 9
        old = window.scene.selection_model.rect()
        QTimer.singleShot(100, lambda: QTest.keyClick(controller._geometry_dialog, Qt.Key.Key_Escape))
        controller._edit_geometry()
        assert window._session_active and window.scene.selection_model.rect() == old
        results.append({"check": "Esc closes numeric dialog without cancelling screenshot", "passed": True})
        (directory / "result.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(json.dumps(results, indent=2))
    finally:
        main._cancel_pending_capture()
        main.hotkey_system.unregister_all()
        if main._capture_thread:
            assert main._capture_thread.wait(5000)
        if main.screenshot_window:
            main.screenshot_window.full_destroy()
        clipboard_utils.deliver_image_async = original_delivery
        outputs.clear()
        (directory / "command.json").write_text(json.dumps({"sequence": 99, "kind": "quit"}), encoding="utf-8")
        try:
            target.wait(timeout=5)
        except subprocess.TimeoutExpired:
            target.terminate()
            target.wait(timeout=5)
        win32api.SetCursorPos(previous_cursor)
        if win32gui.IsWindow(previous_foreground):
            try:
                win32gui.SetForegroundWindow(previous_foreground)
            except Exception:
                pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.run:
        parser.error("Native acceptance requires --run")
    args.output.mkdir(parents=True, exist_ok=True)
    os.environ["QT_QPA_PLATFORM"] = "windows"
    os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "0"
    os.environ["QT_SCALE_FACTOR"] = "1"
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from core.platform_utils import set_dpi_awareness
    set_dpi_awareness()
    run(args.output)
