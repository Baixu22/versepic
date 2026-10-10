"""Opt-in native cursor and frozen multi-region acceptance using a synthetic target only."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def target(directory):
    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtGui import QColor, QPainter, QCursor
    from PySide6.QtWidgets import QApplication, QWidget
    app = QApplication([])
    class Target(QWidget):
        def __init__(self):
            super().__init__()
            self.color = "#739ac5"
            self.sequence = 0
            self.setWindowTitle("Synthetic multi-region and pointer acceptance")
            self.setGeometry(90, 100, 780, 470)
        def paintEvent(self, event):
            painter = QPainter(self)
            painter.fillRect(self.rect(), QColor(self.color))
            painter.fillRect(30, 150, 180, 160, QColor("#b91c1c"))
            painter.fillRect(250, 150, 180, 160, QColor("#1d4ed8"))
            painter.setPen(Qt.GlobalColor.white)
            painter.drawText(30, 60, "Synthetic capture target: no personal content")
            painter.drawText(40, 180, "A")
            painter.drawText(260, 180, "B")
            painter.end()
        def report(self):
            origin = self.mapToGlobal(self.rect().topLeft())
            data = {"hwnd": int(self.winId()), "pid": os.getpid(), "x": origin.x(), "y": origin.y(),
                    "width": self.width(), "height": self.height(), "sequence": self.sequence}
            temporary = directory / "state.tmp"
            temporary.write_text(json.dumps(data), encoding="utf-8")
            try:
                os.replace(temporary, directory / "state.json")
            except PermissionError:
                QTimer.singleShot(30, self.report)
        def poll(self):
            try:
                command = json.loads((directory / "command.json").read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return
            if command["sequence"] == self.sequence:
                return
            self.sequence = command["sequence"]
            if command.get("quit"):
                app.quit()
                return
            self.color = command.get("color", self.color)
            self.setCursor(QCursor(Qt.CursorShape.IBeamCursor if command.get("cursor") == "text" else Qt.CursorShape.ArrowCursor))
            self.update()
            QTimer.singleShot(100, self.report)
    window = Target()
    window.show()
    timer = QTimer(window)
    timer.timeout.connect(window.poll)
    timer.start(30)
    QTimer.singleShot(150, window.report)
    app.exec()


def verify(directory, language, scale):
    from PySide6.QtCore import QObject, QPoint, QRect, QRectF, QSettings, QTimer, Qt
    from PySide6.QtGui import QColor, QPen, QBrush
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    import win32gui
    import win32api
    import win32process
    from pynput.keyboard import Controller, Key
    from core.i18n import I18nManager
    from core.logger import setup_logger
    from core.ui_scale import get_dialog_scale, get_ui_scale
    from core.ui_theme import get_ui_theme
    from capture.capture_service import CaptureService
    from capture.cursor_capture import cursor_snapshot
    from core.save import SaveService
    from settings import get_tool_settings_manager
    from main_app import MainApp
    from ui.image_layout_dialog import get_image_layout_window
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    config = get_tool_settings_manager(QSettings(str(directory / "settings.ini"), QSettings.Format.IniFormat))
    config.set_clipboard_db_path(str(directory / "unused-history.db"))
    config.set_log_enabled(False)
    config.set_log_dir(str(directory / "logs"))
    config.set_app_setting("language", language)
    config.set_app_setting("dialog_scale_percent", scale)
    config.set_screenshot_save_enabled(False)
    config.set_smart_selection(False)
    setup_logger(config)
    assert I18nManager.load_language(language)
    get_dialog_scale().init(config)
    get_ui_scale().init(config)
    theme = get_ui_theme().init(config, app)
    main = MainApp.__new__(MainApp)
    QObject.__init__(main)
    main.app, main.config_manager = app, config
    main.screenshot_window = main.clipboard_window = main._capture_thread = main._capture_countdown = None
    main._collection_resume_timer = None
    main._quitting = main._capture_busy = False
    main.tray_icon = None
    keyboard = Controller()
    previous_foreground = win32gui.GetForegroundWindow()
    previous_cursor = win32api.GetCursorPos()
    (directory / "state.json").write_text("{}", encoding="utf-8")
    (directory / "command.json").write_text(json.dumps({"sequence": 0}), encoding="utf-8")
    process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--target", "--output", str(directory)],
                               creationflags=subprocess.CREATE_NO_WINDOW)
    sequence = 0
    results = []
    def state():
        try:
            return json.loads((directory / "state.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
    def wait(predicate, seconds=10):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            app.processEvents()
            if predicate():
                return
            time.sleep(0.01)
        raise AssertionError("Native multi-region verification timed out")
    def pause(seconds):
        began = time.monotonic()
        wait(lambda: time.monotonic() - began >= seconds)
    def command(**fields):
        nonlocal sequence
        sequence += 1
        (directory / "command.json").write_text(json.dumps({"sequence": sequence, **fields}), encoding="utf-8")
        wait(lambda: state().get("sequence") == sequence)
    try:
        wait(lambda: bool(state().get("hwnd")))
        keyboard.press(Key.alt)
        keyboard.release(Key.alt)
        win32gui.SetForegroundWindow(state()["hwnd"])
        wait(lambda: win32process.GetWindowThreadProcessId(win32gui.GetForegroundWindow())[1] == state()["pid"])
        info = state()
        target_rect = QRect(info["x"], info["y"], info["width"], info["height"])
        for shape in ("arrow", "text"):
            command(cursor=shape)
            win32api.SetCursorPos((info["x"] + 540, info["y"] + 240))
            pause(0.15)
            plain, desktop = CaptureService().capture_all_screens()
            with cursor_snapshot(True) as cursor:
                expected = cursor.desktop_rect()
                hotspot = cursor.hotspot
            pointed, _ = CaptureService(include_cursor=True).capture_all_screens()
            crop = target_rect.translated(-round(desktop.x()), -round(desktop.y()))
            a, b = plain.copy(crop), pointed.copy(crop)
            different = []
            for y in range(a.height()):
                for x in range(a.width()):
                    if a.pixel(x,y) != b.pixel(x,y):
                        different.append((x,y))
            assert different
            local_expected = expected.translated(-target_rect.x(), -target_rect.y())
            assert all(local_expected.contains(QPoint(x,y)) for x,y in different)
            assert a.save(str(directory / f"cursor-{shape}-off.png"))
            assert b.save(str(directory / f"cursor-{shape}-on.png"))
            assert SaveService(config).save_qimage_to_path(b, str(directory / f"cursor-{shape}-saved.png"))
            results.append({"check": shape + " real cursor hotspot and saved pixels", "hotspot": hotspot,
                            "changed_pixels": len(different), "passed": True})
            plain = pointed = a = b = None

        command(cursor="arrow", color="#739ac5")
        config.set_app_setting("screenshot_include_cursor", True)
        main.start_screenshot()
        wait(lambda: main.screenshot_window is not None and main.screenshot_window._session_active)
        screenshot = main.screenshot_window
        original = screenshot.original_image
        desktop_origin = QPoint(round(screenshot.virtual_x), round(screenshot.virtual_y))
        screenshot.scene.selection_model.initialize_confirmed_rect(QRectF(info["x"]+20, info["y"]+130, 440, 230))
        screenshot.scene.addRect(QRectF(info["x"]+40, info["y"]+200, 25, 25), QPen(Qt.PenStyle.NoPen), QBrush(QColor("yellow")))
        # Change the actual target AFTER the screenshot; multi-region must still use the old frame.
        command(color="#00cc88")
        region_a = QRect(info["x"]+30, info["y"]+150, 180, 160).translated(-desktop_origin)
        region_b = QRect(info["x"]+250, info["y"]+150, 180, 160).translated(-desktop_origin)
        region_overlap = QRect(info["x"]+300, info["y"]+230, 320, 160).translated(-desktop_origin)
        errors = []
        def operate():
            dialog = screenshot._multi_region_dialog
            try:
                assert dialog is not None and QApplication.activeModalWidget() is dialog
                dialog.panel.hide()
                for rect in (region_a, region_b, region_overlap):
                    QTest.mousePress(dialog, Qt.MouseButton.LeftButton, pos=rect.topLeft())
                    QTest.mouseMove(dialog, rect.bottomRight())
                    QTest.mouseRelease(dialog, Qt.MouseButton.LeftButton, pos=rect.bottomRight())
                assert len(dialog.selection.regions) == 3
                QTest.keyClick(dialog, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
                assert len(dialog.selection.regions) == 2
                QTest.keyClick(dialog, Qt.Key.Key_Y, Qt.KeyboardModifier.ControlModifier)
                assert len(dialog.selection.regions) == 3
                dialog.list.setCurrentRow(2)
                dialog.move_region(-1)
                assert dialog.selection.regions == [region_a, region_overlap, region_b]
                dialog.panel.show()
                dialog.place_controls()
                for mode in ("light", "dark"):
                    theme.set_mode(mode, persist=False)
                    assert dialog.panel.grab().save(str(directory / f"multi-controls-{mode}.png"))
                # Save only the synthetic target crop, never the full desktop overlay.
                local_target = target_rect.translated(-desktop_origin)
                assert dialog.grab(local_target).save(str(directory / "multi-region-overlay.png"))
                QTest.mouseClick(dialog.collect, Qt.MouseButton.LeftButton)
            except Exception:
                import traceback
                errors.append(traceback.format_exc())
                dialog.reject()
        screenshot.toolbar.more_btn.click()
        assert screenshot.toolbar.multi_region_btn.isVisible()
        QTimer.singleShot(100, operate)
        QTest.mouseClick(screenshot.toolbar.multi_region_btn, Qt.MouseButton.LeftButton)
        assert not errors, errors
        collection = get_image_layout_window()
        assert len(collection.entries) == 3
        for index, rect in enumerate((region_a, region_overlap, region_b)):
            assert collection.images()[index] == original.copy(rect)
            assert collection.images()[index].save(str(directory / f"multi-output-{index+1}.png"))
        assert not screenshot._session_active and collection.isVisible()
        results.append({"check": "three ordered overlapping crops from one frozen frame, no existing annotations or UI pixels",
                        "sizes": [[im.width(), im.height()] for im in collection.images()], "passed": True})
        original = None
        main.start_screenshot()
        wait(lambda: screenshot._session_active)
        screenshot.scene.selection_model.initialize_confirmed_rect(QRectF(target_rect))
        old_scene = screenshot.scene
        def cancel():
            dialog = screenshot._multi_region_dialog
            dialog.selection.add(QRect(20,20,80,60))
            QTest.keyClick(dialog, Qt.Key.Key_Escape)
        QTimer.singleShot(100, cancel)
        screenshot._handle_multi_region()
        assert screenshot._session_active and screenshot.scene is old_scene
        assert len(collection.entries) == 3
        results.append({"check": "native Esc cancels region selection without changing screenshot or basket", "passed": True})
        (directory / "result.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(results, ensure_ascii=False, indent=2))
    finally:
        main._cancel_pending_capture()
        if main._capture_thread:
            assert main._capture_thread.wait(5000)
        if main.screenshot_window:
            main.screenshot_window.full_destroy()
        collection = getattr(app, "_image_layout_window", None)
        if collection is not None:
            collection.close()
        (directory / "command.json").write_text(json.dumps({"sequence": sequence+1, "quit": True}), encoding="utf-8")
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.terminate()
            process.wait(timeout=5)
        win32api.SetCursorPos(previous_cursor)
        if win32gui.IsWindow(previous_foreground):
            try:
                win32gui.SetForegroundWindow(previous_foreground)
            except Exception:
                pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--target", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--language", default="zh")
    parser.add_argument("--scale", type=int, default=100)
    args = parser.parse_args()
    if not (args.run or args.target):
        parser.error("Native acceptance requires --run")
    args.output.mkdir(parents=True, exist_ok=True)
    os.environ["QT_QPA_PLATFORM"] = "windows"
    os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "0"
    os.environ["QT_SCALE_FACTOR"] = "1"
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from core.platform_utils import set_dpi_awareness
    set_dpi_awareness()
    if args.target:
        target(args.output)
    else:
        verify(args.output, args.language, args.scale)
