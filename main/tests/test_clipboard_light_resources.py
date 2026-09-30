"""剪贴板中文覆盖、浅色可读性和图片资源导出回归。"""
import ast
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QFileDialog

from clipboard.ui.theme.theme_styles import glass_tint_alpha, surface_palette
from clipboard.ui.theme.themes import THEME_APPLE, THEME_LIGHT
from core.i18n import XmlTranslator


def test_clipboard_chinese_covers_literal_widget_strings(qapp):
    root = Path(__file__).resolve().parents[1]
    translator = XmlTranslator()
    assert translator.load_from_xml(str(root / "translations/app_zh.xml"))
    missing = []
    for path in (root / "clipboard").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id in ("_tr", "tr") and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)):
                source = node.args[0].value
                if not translator.translate("ClipboardWindow", source):
                    missing.append((str(path), source))
        for cls in (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)):
            for node in ast.walk(cls):
                if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                        and node.func.attr == "tr" and node.args
                        and isinstance(node.args[0], ast.Constant)
                        and isinstance(node.args[0].value, str)):
                    continue
                source = node.args[0].value
                if not translator.translate(cls.name, source):
                    missing.append((cls.name, source))
    assert not missing


def _contrast(a, b):
    def lum(c):
        values = [c.redF(), c.greenF(), c.blueF()]
        return sum((v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4) * w
                   for v, w in zip(values, (.2126, .7152, .0722)))
    x, y = lum(a), lum(b)
    return (max(x, y) + .05) / (min(x, y) + .05)


@pytest.mark.parametrize("theme", [THEME_APPLE, THEME_LIGHT])
def test_light_text_contrast_and_glass_backing(theme):
    palette = surface_palette(theme)
    assert not palette.dark
    assert _contrast(palette.accent_text, palette.tint) >= 4.5
    assert _contrast(palette.text_tertiary, palette.tint) >= 4.5
    assert glass_tint_alpha(False, 100) >= .76
    assert glass_tint_alpha(False, 0) > glass_tint_alpha(False, 100)


def _image_window(payload):
    from clipboard.ui.windows.clipboard_window import ClipboardWindow
    item = SimpleNamespace(id=7, content_type="image", image_id="saved-image", created_at=None)
    return SimpleNamespace(
        controller=SimpleNamespace(get_item=lambda _id: item),
        manager=SimpleNamespace(get_image_data=lambda _id: payload),
        tr=lambda s: s,
        _format_from_save_filter=ClipboardWindow._format_from_save_filter,
    )


@pytest.fixture
def png_payload():
    image = QImage(24, 16, QImage.Format.Format_ARGB32)
    image.fill(QColor(20, 110, 210, 100))
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    assert image.save(buffer, "PNG")
    return bytes(buffer.data())


@pytest.mark.parametrize("extension", ["png", "jpg", "bmp", "webp", "pdf"])
def test_image_save_as_writes_real_resource(qapp, tmp_path, monkeypatch, png_payload, extension):
    from clipboard.ui.windows.clipboard_window import ClipboardWindow
    import ui.dialogs
    path = tmp_path / f"图片资源.{extension}"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (str(path), ""))
    errors = []
    monkeypatch.setattr(ui.dialogs, "show_warning_dialog", lambda *args: errors.append(args))
    ClipboardWindow._save_image_as(_image_window(png_payload), 7)
    assert not errors
    assert path.exists() and path.stat().st_size > 0
    if extension == "pdf":
        assert path.read_bytes().startswith(b"%PDF")
    else:
        image = QImage(str(path))
        assert (image.width(), image.height()) == (24, 16)
        if extension == "png":
            assert image.pixelColor(0, 0).alpha() == 100


def test_image_save_cancel_and_missing_data(qapp, monkeypatch, png_payload):
    from clipboard.ui.windows.clipboard_window import ClipboardWindow
    from core.save import SaveService
    import ui.dialogs
    saved, errors = [], []
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: ("", ""))
    monkeypatch.setattr(SaveService, "save_qimage_to_path", lambda *args, **kwargs: saved.append(args))
    monkeypatch.setattr(ui.dialogs, "show_warning_dialog", lambda *args: errors.append(args))
    ClipboardWindow._save_image_as(_image_window(png_payload), 7)
    assert not saved and not errors
    ClipboardWindow._save_image_as(_image_window(None), 7)
    assert len(errors) == 1 and not saved
    ClipboardWindow._save_image_as(_image_window(b"invalid"), 7)
    assert len(errors) == 2 and not saved


def test_relative_time_is_chinese_at_runtime(qapp):
    from datetime import datetime, timedelta
    from core.i18n import I18nManager
    from clipboard.ui.widgets.item_delegate import format_relative_time

    previous = I18nManager.get_current_language()
    try:
        assert I18nManager.load_language("zh")
        now = datetime(2026, 9, 29, 12, 0)
        assert format_relative_time(now, now) == "刚刚"
        assert format_relative_time(now - timedelta(minutes=3), now) == "3 分钟前"
        assert format_relative_time(now - timedelta(days=1), now).startswith("昨天")
        assert format_relative_time(now - timedelta(days=3), now) == "9月26日"
    finally:
        I18nManager.load_language(previous)


def test_image_resource_survives_storage_reopen(tmp_path, png_payload):
    import gc
    pyclipboard = pytest.importorskip("pyclipboard")
    db = str(tmp_path / "clipboard.db")
    storage = pyclipboard.ClipboardManager(db)
    (Path(storage.get_images_dir()) / "persistent-image.png").write_bytes(png_payload)
    del storage
    gc.collect()
    reopened = pyclipboard.ClipboardManager(db)
    image = QImage.fromData(reopened.get_image_data("persistent-image"))
    assert image.size().width() == 24 and image.pixelColor(0, 0).alpha() == 100


def test_image_save_adds_selected_extension(qapp, tmp_path, monkeypatch, png_payload):
    from clipboard.ui.windows.clipboard_window import ClipboardWindow
    path = tmp_path / "无扩展名"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (str(path), "PNG 图片 (*.png)"))
    ClipboardWindow._save_image_as(_image_window(png_payload), 7)
    assert not QImage(str(path) + ".png").isNull()
