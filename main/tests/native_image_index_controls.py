"""Opt-in real history UI/OCR index controls on isolated database/settings only."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def run(directory, language, scale):
    from PySide6.QtCore import QCoreApplication,QEvent,QSettings,QTimer,Qt
    from PySide6.QtGui import QColor,QImage,QPainter,QFont
    from PySide6.QtWidgets import QApplication,QMenu,QDialogButtonBox
    from PySide6.QtTest import QTest
    app=QApplication([]);app.setQuitOnLastWindowClosed(False)
    from settings import get_tool_settings_manager
    config=get_tool_settings_manager(QSettings(str(directory/'settings.ini'),QSettings.Format.IniFormat))
    assert Path(config.qsettings.fileName()).resolve()==(directory/'settings.ini').resolve()
    from tests.native_image_editor import registry_digest
    before=registry_digest()
    window_registry=QSettings('Jietuba','ClipboardWindow')
    window_before={k:repr(window_registry.value(k)) for k in window_registry.allKeys()}
    config.set_clipboard_db_path(str(directory/'history.db'));config.set_log_enabled(False);config.set_log_dir(str(directory/'logs'))
    config.set_app_setting('language',language);config.set_app_setting('dialog_scale_percent',scale)
    config.set_clipboard_enabled(False)
    from core.i18n import I18nManager
    from core.ui_scale import get_dialog_scale,get_ui_scale
    from core.ui_theme import get_ui_theme
    I18nManager.load_language(language);get_dialog_scale().init(config);get_ui_scale().init(config)
    theme=get_ui_theme().init(config,app)
    from clipboard.core import ClipboardManager
    import clipboard.ui.windows.clipboard_window as module
    from clipboard.ui.widgets.item_delegate import ROLE_ITEM_ID,ROLE_ITEM_DATA
    manager=ClipboardManager(config.get_clipboard_db_path())
    assert manager.is_available and not manager.is_monitoring()
    store=manager.image_text_store
    item=manager.add_item('Synthetic index fixture','image',title='Synthetic index fixture')
    with store.connect() as db:db.execute('UPDATE clipboard SET image_id=? WHERE id=?',('index-fixture',item))
    manager._manager.insert_formats(item,[(13,'CF_UNICODETEXT',list('ORIGINAL_FORMAT'.encode('utf-16le')))])
    raw=manager._manager.get_raw_formats(item)
    image=QImage(800,180,QImage.Format.Format_ARGB32);image.fill(QColor('white'))
    p=QPainter(image);p.setPen(QColor('#172554'));f=QFont('Arial');f.setPixelSize(42);p.setFont(f)
    p.drawText(24,100,'INDEX FIXTURE ALPHA 2048');p.end()
    original_qsettings=module.QSettings
    window_settings=QSettings(str(directory/'window.ini'),QSettings.Format.IniFormat)
    module.QSettings=lambda *a:window_settings
    window=module.ClipboardWindow();assert window._qsettings is window_settings
    records=[];errors=[]
    def wait(condition, seconds=30):
        deadline=time.monotonic()+seconds
        while time.monotonic()<deadline:
            app.processEvents()
            if condition():return
            time.sleep(.01)
        raise AssertionError('Native index controls timed out')
    def row():
        for n in range(window.list_widget.count()):
            entry=window.list_widget.item(n)
            if entry.data(ROLE_ITEM_ID)==item:return n,entry
        raise AssertionError('Fixture row missing')
    def command(label, confirm=True, screenshot=None):
        n,entry=row();window.list_widget.setCurrentRow(n)
        window.list_widget.scrollToItem(entry)
        pos=window.list_widget.visualItemRect(entry).center()
        state={'clicked':False,'ticks':0}
        timer=QTimer()
        def pump():
            try:
                state['ticks']+=1
                if state['ticks']>160:raise AssertionError('Context menu action timed out')
                modal=QApplication.activeModalWidget()
                if modal is not None:
                    role=QDialogButtonBox.ButtonRole.YesRole if confirm else QDialogButtonBox.ButtonRole.NoRole
                    box=modal.button_box
                    button=next(b for b in box.buttons() if box.buttonRole(b)==role)
                    if screenshot:assert modal.grab().save(str(directory/(screenshot+'-confirmation.png')))
                    QTest.mouseClick(button,Qt.MouseButton.LeftButton);return
                menu=QApplication.activePopupWidget()
                if not isinstance(menu,QMenu):return
                target=next((a for a in menu.actions() if a.text()==window.tr(label)),None)
                if target:
                    assert target.isEnabled(),label
                    if screenshot:assert menu.grab().save(str(directory/(screenshot+'-menu.png')))
                    state['clicked']=True
                    if label == "Exclude image from text index":
                        # A repeating QTimer is not reentrant while its click slot
                        # enters QDialog.exec(); use a separate queued callback.
                        QTimer.singleShot(120, respond_confirmation)
                    QTest.mouseClick(menu,Qt.MouseButton.LeftButton,pos=menu.actionGeometry(target).center())
                else:
                    parent=next((a for a in menu.actions() if a.text()==window.tr('Image text index')),None)
                    if parent:
                        menu.setActiveAction(parent)
                        QTest.keyClick(menu,Qt.Key.Key_Right)
            except Exception:
                import traceback
                errors.append(traceback.format_exc())
                if QApplication.activeModalWidget():QApplication.activeModalWidget().reject()
                for w in app.topLevelWidgets():
                    if isinstance(w,QMenu):w.close()
                timer.stop()
        def respond_confirmation():
            modal=QApplication.activeModalWidget()
            try:
                assert modal is not None
                box=modal.button_box
                role=QDialogButtonBox.ButtonRole.YesRole if confirm else QDialogButtonBox.ButtonRole.NoRole
                button=next(b for b in box.buttons() if box.buttonRole(b)==role)
                if screenshot:assert modal.grab().save(str(directory/(screenshot+"-confirmation.png")))
                QTest.mouseClick(button,Qt.MouseButton.LeftButton)
            except Exception:
                import traceback
                errors.append(traceback.format_exc())
                if modal:modal.reject()
        timer.timeout.connect(pump);timer.start(70)
        try:window._show_context_menu(pos)
        finally:timer.stop()
        assert not errors,errors
        assert state['clicked'],label
    try:
        window.show()
        wait(lambda:manager.get_item(item).ocr_status=='failed')
        wait(lambda:window.list_widget.count()>0)
        assert manager.get_item(item).ocr_error=='invalid_image'
        assert window.grab().save(str(directory/'failed.png'))
        source=Path(manager.get_images_dir())/'index-fixture.png';source.parent.mkdir(parents=True,exist_ok=True)
        assert image.save(str(source));digest=hashlib.sha256(source.read_bytes()).hexdigest()
        # Real retry repairs a missing-data failure and executes the actual local OCR model.
        def capture_recognizing(changed):
            if changed==item and manager.get_item(item).ocr_status=='recognizing':
                window.grab().save(str(directory/'recognizing.png'))
        manager._image_indexer.item_state_changed.connect(capture_recognizing)
        command('Retry failed OCR',screenshot='retry')
        wait(lambda:manager.get_item(item).ocr_status=='done')
        text=manager.get_item(item).ocr_text
        assert 'ALPHA' in text and manager.get_history(search='ALPHA')[0].id==item,text
        records.append({'check':'missing image failure -> actual context-menu retry -> real OCR indexed/searchable text','passed':True})
        for color in ('light','dark'):
            theme.set_mode(color,persist=False);app.processEvents()
            assert window.grab().save(str(directory/f'indexed-{color}.png'))
        selected=row()[0];scroll=window.list_widget.verticalScrollBar().value()
        command('Exclude image from text index',confirm=False,screenshot='exclude-no')
        assert manager.get_item(item).ocr_status=='done'
        command('Exclude image from text index',confirm=True,screenshot='exclude-yes')
        assert manager.get_item(item).ocr_status=='excluded' and store.get_result(item) is None
        assert not manager.get_history(search='ALPHA')
        assert window.list_widget.currentRow()==selected and window.list_widget.verticalScrollBar().value()==scroll
        assert row()[1].data(ROLE_ITEM_DATA).ocr_status=='excluded'
        assert window.grab().save(str(directory/'excluded.png'))
        manager.stop_image_indexing();window._start_image_indexing()
        manager._image_indexer._next();assert manager.get_item(item).ocr_status=='excluded'
        child_code="import sys,json;from clipboard.core.image_text import ImageTextStore;s=ImageTextStore(sys.argv[1]);state=s.state(int(sys.argv[2]));assert state['status']=='excluded' and s.pending() is None and s.get_result(int(sys.argv[2])) is None;print(json.dumps(state))"
        env=dict(os.environ);env['PYTHONPATH']=str(Path(__file__).resolve().parents[1])
        child=subprocess.run([sys.executable,'-B','-X','utf8','-c',child_code,store.path,str(item)],capture_output=True,text=True,env=env,timeout=30)
        assert child.returncode==0,child.stderr
        records.append({'check':'actual Yes/No exclusion removes only OCR text; restart/fresh process keep item excluded','passed':True})
        command('Restore image text indexing',screenshot='restore')
        wait(lambda:manager.get_item(item).ocr_status=='done')
        assert manager.get_history(search='ALPHA')
        first_token=store.state(item)['token']
        command('Recognize image text again',screenshot='reindex')
        wait(lambda:manager.get_item(item).ocr_status=='done' and store.state(item)['token']!=first_token)
        assert manager.get_history(search='ALPHA')
        assert hashlib.sha256(source.read_bytes()).hexdigest()==digest and manager._manager.get_raw_formats(item)==raw
        records.append({'check':'restore and re-recognize execute real OCR while source image and original paste formats remain byte-identical','passed':True})
    finally:
        indexer=manager._image_indexer;thread=indexer._thread if indexer else None
        window.close();window.deleteLater();manager.release_storage()
        if thread:assert thread.wait(30000)
        from text_recognition import shutdown_recognition
        shutdown_recognition(30000);app.processEvents();QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        module.QSettings=original_qsettings
        assert registry_digest()==before
        window_registry.sync();assert window_before=={k:repr(window_registry.value(k)) for k in window_registry.allKeys()}
    (directory/'result.json').write_text(json.dumps(records,indent=2),encoding='utf-8');print(json.dumps(records,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--run',action='store_true');parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--language',default='zh');parser.add_argument('--scale',type=int,default=100);args=parser.parse_args()
    if not args.run:parser.error('Requires --run')
    args.output=args.output.resolve();args.output.mkdir(parents=True,exist_ok=True)
    os.environ['QT_QPA_PLATFORM']='windows';os.environ['QT_ENABLE_HIGHDPI_SCALING']='0';os.environ['QT_SCALE_FACTOR']='1'
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
    from core.platform_utils import set_dpi_awareness
    set_dpi_awareness();run(args.output,args.language,args.scale)
