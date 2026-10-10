"""Native image comparison acceptance with synthetic files, history and pins only."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time


def run(directory,language,scale):
    from PySide6.QtCore import QPoint,QPointF,QSettings,QTimer,Qt
    from PySide6.QtGui import QColor,QImage,QPainter,QFont
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication,QAbstractButton
    from settings import get_tool_settings_manager
    app=QApplication([]);app.setQuitOnLastWindowClosed(False)
    config=get_tool_settings_manager(QSettings(str(directory/'settings.ini'),QSettings.Format.IniFormat))
    assert Path(config.qsettings.fileName()).resolve()==(directory/'settings.ini').resolve()
    from tests.native_image_editor import registry_digest
    baseline=registry_digest()
    from core.i18n import I18nManager
    from core.logger import setup_logger
    from core.ui_theme import get_ui_theme
    from core.ui_scale import get_dialog_scale,get_ui_scale
    config.set_clipboard_db_path(str(directory/'history.db'));config.set_log_enabled(False)
    config.set_log_dir(str(directory/'logs'));config.set_ocr_enabled(False)
    config.set_app_setting('language',language);config.set_app_setting('dialog_scale_percent',scale)
    setup_logger(config);I18nManager.load_language(language);get_dialog_scale().init(config);get_ui_scale().init(config)
    theme=get_ui_theme().init(config,app)
    from clipboard.core import ClipboardManager
    from pin.pin_manager import PinManager
    from ui.image_compare import show_image_compare
    manager=ClipboardManager(config.get_clipboard_db_path());assert manager.is_available
    pins=PinManager.instance()
    window=show_image_compare()
    records=[]
    def wait(predicate,seconds=15):
        deadline=time.monotonic()+seconds
        while time.monotonic()<deadline:
            app.processEvents()
            if predicate():return
            time.sleep(.01)
        raise AssertionError('Native comparison condition timed out')
    def pause(seconds):
        start=time.monotonic();wait(lambda:time.monotonic()-start>=seconds)
    a=QImage(800,560,QImage.Format.Format_RGBA8888);a.fill(QColor('#eff6ff'))
    painter=QPainter(a);font=QFont('Arial');font.setPixelSize(38);painter.setFont(font)
    painter.setPen(QColor('#172554'));painter.drawText(40,75,'READ ONLY COMPARISON')
    painter.fillRect(50,140,250,200,QColor('#1d4ed8'));painter.fillRect(440,300,200,140,QColor('#15803d'));painter.end()
    b=QImage(a);painter=QPainter(b);painter.fillRect(100,180,80,60,QColor('#ef4444'));painter.end()
    file_a=directory/'a.png';file_b=directory/'b.png';assert a.save(str(file_a)) and b.save(str(file_b))
    hashes={str(file):hashlib.sha256(file.read_bytes()).hexdigest() for file in (file_a,file_b)}
    identifier=manager.add_item('B fixture','image',title='B fixture')
    with manager.image_text_store.connect() as db:db.execute('UPDATE clipboard SET image_id=? WHERE id=?',('comparison-b',identifier))
    history_file=Path(manager.get_images_dir())/'comparison-b.png';history_file.parent.mkdir(parents=True,exist_ok=True);b.save(str(history_file))
    hashes[str(history_file)]=hashlib.sha256(history_file.read_bytes()).hexdigest()
    errors=[]
    try:
        # File chooser boundary is deterministic; the actual history selector is driven with Qt input.
        import ui.image_compare as module
        original=module.QFileDialog.getOpenFileName
        module.QFileDialog.getOpenFileName=lambda *a,**k:(str(file_a),'PNG (*.png)')
        try:window.choose_file()
        finally:module.QFileDialog.getOpenFileName=original
        assert window.images[0] is not None and window.slot.currentData()==1
        def choose_history():
            picker=QApplication.activeModalWidget()
            try:
                assert picker is not None
                for row in range(picker.list.count()):
                    if picker.list.item(row).data(Qt.ItemDataRole.UserRole)==identifier:
                        picker.list.setCurrentRow(row);picker.list.item(row).setSelected(True);break
                assert picker.selected()==[identifier]
                assert picker.grab().save(str(directory/'history-picker.png'))
                button=next(button for button in picker.findChildren(QAbstractButton) if button.text()==picker.tr('Add selected'))
                QTest.mouseClick(button,Qt.MouseButton.LeftButton)
            except Exception:
                import traceback
                errors.append(traceback.format_exc());picker.reject()
        QTimer.singleShot(150,choose_history);window.choose_history();assert not errors,errors
        assert window.images[1] is not None
        pause(.2);window.fit()
        records.append({'check':'file A and real isolated-history selector B','passed':True})
        for mode in ('light','dark'):
            theme.set_mode(mode,persist=False);pause(.1)
            assert window.grab().save(str(directory/f'side-{mode}.png'))
        # Native wheel on the real viewport, then pan using real Qt mouse events.
        import win32gui
        from pynput.keyboard import Controller as Keyboard,Key
        from pynput.mouse import Controller as Mouse
        keyboard=Keyboard();keyboard.press(Key.alt);keyboard.release(Key.alt)
        win32gui.SetForegroundWindow(int(window.winId()));wait(lambda:win32gui.GetForegroundWindow()==int(window.winId()))
        mouse=Mouse();old=mouse.position
        point=window.views[0].viewport().mapToGlobal(window.views[0].viewport().rect().center());mouse.position=(point.x(),point.y())
        try:
            window.set_zoom(1);old_scale=window._scale;mouse.scroll(0,2)
            wait(lambda:window._scale>old_scale)
        finally:mouse.position=old
        assert window.views[0].transform().m11()==window.views[1].transform().m11()
        view=window.views[0];start=view.viewport().rect().center()
        QTest.mousePress(view.viewport(),Qt.MouseButton.LeftButton,pos=start)
        QTest.mouseMove(view.viewport(),start+QPoint(75,45),delay=80)
        QTest.mouseRelease(view.viewport(),Qt.MouseButton.LeftButton,pos=start+QPoint(75,45))
        centers=[v.mapToScene(v.viewport().rect().center()) for v in window.views]
        assert abs(centers[0].x()-centers[1].x())<=1 and abs(centers[0].y()-centers[1].y())<=1
        records.append({'check':'actual system-wheel zoom and synchronized native pan','passed':True})
        window.mode.setCurrentIndex(1);pause(.15);window.fit()
        view=window.views[0];start=view.mapFromScene(QPointF(400,280));end=view.mapFromScene(QPointF(600,280))
        QTest.mousePress(view.viewport(),Qt.MouseButton.LeftButton,pos=start)
        QTest.mouseMove(view.viewport(),end,delay=80)
        QTest.mouseRelease(view.viewport(),Qt.MouseButton.LeftButton,pos=end)
        assert abs(window.split.value()-75)<=1
        assert window.grab().save(str(directory/'wipe.png'))
        records.append({'check':'native wipe boundary tracks image coordinates','passed':True})
        window.mode.setCurrentIndex(2);wait(lambda:window.result is not None)
        assert window.result.changed_pixels==4800 and window.result.compared_pixels==800*560
        assert window.result.overlay.pixelColor(110,190).alpha()==180
        assert window.result.overlay.pixelColor(40,120).alpha()==0
        assert window.grab().save(str(directory/'difference.png'))
        window.threshold.setValue(255);wait(lambda:window.result is not None and window.result.changed_pixels==0)
        records.append({'check':'known 80x60 edit yields exactly 4800 differing pixels; threshold recomputes','passed':True})
        window.threshold.setValue(0)
        pin=pins.create_pin(a,QPoint(100,100),config_manager=config)
        try:
            window.slot.setCurrentIndex(1)
            def select_pin():
                picker=QApplication.activeModalWidget()
                try:
                    picker.list.setCurrentRow(0);picker.list.item(0).setSelected(True)
                    button=next(button for button in picker.findChildren(QAbstractButton) if button.text()==picker.tr('Add selected'))
                    QTest.mouseClick(button,Qt.MouseButton.LeftButton)
                except Exception:
                    import traceback
                    errors.append(traceback.format_exc());picker.reject()
            QTimer.singleShot(150,select_pin);window.choose_pin();assert not errors,errors
            wait(lambda:window.result is not None and window.result.changed_pixels==0)
            assert pin.canvas is not None and not pin._is_closed
        finally:pin.close_window()
        records.append({'check':'native pin selector supplies same original pixels without altering the pin','passed':True})
        # Different sizes: original coverage mismatch vs explicitly normalized geometry.
        small=a.scaled(400,280,Qt.AspectRatioMode.IgnoreAspectRatio,Qt.TransformationMode.SmoothTransformation)
        assert window.set_image(1,small,'half-size')
        wait(lambda:window.result is not None)
        assert window.canvas_rect.width()==800 and window.result.changed_pixels>0
        window.alignment.setCurrentIndex(1);wait(lambda:window.result is not None)
        assert window.grab().save(str(directory/'resized-comparison.png'))
        records.append({'check':'different-size alignment explicitly switches to resampled comparison','passed':True})
        for file,digest in hashes.items():assert hashlib.sha256(Path(file).read_bytes()).hexdigest()==digest
        window.clear();assert window.images==[None,None] and window.result is None
        records.append({'check':'source file hashes unchanged; clear removes both images and differences','passed':True})
        (directory/'result.json').write_text(json.dumps(records,indent=2),encoding='utf-8')
        print(json.dumps(records,indent=2))
    finally:
        window.shutdown();window.close();pins.close_all();manager.release_storage()
        assert registry_digest()==baseline,'Real settings changed during comparison acceptance'


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--run',action='store_true')
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--language',default='zh')
    parser.add_argument('--scale',type=int,default=100);args=parser.parse_args()
    if not args.run:parser.error('Native comparison acceptance requires --run')
    args.output.mkdir(parents=True,exist_ok=True)
    os.environ['QT_QPA_PLATFORM']='windows';os.environ['QT_ENABLE_HIGHDPI_SCALING']='0';os.environ['QT_SCALE_FACTOR']='1'
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
    from core.platform_utils import set_dpi_awareness
    set_dpi_awareness();run(args.output,args.language,args.scale)
