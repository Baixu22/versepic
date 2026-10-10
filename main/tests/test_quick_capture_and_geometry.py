"""Quick capture targets, dispatch, shortcut settings and precise region editing."""
from dataclasses import FrozenInstanceError
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QObject, QPoint, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QDialog

from capture.quick_capture import CaptureTargetUnavailable, QuickCaptureRequest, make_quick_capture_request
from main_app import MainApp
from settings.tool_settings import ToolSettingsManager
from ui.selection_info.geometry_dialog import RegionGeometryDialog


@pytest.fixture(autouse=True)
def isolated_last_region(monkeypatch):
    monkeypatch.setattr("core.last_capture_region._last_region", None)


def image_and_desktop():
    image = QImage(800, 600, QImage.Format.Format_RGB32)
    image.fill(QColor("#2468ac"))
    image.setPixelColor(30, 40, QColor("#ff0000"))
    return image, QRectF(-200, -100, 800, 600)


@pytest.mark.parametrize("kind", ["screen", "last"])
def test_quick_region_preserves_negative_desktop_coordinates(kind):
    request = QuickCaptureRequest(kind, (-170, -60, 30, 90))
    image, desktop = image_and_desktop()
    captured, bounds, rect = request.capture(Mock(capture_all_screens=Mock(return_value=(image, desktop))))
    assert rect == QRect(-170, -60, 200, 150)
    crop = captured.copy(rect.translated(-int(bounds.x()), -int(bounds.y())))
    assert crop.size().width() == 200 and crop.size().height() == 150
    assert crop.pixelColor(0, 0).name() == "#ff0000"
    with pytest.raises(FrozenInstanceError):
        request.action = "copy"


@pytest.mark.parametrize("area", [(-300, 0, -100, 100), (0, 0, 0, 100), (0, 0, 7, 20), (500, 450, 700, 650)])
def test_invalid_or_out_of_bounds_regions_fail_closed(area):
    request = QuickCaptureRequest("last", area)
    with pytest.raises(CaptureTargetUnavailable):
        request.capture(Mock(capture_all_screens=Mock(return_value=image_and_desktop())))


def test_screen_request_uses_monitor_at_cursor_not_entire_desktop(monkeypatch):
    monitor = Mock(return_value=123)
    monkeypatch.setattr("capture.quick_capture.win32api.MonitorFromPoint", monitor)
    monkeypatch.setattr("capture.quick_capture.win32api.GetMonitorInfo", lambda _: {"Monitor": (-1920, 0, 0, 1080)})
    request = make_quick_capture_request("screen", point=QPoint(-50, 90))
    assert request.resolve() == QRect(-1920, 0, 1920, 1080)
    assert monitor.call_args.args[0] == (-50, 90)


@pytest.mark.parametrize("rect", [None, QRect()])
def test_last_region_requires_a_real_previous_capture(rect):
    with pytest.raises(CaptureTargetUnavailable):
        make_quick_capture_request("last", last_region=rect)


@pytest.fixture
def window_api(monkeypatch):
    import capture.quick_capture as quick
    monkeypatch.setattr(quick.win32gui, "IsWindow", lambda _: True)
    monkeypatch.setattr(quick.win32gui, "IsWindowVisible", lambda _: True)
    monkeypatch.setattr(quick.win32gui, "IsIconic", lambda _: False)
    monkeypatch.setattr(quick.win32process, "GetWindowThreadProcessId", lambda _: (1, 999999))
    monkeypatch.setattr(quick, "get_window_rect_no_shadow", lambda _: [-170, -60, 30, 90])
    return quick


def test_window_request_resolves_native_frame(window_api):
    request = make_quick_capture_request("window", hwnd=123)
    assert request.resolve() == QRect(-170, -60, 200, 150)


@pytest.mark.parametrize("condition", ["closed", "hidden", "minimized", "reused", "own"])
def test_window_identity_visibility_and_ownership_are_checked(window_api, monkeypatch, condition):
    request = make_quick_capture_request("window", hwnd=123)
    if condition == "closed":
        monkeypatch.setattr(window_api.win32gui, "IsWindow", lambda _: False)
    elif condition == "hidden":
        monkeypatch.setattr(window_api.win32gui, "IsWindowVisible", lambda _: False)
    elif condition == "minimized":
        monkeypatch.setattr(window_api.win32gui, "IsIconic", lambda _: True)
    else:
        pid = window_api.os.getpid() if condition == "own" else 999998
        monkeypatch.setattr(window_api.win32process, "GetWindowThreadProcessId", lambda _: (1, pid))
    with pytest.raises(CaptureTargetUnavailable):
        request.resolve()


def test_window_moving_during_grab_is_not_silently_cropped(window_api, monkeypatch):
    frames = iter([[-170, -60, 30, 90], [-169, -60, 31, 90]])
    monkeypatch.setattr(window_api, "get_window_rect_no_shadow", lambda _: next(frames))
    request = QuickCaptureRequest("window", hwnd=123, pid=999999)
    with pytest.raises(CaptureTargetUnavailable):
        request.capture(Mock(capture_all_screens=Mock(return_value=image_and_desktop())))


@pytest.fixture
def main(qapp, tmp_settings):
    app = MainApp.__new__(MainApp)
    QObject.__init__(app)
    app.app = qapp
    app.screenshot_window = None
    app.clipboard_window = None
    app._capture_thread = None
    app._capture_countdown = None
    app._capture_busy = False
    app._quitting = False
    app._capture_foreground_tracker = None
    app.config_manager = ToolSettingsManager(tmp_settings)
    app.config_manager.set_screenshot_save_enabled(False)
    app.tray_icon = Mock()
    app._on_capture_ready = Mock()
    yield app
    app._cancel_pending_capture()
    if app._capture_thread:
        assert app._capture_thread.wait(5000)
    app.deleteLater()


def test_quick_copy_goes_through_real_capture_dispatch(main, monkeypatch, qtbot):
    from core.last_capture_region import get_last_region, set_last_region
    set_last_region(QRect(-170, -60, 200, 150))
    main.config_manager.set_app_setting("quick_capture_result", "copy")
    delivery = Mock()
    monkeypatch.setattr("core.clipboard_utils.deliver_image_async", delivery)
    monkeypatch.setattr("capture.capture_service.CaptureService.capture_all_screens", lambda _: image_and_desktop())
    main.start_quick_capture("last")
    qtbot.waitUntil(lambda: delivery.called)
    output = delivery.call_args.args[0]
    assert output.width() == 200 and output.height() == 150
    assert output.pixelColor(0, 0).name() == "#ff0000"
    assert delivery.call_args.kwargs["save_service"] is None
    assert not main._on_capture_ready.called
    assert get_last_region() == QRect(-170, -60, 200, 150)


def test_quick_edit_preselects_region_on_shared_editor(main):
    model = Mock()
    editor = SimpleNamespace(scene=SimpleNamespace(selection_model=model))
    main._on_capture_ready.return_value = editor
    image, desktop = image_and_desktop()
    rect = QRect(-170, -60, 200, 150)
    main._on_capture_result(image, desktop, rect, "edit")
    main._on_capture_ready.assert_called_once_with(image, desktop)
    model.initialize_confirmed_rect.assert_called_once_with(QRectF(rect))


def test_bad_target_notifies_without_starting_capture(main):
    main.start_quick_capture("window")
    assert main._capture_thread is None
    assert main.tray_icon.showMessage.called


def test_completed_thread_with_pending_result_still_blocks_duplicate_capture(main):
    main._capture_busy = True
    main.start_screenshot()
    main.start_quick_capture("screen")
    assert main._capture_thread is None


def test_quick_copy_respects_existing_auto_save_and_file_reference(main, monkeypatch):
    main.config_manager.set_screenshot_save_enabled(True)
    main.config_manager.set_clipboard_file_reference_enabled(False)
    delivery = Mock()
    monkeypatch.setattr("core.clipboard_utils.deliver_image_async", delivery)
    image, desktop = image_and_desktop()
    main._on_capture_result(image, desktop, QRect(-170, -60, 200, 150), "copy")
    options = delivery.call_args.kwargs
    assert options["save_service"] is not None
    assert options["write_file_reference"] is False
    assert options["save_kwargs"]["image_format"] == "PNG"


@pytest.fixture
def geometry(qtbot):
    dialog = RegionGeometryDialog(QRect(-150, -50, 320, 180), QRect(-200, -100, 800, 600))
    qtbot.addWidget(dialog)
    return dialog


def test_geometry_round_trips_physical_negative_coordinates(geometry):
    assert geometry.selected_rect() == QRect(-150, -50, 320, 180)
    assert geometry.apply_button.isEnabled()
    geometry.fields["width"].setValue(237)
    geometry.fields["height"].setValue(119)
    assert geometry.selected_rect() == QRect(-150, -50, 237, 119)


@pytest.mark.parametrize("index,ratio", [(1, (1, 1)), (2, (4, 3)), (3, (16, 9))])
@pytest.mark.parametrize("axis,value", [("width", 355), ("height", 207)])
def test_ratio_presets_keep_exact_integer_pixel_multiples(geometry, index, ratio, axis, value):
    geometry.ratio_combo.setCurrentIndex(index)
    geometry.fields[axis].setValue(value)
    rect = geometry.selected_rect()
    assert rect.width() * ratio[1] == rect.height() * ratio[0]
    assert geometry.apply_button.isEnabled()


def test_geometry_disables_out_of_bounds_apply_without_moving_origin(geometry):
    geometry.fields["x"].setValue(590)
    assert geometry.fields["x"].value() == 590
    assert not geometry.apply_button.isEnabled()
    geometry._accept_valid()
    assert geometry.result() != QDialog.DialogCode.Accepted
    geometry.fields["width"].setValue(8)
    assert geometry.apply_button.isEnabled()


def test_geometry_preserves_custom_lock_ratio(qtbot):
    dialog = RegionGeometryDialog(QRect(0, 0, 137, 89), QRect(0, 0, 800, 600), locked=True)
    qtbot.addWidget(dialog)
    assert dialog.ratio() == (137, 89)
    dialog.fields["width"].setValue(274)
    assert dialog.selected_rect().size().width() == 274
    assert dialog.selected_rect().height() == 178


def test_impossible_ratio_cannot_be_applied(qtbot):
    dialog = RegionGeometryDialog(QRect(0, 0, 8, 8), QRect(0, 0, 8, 8))
    qtbot.addWidget(dialog)
    dialog.ratio_combo.setCurrentIndex(3)
    assert not dialog.apply_button.isEnabled()


def test_geometry_keyboard_input_commits_before_apply(geometry, qtbot):
    geometry.show()
    field = geometry.fields["width"]
    field.setFocus()
    field.selectAll()
    qtbot.keyClicks(field, "237")
    qtbot.mouseClick(geometry.apply_button, Qt.MouseButton.LeftButton)
    assert geometry.result() == QDialog.DialogCode.Accepted
    assert geometry.selected_rect().width() == 237


def test_settings_quick_hotkeys_and_result_are_saved_reset_and_detected(qtbot, tmp_settings, monkeypatch):
    from ui.settings_ui.dialog import SettingsDialog
    from ui.settings_ui.page_hotkey import validate_global_hotkey_edits
    config = ToolSettingsManager(tmp_settings)
    dialog = SettingsDialog(config_manager=config)
    qtbot.addWidget(dialog)
    dialog._skip_unsaved_close_prompt = True
    dialog.show()
    dialog.quick_screen_hotkey_edit.setText("ctrl+alt+8")
    dialog.quick_window_hotkey_edit.setText("ctrl+alt+9")
    dialog.quick_last_hotkey_edit.setText("ctrl+alt+0")
    dialog.quick_capture_result_combo.setCurrentIndex(1)
    assert dialog._has_unsaved_changes()
    dialog.quick_window_hotkey_edit.setText("ctrl+alt+8")
    assert not validate_global_hotkey_edits(dialog, check_system=False)
    dialog.quick_window_hotkey_edit.setText("ctrl+alt+9")
    monkeypatch.setattr("ui.settings_ui.dialog.validate_global_hotkey_edits", lambda *a, **k: True)
    dialog.apply_settings()
    assert config.get_app_setting("quick_screen_hotkey", "") == "ctrl+alt+8"
    assert config.get_app_setting("quick_window_hotkey", "") == "ctrl+alt+9"
    assert config.get_app_setting("quick_capture_result", "") == "copy"
    dialog._reset_hotkey_page()
    dialog._reset_screenshot_settings_page()
    assert dialog.quick_screen_hotkey_edit.text() == ""
    assert dialog.quick_capture_result_combo.currentData() == "edit"
    dialog.refresh_settings()
    assert dialog.quick_screen_hotkey_edit.text() == "ctrl+alt+8"
    assert dialog.quick_capture_result_combo.currentData() == "copy"


def test_quick_hotkeys_register_distinct_actions_and_keep_existing_binding(main):
    registered = {}
    main.hotkey_system = Mock()
    main.hotkey_system.register_hotkey.side_effect = lambda key, callback: registered.setdefault(key, callback) is not None
    main.config_manager.set_clipboard_enabled(False)
    for kind, key in (("screen", "ctrl+alt+8"), ("window", "ctrl+alt+9"), ("last", "ctrl+alt+0")):
        main.config_manager.set_app_setting(f"quick_{kind}_hotkey", key)
    main.start_quick_capture = Mock()
    main.update_hotkey()
    assert main.config_manager.get_hotkey() in registered
    for key in ("ctrl+alt+8", "ctrl+alt+9", "ctrl+alt+0"):
        registered[key]()
    assert [call.args[0] for call in main.start_quick_capture.call_args_list] == ["screen", "window", "last"]


def test_quick_result_after_quit_has_no_delivery(main, monkeypatch):
    delivery = Mock()
    monkeypatch.setattr("core.clipboard_utils.deliver_image_async", delivery)
    main._quitting = True
    image, desktop = image_and_desktop()
    main._on_capture_result(image, desktop, QRect(-170, -60, 200, 150), "copy")
    assert not delivery.called and not main._on_capture_ready.called


def test_target_error_clears_busy_and_allows_retry(main, monkeypatch, qtbot):
    from core.last_capture_region import set_last_region
    set_last_region(QRect(-1000, 0, 200, 150))
    monkeypatch.setattr("capture.capture_service.CaptureService.capture_all_screens", lambda _: image_and_desktop())
    main.start_quick_capture("last")
    qtbot.waitUntil(lambda: main.tray_icon.showMessage.called)
    assert not main._capture_busy
    assert main._capture_thread.wait(5000)
    set_last_region(QRect(-170, -60, 200, 150))
    main.start_quick_capture("last")
    qtbot.waitUntil(lambda: main._on_capture_ready.called)


def test_native_frame_query_failure_uses_win32_fallback(monkeypatch):
    import capture.window_finder as finder
    monkeypatch.setattr(finder.ctypes.windll.dwmapi, "DwmGetWindowAttribute", lambda *a: -1)
    monkeypatch.setattr(finder.win32gui, "GetWindowRect", lambda _: [-100, -50, 200, 150])
    assert finder.get_window_rect_no_shadow(123) == [-100, -50, 200, 150]


@pytest.fixture
def geometry_controller(qtbot):
    from PySide6.QtWidgets import QWidget
    from canvas.scene import CanvasScene
    from canvas.view import CanvasView
    from core.export import ExportService
    from settings import get_tool_settings_manager
    from ui.mask_overlay import MaskOverlayWidget
    from ui.selection_info.panel import SelectionInfoPanel
    from ui.selection_info.controller import SelectionInfoController
    image, bounds = image_and_desktop()
    scene = CanvasScene(image, bounds)
    parent = QWidget()
    parent.resize(800, 600)
    qtbot.addWidget(parent)
    view = CanvasView(scene, parent)
    panel = SelectionInfoPanel(parent, view)
    exporter = ExportService(scene)
    mask = MaskOverlayWidget(parent, scene.selection_model)
    controller = SelectionInfoController(panel, scene.selection_model, scene.selection_item,
                                        exporter, mask, parent, get_tool_settings_manager())
    scene.selection_model.initialize_confirmed_rect(QRectF(-150, -50, 320, 180))
    yield controller, scene, exporter, panel
    if controller._parent_window is not None:
        controller.cleanup()
    scene.deleteLater()


def test_geometry_controller_keeps_annotations_and_exports_exact_pixels(geometry_controller, monkeypatch):
    from PySide6.QtGui import QBrush, QPen
    controller, scene, exporter, panel = geometry_controller
    item = scene.addRect(QRectF(-150, -40, 30, 30), QPen(Qt.PenStyle.NoPen), QBrush(QColor("red")))
    original_rect = item.rect()

    def edit(dialog):
        for key, value in {"x": -170, "y": -60, "width": 237, "height": 119}.items():
            dialog.fields[key].setValue(value)
        assert dialog._validate()
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(RegionGeometryDialog, "exec", edit)
    controller._edit_geometry()
    assert scene.selection_model.rect() == QRectF(-170, -60, 237, 119)
    assert item.scene() is scene and item.rect() == original_rect
    output = exporter.export(scene.selection_model.rect())
    assert (output.width(), output.height()) == (237, 119)
    assert output.pixelColor(25, 25).name() == "#ff0000"
    assert not panel.btn_lock.isChecked()


def test_geometry_ratio_is_carried_back_to_drag_lock(geometry_controller, monkeypatch):
    controller, scene, exporter, panel = geometry_controller

    def edit(dialog):
        dialog.ratio_combo.setCurrentIndex(1)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(RegionGeometryDialog, "exec", edit)
    controller._edit_geometry()
    assert panel.btn_lock.isChecked()
    assert controller._lock_ratio.ratio == 1
    assert scene.selection_model.rect().width() == scene.selection_model.rect().height()


def test_cancel_geometry_does_not_change_model(geometry_controller, monkeypatch):
    controller, scene, exporter, panel = geometry_controller
    original = scene.selection_model.rect()
    monkeypatch.setattr(RegionGeometryDialog, "exec", lambda _: QDialog.DialogCode.Rejected)
    controller._edit_geometry()
    assert scene.selection_model.rect() == original


def test_session_cleanup_rejects_open_geometry_dialog(geometry_controller):
    from PySide6.QtCore import QTimer
    controller, scene, exporter, panel = geometry_controller
    original = scene.selection_model.rect()
    QTimer.singleShot(0, controller.cleanup)
    controller._edit_geometry()
    assert controller._geometry_dialog is None
    assert scene.selection_model.rect() == original


@pytest.mark.parametrize("mode", ["border", "shadow"])
def test_geometry_displays_actual_decorated_output_size(geometry_controller, monkeypatch, mode):
    controller, scene, exporter, panel = geometry_controller
    controller._border_shadow._enabled = True
    controller._border_shadow._mode = mode
    controller._border_shadow._size = 9
    def edit(dialog):
        dialog.fields["width"].setValue(237)
        dialog.fields["height"].setValue(119)
        assert "255" in dialog.output_size.text() and "137" in dialog.output_size.text()
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(RegionGeometryDialog, "exec", edit)
    panel.btn_geometry.click()
    image = exporter.export(scene.selection_model.rect())
    assert (image.width(), image.height()) == (255, 137)


def test_numeric_region_keeps_rounded_corner_export(geometry_controller, monkeypatch):
    controller, scene, exporter, panel = geometry_controller
    controller._rounded_corners._enabled = True
    controller._rounded_corners._radius = 16
    def edit(dialog):
        dialog.fields["width"].setValue(237)
        dialog.fields["height"].setValue(119)
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(RegionGeometryDialog, "exec", edit)
    panel.btn_geometry.click()
    image = exporter.export(scene.selection_model.rect())
    assert (image.width(), image.height()) == (237, 119)
    assert image.pixelColor(0, 0).alpha() == 0


QUICK_MESSAGES = {
  "RegionGeometryDialog": [
    "Exact Region",
    "Physical pixels. Negative coordinates are valid on other screens.",
    "X",
    "Y",
    "Width",
    "Height",
    "Aspect Ratio",
    "Free",
    "Current ratio",
    "Cancel",
    "Apply",
    "Ratio presets use whole-pixel multiples.",
    "The region or ratio does not fit the captured desktop.",
    "Output: %1 × %2 px",
    " (including border/shadow)"
  ],
  "SelectionInfoPanel": [
    "Exact Region"
  ],
  "SystemTray": [
    "Quick capture",
    "Capture Current Screen",
    "Capture Active Window",
    "Capture Last Region"
  ],
  "MainApp": [
    "Capture Current Screen",
    "Capture Active Window",
    "Capture Last Region",
    "Capture target is unavailable or moved. Use region capture or choose another target."
  ],
  "SettingsDialog": [
    "Capture Current Screen",
    "Capture Active Window",
    "Capture Last Region",
    "Quick Capture Result",
    "Copy also follows the auto-save setting. Ordinary screenshots are unchanged.",
    "Open in editor",
    "Copy directly"
  ]
}

@pytest.mark.parametrize("language", ["en", "zh", "ja", "ko"])
def test_compiled_quick_capture_and_geometry_messages(qapp, language):
    from pathlib import Path
    from PySide6.QtCore import QTranslator
    translator = QTranslator()
    resource = Path(__file__).resolve().parents[1] / "translations" / f"app_{language}.qm"
    assert translator.load(str(resource))
    for context, strings in QUICK_MESSAGES.items():
        for source in strings:
            assert translator.translate(context, source), (language, context, source)


def test_ratio_spin_arrows_advance_in_valid_pixel_steps(geometry):
    geometry.ratio_combo.setCurrentIndex(3)
    before = geometry.selected_rect()
    geometry.fields["width"].stepUp()
    after = geometry.selected_rect()
    assert after.width() == before.width() + 16
    assert after.height() == before.height() + 9
    geometry.fields["height"].stepDown()
    assert geometry.selected_rect() == before
    geometry.ratio_combo.setCurrentIndex(0)
    assert geometry.fields["width"].singleStep() == 1


def test_quick_shortcut_during_countdown_does_not_resolve_or_error(main):
    main._capture_countdown = Mock(is_pending=True)
    main.start_quick_capture("window")
    assert not main.tray_icon.showMessage.called
    assert main._capture_thread is None


def test_quick_shortcut_keeps_existing_editor_instead_of_resolving_new_target(main):
    main.screenshot_window = SimpleNamespace(_session_active=True)
    main.start_screenshot = Mock()
    main.start_quick_capture("window")
    main.start_screenshot.assert_called_once()
    assert not main.tray_icon.showMessage.called
