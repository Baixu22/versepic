"""Native magnify-callout acceptance on the file editor, isolated settings, no user clipboard."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time


def registry_digest():
    from tests.native_image_editor import registry_digest as digest
    return digest()


def unique_image(width=80, height=60):
    from PySide6.QtGui import QColor, QImage
    image = QImage(width, height, QImage.Format.Format_ARGB32)
    for y in range(height):
        for x in range(width):
            image.setPixelColor(x, y, QColor(x * 3 % 256, y * 5 % 256, (x * 7 + y) % 256))
    return image


def run(directory, language, scale):
    from PySide6.QtCore import QPoint, QPointF, QRectF, QSettings, Qt
    from PySide6.QtGui import QColor
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from settings import get_tool_settings_manager
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    config = get_tool_settings_manager(QSettings(str(directory / "settings.ini"), QSettings.Format.IniFormat))
    assert Path(config.qsettings.fileName()).resolve() == (directory / "settings.ini").resolve()
    before_registry = registry_digest()
    from core.i18n import I18nManager
    from core.ui_scale import get_dialog_scale, get_ui_scale
    from core.ui_theme import get_ui_theme
    from ui.image_editor import show_image_editor
    from canvas.items import MagnifyCalloutItem
    from pin.pin_canvas import PinCanvas
    from PySide6.QtWidgets import QWidget
    config.set_log_enabled(False)
    config.set_log_dir(str(directory / "logs"))
    config.set_clipboard_db_path(str(directory / "unused-history.db"))
    config.set_app_setting("language", language)
    config.set_app_setting("dialog_scale_percent", scale)
    config.update_settings("magnify", color="#FF0000", stroke_width=1, opacity=1.0)
    I18nManager.load_language(language)
    get_dialog_scale().init(config)
    get_ui_scale().init(config)
    theme = get_ui_theme().init(config, app)
    source = unique_image()
    original = directory / "source.png"
    assert source.save(str(original))
    source_hash = hashlib.sha256(original.read_bytes()).hexdigest()
    editor = show_image_editor(str(original))
    records = []

    def color_in_callout(image, item, rgb):
        x0 = int(round(item.pos().x())) + 3
        y0 = int(round(item.pos().y())) + 3
        x1 = x0 + max(1, int(item.rect().width()) - 6)
        y1 = y0 + max(1, int(item.rect().height()) - 6)
        for y in range(max(0, y0), min(image.height(), y1)):
            for x in range(max(0, x0), min(image.width(), x1)):
                if image.pixelColor(x, y).getRgb()[:3] == rgb:
                    return True
        return False

    def wait(condition, seconds=20):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            app.processEvents()
            if condition():
                return
            time.sleep(0.01)
        raise AssertionError("Native magnify condition timed out")

    try:
        wait(lambda: editor.canvas is not None and editor.view is not None and editor.toolbar is not None)
        wait(lambda: editor.view.viewport().width() > 50)
        editor.fit_view()
        app.processEvents()
        assert "magnify" in editor.toolbar.LAYOUT
        assert editor.toolbar.magnify_btn.isVisible()
        for color in ("light", "dark"):
            theme.set_mode(color, persist=False)
            app.processEvents()
            assert editor.grab().save(str(directory / f"editor-{color}.png"))
        theme.set_mode("light", persist=False)
        QTest.mouseClick(editor.toolbar.magnify_btn, Qt.MouseButton.LeftButton)
        app.processEvents()
        assert editor.toolbar.current_tool == "magnify" or editor.toolbar.magnify_btn.isChecked()
        a = editor.view.mapFromScene(QPointF(16, 12))
        b = editor.view.mapFromScene(QPointF(32, 24))
        QTest.mousePress(editor.view.viewport(), Qt.MouseButton.LeftButton, pos=a)
        QTest.mouseMove(editor.view.viewport(), b)
        QTest.mouseRelease(editor.view.viewport(), Qt.MouseButton.LeftButton, pos=b)
        app.processEvents()
        items = [item for item in editor.canvas.scene.items() if isinstance(item, MagnifyCalloutItem)]
        assert len(items) == 1, items
        item = items[0]
        source_rect = item.source_rect()
        assert source_rect.width() >= 8 and source_rect.height() >= 8
        exported = editor.render_image()
        assert exported.save(str(directory / "exported.png"))
        sample = item._sample()
        sx = int(round(source_rect.x() + 4))
        sy = int(round(source_rect.y() + 4))
        expected = source.pixelColor(sx, sy)
        local_x = (sx - source_rect.x()) * item.zoom()
        local_y = (sy - source_rect.y()) * item.zoom()
        sample_x = int(local_x + item.zoom() / 2)
        sample_y = int(local_y + item.zoom() / 2)
        sampled = sample.pixelColor(sample_x, sample_y)
        cx = item.pos().x() + local_x + item.zoom() / 2
        cy = item.pos().y() + local_y + item.zoom() / 2
        actual = exported.pixelColor(int(cx), int(cy))
        (directory / "first-pixel.json").write_text(json.dumps({
            "actual": actual.getRgb(), "sampled": sampled.getRgb(), "expected": expected.getRgb(),
            "pos": [item.pos().x(), item.pos().y()],
            "source": [source_rect.x(), source_rect.y(), source_rect.width(), source_rect.height()],
            "zoom": item.zoom(), "cx": cx, "cy": cy, "exported": [exported.width(), exported.height()]
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        assert sampled.getRgb()[:3] == expected.getRgb()[:3], (sampled.getRgb(), expected.getRgb(), source_rect)
        assert actual.getRgb()[:3] == expected.getRgb()[:3], (actual.getRgb(), expected.getRgb(), item.pos(), source_rect, item.zoom())
        records.append({"check": "native editor magnify tool draws callout whose export matches original pixels", "passed": True})
        from canvas.items import RectItem
        from PySide6.QtGui import QPen
        cover = RectItem(QRectF(source_rect), QPen(QColor("white"), 20))
        cover.setZValue(80)
        editor.canvas.scene.addItem(cover)
        still = item._sample()
        assert still.pixelColor(sample_x, sample_y).getRgb()[:3] == expected.getRgb()[:3]
        editor.canvas.scene.removeItem(cover)
        records.append({"check": "callout samples background pixels only; covering annotations are ignored", "passed": True})
        old_source = QRectF(item.source_rect())
        item.setPos(item.pos() + QPointF(-6, 4))
        moved = editor.render_image()
        assert moved.save(str(directory / "moved.png"))
        assert item.source_rect() == old_source
        moved_sample = item._sample()
        assert moved_sample.pixelColor(sample_x, sample_y).getRgb()[:3] == expected.getRgb()[:3]
        assert color_in_callout(moved, item, expected.getRgb()[:3])
        records.append({"check": "moving the callout does not shift the sampled source pixels", "passed": True})
        parent = QWidget()
        parent.toolbar = None
        parent.view = None
        parent._is_editing = False
        pin = PinCanvas(parent, source.size(), source)
        try:
            drawing = editor.canvas.scene.get_drawing_items_in_rect(QRectF(0, 0, source.width(), source.height()))
            pin.initialize_from_items(drawing, QPoint(0, 0))
            cloned = [entry for entry in pin.scene.items() if isinstance(entry, MagnifyCalloutItem)]
            assert len(cloned) == 1
            sample = cloned[0]._sample()
            assert sample.pixelColor(sample_x, sample_y).getRgb()[:3] == expected.getRgb()[:3]
            from core.export import ExportService
            pin_export = ExportService(pin.scene).export(QRectF(0, 0, source.width(), source.height()))
            assert pin_export.save(str(directory / "pin-inherited.png"))
        finally:
            pin.cleanup()
            parent.deleteLater()
        records.append({"check": "pin inheritance keeps original-pixel sampling", "passed": True})
        saved = directory / "saved.png"
        assert editor.start_save(str(saved))
        wait(lambda: editor._worker is None and saved.exists())
        assert hashlib.sha256(original.read_bytes()).hexdigest() == source_hash
        records.append({"check": "file export writes a new PNG; source image hash unchanged", "passed": True})
        assert registry_digest() == before_registry
        records.append({"check": "real configuration registry digest unchanged", "passed": True})
    finally:
        editor._force_close = True
        editor.close()
        app.processEvents()
    (directory / "result.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(records, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--language", default="zh")
    parser.add_argument("--scale", type=int, default=100)
    args = parser.parse_args()
    if not args.run:
        parser.error("Native magnify acceptance requires --run")
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    os.environ["QT_QPA_PLATFORM"] = "windows"
    os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "0"
    os.environ["QT_SCALE_FACTOR"] = "1"
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from core.platform_utils import set_dpi_awareness
    set_dpi_awareness()
    run(args.output, args.language, args.scale)
