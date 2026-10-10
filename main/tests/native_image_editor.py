"""Opt-in image editor acceptance: native drag/drop, annotations, crop, save and cleanup."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import threading
import time


def registry_digest():
    import winreg
    rows=[]
    def visit(relative):
        try:key=winreg.OpenKey(winreg.HKEY_CURRENT_USER,r"Software\Jietuba\ToolSettings"+("\\"+relative if relative else ""))
        except FileNotFoundError:return
        with key:
            i=0
            while True:
                try:name,value,kind=winreg.EnumValue(key,i)
                except OSError:break
                rows.append((relative,name,repr(value),kind));i+=1
            i=0
            while True:
                try:name=winreg.EnumKey(key,i)
                except OSError:break
                visit(relative+("\\" if relative else "")+name);i+=1
    visit("")
    return hashlib.sha256(json.dumps(sorted(rows),ensure_ascii=False).encode()).hexdigest()


def run(directory,language,scale):
    from PySide6.QtCore import QMimeData,QPointF,QSettings,QTimer,QUrl,Qt
    from PySide6.QtGui import QColor,QDrag,QFont,QImage,QPainter
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication,QPushButton
    from settings import get_tool_settings_manager
    app=QApplication([])
    app.setQuitOnLastWindowClosed(False)
    config=get_tool_settings_manager(QSettings(str(directory/"settings.ini"),QSettings.Format.IniFormat))
    assert Path(config.qsettings.fileName()).resolve()==(directory/"settings.ini").resolve()
    before_registry=registry_digest()
    from core.i18n import I18nManager
    from core.logger import setup_logger
    from core.ui_scale import get_dialog_scale,get_ui_scale
    from core.ui_theme import get_ui_theme
    from core.image_document import ImageGeometry
    from ui.image_editor import show_image_editor
    from pynput.mouse import Controller,Button
    config.set_log_enabled(False)
    config.set_log_dir(str(directory/"logs"))
    config.set_clipboard_db_path(str(directory/"unused.db"))
    config.set_app_setting("language",language)
    config.set_app_setting("dialog_scale_percent",scale)
    config.set_screenshot_save_enabled(False)
    config.set_ocr_enabled(False)
    setup_logger(config)
    I18nManager.load_language(language)
    get_dialog_scale().init(config);get_ui_scale().init(config)
    theme=get_ui_theme().init(config,app)
    source=QImage(640,420,QImage.Format.Format_ARGB32)
    source.fill(QColor("#eff6ff"))
    painter=QPainter(source)
    painter.fillRect(20,100,220,150,QColor("#1d4ed8"))
    painter.fillRect(330,190,240,150,QColor("#15803d"))
    painter.setPen(QColor("#172554"))
    font=QFont("Arial");font.setPixelSize(36);painter.setFont(font)
    painter.drawText(30,60,"EDITOR SAMPLE 123")
    painter.end()
    original=directory/"source.png"
    assert source.save(str(original))
    before_file=hashlib.sha256(original.read_bytes()).hexdigest()
    editor=show_image_editor()
    editor.move(400,120)
    class DragSource(QPushButton):
        def __init__(self):
            super().__init__("Drag synthetic image")
            self.setGeometry(40,140,280,100)
            self.setWindowFlags(Qt.WindowType.Tool|Qt.WindowType.WindowStaysOnTopHint)
            self.started=False
            self.filename=original
            self.outcome=None
        def mouseMoveEvent(self,event):
            if event.buttons() & Qt.MouseButton.LeftButton and not self.started:
                self.started=True
                mime=QMimeData();mime.setUrls([QUrl.fromLocalFile(str(self.filename))])
                drag=QDrag(self);drag.setMimeData(mime)
                self.outcome=drag.exec(Qt.DropAction.CopyAction)
            super().mouseMoveEvent(event)
    source_window=DragSource();source_window.show()
    import win32gui
    from pynput.keyboard import Controller as Keyboard, Key
    mouse=Controller();old_position=mouse.position
    results=[]
    def wait(predicate,seconds=15):
        end=time.monotonic()+seconds
        while time.monotonic()<end:
            app.processEvents()
            if predicate():return
            time.sleep(.01)
        raise AssertionError("Native editor acceptance timed out")
    def pause(seconds):
        began=time.monotonic();wait(lambda:time.monotonic()-began>=seconds,seconds+2)
    def focus_source():
        keyboard=Keyboard()
        keyboard.press(Key.alt);keyboard.release(Key.alt)
        win32gui.SetForegroundWindow(int(source_window.winId()))
        wait(lambda:win32gui.GetForegroundWindow()==int(source_window.winId()))
        pause(.15)

    try:
        assert QTest.qWaitForWindowExposed(source_window)
        assert QTest.qWaitForWindowExposed(editor)
        source_window.raise_()
        source_window.activateWindow()
        pause(.3)
        focus_source()
        start=source_window.mapToGlobal(source_window.rect().center())
        finish=editor.placeholder.mapToGlobal(editor.placeholder.rect().center())
        errors=[]
        def drag_file():
            try:
                mouse.position=(start.x(),start.y());time.sleep(.15);mouse.press(Button.left)
                for step in range(1,24):
                    mouse.position=(round(start.x()+(finish.x()-start.x())*step/23),round(start.y()+(finish.y()-start.y())*step/23))
                    time.sleep(.03)
                mouse.release(Button.left)
            except Exception as exc:errors.append(str(exc))
            finally:
                mouse.release(Button.left)
        thread=threading.Thread(target=drag_file);thread.start()
        wait(lambda:not thread.is_alive());thread.join()
        assert not errors,errors
        wait(lambda:source_window.started and source_window.outcome is not None)
        assert source_window.outcome==Qt.DropAction.CopyAction,(source_window.outcome,editor.status.text(),start,finish)
        wait(lambda:editor.source_path==str(original.resolve()))
        source_window.hide()
        results.append({"check":"native file drag/drop opens image via public editor window","passed":True})
        wait(lambda:editor.view.viewport().width()>200)
        editor.fit_view()
        assert editor.render_image().convertToFormat(QImage.Format.Format_ARGB32)==source
        # Draw with the actual existing toolbar and CanvasView, not a synthetic scene patch.
        QTest.mouseClick(editor.toolbar.rect_btn,Qt.MouseButton.LeftButton)
        editor.toolbar.color_changed.emit(QColor("#dc2626"))
        a=editor.view.mapFromScene(QPointF(50,115));b=editor.view.mapFromScene(QPointF(190,210))
        QTest.mousePress(editor.view.viewport(),Qt.MouseButton.LeftButton,pos=a)
        QTest.mouseMove(editor.view.viewport(),b)
        QTest.mouseRelease(editor.view.viewport(),Qt.MouseButton.LeftButton,pos=b)
        assert editor.canvas.undo_stack.count()>=1 and editor.has_changes()
        editor._end_edit()
        count=editor.canvas.undo_stack.index()
        QTest.keyClick(editor.view,Qt.Key.Key_Z,Qt.KeyboardModifier.ControlModifier)
        assert editor.canvas.undo_stack.index()==count-1
        QTest.keyClick(editor.view,Qt.Key.Key_Y,Qt.KeyboardModifier.ControlModifier)
        assert editor.canvas.undo_stack.index()==count
        results.append({"check":"shared annotation toolbar drawing and keyboard undo/redo","passed":True})
        annotated=editor.render_image()
        from text_recognition import recognize_async
        recognized=[]
        ocr_thread=recognize_async(annotated,lambda text,reason:recognized.append((text,reason)))
        wait(lambda:bool(recognized),seconds=40)
        assert ocr_thread.wait(10000)
        assert not recognized[0][1],recognized
        assert "EDITOR" in recognized[0][0].upper() and "123" in recognized[0][0],recognized
        (directory/"ocr-local.txt").write_text(recognized[0][0],encoding="utf-8")
        results.append({"check":"real local OCR recognizes text in the edited image","passed":True})
        item_ids={id(item) for item in editor.canvas.scene.items()}
        editor.transform("right")
        editor.crop_button.setChecked(True)
        start=editor.view.mapFromScene(QPointF(20,80));end=editor.view.mapFromScene(QPointF(590,370))
        QTest.mousePress(editor.view.viewport(),Qt.MouseButton.LeftButton,pos=start)
        QTest.mouseMove(editor.view.viewport(),end)
        QTest.mouseRelease(editor.view.viewport(),Qt.MouseButton.LeftButton,pos=end)
        assert editor.geometry_state.rotation==90 and editor.geometry_state.crop!=(0,0,640,420)
        geometry_errors=[]
        def precise():
            dialog=editor._geometry_dialog
            try:
                for name,value in {"x":20,"y":80,"width":570,"height":290,"output":145}.items():
                    widget=dialog.fields[name]
                    widget.setFocus();widget.selectAll();QTest.keyClicks(widget,str(value));QTest.keyClick(widget,Qt.Key.Key_Tab)
                assert dialog.apply_button.isEnabled()
                assert dialog.grab().save(str(directory/"geometry-dialog.png"))
                QTest.mouseClick(dialog.apply_button,Qt.MouseButton.LeftButton)
            except Exception:
                import traceback
                geometry_errors.append(traceback.format_exc());dialog.reject()
        QTimer.singleShot(100,precise)
        editor.edit_geometry()
        assert not geometry_errors,geometry_errors
        assert editor.geometry_state==ImageGeometry((20,80,570,290),90,False,False,145)
        assert item_ids=={id(item) for item in editor.canvas.scene.items()}
        expected=editor.geometry_state.apply_to_pixels(annotated.copy(20,80,570,290))
        assert editor.render_image()==expected
        results.append({"check":"rotated drag crop plus exact input retain live annotations and output pixels","size":[expected.width(),expected.height()],"passed":True})
        for mode in ("light","dark"):
            theme.set_mode(mode,persist=False);pause(.1)
            assert editor.grab().save(str(directory/f"editor-{mode}.png"))
        assert not editor.start_save(str(original))
        destination=directory/"edited.png"
        assert editor.start_save(str(destination))
        wait(lambda:editor._worker is None)
        assert QImage(str(destination)).convertToFormat(QImage.Format.Format_ARGB32)==expected.convertToFormat(QImage.Format.Format_ARGB32)
        assert not editor.has_changes()
        assert hashlib.sha256(original.read_bytes()).hexdigest()==before_file
        results.append({"check":"save source protection and exact non-destructive export","passed":True})
        # OCR must use final geometry; prove the image boundary without transmitting data.
        import text_recognition
        actual=[];previous=text_recognition.show_text_recognition
        text_recognition.show_text_recognition=lambda image,parent:actual.append(image)
        try:editor.recognize()
        finally:text_recognition.show_text_recognition=previous
        assert actual[0]==expected
        results.append({"check":"OCR receives final crop/rotation/resize pixels rather than stale source","passed":True})
        source_window.filename=destination
        source_window.started=False
        source_window.outcome=None
        source_window.show();source_window.raise_();source_window.activateWindow()
        pause(.3)
        focus_source()
        start=source_window.mapToGlobal(source_window.rect().center())
        finish=editor.view.viewport().mapToGlobal(editor.view.viewport().rect().center())
        thread=threading.Thread(target=drag_file);thread.start()
        wait(lambda:not thread.is_alive());thread.join()
        wait(lambda:source_window.started and source_window.outcome is not None)
        assert source_window.outcome==Qt.DropAction.CopyAction,(source_window.outcome,editor.status.text(),start,finish)
        wait(lambda:editor.source_path==str(destination.resolve()))
        source_window.hide()
        wait(lambda:editor.view.viewport().width()>200)
        assert editor.render_image().size()==expected.size()
        assert editor.geometry_state.rotation==0
        results.append({"check":"native drop onto existing canvas opens saved image as a fresh document","passed":True})
        (directory/"result.json").write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding="utf-8")
        print(json.dumps(results,ensure_ascii=False,indent=2))
    finally:
        from text_recognition import shutdown_recognition
        shutdown_recognition(timeout_ms=10000)
        source_window.close()
        mouse.position=old_position
        editor._force_close=True
        editor.close()
        if editor._worker is not None:wait(lambda:editor._worker is None)
        assert registry_digest()==before_registry,"Real settings changed during native acceptance"


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--run",action="store_true")
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--language",default="zh")
    parser.add_argument("--scale",type=int,default=100)
    args=parser.parse_args()
    if not args.run:parser.error("Native editor acceptance requires --run")
    args.output.mkdir(parents=True,exist_ok=True)
    os.environ["QT_QPA_PLATFORM"]="windows";os.environ["QT_ENABLE_HIGHDPI_SCALING"]="0";os.environ["QT_SCALE_FACTOR"]="1"
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
    from core.platform_utils import set_dpi_awareness
    set_dpi_awareness()
    run(args.output,args.language,args.scale)
