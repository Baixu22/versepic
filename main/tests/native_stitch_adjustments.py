"""Opt-in native scroll capture: actual wheel events, checkpoint undo and seam review."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def target(directory):
    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtGui import QPainter, QColor
    from PySide6.QtWidgets import QApplication, QWidget
    app = QApplication([])
    class View(QWidget):
        def __init__(self):
            super().__init__()
            self.offset = 0
            self.axis = "vertical"
            self.sequence = 0
            self.setWindowTitle("Synthetic scroll-capture acceptance")
            self.setGeometry(80,100,420,320)
        def paintEvent(self, event):
            p = QPainter(self)
            length = self.height() if self.axis == "vertical" else self.width()
            for i in range(length):
                row = (i+self.offset)//4
                color = QColor((row*37)%256, (row*91+40)%256, (row*13+90)%256)
                if self.axis == "vertical":
                    p.fillRect(0,i,self.width(),1,color)
                else:
                    p.fillRect(i,0,1,self.height(),color)
            p.fillRect(0,0,self.width(),24,QColor("#334155"))
            p.fillRect(self.width()-12,0,12,self.height(),QColor("#94a3b8"))
            p.setPen(Qt.GlobalColor.white)
            p.drawText(8,18,"Synthetic fixed header")
            p.end()
        def wheelEvent(self,event):
            self.offset = max(0, self.offset-round(event.angleDelta().y()/120)*40)
            self.update()
            QTimer.singleShot(50,self.report)
            event.accept()
        def report(self):
            point = self.mapToGlobal(self.rect().topLeft())
            data = {"hwnd":int(self.winId()),"pid":os.getpid(),"x":point.x(),"y":point.y(),
                    "width":self.width(),"height":self.height(),"offset":self.offset,"sequence":self.sequence}
            temp=directory/"state.tmp"
            temp.write_text(json.dumps(data),encoding="utf-8")
            try:
                os.replace(temp,directory/"state.json")
            except PermissionError:
                QTimer.singleShot(30,self.report)
        def poll(self):
            try:
                command=json.loads((directory/"command.json").read_text(encoding="utf-8"))
            except (OSError,json.JSONDecodeError):
                return
            if command["sequence"]==self.sequence:
                return
            self.sequence=command["sequence"]
            if command.get("quit"):
                app.quit()
                return
            self.axis=command.get("axis",self.axis)
            self.offset=command.get("offset",self.offset)
            self.update()
            QTimer.singleShot(80,self.report)
    view=View()
    view.show()
    timer=QTimer(view)
    timer.timeout.connect(view.poll)
    timer.start(30)
    QTimer.singleShot(100,view.report)
    app.exec()


def run(directory, language, scale):
    from PySide6.QtCore import QSettings, QRect, QTimer, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from PIL import Image
    import win32api, win32gui, win32process
    from pynput.mouse import Controller as Mouse
    from pynput.keyboard import Controller as Keyboard, Key
    from core.i18n import I18nManager
    from core.logger import setup_logger
    from core.ui_scale import get_dialog_scale, get_ui_scale
    from core.ui_theme import get_ui_theme
    from settings import get_tool_settings_manager
    from stitch.session import join_images
    app=QApplication([])
    app.setQuitOnLastWindowClosed(False)
    config=get_tool_settings_manager(QSettings(str(directory/"settings.ini"),QSettings.Format.IniFormat))
    assert Path(config.qsettings.fileName()).resolve()==(directory/"settings.ini").resolve(), "Refuse to write non-isolated settings"
    from stitch.scroll_window import ScrollCaptureWindow
    config.set_clipboard_db_path(str(directory/"unused-clipboard.db"))
    config.set_log_enabled(False)
    config.set_log_dir(str(directory/"logs"))
    config.set_screenshot_save_path(str(directory/"output"))
    config.set_screenshot_format("PNG")
    config.set_app_setting("language",language)
    config.set_app_setting("dialog_scale_percent",scale)
    setup_logger(config)
    I18nManager.load_language(language)
    get_dialog_scale().init(config)
    get_ui_scale().init(config)
    theme=get_ui_theme().init(config,app)
    (directory/"state.json").write_text("{}",encoding="utf-8")
    (directory/"command.json").write_text(json.dumps({"sequence":0}),encoding="utf-8")
    process=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),"--target","--output",str(directory)],creationflags=subprocess.CREATE_NO_WINDOW)
    previous=win32gui.GetForegroundWindow()
    old_mouse=win32api.GetCursorPos()
    sequence=0
    window=None
    results=[]
    def state():
        try:
            return json.loads((directory/"state.json").read_text(encoding="utf-8"))
        except (OSError,json.JSONDecodeError):
            return {}
    def wait(predicate,seconds=10):
        deadline=time.monotonic()+seconds
        while time.monotonic()<deadline:
            app.processEvents()
            if predicate():
                return
            time.sleep(0.01)
        raise AssertionError("Native scroll acceptance timed out")
    def pause(seconds):
        started=time.monotonic()
        wait(lambda: time.monotonic()-started>=seconds)
    def command(**fields):
        nonlocal sequence
        sequence+=1
        (directory/"command.json").write_text(json.dumps({"sequence":sequence,**fields}),encoding="utf-8")
        wait(lambda:state().get("sequence")==sequence)
    def focus():
        keyboard=Keyboard()
        keyboard.press(Key.alt);keyboard.release(Key.alt)
        win32gui.SetForegroundWindow(state()["hwnd"])
        wait(lambda:win32process.GetWindowThreadProcessId(win32gui.GetForegroundWindow())[1]==state()["pid"])
    try:
        wait(lambda:bool(state().get("hwnd")))
        for axis,reverse in (("vertical",False),("vertical",True),("horizontal",False),("horizontal",True)):
            command(axis=axis,offset=240 if reverse else 0)
            focus()
            info=state()
            config.set_long_stitch_ignore_top_pixels(0)
            config.set_app_setting("long_stitch_ignore_right_pixels",0)
            window=ScrollCaptureWindow(QRect(info["x"],info["y"],info["width"],info["height"]),config_manager=config)
            # Set initial axis before the first frame; do not enable unrelated horizontal keyboard remapping.
            window.scroll_direction=axis
            window._stitch_session.set_axis(axis)
            window.toolbar.update_direction(axis)
            window.show()
            wait(lambda window=window:len(window.screenshots)==1)
            before=window.stitched_result.copy()
            errors=[]
            def ignore(window=window, axis=axis, reverse=reverse, errors=errors):
                dialog=window._adjustment_dialog
                try:
                    assert dialog is not None and QApplication.activeModalWidget() is dialog
                    dialog.top.setValue(24)
                    dialog.right.setValue(12)
                    assert dialog.grab().save(str(directory/f"ignore-{axis}-{reverse}.png"))
                    QTest.mouseClick(dialog.apply,Qt.MouseButton.LeftButton)
                except Exception:
                    import traceback
                    errors.append(traceback.format_exc());dialog.reject()
            QTimer.singleShot(100,ignore)
            QTest.mouseClick(window.toolbar.ignore_btn,Qt.MouseButton.LeftButton)
            assert not errors,errors
            assert window.stitched_result.tobytes()==before.tobytes()
            if axis=="vertical" and not reverse:
                focus()
                win32api.SetCursorPos((info["x"]+150,info["y"]+180))
                Mouse().scroll(0,-3)
                wait(lambda:state()["offset"]==120)
                wait(lambda window=window:len(window.screenshots)==2)
            else:
                command(offset=120)
                QTest.mouseClick(window.toolbar.manual_capture_btn,Qt.MouseButton.LeftButton)
                wait(lambda window=window:len(window.screenshots)==2)
            correct_overlap=window._stitch_session.state.overlap
            direction="up" if reverse else "down"
            frame=window._stitch_session.state.last_frame
            expected=join_images(before,frame,axis,direction,(frame.height if axis=="vertical" else frame.width)-120)
            assert window.stitched_result.size==expected.size
            assert window.stitched_result.tobytes()==expected.tobytes()
            assert window.scroll_locked_direction==direction
            original=window.stitched_result.copy()
            def edit(amount, accept=True, window=window, axis=axis, reverse=reverse, errors=errors):
                def operate():
                    dialog=window._adjustment_dialog
                    try:
                        assert not window.capture_timer.isActive()
                        dialog.overlap.setValue(amount)
                        theme.set_mode("dark" if reverse else "light",persist=False)
                        assert dialog.grab().save(str(directory/f"seam-{axis}-{reverse}.png"))
                        if accept:
                            QTest.mouseClick(dialog.apply,Qt.MouseButton.LeftButton)
                        else:
                            QTest.keyClick(dialog,Qt.Key.Key_Escape)
                    except Exception:
                        import traceback
                        errors.append(traceback.format_exc());dialog.reject()
                QTimer.singleShot(100,operate)
                QTest.mouseClick(window.toolbar.repair_btn,Qt.MouseButton.LeftButton)
                assert not errors,errors
            edit(correct_overlap-8,False)
            assert window.stitched_result.tobytes()==original.tobytes()
            edit(correct_overlap-8)
            assert window.stitched_result.size!=original.size
            edit(correct_overlap)
            assert window.stitched_result.tobytes()==original.tobytes()
            QTest.mouseClick(window.toolbar.undo_btn,Qt.MouseButton.LeftButton)
            assert len(window.screenshots)==1 and window.scroll_locked_direction is None
            assert window.stitched_result.tobytes()==before.tobytes()
            QTest.mouseClick(window.toolbar.manual_capture_btn,Qt.MouseButton.LeftButton)
            assert len(window.screenshots)==2
            assert window.stitched_result.tobytes()==original.tobytes()
            command(offset=0 if reverse else 240)
            QTest.mouseClick(window.toolbar.manual_capture_btn,Qt.MouseButton.LeftButton)
            assert len(window.screenshots)==3
            result_file=directory/f"result-{axis}-{reverse}.png"
            window.stitched_result.save(result_file)
            assert window._stitch_session.retained_bytes<=96*1024*1024
            results.append({"check":axis+(" reverse" if reverse else " forward"),"overlap":correct_overlap,
                            "size":list(window.stitched_result.size),"frames":3,"passed":True})
            # Exercise production finish->save, but never write the personal system clipboard.
            copied=[]
            window._copy_to_clipboard=lambda window=window, copied=copied:copied.append(window.stitched_result.copy())
            window.set_save_directory(str(directory/f"saved-{axis}-{reverse}"))
            QTest.mouseClick(window.toolbar.finish_btn,Qt.MouseButton.LeftButton)
            def saved(axis=axis, reverse=reverse):
                files=list((directory/f"saved-{axis}-{reverse}").glob("*.png"))
                return bool(files and files[0].stat().st_size>0)
            wait(saved)
            with Image.open(next((directory/f"saved-{axis}-{reverse}").glob("*.png"))) as output:
                assert output.convert("RGB").tobytes()==copied[0].tobytes()
            assert window._stitch_session.state.result is None and not window._stitch_session.checkpoints
            window=None
        (directory/"result.json").write_text(json.dumps(results,indent=2),encoding="utf-8")
        print(json.dumps(results,indent=2))
    finally:
        if window is not None:
            window._on_cancel()
        (directory/"command.json").write_text(json.dumps({"sequence":sequence+1,"quit":True}),encoding="utf-8")
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.terminate();process.wait(timeout=5)
        win32api.SetCursorPos(old_mouse)
        if win32gui.IsWindow(previous):
            try:
                win32gui.SetForegroundWindow(previous)
            except Exception:
                pass


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--run",action="store_true")
    parser.add_argument("--target",action="store_true",help=argparse.SUPPRESS)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--language",default="zh")
    parser.add_argument("--scale",type=int,default=100)
    args=parser.parse_args()
    if not(args.run or args.target):parser.error("Native acceptance requires --run")
    args.output.mkdir(parents=True,exist_ok=True)
    os.environ["QT_QPA_PLATFORM"]="windows"
    os.environ["QT_ENABLE_HIGHDPI_SCALING"]="0"
    os.environ["QT_SCALE_FACTOR"]="1"
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
    from core.platform_utils import set_dpi_awareness
    set_dpi_awareness()
    if args.target:target(args.output)
    else:run(args.output,args.language,args.scale)
