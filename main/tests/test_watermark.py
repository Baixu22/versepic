# -*- coding: utf-8 -*-
"""TF-0038 导出水印：默认关闭、位置/边距/透明度、文字与图片、格式一致、不动源文件。"""
from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QImage

from canvas.scene import CanvasScene
from core.export import ExportService
from core.save import SaveService
from core.watermark import (
    KIND_IMAGE,
    KIND_TEXT,
    POSITION_BOTTOM_RIGHT,
    POSITION_CENTER,
    POSITION_TOP_LEFT,
    WatermarkOptions,
    load_watermark_image,
    options_from_mapping,
    preview,
    render,
)

SIZE = 160


def _image(width=SIZE, height=SIZE, color="#3366CC"):
    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(QColor(color))
    return image


def _transparent_image(width=SIZE, height=SIZE):
    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(QColor(0, 0, 0, 0))
    return image


def _changed_bounds(before: QImage, after: QImage):
    xs, ys = [], []
    for y in range(after.height()):
        for x in range(after.width()):
            if before.pixelColor(x, y) != after.pixelColor(x, y):
                xs.append(x)
                ys.append(y)
    if not xs:
        return None
    return (min(xs), min(ys), max(xs), max(ys))


def test_disabled_or_empty_watermark_returns_the_original_image(qapp):
    image = _image()
    assert render(image, WatermarkOptions()) is image
    assert render(image, WatermarkOptions(enabled=True, kind=KIND_TEXT, text="   ")) is image
    assert options_from_mapping({}).enabled is False


def test_text_watermark_position_is_honoured_and_stays_inside(qapp):
    image = _image()
    bottom_right = render(image, WatermarkOptions(enabled=True, text="© 2026 Demo", position=POSITION_BOTTOM_RIGHT))
    top_left = render(image, WatermarkOptions(enabled=True, text="© 2026 Demo", position=POSITION_TOP_LEFT))

    br = _changed_bounds(image, bottom_right)
    tl = _changed_bounds(image, top_left)
    assert br is not None and tl is not None
    assert br != tl
    assert br[2] < image.width() and br[3] < image.height()
    assert tl[0] >= 0 and tl[1] >= 0
    # 右下角：右/下边贴近边距；左上角：左/上边贴近边距（渲染像素略内缩，给一点容差）
    assert br[2] >= image.width() - 26 and br[3] >= image.height() - 26
    assert tl[0] <= 26 and tl[1] <= 26


def test_long_text_on_small_image_shrinks_instead_of_clipping(qapp):
    image = _image(48, 24)
    result = render(
        image,
        WatermarkOptions(enabled=True, text="非常长的水印文字 Very Long Watermark", position=POSITION_CENTER, scale=3.0),
    )
    bounds = _changed_bounds(image, result)
    assert bounds is not None
    assert bounds[0] >= 0 and bounds[1] >= 0
    assert bounds[2] < image.width() and bounds[3] < image.height()
    assert result.size() == image.size()


def test_transparent_background_stays_transparent_away_from_watermark(qapp):
    image = _transparent_image()
    result = render(image, WatermarkOptions(enabled=True, text="© 2026", position=POSITION_BOTTOM_RIGHT))
    assert result.pixelColor(1, 1).alpha() == 0, "没被水印覆盖的透明像素必须保持透明"


def test_opacity_is_applied(qapp):
    image = _image()
    strong = render(image, WatermarkOptions(enabled=True, text="© 2026", opacity=1.0))
    faint = render(image, WatermarkOptions(enabled=True, text="© 2026", opacity=0.2))
    # 覆盖区域一致（同一位置同一字号），但像素必须真的不同：不透明度不是摆设
    assert _changed_bounds(image, strong) == _changed_bounds(image, faint)
    assert _changed_bounds(strong, faint) is not None, "不同不透明度必须画出不同结果"


def test_image_watermark_is_scaled_and_bounded(qapp, tmp_path):
    logo = QImage(60, 30, QImage.Format.Format_ARGB32)
    logo.fill(QColor(255, 0, 0))
    logo_path = tmp_path / "logo.png"
    assert logo.save(str(logo_path))
    assert load_watermark_image(logo_path) is not None

    image = _image()
    options = WatermarkOptions(enabled=True, kind=KIND_IMAGE, image_path=str(logo_path), scale=3.0)
    result = render(image, options)
    bounds = _changed_bounds(image, result)
    assert bounds is not None
    assert bounds[2] < image.width() and bounds[3] < image.height()
    assert (bounds[2] - bounds[0]) <= image.width() - 2 * options.margin


def test_missing_or_broken_image_watermark_is_ignored(qapp, tmp_path):
    image = _image()
    missing = render(image, WatermarkOptions(enabled=True, kind=KIND_IMAGE, image_path=str(tmp_path / "nope.png")))
    assert _changed_bounds(image, missing) is None

    broken = tmp_path / "broken.png"
    broken.write_bytes(b"not an image")
    assert load_watermark_image(broken) is None
    assert _changed_bounds(image, render(image, WatermarkOptions(enabled=True, kind=KIND_IMAGE, image_path=str(broken)))) is None


def test_extra_fields_like_window_title_are_ignored(qapp):
    options = options_from_mapping({
        "enabled": True,
        "kind": KIND_TEXT,
        "text": "© 2026 Demo",
        "window_title": "Secret Window",
        "user_name": "alice",
    })
    assert options.text == "© 2026 Demo"
    assert not hasattr(options, "window_title")
    image = _image()
    assert _changed_bounds(
        render(image, options),
        preview(image, WatermarkOptions(enabled=True, text="© 2026 Demo")),
    ) is None, "预览与导出必须走同一套渲染"


def test_export_chain_applies_watermark_only_when_enabled(qapp):
    from settings import get_tool_settings_manager

    manager = get_tool_settings_manager()
    keys = {
        "watermark_enabled": manager.get_app_setting("watermark_enabled", False),
        "watermark_kind": manager.get_app_setting("watermark_kind", "text"),
        "watermark_text": manager.get_app_setting("watermark_text", ""),
        "watermark_position": manager.get_app_setting("watermark_position", "bottom_right"),
    }
    image = _image()
    scene = CanvasScene(image, QRectF(0, 0, SIZE, SIZE), enable_mosaic=True)
    scene.selection_model.initialize_confirmed_rect(QRectF(0, 0, SIZE, SIZE))
    service = ExportService(scene)
    rect = QRectF(0, 0, SIZE, SIZE)
    try:
        manager.set_app_setting("watermark_enabled", False)
        plain = service.export(rect)
        assert _changed_bounds(plain, service.export_with_legend(rect)) is None

        manager.set_app_setting("watermark_enabled", True)
        manager.set_app_setting("watermark_kind", "text")
        manager.set_app_setting("watermark_text", "© 2026 Demo")
        manager.set_app_setting("watermark_position", "bottom_right")
        marked = service.export_with_legend(rect)
        assert _changed_bounds(plain, marked) is not None, "开启后水印必须进最终成图"
    finally:
        manager.set_app_setting("watermark_enabled", keys["watermark_enabled"])
        manager.set_app_setting("watermark_kind", keys["watermark_kind"])
        manager.set_app_setting("watermark_text", keys["watermark_text"])
        manager.set_app_setting("watermark_position", keys["watermark_position"])


def test_watermark_survives_all_save_formats_and_source_file_is_untouched(qapp, tmp_path):
    from settings import get_tool_settings_manager

    source_path = tmp_path / "source.png"
    plain = _image()
    assert plain.save(str(source_path))
    source_bytes = source_path.read_bytes()

    marked = render(plain, WatermarkOptions(enabled=True, text="© 2026 Demo"))
    assert _changed_bounds(plain, marked) is not None

    service = SaveService(get_tool_settings_manager())
    targets = {}
    for fmt, name in (("PNG", "out.png"), ("JPEG", "out.jpg"), ("WEBP", "out.webp"), ("PDF", "out.pdf")):
        target = tmp_path / name
        assert service.save_qimage_to_path(marked, str(target), image_format=fmt), fmt
        assert target.exists() and target.stat().st_size > 0
        targets[fmt] = target

    for fmt in ("PNG", "JPEG", "WEBP"):
        reloaded = QImage(str(targets[fmt]))
        assert not reloaded.isNull()
        assert _changed_bounds(_image(), reloaded) is not None, fmt

    assert source_path.read_bytes() == source_bytes, "导出水印不能改写源文件"

def test_watermark_settings_controls_build_and_preview(qapp):
    from PySide6.QtWidgets import QWidget

    from ui.settings_ui.components import SettingCardGroup
    from ui.settings_ui.watermark_controls import add_watermark_controls

    class _Config:
        def __init__(self):
            self.saved = {}

        def get_app_setting(self, key, default=None):
            return self.saved.get(key, default)

    class _Dialog(QWidget):
        def __init__(self):
            super().__init__()
            self.config_manager = _Config()

        def tr(self, text):
            return text

    dialog = _Dialog()
    group = SettingCardGroup("Watermark", dialog)
    add_watermark_controls(dialog, group)

    assert dialog.watermark_toggle.isChecked() is False, "水印默认关闭"
    assert dialog.watermark_preview.pixmap() is not None, "预览必须画出来"
    assert not dialog.watermark_text_edit.isEnabled(), "关闭时参数不可编辑"

    dialog.watermark_toggle.setChecked(True)
    assert dialog.watermark_text_edit.isEnabled()
    assert dialog.watermark_kind_combo.currentData() == "text"

    dialog.watermark_kind_combo.setCurrentIndex(dialog.watermark_kind_combo.findData("image"))
    assert not dialog.watermark_text_edit.isEnabled()
    assert dialog.watermark_image_edit.isEnabled()
