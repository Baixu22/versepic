"""Native acceptance: image selection, composition, PDF export and continuous capture.
Only synthetic content and an isolated database are used. Requires explicit --run.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time


def run(directory, language, scale):
    from PySide6.QtCore import QObject, QPoint, QRectF, QSettings, QSize, Qt
    from PySide6.QtGui import QColor, QImage, QPainter, QFont, QPen, QBrush
    from PySide6.QtPdf import QPdfDocument
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    import win32gui
    import win32process
    from pynput.keyboard import Controller as Keyboard, Key
    from pynput.mouse import Controller as Mouse, Button
    from clipboard.core import ClipboardManager
    from core.i18n import I18nManager
    from core.logger import setup_logger
    from core.ui_scale import get_dialog_scale, get_ui_scale
    from core.ui_theme import get_ui_theme
    from main_app import MainApp
    from pin.pin_manager import PinManager
    from settings import get_tool_settings_manager
    from ui.image_layout_dialog import get_image_layout_window, ImageSourcePicker
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    config = get_tool_settings_manager(QSettings(str(directory / "settings.ini"), QSettings.Format.IniFormat))
    config.set_clipboard_db_path(str(directory / "clipboard.db"))
    config.set_log_enabled(False)
    config.set_log_dir(str(directory / "logs"))
    setup_logger(config)
    config.set_app_setting("language", language)
    config.set_app_setting("dialog_scale_percent", scale)
    config.set_screenshot_save_enabled(False)
    config.set_smart_selection(False)
    config.set_ocr_enabled(False)
    assert I18nManager.load_language(language)
    get_dialog_scale().init(config)
    get_ui_scale().init(config)
    theme = get_ui_theme().init(config, app)
    manager = ClipboardManager(config.get_clipboard_db_path())
    assert manager.is_available
    collection = get_image_layout_window()
    collection.show()
    results = []
    source_hashes = {}

    def wait(predicate, timeout=15):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            app.processEvents()
            if predicate():
                return
            time.sleep(0.01)
        raise AssertionError("Native image collection condition timed out")

    def pause(seconds):
        start = time.monotonic()
        wait(lambda: time.monotonic() - start >= seconds)

    def sample(name, color, width, height):
        image = QImage(width, height, QImage.Format.Format_ARGB32)
        image.fill(QColor(color))
        painter = QPainter(image)
        painter.setPen(QColor("white"))
        font = QFont("Segoe UI")
        font.setPixelSize(28)
        painter.setFont(font)
        painter.drawText(image.rect(), Qt.AlignmentFlag.AlignCenter, name)
        painter.setPen(QPen(QColor("white"), 5))
        painter.drawRect(5, 5, width - 10, height - 10)
        painter.end()
        return image

    identifiers = []
    for index, (label, color, size) in enumerate((("A — wide", "#b91c1c", (420, 220)),
                                                 ("B — tall", "#1d4ed8", (180, 400)))):
        picture = sample(label, color, *size)
        item_id = manager.add_item(label, "image", title=label)
        image_id = f"fixture-{index}"
        with manager.image_text_store.connect() as db:
            db.execute("UPDATE clipboard SET image_id=? WHERE id=?", (image_id, item_id))
        file = Path(manager.get_images_dir()) / (image_id + ".png")
        file.parent.mkdir(parents=True, exist_ok=True)
        assert picture.save(str(file))
        source_hashes[str(file)] = hashlib.sha256(file.read_bytes()).hexdigest()
        identifiers.append(item_id)

    picker = ImageSourcePicker(manager=manager, parent=collection)
    picker.show()
    pause(0.1)
    # Search result order is newest first. Explicitly select both without loading originals beforehand.
    for index in range(picker.list.count()):
        picker.list.item(index).setSelected(True)
    assert picker.grab().save(str(directory / "history-picker.png"))
    chosen = picker.selected()
    picker.close()
    assert collection.add_history_ids(manager, chosen) == 0
    pin_manager = PinManager.instance()
    pin = pin_manager.create_pin(sample("C — pinned", "#15803d", 320, 180), QPoint(90, 110), config_manager=config)
    pin.show()
    pin.canvas.scene.addRect(QRectF(20, 20, 20, 20), QPen(Qt.PenStyle.NoPen), QBrush(QColor("yellow")))
    assert collection.add_pin_images([pin]) == 0
    pin.close_window()
    assert collection.images()[-1].pixelColor(25, 25).name() == "#ffff00"
    assert len(collection.entries) == 3
    results.append({"check": "multiple real database originals and a live annotated-capable pin are imported", "passed": True})
    source_order = [entry[0] for entry in collection.ordered_entries()]
    collection.raise_()
    collection.activateWindow()
    keyboard=Keyboard()
    keyboard.press(Key.alt);keyboard.release(Key.alt)
    win32gui.SetForegroundWindow(int(collection.winId()))
    wait(lambda: win32gui.GetForegroundWindow()==int(collection.winId()))
    pause(0.2)
    mouse = Mouse()
    old_position = mouse.position
    first = collection.list.visualItemRect(collection.list.item(0)).center()
    last = collection.list.visualItemRect(collection.list.item(2)).bottomLeft() + QPoint(20, -2)
    start = collection.list.viewport().mapToGlobal(first)
    end = collection.list.viewport().mapToGlobal(last)
    errors = []
    def drag():
        try:
            mouse.position = (start.x(), start.y())
            time.sleep(0.1)
            mouse.press(Button.left)
            for step in range(1, 16):
                mouse.position = (round(start.x() + (end.x() - start.x()) * step / 15),
                                  round(start.y() + (end.y() - start.y()) * step / 15))
                time.sleep(0.03)
            mouse.release(Button.left)
        except Exception as exc:
            errors.append(str(exc))
    thread = threading.Thread(target=drag)
    thread.start()
    wait(lambda: not thread.is_alive())
    thread.join()
    mouse.position = old_position
    assert not errors
    wait(lambda: [entry[0] for entry in collection.ordered_entries()] != source_order)
    new_order = [entry[0] for entry in collection.ordered_entries()]
    assert new_order != source_order, (new_order, source_order)
    results.append({"check": "native drag reorders source images persistently", "order": new_order, "passed": True})

    for mode in ("light", "dark"):
        theme.set_mode(mode, persist=False)
        collection.width_spin.setValue(240)
        collection.padding.setValue(14)
        collection.gap.setValue(10)
        collection.update_preview()
        pause(0.1)
        assert collection.grab().save(str(directory / f"layout-{mode}.png"))
    options = collection.layout_options()
    expected, _ = options.geometry(collection.images())
    output = directory / "combined.png"
    assert collection.start_export(str(output))
    wait(lambda: collection._worker is None)
    assert QImage(str(output)).size() == expected
    results.append({"check": "composition preview dimensions equal actual output", "size": [expected.width(), expected.height()], "passed": True})
    collection.mode.setCurrentIndex(1)
    collection.paper.setCurrentIndex(1)
    collection.margin.setValue(12)
    collection.update_preview()
    pdf = directory / "pages.pdf"
    assert collection.start_export(str(pdf))
    wait(lambda: collection._worker is None)
    assert collection.grab().save(str(directory / "pdf-preview.png"))
    document = QPdfDocument()
    assert document.load(str(pdf)) == QPdfDocument.Error.None_
    assert document.pageCount() == 3
    for index in range(3):
        assert document.render(index, QSize(595, 842)).save(str(directory / f"pdf-page-{index+1}.png"))
        assert document.getAllText(index).text() == ""
    document.close()
    results.append({"check": "three ordered A4 pages open in independent PDFium renderer with no hidden text", "passed": True})
    assert all(hashlib.sha256(Path(file).read_bytes()).hexdigest() == digest for file, digest in source_hashes.items())
    results.append({"check": "all source history files remain byte-identical", "passed": True})

    # Exercise the production MainApp session loop against a separate native synthetic target.
    collection.clear_collection()
    main = MainApp.__new__(MainApp)
    QObject.__init__(main)
    main.app, main.config_manager = app, config
    main.screenshot_window = main.clipboard_window = main._capture_thread = main._capture_countdown = None
    main._collection_resume_timer = None
    main._quitting = main._capture_busy = False
    main.tray_icon = None
    previous_foreground = win32gui.GetForegroundWindow()
    (directory / "target.json").write_text("{}", encoding="utf-8")
    (directory / "command.json").write_text(json.dumps({"sequence": 0, "kind": "idle"}), encoding="utf-8")
    process = subprocess.Popen([sys.executable, str(Path(__file__).with_name("native_delayed_capture.py")), "--target", "--output", str(directory)],
                               creationflags=subprocess.CREATE_NO_WINDOW)
    def target_state():
        try:
            return json.loads((directory / "target.json").read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {}
    try:
        wait(lambda: bool(target_state().get("hwnd")))
        keyboard = Keyboard()
        keyboard.press(Key.alt)
        keyboard.release(Key.alt)
        win32gui.SetForegroundWindow(target_state()["hwnd"])
        wait(lambda: win32process.GetWindowThreadProcessId(win32gui.GetForegroundWindow())[1] == target_state()["pid"])
        collection.hide()
        main.start_screenshot()
        wait(lambda: main.screenshot_window is not None and main.screenshot_window._session_active)
        window = main.screenshot_window
        x, y, w, h = target_state()["rect"]
        region = QRectF(x + 40, y + 180, 320, 160)
        window.scene.selection_model.initialize_confirmed_rect(region)
        window.scene.addRect(QRectF(x + 60, y + 200, 30, 30), QPen(Qt.PenStyle.NoPen), QBrush(QColor("red")))
        QTest.mouseClick(window.toolbar.more_btn, Qt.MouseButton.LeftButton)
        pause(0.05)
        assert window.toolbar.collect_next_btn.isVisible()
        assert window.toolbar._more_popup.grab().save(str(directory / "collection-actions.png"))
        QTest.mouseClick(window.toolbar.collect_next_btn, Qt.MouseButton.LeftButton)
        assert len(collection.entries) == 1
        wait(lambda: window._session_active)
        assert main.screenshot_window is window
        assert not window.scene.selection_model.is_confirmed
        assert not collection.isVisible()
        window.scene.selection_model.initialize_confirmed_rect(region)
        QTest.mouseClick(window.toolbar.more_btn, Qt.MouseButton.LeftButton)
        pause(0.05)
        assert window.toolbar.collect_review_btn.isVisible()
        QTest.mouseClick(window.toolbar.collect_review_btn, Qt.MouseButton.LeftButton)
        wait(lambda: collection.isVisible())
        assert len(collection.entries) == 2
        first, second = collection.images()
        assert first.pixelColor(25, 25).name() == "#ff0000"
        assert second.pixelColor(25, 25).name() != "#ff0000"
        assert first.save(str(directory / "continuous-first.png"))
        assert second.save(str(directory / "continuous-second.png"))
        results.append({"check": "continuous capture reuses shell but not annotations or selections", "passed": True})
        main.start_screenshot()
        wait(lambda: window._session_active)
        QTest.keyClick(window, Qt.Key.Key_Escape)
        wait(lambda: collection.isVisible())
        assert len(collection.entries) == 2
        results.append({"check": "Esc cancels next screenshot and restores intact collection", "passed": True})
    finally:
        main._cancel_pending_capture()
        if main._capture_thread:
            assert main._capture_thread.wait(5000)
        if main.screenshot_window:
            main.screenshot_window.full_destroy()
        (directory / "command.json").write_text(json.dumps({"sequence": 99, "kind": "quit"}), encoding="utf-8")
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.terminate()
            process.wait(timeout=5)
        collection.close()
        manager.release_storage()
        if win32gui.IsWindow(previous_foreground):
            try:
                win32gui.SetForegroundWindow(previous_foreground)
            except Exception:
                pass
    (directory / "result.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--language", default="zh")
    parser.add_argument("--scale", type=int, default=100)
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
    run(args.output, args.language, args.scale)
