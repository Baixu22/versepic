"""Opt-in native rule review, real OCR and history entry; synthetic content only."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace


def run(directory,language,scale):
    from PySide6.QtCore import QCoreApplication,QEvent,QSettings,QSize,QTimer,Qt
    from PySide6.QtGui import QColor,QFont,QImage,QPainter
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication,QAbstractButton
    app=QApplication([]);app.setQuitOnLastWindowClosed(False)
    from settings import get_tool_settings_manager
    config=get_tool_settings_manager(QSettings(str(directory/'settings.ini'),QSettings.Format.IniFormat))
    assert Path(config.qsettings.fileName()).resolve()==(directory/'settings.ini').resolve()
    from tests.native_image_editor import registry_digest
    baseline=registry_digest()
    config.set_log_enabled(False);config.set_log_dir(str(directory/'logs'))
    config.set_clipboard_db_path(str(directory/'history.db'))
    config.set_app_setting('language',language);config.set_app_setting('dialog_scale_percent',scale)
    config.set_app_setting('screenshot_size_mode','half')
    from core.i18n import I18nManager
    from core.ui_scale import get_dialog_scale,get_ui_scale
    from core.ui_theme import get_ui_theme
    I18nManager.load_language(language);get_dialog_scale().init(config);get_ui_scale().init(config)
    theme=get_ui_theme().init(config,app)
    from text_recognition.redaction_window import show_redaction
    from text_recognition.redaction import RedactionPresetStore,redact_image
    from text_recognition import shutdown_recognition
    from clipboard.core import ClipboardManager
    from clipboard.ui.windows.clipboard_window import ClipboardWindow
    source=QImage(1000,620,QImage.Format.Format_ARGB32);source.fill(QColor('white'))
    painter=QPainter(source);font=QFont('Arial');font.setPixelSize(30);painter.setFont(font);painter.setPen(QColor('#172554'))
    for y,text in [(70,'SYNTHETIC PRIVACY FIXTURE - NOT REAL ACCOUNTS'),(150,'ID 11010519491231002X'),
                   (240,'Card 4111 1111 1111 1111'),(330,'Phone 138 1234 5678'),(420,'Email demo@example.com'),
                   (530,'MANUAL AREA: review this text')]:painter.drawText(30,y,text)
    painter.end();source.setText('PrivateMetadata','DO_NOT_EXPORT_RAW_SOURCE')
    source_path=directory/'source.png';assert source.save(str(source_path))
    source_hash=hashlib.sha256(source_path.read_bytes()).hexdigest()
    records=[];errors=[]
    def wait(predicate,seconds=45):
        deadline=time.monotonic()+seconds
        while time.monotonic()<deadline:
            app.processEvents()
            if predicate():return
            time.sleep(.01)
        raise AssertionError('Native redaction timed out')
    window=show_redaction(source);manager=None;history_window=None
    try:
        wait(lambda:window._thread is None)
        assert window._result.get('code')==100,window.status.text()
        (directory/'ocr-result.json').write_text(json.dumps(window._result,ensure_ascii=False,indent=2),encoding='utf-8')
        window.presets.setCurrentIndex(3)
        assert window.candidates.count()>=4,[window.candidates.item(i).text() for i in range(window.candidates.count())]
        records.append({'check':'real local OCR detects synthetic ID, card, phone and email lines with all checks','passed':True})
        # Native input from displayed view coordinates creates a manual mask.
        view=window.preview;view.fitInView(view.sceneRect(),Qt.AspectRatioMode.KeepAspectRatio)
        start=view.mapFromScene(25,490);end=view.mapFromScene(700,548)
        QTest.mousePress(view.viewport(),Qt.MouseButton.LeftButton,pos=start)
        QTest.mouseMove(view.viewport(),end)
        QTest.mouseRelease(view.viewport(),Qt.MouseButton.LeftButton,pos=end)
        assert window._manual and window.selected_rectangles()
        count=window.candidates.count();window.candidates.item(0).setCheckState(Qt.CheckState.Unchecked)
        assert len(window.selected_rectangles())==count-1
        window.candidates.item(0).setCheckState(Qt.CheckState.Checked)
        window.keywords.setText('EPHEMERAL_KEYWORD_NOT_SAVED')
        def fill_name():
            try:
                from ui.fluent_lite import LineEdit
                modal=QApplication.activeModalWidget();assert modal is not None
                edit=modal.findChild(LineEdit);edit.setFocus();QTest.keyClicks(edit,'Safe review')
                save=next(b for b in modal.findChildren(QAbstractButton) if b.text()==window.tr('Save') or b.text() in ('保存','Save'))
                QTest.mouseClick(save,Qt.MouseButton.LeftButton)
            except Exception:
                import traceback
                errors.append(traceback.format_exc())
                if QApplication.activeModalWidget():QApplication.activeModalWidget().reject()
        QTimer.singleShot(100,fill_name);QTest.mouseClick(window.save_preset_button,Qt.MouseButton.LeftButton)
        assert not errors,errors
        presets=window.preset_store.load();assert len(presets)==1 and presets[0]['name']=='Safe review'
        raw=config.get_app_setting(RedactionPresetStore.KEY,'')
        assert 'EPHEMERAL' not in raw and '110105' not in raw and 'demo@' not in raw
        config.qsettings.sync()
        child_code="import sys,json;from pathlib import Path;from PySide6.QtCore import QCoreApplication,QSettings;app=QCoreApplication([]);from settings import get_tool_settings_manager;from text_recognition.redaction import RedactionPresetStore;c=get_tool_settings_manager(QSettings(sys.argv[1],QSettings.Format.IniFormat));assert Path(c.qsettings.fileName()).resolve()==Path(sys.argv[1]).resolve();print(json.dumps(RedactionPresetStore(c).load()))"
        env=dict(os.environ);env['PYTHONPATH']=str(Path(__file__).resolve().parents[1])
        child=subprocess.run([sys.executable,'-B','-X','utf8','-c',child_code,str(directory/'settings.ini')],capture_output=True,text=True,env=env,timeout=30)
        assert child.returncode==0,child.stderr
        assert json.loads(child.stdout)==presets
        records.append({'check':'native manual coverage/review and saved rule switches survive a fresh process without keywords/OCR/image data','passed':True})
        for mode in ('light','dark'):
            theme.set_mode(mode,persist=False);app.processEvents()
            assert window.grab().save(str(directory/f'review-{mode}.png'))
        # Save through the real window action; deterministic file-dialog boundary only.
        import text_recognition.redaction_window as module
        original=module.QFileDialog.getSaveFileName
        try:
            for suffix in ('png','jpg','pdf'):
                destination=directory/f'redacted.{suffix}'
                module.QFileDialog.getSaveFileName=lambda *a,destination=destination,**k:(str(destination),'')
                QTest.mouseClick(window.save_button,Qt.MouseButton.LeftButton)
                assert destination.exists(),window.status.text()
            module.QFileDialog.getSaveFileName=lambda *a,**k:(str(source_path),'PNG (*.png)')
            window._save();assert hashlib.sha256(source_path.read_bytes()).hexdigest()==source_hash
        finally:module.QFileDialog.getSaveFileName=original
        from PIL import Image
        expected=redact_image(source,window.selected_rectangles())
        assert QImage(str(directory/'redacted.png'))==expected
        with Image.open(directory/'redacted.jpg') as output:
            assert output.size==(1000,620) and 'PrivateMetadata' not in str(output.info)
        from PySide6.QtPdf import QPdfDocument
        pdf=QPdfDocument();assert pdf.load(str(directory/'redacted.pdf'))==QPdfDocument.Error.None_
        assert pdf.pageCount()==1 and pdf.getAllText(0).text()==''
        rendered=pdf.render(0,QSize(1000,620));assert not rendered.isNull()
        assert rendered.save(str(directory/'pdf-render.png'));pdf.close()
        for rect in window.selected_rectangles():
            point=rect.center()
            assert rendered.pixelColor(point)==QColor('black')
        records.append({'check':'real window saves flattened original-resolution PNG/JPEG/PDF and refuses source overwrite; PDF has no text layer','passed':True})
        # Real isolated history item runs the same review handler/recognizer.
        manager=ClipboardManager(config.get_clipboard_db_path());assert manager.is_available
        identifier=manager.add_item('Synthetic rules fixture','image',title='Synthetic rules fixture')
        with manager.image_text_store.connect() as db:db.execute('UPDATE clipboard SET image_id=? WHERE id=?',('redaction-fixture',identifier))
        history_path=Path(manager.get_images_dir())/'redaction-fixture.png';history_path.parent.mkdir(parents=True,exist_ok=True)
        assert source.save(str(history_path));history_hash=hashlib.sha256(history_path.read_bytes()).hexdigest()
        ClipboardWindow._process_image(SimpleNamespace(manager=manager),identifier,redact=True)
        history_window=app._modeless_dialogs[-1];assert history_window is not window
        wait(lambda:history_window._thread is None)
        history_window.presets.setCurrentIndex(4)
        assert history_window.china_ids.isChecked() and history_window.bank_cards.isChecked()
        assert history_window.candidates.count()>=4
        assert not history_window.keywords.text()
        assert hashlib.sha256(history_path.read_bytes()).hexdigest()==history_hash
        records.append({'check':'actual isolated history entry opens the same rules/preset UI; history image and metadata are not overwritten','passed':True})
        # Cancel then confirm deletion; current mask/source content must stay unchanged.
        from PySide6.QtWidgets import QDialogButtonBox
        def respond(accepted):
            modal=QApplication.activeModalWidget()
            try:
                box=modal.button_box
                role=QDialogButtonBox.ButtonRole.YesRole if accepted else QDialogButtonBox.ButtonRole.NoRole
                button=next(b for b in box.buttons() if box.buttonRole(b)==role)
                assert modal.grab().save(str(directory/f'delete-confirm-{accepted}.png'))
                QTest.mouseClick(button,Qt.MouseButton.LeftButton)
            except Exception:
                import traceback
                errors.append(traceback.format_exc())
                if modal:modal.reject()
        QTimer.singleShot(100,lambda:respond(False));QTest.mouseClick(history_window.delete_preset_button,Qt.MouseButton.LeftButton)
        assert not errors and history_window.preset_store.load(),errors
        QTimer.singleShot(100,lambda:respond(True));QTest.mouseClick(history_window.delete_preset_button,Qt.MouseButton.LeftButton)
        assert not errors and not history_window.preset_store.load(),errors
        assert history_window.china_ids.isChecked()
        assert hashlib.sha256(source_path.read_bytes()).hexdigest()==source_hash
        records.append({'check':'delete affects only the selected saved rule combination; cancellation and source files remain intact','passed':True})
    finally:
        if history_window:history_window.close()
        window.close();shutdown_recognition(30000)
        if manager:manager.release_storage()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        assert registry_digest()==baseline,'Real settings changed'
    (directory/'result.json').write_text(json.dumps(records,indent=2),encoding='utf-8');print(json.dumps(records,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--run',action='store_true')
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--language',default='zh');parser.add_argument('--scale',type=int,default=100)
    args=parser.parse_args()
    if not args.run:parser.error('Native redaction acceptance requires --run')
    args.output=args.output.resolve();args.output.mkdir(parents=True,exist_ok=True)
    os.environ['QT_QPA_PLATFORM']='windows';os.environ['QT_ENABLE_HIGHDPI_SCALING']='0';os.environ['QT_SCALE_FACTOR']='1'
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
    from core.platform_utils import set_dpi_awareness
    set_dpi_awareness();run(args.output,args.language,args.scale)
