"""Sensitive session policy and derived-window containment (clipboard mocked)."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QCoreApplication,QEvent,QPoint,QRect,QRectF,Qt
from PySide6.QtGui import QColor,QImage

from core.capture_privacy import is_sensitive
from main_app import MainApp
from settings.tool_settings import ToolSettingsManager
from ui.screenshot_window import ScreenshotWindow


def picture():
    image=QImage(640,480,QImage.Format.Format_ARGB32);image.fill(QColor('#b22d50'));return image


@pytest.fixture
def config(tmp_settings,tmp_path):
    c=ToolSettingsManager(tmp_settings);c.set_screenshot_save_path(str(tmp_path));c.set_screenshot_save_enabled(True)
    c.set_ocr_enabled(True)
    return c


@pytest.fixture
def warnings(monkeypatch):
    w=Mock();monkeypatch.setattr('ui.dialogs.show_warning_dialog',w);return w


@pytest.fixture
def capture(qapp,monkeypatch,config):
    from pin.pin_manager import PinManager
    monkeypatch.setattr('core.capture_privacy.ensure_supported',lambda *a:True)
    monkeypatch.setattr(PinManager,'_instance',None)
    window=ScreenshotWindow(config,prefetched_image=picture(),prefetched_rect=QRect(0,0,640,480),sensitive=True)
    window.scene.selection_model.initialize_confirmed_rect(QRectF(0,0,240,180))
    yield window
    window.full_destroy();PinManager.instance().close_all()
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)


def test_session_has_visible_policy_and_resets_before_reuse(capture):
    assert capture.sensitive_capture and capture.scene.sensitive_capture and capture._privacy_label.isVisible()
    capture.cleanup_and_close()
    assert capture.original_image is None and capture.scene is None and not capture.sensitive_capture
    capture.prepare_new_session(picture(),QRect(0,0,640,480))
    assert not capture.sensitive_capture and not capture.scene.sensitive_capture and not capture._privacy_label.isVisible()


def test_cancel_never_copies_or_saves(capture,monkeypatch):
    copy=Mock();monkeypatch.setattr('core.clipboard_utils.copy_image_to_clipboard',copy)
    save=Mock();monkeypatch.setattr('core.save.SaveService.save_qimage_to_path',save)
    capture.cleanup_and_close()
    copy.assert_not_called();save.assert_not_called()


@pytest.mark.parametrize('action',['handle_copy','handle_confirm'])
def test_explicit_copy_uses_sensitive_flag_and_no_save(capture,monkeypatch,action):
    from core.last_capture_region import get_last_region
    before=get_last_region()
    copied=Mock();monkeypatch.setattr('core.clipboard_utils.copy_image_to_clipboard',copied)
    save=Mock();monkeypatch.setattr('core.save.SaveService.save_qimage',save)
    getattr(capture.action_handler,action)()
    assert copied.call_count==1 and copied.call_args.kwargs=={'sensitive':True}
    save.assert_not_called();assert not capture._session_active
    assert get_last_region()==before


def test_copy_failure_keeps_session_open_and_no_ordinary_fallback(capture,monkeypatch,warnings):
    copy=Mock(side_effect=RuntimeError('private secret exception text'))
    monkeypatch.setattr('core.clipboard_utils.copy_image_to_clipboard',copy)
    capture.action_handler.handle_copy()
    assert capture._session_active and is_sensitive(capture)
    assert copy.call_count==1 and 'private secret' not in str(warnings.call_args)


@pytest.mark.parametrize('method',['handle_save','handle_collect','handle_screenshot_translate','handle_text_recognize','handle_scan_code'])
def test_actions_refuse_persistent_or_text_exits(capture,warnings,method):
    getattr(capture.action_handler,method)()
    assert warnings.call_count==1 and capture._session_active


@pytest.mark.parametrize('method',['_open_editable_project','_handle_multi_region','start_gif_record_mode','start_long_screenshot_mode'])
def test_direct_session_exits_refuse_sensitive_content(capture,warnings,method):
    getattr(capture,method)()
    assert warnings.call_count==1 and capture._session_active


def test_pin_inherits_sensitive_flag_and_does_not_implicitly_copy(capture,monkeypatch):
    from pin.pin_manager import PinManager
    copy=Mock();monkeypatch.setattr('core.clipboard_utils.copy_image_to_clipboard',copy)
    capture.action_handler.handle_pin()
    pins=PinManager.instance().get_all_pins();assert len(pins)==1
    pin=pins[0];assert is_sensitive(pin) and is_sensitive(pin.canvas.scene)
    assert not pin._ocr_mgr.init_now(force=True) and pin._ocr_mgr.ocr_thread is None
    copy.assert_not_called()
    assert not capture._session_active
    with pytest.raises(ValueError):pin.get_current_image()
    assert not pin.get_current_image(allow_sensitive=True).isNull()
    pin.copy_to_clipboard()
    assert copy.call_count==1 and copy.call_args.kwargs=={'sensitive':True}


@pytest.fixture
def private_pin(qapp,config,monkeypatch):
    import shiboken6
    from pin.pin_window import PinWindow
    pin=PinWindow(picture(),QPoint(30,40),config,sensitive=True)
    yield pin
    if shiboken6.isValid(pin):pin.close_window()
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)


@pytest.mark.parametrize('method',['save_image','copy_all_text','_on_translate_clicked','compare_image','open_editable_project'])
def test_pin_direct_exits_are_blocked(private_pin,warnings,method):
    getattr(private_pin,method)();assert warnings.call_count==1


def test_private_pin_not_exportable_via_workspace_or_project(private_pin):
    from pin.workspace import snapshot_workspace
    from core.editable_project import snapshot_project,ProjectError
    from core.image_document import ImageGeometry
    with pytest.raises(ProjectError):snapshot_workspace([private_pin],'private')
    with pytest.raises(ProjectError):snapshot_project(private_pin.canvas.scene,ImageGeometry((0,0,640,480)))


def test_batch_pin_save_does_not_even_reserve_private_filename(private_pin,config,tmp_path,monkeypatch):
    from pin.pin_manager import PinManager
    manager=PinManager.instance();monkeypatch.setattr(manager,'get_all_pins',lambda:[private_pin])
    reserve=Mock();monkeypatch.setattr('core.save.SaveService.reserve_save_path',reserve)
    assert manager.save_all_to_directory(str(tmp_path))==(0,1)
    reserve.assert_not_called()


def test_collection_and_compare_cannot_read_private_pin(private_pin,qapp):
    from ui.image_compare import ImageCompareWindow
    # The public image accessor is the shared export guard for both callers.
    from ui.image_layout_dialog import get_image_layout_window
    collection=get_image_layout_window()
    try:
        assert collection.add_pin_images([private_pin])==1 and not collection.entries
    finally:collection.close()
    compare=ImageCompareWindow()
    try:assert not compare.load_pin(private_pin) and compare.images==[None,None]
    finally:compare.close()


def test_main_result_transfers_only_explicit_private_request(qapp):
    owner=SimpleNamespace(_on_capture_ready=Mock(),_quitting=False)
    MainApp._on_capture_result(owner,picture(),QRect(0,0,640,480),None,'private')
    assert owner._on_capture_ready.call_args.kwargs=={'sensitive':True}
    MainApp._on_capture_result(owner,picture(),QRect(0,0,640,480),None,'edit')
    assert owner._on_capture_ready.call_args.kwargs=={}


def test_missing_protocol_does_not_start_private_capture(qapp,monkeypatch):
    owner=SimpleNamespace(start_screenshot=Mock())
    monkeypatch.setattr('core.capture_privacy.ensure_supported',lambda:False)
    MainApp.start_sensitive_screenshot(owner)
    owner.start_screenshot.assert_not_called()


def test_redaction_receives_policy_before_capture_is_destroyed(capture,monkeypatch):
    shown=Mock();monkeypatch.setattr('text_recognition.redaction_window.show_redaction',shown)
    capture.action_handler.handle_smart_redact()
    assert shown.call_count==1 and shown.call_args.kwargs=={'sensitive':True}
    assert not capture._session_active


def test_sensitive_redaction_disallows_files_and_presets_but_can_copy(qapp,config,monkeypatch,warnings):
    import shiboken6
    from text_recognition.redaction_window import RedactionWindow
    monkeypatch.setattr('settings.get_tool_settings_manager',lambda:config)
    start=Mock(return_value=Mock());monkeypatch.setattr('text_recognition.redaction_window.recognize_async',start)
    window=RedactionWindow(picture(),sensitive=True)
    try:
        assert start.call_args.kwargs['sensitive'] is True
        window._add_manual(QRect(10,10,30,30))
        assert not window.save_button.isEnabled() and window.copy_button.isEnabled()
        window._save();window._save_preset();window._delete_preset();assert warnings.call_count==3
        copied=Mock();monkeypatch.setattr('core.clipboard_utils.copy_image_to_clipboard',copied)
        window._copy();assert copied.call_args.kwargs=={'sensitive':True}
        assert copied.call_args.args[0].pixelColor(15,15)==QColor('black')
    finally:
        if shiboken6.isValid(window):window.close()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)


def test_sensitive_ocr_does_not_log_engine_errors_and_context_is_reset(qapp,monkeypatch):
    from core.capture_privacy import sensitive_ocr
    from text_recognition.recognizer import RecognizeThread
    import ocr.ocr_manager as ocr_module
    monkeypatch.setattr('ocr.is_ocr_available',lambda:True)
    leaked=Mock();monkeypatch.setattr('core.logger.log_error',leaked)
    def fail(*args,**kwargs):
        assert sensitive_ocr.get()
        ocr_module._ocr_log('SECRET_SENTINEL','ERROR')
        raise ValueError('SECRET_SENTINEL')
    monkeypatch.setattr('ocr.recognize_text',fail)
    recognized=[];thread=RecognizeThread(picture(),sensitive=True)
    thread.details_ready.connect(lambda data,reason:recognized.append((data,reason)))
    thread.run();assert recognized==[({},'failed')]
    leaked.assert_not_called();assert not sensitive_ocr.get()


def test_private_text_edits_cannot_use_unmarked_copy_cut_or_context_menu(qtbot):
    from PySide6.QtWidgets import QWidget,QLineEdit
    from PySide6.QtGui import QKeyEvent,QContextMenuEvent
    from core.capture_privacy import install_text_guard
    owner=QWidget();qtbot.addWidget(owner);owner.sensitive_capture=True
    edit=QLineEdit('secret',owner);install_text_guard(owner)
    guard=owner._private_text_guard
    for key in (Qt.Key.Key_C,Qt.Key.Key_X):
        event=QKeyEvent(QEvent.Type.KeyPress,key,Qt.KeyboardModifier.ControlModifier)
        assert guard.eventFilter(edit,event)
    event=QContextMenuEvent(QContextMenuEvent.Reason.Mouse,QPoint(1,1),QPoint(1,1))
    assert guard.eventFilter(edit,event)
    owner.sensitive_capture=False
    assert not guard.eventFilter(edit,event)


def test_ordinary_window_and_outside_text_widget_not_intercepted(qtbot):
    from PySide6.QtWidgets import QWidget,QLineEdit
    from PySide6.QtGui import QKeyEvent
    from core.capture_privacy import install_text_guard
    owner=QWidget();qtbot.addWidget(owner);owner.sensitive_capture=True
    outside=QLineEdit();qtbot.addWidget(outside);install_text_guard(owner)
    event=QKeyEvent(QEvent.Type.KeyPress,Qt.Key.Key_C,Qt.KeyboardModifier.ControlModifier)
    assert not owner._private_text_guard.eventFilter(outside,event)


def test_destroyed_owner_cannot_break_application_event_filter(qapp,qtbot):
    from PySide6.QtWidgets import QWidget,QLineEdit
    from PySide6.QtGui import QKeyEvent
    from core.capture_privacy import install_text_guard
    owner=QWidget();owner.sensitive_capture=True;install_text_guard(owner)
    guard=owner._private_text_guard
    owner.deleteLater();QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    outside=QLineEdit();qtbot.addWidget(outside)
    event=QKeyEvent(QEvent.Type.KeyPress,Qt.Key.Key_C,Qt.KeyboardModifier.ControlModifier)
    assert not guard.eventFilter(outside,event)


@pytest.mark.parametrize('language',['en','zh','ja','ko'])
def test_compiled_sensitive_messages_have_exact_context(language):
    import ast
    from pathlib import Path
    from PySide6.QtCore import QTranslator
    main=Path(__file__).resolve().parents[1]
    translator=QTranslator();assert translator.load(str(main/'translations'/f'app_{language}.qm'))
    tree=ast.parse((main/'core'/'capture_privacy.py').read_text(encoding='utf-8'))
    for node in ast.walk(tree):
        if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id=='_tr':
            assert translator.translate('CapturePrivacy',node.args[0].value)
    assert translator.translate('SystemTray','Sensitive screenshot (once)')


def test_busy_normal_session_cannot_be_silently_reclassified_as_private(capture):
    # MainApp must not mutate a session already in use when a different entry is chosen.
    capture.sensitive_capture=False;capture.scene.sensitive_capture=False
    owner=SimpleNamespace(_quitting=False,_capture_countdown=None,screenshot_window=capture)
    MainApp.start_screenshot(owner,sensitive=True)
    assert not capture.sensitive_capture and not capture.scene.sensitive_capture


def test_private_scene_blocks_project_before_accessing_source():
    from core.editable_project import snapshot_project,ProjectError
    source=SimpleNamespace(sensitive_capture=True,background=Mock())
    with pytest.raises(ProjectError):snapshot_project(source,None)
    source.background.image.assert_not_called()


def test_pending_private_ocr_translation_callback_does_not_publish(private_pin,monkeypatch):
    translate=Mock();monkeypatch.setattr(private_pin._translation_helper,'complete_ocr_translation',translate)
    private_pin._on_ocr_translation_finished(True,'PRIVATE_TEXT')
    translate.assert_not_called()


def test_real_capture_thread_request_marker_does_not_persist_to_next_request(qapp,config,qtbot,monkeypatch):
    from PySide6.QtCore import QObject
    owner=MainApp.__new__(MainApp);QObject.__init__(owner)
    owner.app=qapp;owner.config_manager=config;owner.screenshot_window=None;owner.clipboard_window=None
    owner._capture_countdown=None;owner._capture_thread=None;owner._capture_busy=False;owner._quitting=False
    owner._on_capture_ready=Mock()
    monkeypatch.setattr('core.capture_privacy.ensure_supported',lambda *a:True)
    monkeypatch.setattr('capture.capture_service.CaptureService.capture_all_screens',lambda self:(picture(),QRect(0,0,640,480)))
    owner.start_sensitive_screenshot()
    qtbot.waitUntil(lambda:owner._on_capture_ready.call_count==1)
    assert owner._capture_thread.wait(5000)
    assert owner._on_capture_ready.call_args.kwargs=={'sensitive':True}
    owner.start_screenshot()
    qtbot.waitUntil(lambda:owner._on_capture_ready.call_count==2)
    assert owner._capture_thread.wait(5000)
    assert owner._on_capture_ready.call_args.kwargs=={}
    owner.deleteLater()
