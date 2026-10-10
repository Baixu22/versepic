"""Opt-in native settings, real encoders and cross-process region-preset acceptance."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def verify_presets(settings_file):
    from PySide6.QtCore import QSettings, QRect
    from PySide6.QtWidgets import QApplication
    from capture.region_presets import RegionPresetStore, current_screen_layout
    from settings import get_tool_settings_manager
    app = QApplication([])
    config = get_tool_settings_manager(QSettings(str(settings_file), QSettings.Format.IniFormat))
    store = RegionPresetStore(config)
    records = store.load()
    assert len(records) == 1
    layout = current_screen_layout()
    bounds = QRect()
    for screen in layout:
        bounds = bounds.united(QRect(*screen["rect"]))
    rect, locked = store.resolve(records[0]["id"], layout, bounds)
    print(json.dumps({"name": records[0]["name"], "rect": [rect.x(), rect.y(), rect.width(), rect.height()],
                      "layout": layout, "locked": locked, "application": app.platformName()}, ensure_ascii=False))


def run(directory, language="zh", scale=100):
    from PIL import Image
    from PySide6.QtCore import QSettings, QRect, Qt
    from PySide6.QtGui import QImage, QColor
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QAbstractButton
    from capture.region_presets import RegionPresetStore, current_screen_layout
    from core.i18n import I18nManager
    from core.save import SaveService
    from core.ui_theme import get_ui_theme
    from settings import get_tool_settings_manager
    from ui.selection_info.geometry_dialog import RegionGeometryDialog
    from ui.settings_ui.dialog import SettingsDialog
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    settings_file = directory / "settings.ini"
    config = get_tool_settings_manager(QSettings(str(settings_file), QSettings.Format.IniFormat))
    config.set_clipboard_db_path(str(directory / "unused-clipboard.db"))
    config.set_clipboard_enabled(False)
    config.set_log_enabled(False)
    config.set_log_dir(str(directory / "logs"))
    config.set_screenshot_save_path(str(directory / "images"))
    config.set_app_setting("capture_region_presets", "[]")
    for key in ("hotkey", "hotkey_2", "clipboard_hotkey", "clipboard_hotkey_2",
                "translation_hotkey", "translation_hotkey_2", "pin_clipboard_hotkey", "pin_clipboard_hotkey_2"):
        setter = getattr(config, "set_" + key)
        setter("")
    config.set_app_setting("language", language)
    config.set_app_setting("dialog_scale_percent", scale)
    from core.logger import setup_logger
    from core.ui_scale import get_dialog_scale, get_ui_scale
    setup_logger(config)
    get_dialog_scale().init(config)
    get_ui_scale().init(config)
    assert I18nManager.load_language(language)
    theme = get_ui_theme().init(config, app)
    dialog = SettingsDialog(config_manager=config)
    dialog.show()
    dialog._on_nav_changed(1, "capture")
    dialog.capture_sections.setCurrentItem("saving")
    scroll = dialog.capture_stack.widget(2)
    results = []
    regions = []

    def pause(seconds=0.1):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)

    def enter(field, text):
        field.setFocus()
        field.selectAll()
        QTest.keyClicks(field, text)
        QTest.keyClick(field, Qt.Key.Key_Tab)

    try:
        share = next(button for button in dialog.findChildren(QAbstractButton) if button.text() == dialog.tr("Share WebP"))
        scroll.ensureWidgetVisible(share, 0, 40)
        pause()
        QTest.mouseClick(share, Qt.MouseButton.LeftButton)
        assert dialog.output_size_combo.currentData() == "half"
        results.append({"check": "sharing preset defaults to shrinking, never enlargement", "passed": True})
        dialog.screenshot_format_combo.setCurrentIndex(dialog.screenshot_format_combo.findData("WEBP"))
        dialog.output_size_combo.setCurrentIndex(dialog.output_size_combo.findData("width"))
        enter(dialog.output_width_spin, "120")
        enter(dialog.output_quality_spin, "77")
        enter(dialog.output_template_edit, "{date}_{project}_{index}")
        enter(dialog.output_project_edit, "native-case")
        dialog.output_date_toggle.setChecked(True)
        QTest.mouseClick(dialog._footer_ok_btn, Qt.MouseButton.LeftButton)
        pause()
        assert config.get_app_setting("screenshot_output_width", 0) == 120
        assert config.get_screenshot_quality() == 77
        for mode in ("light", "dark"):
            theme.set_mode(mode, persist=False)
            for name, field in (("size", dialog.output_size_combo), ("naming", dialog.output_template_edit),
                                ("preview", dialog.output_name_preview)):
                scroll.ensureWidgetVisible(field, 0, 40)
                pause()
                assert scroll.horizontalScrollBar().maximum() == 0
                assert dialog.grab().save(str(directory / f"settings-{mode}-{name}.png"))
        results.append({"check": "native settings input, save and light/dark layout", "passed": True})

        service = SaveService(config)
        snapshot = service.output_options()
        image = QImage(240, 160, QImage.Format.Format_ARGB32)
        image.fill(QColor("#2175a0"))
        ok, first = service.save_qimage(image, prefix="", image_format="WEBP", output_options=snapshot)
        assert ok and QImage(first).size().width() == 120 and QImage(first).height() == 80
        ok, second = service.save_qimage(image, prefix="", image_format="WEBP", output_options=snapshot)
        assert ok and first != second
        assert Path(first).name == snapshot.filename("", "", "WEBP", 1)
        assert Path(second).name == snapshot.filename("", "", "WEBP", 2)
        assert Path(first).parent.name == snapshot.moment.strftime("%Y-%m-%d")
        results.append({"check": "real WebP resize/quality, date directory and collision-safe naming", "passed": True,
                        "outputs": [Path(first).name, Path(second).name], "size": [120, 80]})
        done = []
        pil_file = service.save_pil_async(Image.new("RGBA", (240, 160), "blue"), prefix="long", image_format="PNG",
                                          callback=lambda ok, path: done.append(ok))
        deadline = time.monotonic() + 10
        while not done and time.monotonic() < deadline:
            pause(0.05)
        assert done == [True]
        assert QImage(pil_file).width() == 120 and QImage(pil_file).height() == 80
        pdf = directory / "resized.pdf"
        assert service.save_qimage_to_path(image, str(pdf), output_options=snapshot)
        from PySide6.QtPdf import QPdfDocument
        document = QPdfDocument()
        assert document.load(str(pdf)) == QPdfDocument.Error.None_
        assert document.pageCount() == 1
        document.close()
        results.append({"check": "real asynchronous Pillow output and readable PDF", "passed": True})
        dialog._skip_unsaved_close_prompt = True
        dialog.close()

        layout = current_screen_layout()
        bounds = QRect()
        for screen in layout:
            bounds = bounds.united(QRect(*screen["rect"]))
        initial = QRect(bounds.x() + 80, bounds.y() + 90, 320, 180)
        region = RegionGeometryDialog(initial, bounds, config=config, layout_signature=layout)
        regions.append(region)
        region.show()
        assert "120" in region.saved_size.text() and "68" in region.saved_size.text()
        enter(region.preset_name, "native-region")
        QTest.mouseClick(region.preset_save, Qt.MouseButton.LeftButton)
        identifier = region.preset_combo.currentData()
        assert identifier is not None
        pause()
        assert region.grab().save(str(directory / "preset-saved.png"))
        reader = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--verify-presets", str(settings_file)],
                                capture_output=True, text=True, encoding="utf-8", check=True,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        persisted = json.loads(reader.stdout)
        assert persisted["rect"] == [initial.x(), initial.y(), 320, 180]
        (directory / "cross-process-preset.json").write_text(reader.stdout, encoding="utf-8")
        region.close()
        results.append({"check": "preset saved by native UI and resolved by a fresh process", "passed": True})

        changed = json.loads(json.dumps(layout))
        changed[0]["dpi"] = [value + 24 for value in changed[0]["dpi"]]
        current = QRect(initial.x() + 10, initial.y() + 10, 240, 160)
        mismatch = RegionGeometryDialog(current, bounds, config=config, layout_signature=changed)
        regions.append(mismatch)
        theme.set_mode("light", persist=False)
        mismatch.show()
        mismatch.preset_combo.setCurrentIndex(mismatch.preset_combo.findData(identifier))
        pause()
        assert not mismatch.apply_button.isEnabled()
        assert mismatch.selected_rect() == current
        assert mismatch.grab().save(str(directory / "preset-layout-warning.png"))
        QTest.mouseClick(mismatch.preset_save, Qt.MouseButton.LeftButton)
        assert mismatch.apply_button.isEnabled()
        enter(mismatch.preset_name, "renamed-region")
        QTest.mouseClick(mismatch.preset_rename, Qt.MouseButton.LeftButton)
        assert RegionPresetStore(config).get(identifier)["name"] == "renamed-region"
        QTest.mouseClick(mismatch.preset_delete, Qt.MouseButton.LeftButton)
        assert RegionPresetStore(config).load() == []
        results.append({"check": "simulated DPI mismatch requires explicit review; native update/rename/delete work", "passed": True})
        (directory / "result.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(results, ensure_ascii=False, indent=2))
    finally:
        dialog._skip_unsaved_close_prompt = True
        dialog.close()
        for region in regions:
            region.close()
        app.processEvents()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--language", default="zh")
    parser.add_argument("--scale", type=int, default=100)
    parser.add_argument("--verify-presets", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not args.run and args.verify_presets is None:
        parser.error("Native verification requires --run")
    os.environ["QT_QPA_PLATFORM"] = "windows"
    os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "0"
    os.environ["QT_SCALE_FACTOR"] = "1"
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from core.platform_utils import set_dpi_awareness
    set_dpi_awareness()
    if args.verify_presets:
        verify_presets(args.verify_presets)
    else:
        if args.output is None:
            parser.error("--output is required")
        args.output.mkdir(parents=True, exist_ok=True)
        run(args.output, args.language, args.scale)
