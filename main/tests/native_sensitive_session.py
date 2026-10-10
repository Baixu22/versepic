"""Native sensitive-session UI checks with synthetic captures and mocked OS copy.

This does NOT verify real clipboard-monitor exclusion. That separate driver still
requires a noninteractive window station; never touch the user's clipboard here.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import time


def run(directory,language,scale):
    from PySide6.QtCore import QCoreApplication,QEvent,QObject,QRect,QRectF,QSettings,QTimer,Qt
    from PySide6.QtGui import QColor,QFont,QImage,QPainter
    from PySide6.QtWidgets import QApplication
    from PySide6.QtTest import QTest
    app=QApplication([]);app.setQuitOnLastWindowClosed(False)
    from settings import get_tool_settings_manager
    config=get_tool_settings_manager(QSettings(str(directory/'settings.ini'),QSettings.Format.IniFormat))
    assert Path(config.qsettings.fileName()).resolve()==(directory/'settings.ini').resolve()
    from tests.native_image_editor import registry_digest
    registry_before=registry_digest()
    config.set_log_enabled(False);config.set_log_dir(str(directory/'logs'))
    config.set_clipboard_db_path(str(directory/'history.db'))
    output=directory/'output';output.mkdir()
    config.set_screenshot_save_path(str(output));config.set_screenshot_save_enabled(True)
    config.set_ocr_enabled(True);config.set_smart_selection(False)
    config.set_app_setting('language',language);config.set_app_setting('dialog_scale_percent',scale)
    from core.i18n import I18nManager
    from core.ui_scale import get_dialog_scale,get_ui_scale
    from core.ui_theme import get_ui_theme
    I18nManager.load_language(language);get_dialog_scale().init(config);get_ui_scale().init(config)
    theme=get_ui_theme().init(config,app)
    from main_app import MainApp
    from core import clipboard_utils
    from pin.pin_manager import PinManager
    from capture.capture_service import CaptureService
    from text_recognition import shutdown_recognition
    from text_recognition.redaction_window import RedactionWindow
    source=QImage(900,550,QImage.Format.Format_ARGB32);source.fill(QColor('#f1f5fb'))
    painter=QPainter(source);font=QFont('Arial');font.setPixelSize(38);painter.setFont(font)
    painter.setPen(QColor('#172554'));painter.drawText(30,80,'SYNTHETIC PRIVATE SESSION')
    painter.drawText(30,180,'Card 4111 1111 1111 1111');painter.end()
    capture_original=CaptureService.capture_all_screens
    CaptureService.capture_all_screens=lambda self:(QImage(source),QRect(0,0,900,550))
    copy_original=clipboard_utils.copy_image_to_clipboard
    copies=[]
    clipboard_utils.copy_image_to_clipboard=lambda image,**kw:copies.append((QImage(image),kw))
    main=MainApp.__new__(MainApp);QObject.__init__(main)
    main.app=app;main.config_manager=config;main.screenshot_window=None;main.clipboard_window=None
    main._capture_thread=None;main._capture_countdown=None;main._capture_busy=False;main._quitting=False;main.tray_icon=None
    records=[];redaction=None
    def wait(condition,seconds=45):
        deadline=time.monotonic()+seconds
        while time.monotonic()<deadline:
            app.processEvents()
            if condition():return
            time.sleep(.01)
        raise AssertionError('Sensitive-session native UI timed out')
    def start():
        main.start_sensitive_screenshot()
        wait(lambda:main.screenshot_window is not None and main.screenshot_window._session_active)
        win=main.screenshot_window
        win.scene.selection_model.initialize_confirmed_rect(QRectF(20,20,800,470))
        assert win.sensitive_capture and win.scene.sensitive_capture
        return win
    try:
        win=start();assert not copies
        for mode in ('light','dark'):
            theme.set_mode(mode,persist=False);app.processEvents()
            win._privacy_label.raise_();assert win.grab().save(str(directory/f'capture-{mode}.png'))
        # Cancel is a real Qt Esc shortcut. A fresh ordinary session must reset policy.
        QTest.keyClick(win,Qt.Key.Key_Escape);wait(lambda:not win._session_active)
        assert not copies and not list(output.iterdir())
        main.start_screenshot();wait(lambda:win._session_active)
        assert not win.sensitive_capture and not win.scene.sensitive_capture
        win.cleanup_and_close()
        records.append({'check':'sensitive entry, visible policy, Esc without copy, and ordinary cached-session reset','passed':True})
        win=start();win.action_handler.handle_pin()
        pins=PinManager.instance().get_all_pins();assert len(pins)==1 and pins[0].sensitive_capture
        pin=pins[0];assert not copies and not pin._ocr_mgr.init_now(force=True)
        pin.toggle_thumbnail_mode();pin.toggle_thumbnail_mode()
        assert pin.grab().save(str(directory/'sensitive-pin.png'))
        pin.copy_to_clipboard();assert len(copies)==1 and copies[-1][1]=={'sensitive':True}
        try:pin.get_current_image();raise AssertionError('Private pin exported publicly')
        except ValueError:pass
        pin.close_window()
        records.append({'check':'sensitive pin retains marker policy, does not auto-copy/OCR, allows private Copy, blocks public pixels','passed':True})
        win=start();win.action_handler.handle_smart_redact()
        redaction=next(w for w in app.topLevelWidgets() if isinstance(w,RedactionWindow))
        wait(lambda:redaction._thread is None)
        redaction.presets.setCurrentIndex(3)
        assert redaction.sensitive_capture and redaction.candidates.count()>=1
        assert not redaction.save_button.isEnabled() and not redaction.save_preset_button.isEnabled()
        assert redaction.grab().save(str(directory/'sensitive-redaction.png'))
        QTest.mouseClick(redaction.copy_button,Qt.MouseButton.LeftButton)
        assert len(copies)==2 and copies[-1][1]=={'sensitive':True}
        redaction.close();redaction=None
        records.append({'check':'real local OCR redaction inherits sensitive copy policy and disables file/preset persistence','passed':True})
        win=start()
        def acknowledge():
            modal=QApplication.activeModalWidget()
            if modal:modal.accept()
        QTimer.singleShot(150,acknowledge);win.action_handler.handle_save()
        assert win._session_active and not list(output.iterdir())
        win.action_handler.handle_copy();assert len(copies)==3 and copies[-1][1]=={'sensitive':True}
        assert not win._session_active and not list(output.iterdir())
        records.append({'check':'save is refused; explicit image Copy closes only its session and schedules no file write','passed':True})
        assert config.get_screenshot_save_enabled() and config.get_ocr_enabled()
        assert not (directory/'history.db').exists()
    finally:
        if redaction:redaction.close()
        if main.screenshot_window:main.screenshot_window.full_destroy()
        if main._capture_thread:assert main._capture_thread.wait(10000)
        PinManager.instance().close_all();shutdown_recognition(30000)
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        clipboard_utils.copy_image_to_clipboard=copy_original
        CaptureService.capture_all_screens=capture_original
        assert registry_digest()==registry_before
    result={'checks':records,'copy_boundary':'mocked; no real OS clipboard writes','capture_boundary':'synthetic frame returned by capture service',
            'real_clipboard_exclusion_verified':False,'real_registry_unchanged':True,'output_directory_empty':not list(output.iterdir())}
    (directory/'result.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--run',action='store_true');parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--language',default='zh');parser.add_argument('--scale',type=int,default=100);args=parser.parse_args()
    if not args.run:parser.error('Requires --run')
    args.output=args.output.resolve();args.output.mkdir(parents=True,exist_ok=True)
    os.environ['QT_QPA_PLATFORM']='windows';os.environ['QT_ENABLE_HIGHDPI_SCALING']='0';os.environ['QT_SCALE_FACTOR']='1'
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
    from core.platform_utils import set_dpi_awareness
    set_dpi_awareness();run(args.output,args.language,args.scale)
