"""Output encoding, names, asynchronous option snapshots and persistent regions."""
from datetime import datetime
import json
from pathlib import Path
import random
import threading
from unittest.mock import Mock

from PIL import Image, ImageChops, ImageStat
import pytest
from PySide6.QtCore import QObject, QRect, QSettings, Slot
from PySide6.QtGui import QColor, QImage

from capture.region_presets import PresetLayoutChanged, RegionPresetStore
from core.image_output import ImageOutputOptions, safe_filename_part, validate_filename_template
from core.save import SaveService, save_notifications
from settings.tool_settings import ToolSettingsManager
from ui.selection_info.geometry_dialog import RegionGeometryDialog


LAYOUT = [{"name": "left", "rect": [-400, -200, 1200, 800], "dpi": [144, 144], "primary": True}]
BOUNDS = QRect(-400, -200, 1200, 800)


@pytest.fixture
def config(tmp_settings, tmp_path):
    config = ToolSettingsManager(tmp_settings)
    config.set_screenshot_save_path(str(tmp_path / "images"))
    return config


@pytest.fixture
def service(config, qapp):
    return SaveService(config)


def source_image():
    image = QImage(100, 60, QImage.Format.Format_ARGB32)
    image.fill(QColor("#2175a0"))
    image.setPixelColor(0, 0, QColor(0, 0, 0, 0))
    return image


@pytest.mark.parametrize("backend", ["qt", "pil"])
@pytest.mark.parametrize("fmt", ["PNG", "JPG", "BMP", "WEBP", "PDF"])
@pytest.mark.parametrize("mode,size", [("original", (100, 60)), ("half", (50, 30)), ("width", (37, 22))])
def test_real_encoders_use_requested_output_size(service, tmp_path, backend, fmt, mode, size):
    options = ImageOutputOptions(size_mode=mode, width=37, quality=93)
    output = tmp_path / f"{backend}-{mode}.{fmt.lower()}"
    if backend == "qt":
        source = source_image()
        assert service.save_qimage_to_path(source, str(output), image_format=fmt, output_options=options)
        assert (source.width(), source.height()) == (100, 60)
    else:
        source = Image.new("RGBA", (100, 60), (33, 117, 160, 255))
        assert service._save_pil_to_path(source, str(output), fmt, pdf_dpi=72, output_options=options)
        assert source.size == (100, 60)
    if fmt == "PDF":
        from PySide6.QtPdf import QPdfDocument
        document = QPdfDocument()
        assert document.load(str(output)) == QPdfDocument.Error.None_
        assert document.pageCount() == 1
        points = document.pagePointSize(0)
        dpi = 300 if backend == "qt" else 72
        # Qt stores page geometry on an integer-point grid; embedded raster pixels remain exact.
        assert abs(points.width() - size[0] * 72 / dpi) <= 0.5
        assert abs(points.height() - size[1] * 72 / dpi) <= 0.5
        import re
        rasters = re.findall(rb"/Subtype\s*/Image\b(?:(?!>>).)*?/Width\s+(\d+)\s*/Height\s+(\d+)",
                             output.read_bytes(), re.S)
        assert size in [(int(w), int(h)) for w, h in rasters]
        document.close()
    else:
        with Image.open(output) as saved:
            assert saved.size == size


@pytest.mark.parametrize("fmt,expected", [("JPG", (17,)), ("WEBP", (17,)), ("PNG", ()), ("BMP", ())])
def test_qt_quality_is_passed_only_to_lossy_formats(service, tmp_path, monkeypatch, fmt, expected):
    calls = []
    def encode(image, output, image_format, *args):
        calls.append((image_format, args))
        Path(output).write_bytes(b"encoded-test-fixture")
        return True
    monkeypatch.setattr(QImage, "save", encode)
    assert service.save_qimage_to_path(source_image(), str(tmp_path / "image"), image_format=fmt,
                                      output_options=ImageOutputOptions(quality=17))
    assert calls == [(fmt, expected)]


@pytest.mark.parametrize("fmt", ["JPG", "WEBP"])
@pytest.mark.parametrize("backend", ["qt", "pil"])
def test_quality_changes_real_file_size_and_reconstruction_error(service, tmp_path, fmt, backend):
    pixels = random.Random(37).randbytes(128 * 96 * 3)
    source = Image.frombytes("RGB", (128, 96), pixels)
    image = QImage(pixels, 128, 96, 128 * 3, QImage.Format.Format_RGB888).copy()
    metrics = []
    for quality in (15, 95):
        file = tmp_path / f"{backend}-{quality}.{fmt.lower()}"
        options = ImageOutputOptions(quality=quality)
        if backend == "qt":
            assert service.save_qimage_to_path(image, str(file), image_format=fmt, output_options=options)
        else:
            assert service._save_pil_to_path(source, str(file), fmt, pdf_dpi=72, output_options=options)
        with Image.open(file) as decoded:
            error = sum(ImageStat.Stat(ImageChops.difference(source, decoded.convert("RGB"))).mean)
        metrics.append((file.stat().st_size, error))
    assert metrics[1][0] > metrics[0][0]
    assert metrics[1][1] < metrics[0][1]


def test_jpeg_alpha_flattens_to_white_and_dpr_does_not_crop(service, tmp_path):
    image = QImage(32, 24, QImage.Format.Format_ARGB32)
    image.fill(QColor(0, 0, 0, 0))
    image.setPixelColor(31, 23, QColor("red"))
    image.setDevicePixelRatio(2)
    png = tmp_path / "dpr.png"
    assert service.save_qimage_to_path(image, str(png))
    decoded = QImage(str(png))
    assert decoded.pixelColor(31, 23).name() == "#ff0000"
    jpg = tmp_path / "alpha.jpg"
    assert service.save_qimage_to_path(image, str(jpg))
    assert QImage(str(jpg)).pixelColor(0, 0).red() >= 250
    assert image.devicePixelRatio() == 2


@pytest.mark.parametrize("existing", [b"valuable existing content", b""])
def test_failed_encoding_keeps_existing_target(service, tmp_path, monkeypatch, existing):
    target = tmp_path / "existing.png"
    target.write_bytes(existing)
    monkeypatch.setattr(service, "_save_qimage_to_path", lambda *a, **k: False)
    assert not service.save_qimage_to_path(source_image(), str(target))
    assert target.read_bytes() == existing
    assert not list(tmp_path.glob(".versepic-*"))


def test_failed_reserved_save_removes_only_its_own_placeholder(service, tmp_path, monkeypatch):
    target = service.reserve_save_path(directory=str(tmp_path))
    monkeypatch.setattr(service, "_save_qimage_to_path", lambda *a, **k: False)
    assert not service.save_qimage_to_path(source_image(), target)
    assert not Path(target).exists()
    assert not list(tmp_path.glob(".versepic-*"))


def test_oversized_resize_fails_without_modifying_original(service, tmp_path):
    target = tmp_path / "keep.png"
    target.write_bytes(b"keep")
    image = QImage(1, 10000, QImage.Format.Format_RGB32)
    assert not service.save_qimage_to_path(image, str(target), output_options=ImageOutputOptions(size_mode="width", width=16384))
    assert target.read_bytes() == b"keep"


@pytest.mark.parametrize("template", ["{project.__class__}", "{project[0]}", "{index:100000000}", "{unknown}", "{index!r}", "{"])
def test_templates_reject_accessors_and_unbounded_formatting(template):
    with pytest.raises(ValueError):
        validate_filename_template(template)


@pytest.mark.parametrize("name", ["CON", "con.txt", "LPT1", "COM¹.txt", "../escape", "x:y", "a/b\\c", "..", "a\nname"])
def test_filename_parts_cannot_escape_or_use_device_names(name):
    result = safe_filename_part(name)
    assert result not in ("", ".", "..")
    assert all(c not in result for c in '/\\:<>"|?*\n')
    assert not result.upper().split(".")[0] in {"CON", "LPT1", "COM¹"}


def test_template_date_folder_and_collision_names_match_snapshot(service, tmp_path):
    options = ImageOutputOptions(directory=str(tmp_path), template="{date}_{project}_{index}", project="case/42",
                                 date_folders=True, moment=datetime(2026, 10, 9, 23, 59, 59))
    first = Path(service.reserve_save_path(prefix="", output_options=options))
    second = Path(service.reserve_save_path(prefix="", output_options=options))
    assert first.parent == tmp_path / "2026-10-09"
    assert first.name == "2026-10-09_case_42_001.png"
    assert second.name == "2026-10-09_case_42_002.png"
    assert first.name == options.filename("", "", "PNG")


def test_concurrent_reservation_never_overwrites_a_file(service, tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    options = ImageOutputOptions(template="shot_{index}")
    with ThreadPoolExecutor(max_workers=4) as pool:
        paths = list(pool.map(lambda _: service.reserve_save_path(directory=str(tmp_path), output_options=options), range(12)))
    assert len(set(paths)) == 12
    assert sorted(Path(p).name for p in paths) == [f"shot_{i:03d}.png" for i in range(1, 13)]


def test_clipboard_delivery_snapshots_options_before_background_work(service, config, tmp_path, monkeypatch):
    from core import clipboard_utils
    config.set_app_setting("screenshot_size_mode", "half")
    config.set_app_setting("screenshot_name_template", "{project}_{index}")
    config.set_app_setting("screenshot_project_name", "before")
    ready, release = threading.Event(), threading.Event()
    original = service.save_qimage
    caller = threading.get_ident()
    def save(image, **kwargs):
        assert threading.get_ident() != caller
        ready.set()
        assert release.wait(5)
        return original(image, **kwargs)
    monkeypatch.setattr(service, "save_qimage", save)
    monkeypatch.setattr(clipboard_utils, "copy_image_to_clipboard", lambda *a, **k: None)
    thread = clipboard_utils.deliver_image_async(source_image(), save_service=service,
                                                save_kwargs={"directory": str(tmp_path), "prefix": ""},
                                                write_file_reference=False)
    assert ready.wait(5)
    config.set_app_setting("screenshot_size_mode", "original")
    config.set_app_setting("screenshot_project_name", "after")
    monkeypatch.setattr(config, "get_app_setting", lambda *a: pytest.fail("Worker accessed live settings"))
    release.set()
    thread.join(5)
    assert not thread.is_alive()
    output = QImage(str(tmp_path / "before_001.png"))
    assert (output.width(), output.height()) == (50, 30)


def test_worker_save_failure_reaches_gui_thread(service, tmp_path, qtbot, monkeypatch):
    calls = []
    caller = threading.get_ident()
    class Receiver(QObject):
        @Slot(str)
        def failed(self, path):
            calls.append((path, threading.get_ident()))
    receiver = Receiver()
    notifier = save_notifications()
    notifier.failed.connect(receiver.failed)
    monkeypatch.setattr(service, "_save_qimage_to_path", lambda *a, **k: False)
    try:
        service.save_qimage_async(source_image(), directory=str(tmp_path))
        qtbot.waitUntil(lambda: bool(calls))
        assert calls[0][1] == caller
    finally:
        notifier.failed.disconnect(receiver.failed)


def test_batch_pin_save_uses_real_output_options_and_keeps_old_files(config, qapp, tmp_path, monkeypatch):
    from pin.pin_manager import PinManager
    from types import SimpleNamespace
    old = PinManager._instance
    PinManager._instance = None
    manager = PinManager.instance()
    config.set_app_setting("screenshot_size_mode", "half")
    monkeypatch.setattr("core.save.get_tool_settings_manager", lambda: config)
    manager.pin_windows = [SimpleNamespace(get_current_image=source_image)]
    (tmp_path / "pins_001.png").write_bytes(b"existing")
    try:
        assert manager.save_all_to_directory(str(tmp_path)) == (1, 0)
        assert (tmp_path / "pins_001.png").read_bytes() == b"existing"
        output = QImage(str(tmp_path / "pins_002.png"))
        assert (output.width(), output.height()) == (50, 30)
    finally:
        manager.pin_windows = []
        PinManager._instance = old


def test_saved_region_survives_settings_reopen_and_supports_rename_delete(config, tmp_settings):
    store = RegionPresetStore(config)
    identifier = store.save("Report", QRect(-100, 20, 320, 180), LAYOUT, locked=True)
    reopened = ToolSettingsManager(QSettings(tmp_settings.fileName(), QSettings.Format.IniFormat))
    store = RegionPresetStore(reopened)
    assert store.resolve(identifier, LAYOUT, BOUNDS) == (QRect(-100, 20, 320, 180), True)
    store.rename(identifier, "Report renamed")
    assert store.get(identifier)["name"] == "Report renamed"
    assert store.delete(identifier) is True
    assert store.load() == []


@pytest.mark.parametrize("change", ["position", "dpi", "missing"])
def test_saved_region_rejects_layout_or_scale_changes(config, change):
    store = RegionPresetStore(config)
    identifier = store.save("Test", QRect(-100, 20, 320, 180), LAYOUT)
    other = json.loads(json.dumps(LAYOUT))
    if change == "position":
        other[0]["rect"][0] = 0
    elif change == "dpi":
        other[0]["dpi"] = [192, 192]
    else:
        other[0]["name"] = "different monitor"
    with pytest.raises(PresetLayoutChanged):
        store.resolve(identifier, other, BOUNDS)
    assert store.get(identifier)["rect"] == [-100, 20, 320, 180]


def test_corrupt_presets_are_not_overwritten(config):
    original = '{"unknown":true}'
    config.set_app_setting("capture_region_presets", original)
    with pytest.raises(ValueError):
        RegionPresetStore(config).save("New", QRect(0, 0, 80, 60), LAYOUT)
    assert config.get_app_setting("capture_region_presets", "") == original


def test_duplicate_region_name_is_not_an_implicit_overwrite(config):
    store = RegionPresetStore(config)
    store.save("Report", QRect(0, 0, 80, 60), LAYOUT)
    with pytest.raises(ValueError):
        store.save("report", QRect(0, 0, 160, 90), LAYOUT)
    assert store.load()[0]["rect"] == [0, 0, 80, 60]


def test_preset_dialog_crud_and_mismatch_require_review(config, qtbot):
    store = RegionPresetStore(config)
    identifier = store.save("Report", QRect(-100, 20, 320, 180), LAYOUT)
    current = QRect(20, 30, 100, 80)
    dialog = RegionGeometryDialog(current, BOUNDS, config=config, layout_signature=LAYOUT)
    qtbot.addWidget(dialog)
    dialog.preset_combo.setCurrentIndex(dialog.preset_combo.findData(identifier))
    assert dialog.selected_rect() == QRect(-100, 20, 320, 180)
    dialog.preset_name.setText("Renamed")
    dialog.preset_rename.click()
    assert store.get(identifier)["name"] == "Renamed"
    other = json.loads(json.dumps(LAYOUT))
    other[0]["dpi"] = [192, 192]
    mismatch = RegionGeometryDialog(current, BOUNDS, config=config, layout_signature=other)
    qtbot.addWidget(mismatch)
    mismatch.preset_combo.setCurrentIndex(mismatch.preset_combo.findData(identifier))
    assert mismatch.selected_rect() == current
    assert not mismatch.apply_button.isEnabled()
    mismatch.preset_save.click()
    assert mismatch.apply_button.isEnabled()
    assert store.resolve(identifier, other, BOUNDS)[0] == current
    mismatch.preset_delete.click()
    assert store.load() == []


def test_output_settings_save_reset_and_preserve_invalid_template(config, qtbot, monkeypatch):
    from ui.settings_ui.dialog import SettingsDialog
    dialog = SettingsDialog(config_manager=config)
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.output_size_combo.setCurrentIndex(2)
    dialog.output_width_spin.setValue(128)
    dialog.output_quality_spin.setValue(73)
    dialog.output_template_edit.setText("{project}_{index}")
    dialog.output_project_edit.setText("report")
    dialog.output_date_toggle.setChecked(True)
    assert "report_001.png" in dialog.output_name_preview.text()
    assert dialog._has_unsaved_changes()
    monkeypatch.setattr("ui.settings_ui.dialog.validate_global_hotkey_edits", lambda *a, **k: True)
    dialog.apply_settings()
    options = ImageOutputOptions.from_config(config)
    assert (options.size_mode, options.width, options.quality) == ("width", 128, 73)
    assert options.template == "{project}_{index}" and options.date_folders
    dialog._reset_screenshot_settings_page()
    assert dialog.output_size_combo.currentData() == "original"
    assert dialog.output_template_edit.text() == ""
    dialog.refresh_settings()
    assert dialog.output_width_spin.value() == 128
    warnings = []
    monkeypatch.setattr("ui.settings_ui.dialog.show_warning_dialog", lambda *args: warnings.append(args))
    dialog.output_template_edit.setText("{project.__class__}")
    dialog.apply_settings()
    assert warnings
    assert config.get_app_setting("screenshot_name_template", "") == "{project}_{index}"
    dialog._skip_unsaved_close_prompt = True


def test_failed_atomic_replace_keeps_original_and_cleans_staging(service, tmp_path, monkeypatch):
    target = tmp_path / "locked.png"
    target.write_bytes(b"original")
    monkeypatch.setattr("core.save.os.replace", Mock(side_effect=PermissionError("locked")))
    assert not service.save_qimage_to_path(source_image(), str(target))
    assert target.read_bytes() == b"original"
    assert not list(tmp_path.glob(".versepic-*"))


def test_manual_save_failure_keeps_capture_open(service, tmp_path, monkeypatch):
    from tools.action import ActionTools
    action = ActionTools.__new__(ActionTools)
    action.config_manager = service.config_manager
    action.parent_window = Mock()
    action._temporarily_exit_editing = Mock()
    action._remember_last_region = Mock()
    action._cleanup_and_close = Mock()
    action.export_service = Mock()
    action.export_service.scene.selection_model.rect.return_value = QRect(0, 0, 100, 60)
    action.export_service.export.return_value = source_image()
    action.save_service = Mock(save_qimage_to_path=Mock(return_value=False))
    warnings = []
    monkeypatch.setattr("tools.action.QFileDialog.getSaveFileName", lambda *a: (str(tmp_path / "fail.png"), "PNG (*.png)"))
    monkeypatch.setattr("ui.dialogs.show_warning_dialog", lambda *a: warnings.append(a))
    action.handle_save()
    assert warnings
    action._cleanup_and_close.assert_not_called()


def test_pil_async_freezes_settings_before_encoding(service, config, tmp_path, monkeypatch):
    config.set_app_setting("screenshot_size_mode", "half")
    ready, release, done = threading.Event(), threading.Event(), threading.Event()
    original = service._save_pil_to_path
    def save(*args, **kwargs):
        ready.set()
        assert release.wait(5)
        return original(*args, **kwargs)
    monkeypatch.setattr(service, "_save_pil_to_path", save)
    output = service.save_pil_async(Image.new("RGB", (100, 60), "blue"), directory=str(tmp_path),
                                    callback=lambda ok, path: done.set())
    assert ready.wait(5)
    config.set_app_setting("screenshot_size_mode", "original")
    monkeypatch.setattr(config, "get_app_setting", lambda *a: pytest.fail("Worker accessed live settings"))
    release.set()
    assert done.wait(5)
    with Image.open(output) as image:
        assert image.size == (50, 30)


def test_layout_comparison_ignores_monitor_enumeration_order(config):
    store = RegionPresetStore(config)
    layout = LAYOUT + [{"name": "right", "rect": [800, -200, 1200, 800], "dpi": [96, 96], "primary": False}]
    identifier = store.save("Two", QRect(0, 0, 80, 60), layout)
    assert store.resolve(identifier, list(reversed(layout)), BOUNDS)[0] == QRect(0, 0, 80, 60)


def test_region_settings_reset_does_not_delete_explicit_presets(config, qtbot):
    from ui.settings_ui.dialog import SettingsDialog
    store = RegionPresetStore(config)
    identifier = store.save("Keep", QRect(0, 0, 80, 60), LAYOUT)
    dialog = SettingsDialog(config_manager=config)
    qtbot.addWidget(dialog)
    dialog._reset_screenshot_settings_page()
    assert store.get(identifier)["name"] == "Keep"
    dialog._skip_unsaved_close_prompt = True


OUTPUT_MESSAGES = {
  "SettingsDialog": [
    "Saved Image Size",
    "These settings affect saved files; clipboard images keep their original size.",
    "Original size",
    "50% size",
    "Specified width",
    "Image Quality",
    "Applies to JPG and WebP only. PNG and BMP remain lossless.",
    "Output Presets",
    "Original PNG",
    "Share WebP",
    "Automatic File Names",
    "Leave empty for the original naming. Fields: {date}, {time}, {timestamp}, {index}, {project}, {prefix}, {suffix}.",
    "Project Name",
    "Optional text for the {project} field. Window titles are never added automatically.",
    "Date Subfolders",
    "Place automatically named images in a YYYY-MM-DD folder.",
    "File Name Preview",
    "Example for a normal screenshot; capture time and collisions determine the final name.",
    "Invalid template: use only the listed fields, without formatting.",
    "Invalid File Name Template",
    "Use only the listed filename fields, without formatting."
  ],
  "RegionGeometryDialog": [
    "Saved Regions",
    "Preset name",
    "Save preset",
    "Update preset",
    "Rename",
    "Delete preset",
    "Preset changes are saved immediately; Apply changes the selection.",
    "Saved region data is invalid. Existing data was left unchanged.",
    "No preset",
    "Saved region loaded.",
    "Screen layout or scale changed. Review the current region and update the preset, or choose No preset.",
    "Preset saved.",
    "Could not save preset. Check the name and settings location.",
    "Preset renamed.",
    "Could not rename preset. Names must be unique.",
    "Preset deleted.",
    "Could not delete preset."
  ],
  "MainApp": [
    "Save failed",
    "Could not save the image. Check the output size, folder permissions and free space."
  ],
  "ActionTools": [
    "Save Failed",
    "Failed to save image."
  ]
}

@pytest.mark.parametrize("language", ["en", "zh", "ja", "ko"])
def test_compiled_output_and_preset_messages(qapp, language):
    from PySide6.QtCore import QTranslator
    translator = QTranslator()
    file = Path(__file__).resolve().parents[1] / "translations" / f"app_{language}.qm"
    assert translator.load(str(file))
    for context, sources in OUTPUT_MESSAGES.items():
        for source in sources:
            assert translator.translate(context, source), (language, context, source)


OUTPUT_MESSAGES["RegionGeometryDialog"] += ["Saved file: %1 × %2 px", "Saved file would be too large. Reduce the output width."]


def test_geometry_distinguishes_capture_pixels_from_resized_file(config, qtbot, tmp_path):
    config.set_app_setting("screenshot_size_mode", "half")
    dialog = RegionGeometryDialog(QRect(0, 0, 320, 180), BOUNDS, config=config, layout_signature=LAYOUT, padding=9)
    qtbot.addWidget(dialog)
    assert "338" in dialog.output_size.text() and "198" in dialog.output_size.text()
    assert "169" in dialog.saved_size.text() and "99" in dialog.saved_size.text()
    image = QImage(338, 198, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    file = tmp_path / "with-border.png"
    assert SaveService(config).save_qimage_to_path(image, str(file))
    assert QImage(str(file)).size().width() == 169 and QImage(str(file)).height() == 99


def test_truncated_index_template_still_produces_unique_names(service, tmp_path):
    options = ImageOutputOptions(template="a" * 118 + "{index}")
    validate_filename_template(options.template)
    names = [service.reserve_save_path(directory=str(tmp_path), output_options=options) for _ in range(3)]
    assert len(set(names)) == 3
    assert all(len(Path(name).name) < 255 for name in names)


def test_invalid_numeric_settings_do_not_break_clipboard_submission(config, monkeypatch):
    original = config.get_app_setting
    def get(key, default):
        if key == "screenshot_output_width":
            raise ValueError("Corrupt numeric setting")
        return original(key, default)
    monkeypatch.setattr(config, "get_app_setting", get)
    monkeypatch.setattr(config, "get_screenshot_quality", Mock(side_effect=ValueError("bad quality")))
    options = ImageOutputOptions.from_config(config)
    assert options.width == 1600 and options.quality == 85


def test_share_preset_shrinks_small_images_instead_of_upscaling(config, qtbot, tmp_path):
    from PySide6.QtWidgets import QAbstractButton
    from ui.settings_ui.dialog import SettingsDialog
    dialog = SettingsDialog(config_manager=config)
    qtbot.addWidget(dialog)
    button = next(button for button in dialog.findChildren(QAbstractButton) if button.text() == dialog.tr("Share WebP"))
    button.click()
    assert dialog.screenshot_format_combo.currentData() == "WEBP"
    assert dialog.output_size_combo.currentData() == "half"
    options = ImageOutputOptions(size_mode=dialog.output_size_combo.currentData(),
                                 width=dialog.output_width_spin.value(), quality=dialog.output_quality_spin.value())
    target = tmp_path / "share.webp"
    assert SaveService(config).save_qimage_to_path(source_image(), str(target), output_options=options)
    assert (QImage(str(target)).width(), QImage(str(target)).height()) == (50, 30)
    dialog._skip_unsaved_close_prompt = True


OUTPUT_MESSAGES["SettingsDialog"].append("Transparent areas use white in JPG, BMP and PDF.")


@pytest.mark.parametrize("backend", ["qt", "pil"])
@pytest.mark.parametrize("fmt", ["PNG", "WEBP", "JPG", "BMP"])
def test_transparency_is_preserved_or_explicitly_flattened_white(service, tmp_path, backend, fmt):
    target = tmp_path / f"alpha-{backend}.{fmt.lower()}"
    if backend == "qt":
        image = QImage(16, 16, QImage.Format.Format_ARGB32)
        image.fill(QColor(0, 0, 0, 0))
        assert service.save_qimage_to_path(image, str(target), image_format=fmt)
        assert image.pixelColor(0, 0).alpha() == 0
    else:
        image = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
        assert service._save_pil_to_path(image, str(target), fmt, pdf_dpi=72)
        assert image.getpixel((0, 0))[3] == 0
    with Image.open(target) as decoded:
        pixel = decoded.convert("RGBA").getpixel((0, 0))
    if fmt in ("PNG", "WEBP"):
        assert pixel[3] == 0
    else:
        assert pixel[3] == 255 and min(pixel[:3]) >= 250


def test_long_screenshot_honors_selected_format_and_size(service, config, tmp_path, qtbot):
    from types import SimpleNamespace
    from stitch.scroll_window import ScrollCaptureWindow
    config.set_screenshot_format("WEBP")
    config.set_app_setting("screenshot_size_mode", "half")
    window = SimpleNamespace(stitched_result=Image.new("RGB", (100, 60), "blue"),
                             scroll_direction="vertical", save_directory=str(tmp_path), save_service=service)
    ScrollCaptureWindow._save_result(window)
    def saved():
        paths = list(tmp_path.glob("*.webp"))
        return bool(paths and paths[0].stat().st_size > 0)
    qtbot.waitUntil(saved)
    with Image.open(next(tmp_path.glob("*.webp"))) as image:
        assert image.size == (50, 30)
