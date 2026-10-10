"""Image collections, bounded composition, multi-page output, cancellation and continuous capture."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import threading

import pytest
from PySide6.QtCore import QBuffer, QIODevice, QRectF, QSize
from PySide6.QtGui import QColor, QImage
from PySide6.QtPdf import QPdfDocument

from core.image_layout import (ImageLayoutError, ExportCancelled, LayoutOptions, PageOptions, compose_images,
                               decode_image, render_pdf_preview)
from core.save import SaveService
from settings.tool_settings import ToolSettingsManager
from ui.image_layout_dialog import ImageLayoutDialog, ImageSourcePicker


def image(color, width=80, height=60):
    result = QImage(width, height, QImage.Format.Format_ARGB32)
    result.fill(QColor(color))
    return result


def encoded(picture):
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    assert picture.save(buffer, "PNG")
    return bytes(buffer.data())


@pytest.fixture
def config(tmp_settings, tmp_path):
    config = ToolSettingsManager(tmp_settings)
    config.set_screenshot_save_path(str(tmp_path))
    return config


@pytest.fixture
def dialog(qtbot, config):
    window = ImageLayoutDialog(config)
    yield window
    import shiboken6
    if shiboken6.isValid(window):
        window.shutdown()
        if window._worker is not None:
            qtbot.waitUntil(lambda: window._worker is None)
        window.close()


@pytest.mark.parametrize("direction,size,red_pixel,blue_pixel", [
    ("vertical", (84, 129), (10, 10), (10, 75)),
    ("horizontal", (169, 64), (10, 10), (95, 10)),
])
def test_layout_dimensions_order_and_gaps(direction, size, red_pixel, blue_pixel):
    sources = [image("red"), image("blue")]
    options = LayoutOptions(direction=direction, gap=5, padding=2)
    result = compose_images(sources, options)
    assert (result.width(), result.height()) == size
    assert result.pixelColor(*red_pixel).name() == "#ff0000"
    assert result.pixelColor(*blue_pixel).name() == "#0000ff"
    assert result.pixelColor(0, 0).name() == "#ffffff"
    assert sources[0].pixelColor(0, 0).name() == "#ff0000"


def test_common_width_transparency_and_preview_do_not_allocate_full_layout():
    sources = [image("transparent", 100, 50), image("blue", 40, 80)]
    options = LayoutOptions(common_width=200, gap=10, padding=5, background="#00000000")
    size, rects = options.geometry(sources)
    assert size == QSize(210, 520)
    assert [r.size().toSize() for r in rects] == [QSize(200, 100), QSize(200, 400)]
    preview = compose_images(sources, options, preview_edge=130)
    assert max(preview.width(), preview.height()) <= 130
    assert preview.pixelColor(0, 0).alpha() == 0
    assert sources[0].size() == QSize(100, 50)


@pytest.mark.parametrize("options", [LayoutOptions(common_width=16384), LayoutOptions(direction="invalid"), LayoutOptions(gap=-1)])
def test_oversized_or_invalid_layout_rejected_before_allocation(options):
    with pytest.raises(ImageLayoutError):
        options.geometry([image("red", 1, 10000), image("blue", 1, 10000)])


def test_layout_limits_include_image_count_and_empty_sources():
    for images in ([], [QImage()], [image("red", 1, 1)] * 51):
        with pytest.raises(ImageLayoutError):
            LayoutOptions().geometry(images)


def test_compressed_dimensions_are_checked_before_decoding():
    data = encoded(image("red", 100, 100))
    with pytest.raises(ImageLayoutError):
        decode_image(data, remaining_pixels=9999)
    assert decode_image(data).size() == QSize(100, 100)
    with pytest.raises(ImageLayoutError):
        decode_image(b"not an image")


@pytest.mark.parametrize("mode", ["original", "a4", "letter"])
@pytest.mark.parametrize("landscape", [False, True])
def test_pdf_page_sizes_order_margins_and_no_hidden_text(qapp, tmp_path, config, mode, landscape):
    images = [image("red", 120, 60), image("blue", 60, 120), image("transparent", 80, 80)]
    options = PageOptions(mode, landscape, 10)
    destination = tmp_path / "pages.pdf"
    assert SaveService(config).save_image_pages(images, str(destination), options)
    document = QPdfDocument()
    assert document.load(str(destination)) == QPdfDocument.Error.None_
    assert document.pageCount() == 3
    try:
        for index, picture in enumerate(images):
            size, target = options.geometry(picture)
            actual = document.pagePointSize(index)
            assert abs(actual.width() - size.width()) < 1
            assert abs(actual.height() - size.height()) < 1
            assert target.left() >= 10 * 72 / 25.4 - 0.1
            assert target.top() >= 10 * 72 / 25.4 - 0.1
            page = document.render(index, QSize(400, 400))
            assert not page.isNull()
            center = page.pixelColor(200, 200)
            expected = ("#ff0000", "#0000ff", "#ffffff")[index]
            assert center.name() == expected
            assert document.getAllText(index).text() == ""
    finally:
        document.close()


def test_pdf_preview_uses_the_same_geometry_as_export():
    source = image("red", 200, 50)
    options = PageOptions("a4", False, 20)
    preview = render_pdf_preview(source, options)
    assert preview.pixelColor(2, 2).name() == "#ffffff"
    assert preview.pixelColor(preview.width() // 2, preview.height() // 2).name() == "#ff0000"


def test_pdf_original_page_limit_has_a_safe_fixed_paper_alternative():
    source = image("red", 1, 30000)
    with pytest.raises(ImageLayoutError):
        PageOptions().geometry(source)
    assert PageOptions("a4").geometry(source)[1].height() > 0


def test_cancelled_pdf_never_replaces_existing_file(config, tmp_path):
    destination = tmp_path / "keep.pdf"
    destination.write_bytes(b"original")
    cancel = threading.Event()
    assert not SaveService(config).save_image_pages([image("red"), image("blue")], str(destination), PageOptions(),
                                                    cancelled=cancel.is_set, progress=lambda *a: cancel.set())
    assert destination.read_bytes() == b"original"
    assert not list(tmp_path.glob(".versepic-*"))


def test_cancelled_composition_and_atomic_encoding_leave_target_unchanged(config, tmp_path):
    with pytest.raises(ExportCancelled):
        compose_images([image("red")], LayoutOptions(), cancelled=lambda: True)
    destination = tmp_path / "keep.png"
    destination.write_bytes(b"original")
    cancel = threading.Event()
    service = SaveService(config)
    def write(file):
        Path(file).write_bytes(b"new")
        cancel.set()
        return True
    assert not service._atomic_save(str(destination), write, cancelled=cancel.is_set)
    assert destination.read_bytes() == b"original"
    assert not list(tmp_path.glob(".versepic-*"))


def test_dialog_reorder_remove_and_original_images_are_unchanged(dialog):
    red = image("red")
    dialog.add_image("red", red, "red")
    dialog.add_image("blue", image("blue"), "blue")
    assert not dialog.add_image("duplicate", red, "red")
    dialog.move_current(-1)
    assert [name for name, _, _ in dialog.ordered_entries()] == ["blue", "red"]
    red.fill(QColor("green"))
    assert dialog.images()[1].pixelColor(1, 1).name() == "#ff0000"
    dialog.remove_current()
    assert [name for name, _, _ in dialog.ordered_entries()] == ["red"]
    dialog.clear_collection()
    dialog.update_preview()
    assert not dialog.entries and not dialog.export_button.isEnabled()
    assert dialog._preview is None


def test_history_multi_selection_uses_originals_and_rejects_stale_entries(dialog):
    records = {1: SimpleNamespace(id=1, image_id="one", title="one", content_type="image"),
               2: SimpleNamespace(id=2, image_id="two", title="two", content_type="image")}
    manager = Mock(get_item=lambda key: records.get(key), get_image_data=lambda key: encoded(image("red" if key == "one" else "blue")))
    assert dialog.add_history_ids(manager, [1, 2, 3]) == 1
    assert len(dialog.entries) == 2
    assert "1" in dialog.status.text()
    assert dialog.add_history_ids(manager, [1]) == 0
    assert len(dialog.entries) == 2


def test_metadata_picker_paginates_without_loading_image_bytes(qtbot):
    records = [SimpleNamespace(id=i, title=f"Image {i}", created_at=None) for i in range(75)]
    manager = Mock()
    manager.get_history.side_effect = lambda offset, limit, **kwargs: records[offset:offset + limit]
    picker = ImageSourcePicker(manager=manager)
    qtbot.addWidget(picker)
    assert picker.list.count() == 50 and picker.more.isEnabled()
    picker.load_more()
    assert picker.list.count() == 75 and not picker.more.isEnabled()
    picker.list.item(0).setSelected(True)
    picker.list.item(51).setSelected(True)
    assert picker.selected() == [0, 51]
    manager.get_image_data.assert_not_called()


def test_pinned_image_snapshot_pauses_editing_and_checks_original_size(dialog):
    calls = []
    pin = SimpleNamespace(_is_closed=False, canvas=SimpleNamespace(base_size=QSize(80, 60)),
                          devicePixelRatioF=lambda: 1, get_current_image=lambda: image("red"),
                          _with_edit_paused=lambda fn: (calls.append("paused"), fn()))
    assert dialog.add_pin_images([pin]) == 0
    assert calls == ["paused"]
    pin._is_closed = True
    assert dialog.add_pin_images([pin]) == 1
    assert len(dialog.entries) == 1


def test_export_ignores_global_resize_and_uses_visible_layout_geometry(dialog, config, tmp_path, qtbot):
    config.set_app_setting("screenshot_size_mode", "half")
    dialog.add_image("red", image("red"))
    dialog.add_image("blue", image("blue"))
    expected, _ = dialog.layout_options().geometry(dialog.images())
    destination = tmp_path / "combined.png"
    assert dialog.start_export(str(destination))
    qtbot.waitUntil(lambda: dialog._worker is None, timeout=10000)
    assert QImage(str(destination)).size() == expected
    assert dialog.export_button.isEnabled()
    assert "saved" in dialog.status.text().lower()


def test_dialog_page_preview_tracks_reorder_and_exports_same_order(dialog, tmp_path, qtbot):
    dialog.add_image("red", image("red"))
    dialog.add_image("blue", image("blue"))
    dialog.move_current(-1)
    dialog.mode.setCurrentIndex(1)
    dialog.update_preview()
    assert "2" in dialog.status.text() and "1" in dialog.status.text()
    assert dialog._preview.pixelColor(dialog._preview.width() // 2, dialog._preview.height() // 2).name() == "#0000ff"
    destination = tmp_path / "pages.pdf"
    assert dialog.start_export(str(destination))
    qtbot.waitUntil(lambda: dialog._worker is None, timeout=10000)
    document = QPdfDocument()
    assert document.load(str(destination)) == QPdfDocument.Error.None_
    assert document.render(0, QSize(200, 200)).pixelColor(100, 100).name() == "#0000ff"
    document.close()


def test_cancel_on_close_waits_for_worker_and_does_not_lose_existing_file(dialog, tmp_path, qtbot, monkeypatch):
    import ui.image_layout_dialog as module
    original = module.compose_images
    ready, release = threading.Event(), threading.Event()
    def compose(images, options, **kwargs):
        if not kwargs.get("preview_edge"):
            ready.set()
            assert release.wait(5)
        return original(images, options, **kwargs)
    monkeypatch.setattr(module, "compose_images", compose)
    destination = tmp_path / "keep.png"
    destination.write_bytes(b"keep")
    dialog.add_image("red", image("red"))
    dialog.show()
    assert dialog.start_export(str(destination))
    qtbot.waitUntil(ready.is_set)
    dialog.close()
    assert dialog._worker is not None
    release.set()
    qtbot.waitUntil(lambda: dialog._worker is None)
    assert destination.read_bytes() == b"keep"
    # Qt deletion is deferred; closeEvent released all image references already.
    assert not dialog.entries


def test_export_failure_preserves_collection_for_retry(dialog, tmp_path, qtbot, monkeypatch):
    dialog.add_image("red", image("red"))
    monkeypatch.setattr(dialog.save_service, "save_qimage_to_path", lambda *a, **k: False)
    assert dialog.start_export(str(tmp_path / "fail.png"))
    qtbot.waitUntil(lambda: dialog._worker is None)
    assert len(dialog.entries) == 1 and dialog.export_button.isEnabled()
    assert "failed" in dialog.status.text().lower()


def test_oversized_layout_disables_export_but_allows_pdf_mode(dialog):
    dialog.add_image("tall", image("red", 1, 10000))
    dialog.width_spin.setValue(16000)
    dialog.update_preview()
    assert not dialog.export_button.isEnabled()
    dialog.mode.setCurrentIndex(1)
    dialog.paper.setCurrentIndex(1)
    dialog.update_preview()
    assert dialog.export_button.isEnabled()


def test_collect_actions_keep_original_clipboard_and_store_exact_result(qapp, config, monkeypatch):
    from tools.action import ActionTools
    from ui.image_layout_dialog import get_image_layout_window
    from core.last_capture_region import get_last_region
    monkeypatch.setattr("core.last_capture_region._last_region", None)
    collection = get_image_layout_window()
    action = ActionTools.__new__(ActionTools)
    action.scene = SimpleNamespace(selection_model=SimpleNamespace(rect=lambda: QRectF(0, 0, 80, 60)))
    action.export_service = SimpleNamespace(export=lambda rect: image("red"))
    action._temporarily_exit_editing = Mock()
    action._cleanup_and_close = Mock()
    action.parent_window = SimpleNamespace(collection_continue_requested=Mock(), virtual_x=0, virtual_y=0)
    clipboard = Mock()
    monkeypatch.setattr("core.clipboard_utils.deliver_image_async", clipboard)
    try:
        assert action.handle_collect(True)
        assert len(collection.entries) == 1 and collection._hidden_for_capture
        action.parent_window.collection_continue_requested.emit.assert_called_once()
        assert get_last_region().size() == QSize(80, 60)
        clipboard.assert_not_called()
        assert action.handle_collect(False)
        assert len(collection.entries) == 2 and collection.isVisible()
    finally:
        collection.close()


def test_full_collection_keeps_active_capture_and_original_data(qapp, monkeypatch):
    from tools.action import ActionTools
    from ui.image_layout_dialog import get_image_layout_window
    collection = get_image_layout_window()
    for i in range(50):
        collection.add_image(str(i), image("red", 1, 1))
    action = ActionTools.__new__(ActionTools)
    action.scene = SimpleNamespace(selection_model=SimpleNamespace(rect=lambda: QRectF(0, 0, 80, 60)))
    action.parent_window = None
    action._cleanup_and_close = Mock()
    warnings = []
    monkeypatch.setattr("ui.dialogs.show_warning_dialog", lambda *a: warnings.append(a))
    try:
        assert not action.handle_collect(True)
        action._cleanup_and_close.assert_not_called()
        assert len(collection.entries) == 50 and warnings
    finally:
        collection.close()


LAYOUT_MESSAGES = {
  "ImageSourcePicker": [
    "Choose Images",
    "Search image history",
    "Search",
    "Load more",
    "Add selected",
    "Cancel",
    "Ctrl / Shift selects multiple images. Nothing is copied or deleted.",
    "Pinned image %1",
    "Image",
    "Showing up to 1000 records. Search to narrow the list."
  ],
  "ImageLayoutDialog": [
    "Image Layout and PDF",
    "Add history images",
    "Add pinned images",
    "Add image files",
    "Combined image",
    "One image per PDF page",
    "Vertical",
    "Horizontal",
    "Original widths",
    "White",
    "Transparent",
    "Dark",
    "Original size (96 pixels/inch)",
    "A4",
    "Letter",
    "Portrait",
    "Landscape",
    "Output",
    "Direction",
    "Common width (px)",
    "Gap (px)",
    "Padding (px)",
    "Background",
    "PDF paper",
    "Orientation",
    "Page margins",
    "Drag images to reorder. Layout size is used exactly; file quality follows settings. PDF pages have a white background and no OCR text layer.",
    "Image order",
    "Move up",
    "Move down",
    "Remove image",
    "Clear collection",
    "Add images to begin. Up to 50 images and 64 megapixels in total.",
    "Cancel export",
    "Export…",
    "Image %1",
    "Pinned image",
    "%1 image(s) could not be added: missing, invalid, or over the collection limit.",
    "%1 pages · Previewing page %2",
    "%1 images · %2 × %3 px",
    "This layout exceeds the image or page size limit. Reduce the width or choose A4 / Letter.",
    "Export collection",
    "Choose a file extension matching the selected output.",
    "Exporting…",
    "Cancelling…",
    "Export saved.",
    "Export cancelled.",
    "Export failed. Check image limits, folder permissions and free space.",
    "Choose Images"
  ],
  "ClipboardWindow": [
    "Add to image layout / PDF"
  ],
  "SystemTray": [
    "Image layout / PDF",
    "Arrange pinned images…"
  ],
  "Toolbar": [
    "Collect and capture next",
    "Collect and review images"
  ],
  "ToolbarLayoutDialog": [
    "Collect and capture next",
    "Collect and review images"
  ],
  "ActionTools": [
    "Screenshot %1",
    "Collection unavailable",
    "Finish exporting or remove images from the collection before adding more."
  ]
}

@pytest.mark.parametrize("lang", ["en", "zh", "ja", "ko"])
def test_compiled_layout_messages(qapp, lang):
    from PySide6.QtCore import QTranslator
    translator = QTranslator()
    assert translator.load(str(Path(__file__).resolve().parents[1] / "translations" / f"app_{lang}.qm"))
    for context, messages in LAYOUT_MESSAGES.items():
        for source in messages:
            assert translator.translate(context, source), (lang, context, source)


def test_continuous_capture_uses_real_teardown_and_reuses_clean_shell(qapp, config, qtbot, monkeypatch):
    from PySide6.QtCore import QObject
    from main_app import MainApp
    from ui.image_layout_dialog import get_image_layout_window
    from ui.screenshot_window import ScreenshotWindow
    config.set_smart_selection(False)
    main = MainApp.__new__(MainApp)
    QObject.__init__(main)
    main.app, main.config_manager = qapp, config
    main.screenshot_window = main.clipboard_window = main._capture_countdown = main._capture_thread = None
    main.tray_icon = None
    main._quitting = main._capture_busy = False
    main._collection_resume_timer = None
    rect = QRectF(0, 0, 400, 300)
    monkeypatch.setattr("capture.capture_service.CaptureService.capture_all_screens", lambda _: (image("blue", 400, 300), rect))
    collection = get_image_layout_window()
    try:
        main._on_capture_ready(image("red", 400, 300), rect)
        window = main.screenshot_window
        assert isinstance(window, ScreenshotWindow)
        window.scene.selection_model.initialize_confirmed_rect(QRectF(20, 20, 80, 60))
        old_action = window.action_handler
        window.toolbar.collect_next_btn.click()
        assert old_action.parent_window is None  # The real teardown clears this reference.
        assert len(collection.entries) == 1
        qtbot.waitUntil(lambda: window._session_active, timeout=5000)
        assert main.screenshot_window is window and not window.scene.selection_model.is_confirmed
        window.scene.selection_model.initialize_confirmed_rect(QRectF(20, 20, 80, 60))
        window.toolbar.collect_review_btn.click()
        assert len(collection.entries) == 2
        assert collection.images()[0].pixelColor(10, 10).name() == "#ff0000"
        assert collection.images()[1].pixelColor(10, 10).name() == "#0000ff"
        assert collection.isVisible()
        main.start_screenshot()
        qtbot.waitUntil(lambda: window._session_active)
        window.cleanup_and_close()
        qtbot.waitUntil(collection.isVisible)
        assert len(collection.entries) == 2
    finally:
        main._cancel_pending_capture()
        if main._capture_thread:
            assert main._capture_thread.wait(5000)
        if main.screenshot_window:
            main.screenshot_window.full_destroy()
        collection.close()
        main.deleteLater()


def test_image_budget_rejects_before_collection_changes(dialog, monkeypatch):
    monkeypatch.setattr(dialog, "remaining_pixels", lambda: 100)
    with pytest.raises(ImageLayoutError):
        dialog.add_image("too big", image("red", 11, 10))
    assert not dialog.entries and dialog.list.count() == 0


def test_busy_collection_cannot_be_mutated(dialog, tmp_path, qtbot, monkeypatch):
    release = threading.Event()
    def write(*args, **kwargs):
        assert release.wait(5)
        return False
    monkeypatch.setattr(dialog.save_service, "save_qimage_to_path", write)
    dialog.add_image("red", image("red"))
    dialog.add_image("blue", image("blue"))
    try:
        assert dialog.start_export(str(tmp_path / "busy.png"))
        with pytest.raises(ImageLayoutError):
            dialog.add_image("new", image("green"))
        dialog.clear_collection()
        dialog.remove_current()
        dialog.move_current(-1)
        assert [name for name, _, _ in dialog.ordered_entries()] == ["red", "blue"]
    finally:
        release.set()
        qtbot.waitUntil(lambda: dialog._worker is None)


def test_pdf_failure_keeps_existing_file_and_reports_no_partial_success(config, tmp_path, monkeypatch):
    destination = tmp_path / "old.pdf"
    destination.write_bytes(b"original")
    def fail(images, temporary, *args, **kwargs):
        Path(temporary).write_bytes(b"partial")
        raise OSError("Disk failure")
    monkeypatch.setattr("core.image_layout.write_pdf_pages", fail)
    assert not SaveService(config).save_image_pages([image("red")], str(destination), PageOptions())
    assert destination.read_bytes() == b"original"
    assert not list(tmp_path.glob(".versepic-*"))


def test_history_action_adds_to_collection_without_pasting(qapp, monkeypatch):
    from ui.image_layout_dialog import get_image_layout_window
    from clipboard.ui.windows.clipboard_window import ClipboardWindow
    manager = Mock(get_item=Mock(return_value=SimpleNamespace(id=17, image_id="x", title="fixture", content_type="image")),
                   get_image_data=Mock(return_value=encoded(image("red"))))
    owner = SimpleNamespace(manager=manager, close=Mock())
    try:
        ClipboardWindow._add_to_image_layout(owner, 17)
        collection = get_image_layout_window()
        assert len(collection.entries) == 1 and collection.isVisible()
        owner.close.assert_called_once()
    finally:
        get_image_layout_window().close()


def test_cancelled_save_cleans_only_reserved_placeholder(config, tmp_path):
    service = SaveService(config)
    reserved = service.reserve_save_path(directory=str(tmp_path))
    assert not service.save_qimage_to_path(image("red"), reserved, cancelled=lambda: True)
    assert not Path(reserved).exists()
    old = tmp_path / "old.png"
    old.write_bytes(b"preserve")
    assert not service.save_qimage_to_path(image("red"), str(old), cancelled=lambda: True)
    assert old.read_bytes() == b"preserve"


def test_collection_close_and_reject_destroy_idle_window(qapp,config):
    from PySide6.QtCore import QCoreApplication,QEvent
    import shiboken6
    for method in ("close","reject"):
        window=ImageLayoutDialog(config);window.add_image("sample",image("red"));window.show()
        getattr(window,method)()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        assert not shiboken6.isValid(window)
