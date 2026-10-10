"""Frozen multi-region capture, real Windows cursor compositing and basket transactions."""
from contextlib import contextmanager
from dataclasses import replace
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QPoint, QRect, QRectF, QTimer, Qt
from PySide6.QtGui import QColor, QImage, QPen, QBrush
from PySide6.QtWidgets import QDialog
import win32con
import win32gui

from capture.multi_region import MultiRegionSelection
from capture.cursor_capture import cursor_snapshot, composite_cursor
from settings.tool_settings import ToolSettingsManager
from ui.multi_region_dialog import MultiRegionDialog


def solid(color="white", width=400, height=300):
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(QColor(color))
    return image


def test_multi_regions_keep_overlap_as_independent_ordered_rectangles():
    model = MultiRegionSelection(QRect(0, 0, 400, 300))
    first, second = QRect(20, 30, 80, 60), QRect(40, 40, 80, 60)
    assert model.add(first) and model.add(second)
    assert model.regions == [first, second]
    assert model.pixels == 9600
    first.setWidth(10)
    rectangles = model.regions
    rectangles[0].moveLeft(300)
    assert model.regions[0] == QRect(20, 30, 80, 60)


def test_multi_region_undo_redo_cover_add_delete_reorder_clear():
    model = MultiRegionSelection(QRect(0, 0, 400, 300))
    a, b = QRect(0, 0, 40, 40), QRect(50, 50, 80, 60)
    model.add(a)
    model.add(b)
    model.move(1, -1)
    assert model.regions == [b, a]
    model.remove(0)
    assert model.regions == [a]
    model.clear()
    assert model.regions == []
    for expected in ([a], [b, a], [a, b], [a], []):
        assert model.undo()
        assert model.regions == expected
    for expected in ([a], [a, b], [b, a], [a], []):
        assert model.redo()
        assert model.regions == expected
    model.undo()
    model.add(b)
    assert not model.can_redo


@pytest.mark.parametrize("rect", [QRect(0, 0, 7, 40), QRect(450, 0, 80, 60), QRect(-40, -40, 45, 45)])
def test_invalid_regions_leave_selection_and_undo_unchanged(rect):
    model = MultiRegionSelection(QRect(0, 0, 400, 300))
    with pytest.raises(ValueError):
        model.add(rect)
    assert model.regions == [] and not model.can_undo


def test_regions_are_clipped_to_frozen_bounds_and_capacity_is_enforced():
    model = MultiRegionSelection(QRect(0, 0, 400, 300), max_regions=2, max_pixels=800)
    model.add(QRect(-10, -10, 30, 30))
    assert model.regions == [QRect(0, 0, 20, 20)]
    model.add(QRect(20, 20, 20, 20))
    with pytest.raises(ValueError):
        model.add(QRect(40, 40, 20, 20))
    assert model.pixels == 800
    model.remove(0)
    with pytest.raises(ValueError):
        model.add(QRect(40, 40, 21, 20))
    assert model.pixels == 400


@pytest.fixture
def multi(qtbot):
    image = solid()
    image.setPixelColor(25, 25, QColor("red"))
    dialog = MultiRegionDialog(image, QRect(-200, -100, 400, 300), max_regions=10, max_pixels=50000)
    qtbot.addWidget(dialog)
    dialog.panel.hide()
    return dialog


def drag(qtbot, window, start, end):
    qtbot.mousePress(window, Qt.MouseButton.LeftButton, pos=start)
    qtbot.mouseMove(window, end)
    qtbot.mouseRelease(window, Qt.MouseButton.LeftButton, pos=end)


def test_drag_coordinates_remain_local_but_list_displays_negative_desktop(multi, qtbot):
    drag(qtbot, multi, QPoint(20, 20), QPoint(99, 79))
    assert multi.selection.regions == [QRect(20, 20, 80, 60)]
    assert "(-180, -80)" in multi.list.item(0).text()
    assert multi.source.copy(multi.selection.regions[0]).pixelColor(5, 5).name() == "#ff0000"
    multi.undo()
    assert not multi.collect.isEnabled()
    multi.redo()
    assert multi.collect.isEnabled()


def test_frozen_image_does_not_follow_caller_pixel_edits(qtbot):
    source = solid("red")
    dialog = MultiRegionDialog(source, QRect(0, 0, 400, 300), max_regions=5, max_pixels=50000)
    qtbot.addWidget(dialog)
    source.fill(QColor("blue"))
    assert dialog.source.pixelColor(5, 5).name() == "#ff0000"


def test_empty_enter_cannot_accept_and_tab_moves_control_visibility(multi):
    multi.accept()
    assert multi.result() != QDialog.DialogCode.Accepted
    multi.show()
    multi.panel.show()
    multi.toggle_controls()
    assert multi.panel.isHidden()
    multi.toggle_controls()
    assert not multi.panel.isHidden()
    before = multi.panel.pos()
    multi.move_controls()
    assert multi.panel.pos() != before or multi.width() < multi.panel.width() * 2


@pytest.fixture
def screenshot(qtbot, tmp_settings):
    from ui.screenshot_window import ScreenshotWindow
    config = ToolSettingsManager(tmp_settings)
    config.set_smart_selection(False)
    config.set_screenshot_save_enabled(False)
    source = solid("blue", 800, 600)
    source.setPixelColor(25, 25, QColor("yellow"))
    window = ScreenshotWindow(config, prefetched_image=source, prefetched_rect=QRectF(-200, -100, 800, 600))
    yield window
    window.full_destroy()
    from ui.image_layout_dialog import get_image_layout_window
    get_image_layout_window().close()


def test_real_screenshot_multi_export_uses_same_frame_not_annotations(screenshot, monkeypatch):
    from ui.image_layout_dialog import get_image_layout_window
    from core.last_capture_region import get_last_region
    monkeypatch.setattr("core.last_capture_region._last_region", None)
    screenshot.scene.selection_model.initialize_confirmed_rect(QRectF(-180, -80, 80, 60))
    screenshot.scene.addRect(QRectF(-180, -80, 80, 60), QPen(Qt.PenStyle.NoPen), QBrush(QColor("red")))
    def select(dialog):
        dialog.selection.add(QRect(20, 20, 80, 60))
        dialog.selection.add(QRect(30, 30, 80, 60))
        dialog.selection.move(1, -1)
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(MultiRegionDialog, "exec", select)
    screenshot.toolbar.multi_region_btn.click()
    collection = get_image_layout_window()
    assert len(collection.entries) == 2 and not screenshot._session_active
    assert collection.images()[0].pixelColor(1, 1).name() == "#0000ff"
    assert collection.images()[1].pixelColor(5, 5).name() == "#ffff00"
    assert collection.images()[1].pixelColor(6, 6).name() == "#0000ff"
    assert get_last_region() == QRect(-180, -80, 80, 60)


def test_cancel_multi_region_preserves_existing_screenshot_and_basket(screenshot, monkeypatch):
    from ui.image_layout_dialog import get_image_layout_window
    basket = get_image_layout_window()
    basket.add_image("existing", solid("green", 20, 20))
    original = screenshot.scene
    def cancel(dialog):
        dialog.selection.add(QRect(0, 0, 80, 60))
        return QDialog.DialogCode.Rejected
    monkeypatch.setattr(MultiRegionDialog, "exec", cancel)
    screenshot.toolbar.multi_region_btn.click()
    assert screenshot._session_active and screenshot.scene is original
    assert len(basket.entries) == 1


def test_multi_region_rejected_when_screenshot_tears_down(screenshot):
    QTimer.singleShot(0, screenshot.cleanup_and_close)
    screenshot._handle_multi_region()
    assert screenshot._multi_region_dialog is None and not screenshot._session_active


def test_atomic_import_rolls_back_all_new_crops_if_insertion_fails(qtbot, monkeypatch):
    from ui.image_layout_dialog import ImageLayoutDialog
    collection = ImageLayoutDialog()
    qtbot.addWidget(collection)
    collection.add_image("old", solid("green", 20, 20))
    old = collection.add_image
    count = [0]
    def fail(title, image, identity=None):
        count[0] += 1
        if count[0] == 2:
            raise MemoryError("synthetic allocation failure")
        return old(title, image, identity)
    monkeypatch.setattr(collection, "add_image", fail)
    with pytest.raises(MemoryError):
        collection.add_images_atomic([("one", solid()), ("two", solid())])
    assert [entry[0] for entry in collection.ordered_entries()] == ["old"]


@pytest.fixture
def cursor(monkeypatch):
    handle = win32gui.LoadCursor(0, win32con.IDC_ARROW)
    monkeypatch.setattr(win32gui, "GetCursorInfo", lambda: (win32con.CURSOR_SHOWING, handle, (-90, -40)))
    with cursor_snapshot(True) as snapshot:
        yield snapshot


def test_pointer_switch_off_and_hidden_pointer_do_not_query_or_allocate(monkeypatch):
    get = Mock(side_effect=AssertionError("Unexpected native cursor query"))
    monkeypatch.setattr(win32gui, "GetCursorInfo", get)
    with cursor_snapshot(False) as value:
        assert value is None
    get.assert_not_called()
    monkeypatch.setattr(win32gui, "GetCursorInfo", lambda: (0, 0, (0, 0)))
    with cursor_snapshot(True) as value:
        assert value is None


def test_real_arrow_only_changes_hotspot_relative_bounds_and_keeps_source(cursor):
    image = solid("#88aadd", 200, 150)
    bounds = QRectF(-100, -50, 200, 150)
    result = composite_cursor(image, bounds, cursor)
    changed = [(x, y) for y in range(150) for x in range(200) if result.pixel(x, y) != image.pixel(x, y)]
    expected = cursor.desktop_rect().translated(100, 50)
    assert changed
    assert all(expected.contains(QPoint(x, y)) for x, y in changed)
    assert image.pixelColor(10, 10).name() == "#88aadd"
    assert composite_cursor(image, bounds, None) is image
    assert composite_cursor(image, QRectF(1000, 1000, 200, 150), cursor) is image


@pytest.mark.parametrize("origin", [(-10, -10), (0, 0), (190, 0), (0, 140), (190, 140)])
def test_native_cursor_clipping_matches_full_render_then_crop(cursor, origin):
    source = solid("#88aadd", 200, 150)
    snapshot = replace(cursor, position=(origin[0] + cursor.hotspot[0], origin[1] + cursor.hotspot[1]))
    direct = composite_cursor(source, QRectF(0, 0, 200, 150), snapshot)
    expanded = solid("#88aadd", 400, 350)
    padded = composite_cursor(expanded, QRectF(-100, -100, 400, 350), snapshot)
    assert direct == padded.copy(100, 100, 200, 150)


@pytest.mark.parametrize("cursor_id", [win32con.IDC_ARROW, win32con.IDC_IBEAM, win32con.IDC_CROSS, win32con.IDC_HAND])
def test_different_real_cursor_shapes_are_rendered(monkeypatch, cursor_id):
    handle = win32gui.LoadCursor(0, cursor_id)
    monkeypatch.setattr(win32gui, "GetCursorInfo", lambda: (1, handle, (50, 50)))
    original = solid("#739ac5", 100, 100)
    with cursor_snapshot(True) as snapshot:
        result = composite_cursor(original, QRectF(0, 0, 100, 100), snapshot)
        assert result != original
        assert snapshot.size[0] > 0 and snapshot.size[1] > 0


def test_capture_service_freezes_cursor_before_screen_grab(monkeypatch):
    from capture.capture_service import CaptureService
    import mss
    events = []
    @contextmanager
    def snapshot(enabled):
        events.append("cursor")
        yield "snapshot"
        events.append("released")
    class Screen:
        monitors = [{"left": -100, "top": -50, "width": 20, "height": 10}]
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def grab(self, monitor):
            events.append("grab")
            return type("Shot", (), {"width": 20, "height": 10, "bgra": bytes([1, 2, 3, 255]) * 200})()
    monkeypatch.setattr(mss, "mss", Screen)
    monkeypatch.setattr("capture.cursor_capture.cursor_snapshot", snapshot)
    def combine(image, bounds, cursor):
        events.append("combine")
        assert cursor == "snapshot" and bounds == QRectF(-100, -50, 20, 10)
        return image
    monkeypatch.setattr("capture.cursor_capture.composite_cursor", combine)
    CaptureService(include_cursor=True).capture_all_screens()
    assert events == ["cursor", "grab", "combine", "released"]


def test_real_cursor_objects_are_released_on_repeated_capture(monkeypatch):
    import ctypes
    from ctypes import wintypes
    user = ctypes.windll.user32
    kernel = ctypes.windll.kernel32
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    user.GetGuiResources.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    user.GetGuiResources.restype = wintypes.DWORD
    handle = win32gui.LoadCursor(0, win32con.IDC_ARROW)
    monkeypatch.setattr(win32gui, "GetCursorInfo", lambda: (1, handle, (30, 30)))
    source = solid("white", 100, 100)
    with cursor_snapshot(True) as frozen:
        composite_cursor(source, QRectF(0, 0, 100, 100), frozen)
    process = kernel.GetCurrentProcess()
    before = (user.GetGuiResources(process, 0), user.GetGuiResources(process, 1))
    for _ in range(50):
        with cursor_snapshot(True) as frozen:
            composite_cursor(source, QRectF(0, 0, 100, 100), frozen)
    after = (user.GetGuiResources(process, 0), user.GetGuiResources(process, 1))
    assert after == before


def test_pointer_setting_saves_resets_and_refreshes(qtbot, tmp_settings, monkeypatch):
    from ui.settings_ui.dialog import SettingsDialog
    config = ToolSettingsManager(tmp_settings)
    window = SettingsDialog(config)
    qtbot.addWidget(window)
    window.show()
    assert not window.include_cursor_toggle.isChecked()
    window.include_cursor_toggle.setChecked(True)
    assert window._has_unsaved_changes()
    monkeypatch.setattr("ui.settings_ui.dialog.validate_global_hotkey_edits", lambda *a, **k: True)
    window.apply_settings()
    assert config.get_app_setting("screenshot_include_cursor", False)
    window._reset_screenshot_settings_page()
    assert not window.include_cursor_toggle.isChecked()
    window.refresh_settings()
    assert window.include_cursor_toggle.isChecked()
    window._skip_unsaved_close_prompt = True


MULTI_CURSOR_MESSAGES = {
  "MultiRegionDialog": [
    "Multiple Regions",
    "Drag to add regions from this frozen frame. Overlaps are exported separately. Existing annotations are not included.",
    "Region order",
    "Move up",
    "Move down",
    "Remove",
    "Undo",
    "Redo",
    "Clear",
    "Move controls",
    "Cancel",
    "Collect regions",
    "Region is too small or exceeds the remaining collection capacity.",
    "%1 regions · Tab hides controls · Enter collects · Esc cancels"
  ],
  "Toolbar": [
    "Multiple regions from frozen frame"
  ],
  "ToolbarLayoutDialog": [
    "Multiple regions from frozen frame"
  ],
  "ScreenshotWindow": [
    "Collection unavailable",
    "Finish exporting or remove images before selecting more regions.",
    "Region %1",
    "Regions could not be collected. Existing images were kept."
  ],
  "SettingsDialog": [
    "Include Mouse Pointer",
    "Capture the real pointer at its current position. Applies to static captures, not GIF or scrolling capture."
  ]
}

@pytest.mark.parametrize("lang", ["en", "zh", "ja", "ko"])
def test_compiled_multi_cursor_messages(qapp, lang):
    from pathlib import Path
    from PySide6.QtCore import QTranslator
    translator = QTranslator()
    assert translator.load(str(Path(__file__).resolve().parents[1] / "translations" / f"app_{lang}.qm"))
    for context, messages in MULTI_CURSOR_MESSAGES.items():
        for source in messages:
            assert translator.translate(context, source), (lang, context, source)


def test_monochrome_xor_cursor_inverts_captured_background(monkeypatch):
    import ctypes
    from ctypes import wintypes
    user = ctypes.windll.user32
    user.CreateCursor.argtypes = [wintypes.HINSTANCE, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                  ctypes.c_void_p, ctypes.c_void_p]
    user.CreateCursor.restype = wintypes.HANDLE
    user.DestroyCursor.argtypes = [wintypes.HANDLE]
    user.DestroyCursor.restype = wintypes.BOOL
    and_mask = ctypes.create_string_buffer(b"\xff" * 128)
    xor_bytes = bytearray(128)
    xor_bytes[10*4+1] = 0x80  # Invert exactly x=8, y=10.
    xor_mask = ctypes.create_string_buffer(bytes(xor_bytes))
    handle = user.CreateCursor(None, 3, 4, 32, 32, and_mask, xor_mask)
    assert handle
    monkeypatch.setattr(win32gui, "GetCursorInfo", lambda: (1, handle, (30, 40)))
    try:
        source = solid("#123456", 100, 100)
        with cursor_snapshot(True) as snapshot:
            assert snapshot.hotspot == (3, 4) and snapshot.size == (32, 32)
            result = composite_cursor(source, QRectF(0, 0, 100, 100), snapshot)
        assert result.pixelColor(35, 46).name() == "#edcba9"
        assert result.pixelColor(34, 46).name() == "#123456"
        assert source.pixelColor(35, 46).name() == "#123456"
    finally:
        user.DestroyCursor(handle)


@pytest.mark.parametrize("size", [24, 32, 48, 64])
def test_native_cursor_bitmap_sizes_are_not_rescaled_twice(monkeypatch, size):
    import ctypes
    from ctypes import wintypes
    copy_image = ctypes.windll.user32.CopyImage
    copy_image.argtypes = [wintypes.HANDLE, wintypes.UINT, ctypes.c_int, ctypes.c_int, wintypes.UINT]
    copy_image.restype = wintypes.HANDLE
    handle = copy_image(win32gui.LoadCursor(0, win32con.IDC_ARROW), win32con.IMAGE_CURSOR, size, size, 0)
    assert handle
    monkeypatch.setattr(win32gui, "GetCursorInfo", lambda: (1, handle, (50, 50)))
    destroy = ctypes.windll.user32.DestroyCursor
    destroy.argtypes = [wintypes.HANDLE]
    destroy.restype = wintypes.BOOL
    try:
        with cursor_snapshot(True) as snapshot:
            assert snapshot.size == (size, size)
            result = composite_cursor(solid("white", 180, 180), QRectF(0, 0, 180, 180), snapshot)
            assert result != solid("white", 180, 180)
    finally:
        destroy(int(handle))


def test_snapshot_native_resources_are_released_after_capture_exception(monkeypatch):
    handle = win32gui.LoadCursor(0, win32con.IDC_ARROW)
    monkeypatch.setattr(win32gui, "GetCursorInfo", lambda: (1, handle, (50,50)))
    destroy = win32gui.DestroyIcon
    deleted = Mock(wraps=destroy)
    monkeypatch.setattr(win32gui, "DestroyIcon", deleted)
    with pytest.raises(RuntimeError):
        with cursor_snapshot(True):
            raise RuntimeError("capture failed")
    deleted.assert_called_once()


def test_main_app_freezes_pointer_setting_before_worker_capture(qapp, qtbot, tmp_settings, monkeypatch):
    from PySide6.QtCore import QObject
    from main_app import MainApp
    from capture.capture_service import CaptureService
    config = ToolSettingsManager(tmp_settings)
    config.set_app_setting("screenshot_include_cursor", True)
    main = MainApp.__new__(MainApp)
    QObject.__init__(main)
    main.app, main.config_manager = qapp, config
    main.screenshot_window = main.clipboard_window = main._capture_countdown = main._capture_thread = None
    main._quitting = main._capture_busy = False
    main.tray_icon = Mock()
    main._on_capture_ready = Mock()
    observed = []
    def capture(service):
        observed.append(service.include_cursor)
        return solid(), QRectF(0, 0, 400, 300)
    monkeypatch.setattr(CaptureService, "capture_all_screens", capture)
    try:
        main.start_screenshot()
        config.set_app_setting("screenshot_include_cursor", False)
        qtbot.waitUntil(lambda: main._on_capture_ready.called)
        assert observed == [True]
    finally:
        main._cancel_pending_capture()
        assert main._capture_thread.wait(5000)
        main.deleteLater()


def test_pointer_native_draw_failure_propagates_instead_of_silently_omitting(cursor, monkeypatch):
    monkeypatch.setattr(win32gui, "DrawIconEx", Mock(side_effect=OSError("GDI failure")))
    with pytest.raises(OSError):
        composite_cursor(solid(), QRectF(-100, -50, 400, 300), cursor)


def test_collection_capacity_is_applied_to_multi_region_dialog(screenshot, monkeypatch):
    from ui.image_layout_dialog import get_image_layout_window
    collection = get_image_layout_window()
    collection.add_image("already there", solid("green", 20, 20))
    def inspect(dialog):
        assert dialog.selection.max_regions == 49
        assert dialog.selection.max_pixels == 64_000_000 - 400
        return QDialog.DialogCode.Rejected
    monkeypatch.setattr(MultiRegionDialog, "exec", inspect)
    screenshot._handle_multi_region()
    assert screenshot._session_active and len(collection.entries) == 1
