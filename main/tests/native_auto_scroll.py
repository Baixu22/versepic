"""Explicit native automatic-scroll acceptance with isolated settings and synthetic targets."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def target(directory, web=False):
    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QPainter, QColor
    from PySide6.QtWidgets import QApplication, QWidget, QScrollArea
    app=QApplication([])
    if web:
        return web_target(app,directory)
    class Content(QWidget):
        axis="vertical"
        def paintEvent(self,event):
            p=QPainter(self)
            limit=self.height() if self.axis=="vertical" else self.width()
            for position in range(0,limit,4):
                i=position//4
                color=QColor((i*37)%256,(i*91+40)%256,(i*13+90)%256)
                if self.axis=="vertical":p.fillRect(0,position,self.width(),4,color)
                else:p.fillRect(position,0,4,self.height(),color)
            p.end()
    scroll=QScrollArea()
    scroll.setWindowTitle("Synthetic native auto-scroll target")
    content=Content()
    content.resize(390,800)
    scroll.setWidget(content)
    scroll.setGeometry(90,100,420,330)
    scroll.show()
    sequence=[0]
    def report():
        point=scroll.viewport().mapToGlobal(scroll.viewport().rect().topLeft())
        state={"hwnd":int(scroll.winId()),"pid":os.getpid(),"x":point.x(),"y":point.y(),
               "width":scroll.viewport().width(),"height":scroll.viewport().height(),"sequence":sequence[0],
               "offset":scroll.verticalScrollBar().value() if content.axis=="vertical" else scroll.horizontalScrollBar().value(),
               "maximum":scroll.verticalScrollBar().maximum() if content.axis=="vertical" else scroll.horizontalScrollBar().maximum()}
        temp=directory/"state.tmp"
        temp.write_text(json.dumps(state),encoding="utf-8")
        try:os.replace(temp,directory/"state.json")
        except PermissionError:pass
    def poll():
        try:command=json.loads((directory/"command.json").read_text(encoding="utf-8"))
        except (OSError,json.JSONDecodeError):command={"sequence":sequence[0]}
        if command["sequence"]!=sequence[0]:
            sequence[0]=command["sequence"]
            if command.get("quit"):app.quit();return
            content.axis=command.get("axis","vertical")
            if content.axis=="vertical":content.resize(390,1800)
            else:content.resize(1800,280)
            content.update()
            scroll.horizontalScrollBar().setValue(command.get("offset",0))
            scroll.verticalScrollBar().setValue(command.get("offset",0))
        report()
    timer=QTimer(scroll)
    timer.timeout.connect(poll)
    timer.start(50)
    app.exec()


def web_target(app,directory):
    from PySide6.QtCore import QTimer
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtWebEngineCore import QWebEnginePage,QWebEngineProfile
    view=QWebEngineView()
    profile=QWebEngineProfile(view)  # unnamed profile is off-the-record; no user browser data
    page=QWebEnginePage(profile,view)
    view.setPage(page)
    view.setWindowTitle("Synthetic local web automatic-scroll target")
    view.setGeometry(90,100,420,330)
    sequence=[0]
    view.setHtml('<!doctype html><html><head><style>html,body{margin:0;padding:0;scroll-behavior:auto}canvas{display:block}</style></head><body><canvas id="content"></canvas></body></html>')
    view.show()
    loaded=[False]
    view.loadFinished.connect(lambda ok:loaded.__setitem__(0,ok))
    def report(data):
        try:data=json.loads(data)
        except (ValueError,TypeError):return
        if not isinstance(data,dict):return
        point=view.mapToGlobal(view.rect().topLeft())
        data.update(hwnd=int(view.winId()),pid=os.getpid(),x=point.x(),y=point.y(),width=view.width(),height=view.height(),sequence=sequence[0])
        temp=directory/"state.tmp"
        temp.write_text(json.dumps(data),encoding="utf-8")
        try:os.replace(temp,directory/"state.json")
        except PermissionError:pass
    def poll():
        if not loaded[0]:return
        try:command=json.loads((directory/"command.json").read_text(encoding="utf-8"))
        except (OSError,json.JSONDecodeError):command={"sequence":sequence[0]}
        if command["sequence"]!=sequence[0]:
            sequence[0]=command["sequence"]
            if command.get("quit"):app.quit();return
            horizontal=command.get("axis","vertical")=="horizontal"
            offset=int(command.get("offset",0))
            script = "window.axis="+json.dumps("horizontal" if horizontal else "vertical")+"; const c=document.getElementById('content'); c.width="+str(1800 if horizontal else 390)+";c.height="+str(280 if horizontal else 1800)+"; const ctx=c.getContext('2d'); for(let i=0;i<450;i++){ctx.fillStyle='rgb('+((i*37)%256)+','+((i*91+40)%256)+','+((i*13+90)%256)+')';"+("ctx.fillRect(i*4,0,4,c.height);" if horizontal else "ctx.fillRect(0,i*4,c.width,4);")+"} window.scrollTo("+(str(offset)+",0" if horizontal else "0,"+str(offset))+");"
            page.runJavaScript("(()=>{"+script+"})()")
        page.runJavaScript('JSON.stringify({dpr:devicePixelRatio,innerHeight:innerHeight,innerWidth:innerWidth,offset:window.axis==="horizontal"?scrollX:scrollY,maximum:window.axis==="horizontal"?document.documentElement.scrollWidth-innerWidth:document.documentElement.scrollHeight-innerHeight})',report)
    timer=QTimer(view);timer.timeout.connect(poll);timer.start(80)
    app.exec()
    view.setPage(QWebEnginePage(view))
    page.deleteLater()
    app.processEvents()


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


def run(directory,language,scale,web=False):
    from PySide6.QtCore import QSettings, QRect, QTimer, Qt
    from PySide6.QtGui import QImage
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
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
    from stitch.scroll_window import ScrollCaptureWindow
    from stitch.auto_scroll import AutoScrollOptions
    import win32api,win32gui,win32process
    from pynput.keyboard import Controller,Key
    config.set_clipboard_db_path(str(directory/"unused.db"))
    config.set_log_enabled(False)
    config.set_log_dir(str(directory/"logs"))
    config.set_long_stitch_ignore_top_pixels(0)
    config.set_app_setting("long_stitch_ignore_right_pixels",0)
    config.set_app_setting("language",language)
    config.set_app_setting("dialog_scale_percent",scale)
    setup_logger(config)
    I18nManager.load_language(language)
    get_dialog_scale().init(config);get_ui_scale().init(config)
    theme=get_ui_theme().init(config,app)
    (directory/"state.json").write_text("{}",encoding="utf-8")
    (directory/"command.json").write_text(json.dumps({"sequence":0}),encoding="utf-8")
    target_log=open(directory/"target.log","w",encoding="utf-8")
    child=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),"--target","--output",str(directory)]+(["--web"] if web else []),creationflags=subprocess.CREATE_NO_WINDOW,stdout=target_log,stderr=target_log)
    sequence=0
    window=None
    keyboard=Controller()
    previous=win32gui.GetForegroundWindow()
    pointer=win32api.GetCursorPos()
    results=[]
    def state():
        try:return json.loads((directory/"state.json").read_text(encoding="utf-8"))
        except (OSError,json.JSONDecodeError):return {}
    def wait(predicate,seconds=15):
        deadline=time.monotonic()+seconds
        while time.monotonic()<deadline:
            app.processEvents()
            if predicate():return
            time.sleep(0.01)
        raise AssertionError("Native automatic-scroll condition timed out")
    def pause(seconds):
        start=time.monotonic();wait(lambda:time.monotonic()-start>=seconds,seconds+1)
    def focus():
        keyboard.press(Key.alt);keyboard.release(Key.alt)
        win32gui.SetForegroundWindow(state()["hwnd"])
        wait(lambda:win32process.GetWindowThreadProcessId(win32gui.GetForegroundWindow())[1]==state()["pid"])
        info=state()
        win32api.SetCursorPos((info["x"]+100,info["y"]+100))
    def command(**fields):
        nonlocal sequence
        sequence+=1
        (directory/"command.json").write_text(json.dumps({"sequence":sequence,**fields}),encoding="utf-8")
        wait(lambda:state().get("sequence")==sequence)
        pause(.15)
    def open_window(axis="vertical",offset=0):
        command(axis=axis,offset=offset)
        focus();info=state()
        result=ScrollCaptureWindow(QRect(info["x"],info["y"],min(380,info["width"]),min(260,info["height"])),config_manager=config)
        result.scroll_direction=axis;result._stitch_session.set_axis(axis);result.toolbar.update_direction(axis)
        result.show();wait(lambda:len(result.screenshots)==1)
        return result
    try:
        wait(lambda:bool(state().get("hwnd")))
        for axis,reverse in (("vertical",False),("vertical",True),("horizontal",False),("horizontal",True)):
            window=open_window(axis,800 if reverse else 0)
            start_offset=state()["offset"]
            initial_frame=window.stitched_result.copy()
            captured=[]
            append=window._append_frame
            def record(frame,append=append,captured=captured):
                captured.append((state()["offset"],frame.copy()))
                return append(frame)
            window._append_frame=record
            errors=[]
            def choose(window=window,reverse=reverse,axis=axis,errors=errors):
                dialog=window._adjustment_dialog
                try:
                    dialog.direction.setCurrentIndex(1 if reverse else 0)
                    dialog.inputs["max_steps"].setValue(3)
                    dialog.inputs["interval_ms"].setValue(350)
                    theme.set_mode("dark" if reverse else "light",persist=False)
                    assert dialog.grab().save(str(directory/f"options-{axis}-{reverse}.png"))
                    QTest.mouseClick(dialog.start,Qt.MouseButton.LeftButton)
                except Exception:
                    import traceback
                    errors.append(traceback.format_exc());dialog.reject()
            QTimer.singleShot(100,choose)
            QTest.mouseClick(window.toolbar.auto_btn,Qt.MouseButton.LeftButton)
            assert not errors,errors
            assert window._auto_scroll.active
            focus()
            wait(lambda window=window:not window._auto_scroll.active)
            if window._auto_scroll.steps!=3:
                window.stitched_result.save(directory/"failed-baseline.png")
                if window._stitch_session.pending is not None:
                    window._stitch_session.pending.save(directory/"failed-new-frame.png")
            assert window._auto_scroll.steps==3, window.toolbar.auto_status.text()
            assert len(window.screenshots)==4,window.toolbar.auto_status.text()
            assert window.toolbar.grab().save(str(directory/f"stopped-{axis}-{reverse}.png"))
            pause(.15)
            end_offset=state()["offset"]
            result=window.stitched_result
            original_length=window.capture_rect.height() if axis=="vertical" else window.capture_rect.width()
            result_length=result.height if axis=="vertical" else result.width
            assert result_length==original_length+abs(end_offset-start_offset)
            if web:
                # Chromium at fractional deviceScale interpolates boundary colors. Compare
                # against its actual captured pixels, using independent DOM offsets for joins.
                from PIL import Image
                expected_image=initial_frame
                previous_offset=start_offset
                for offset,frame in captured:
                    shift=abs(offset-previous_offset)
                    if not shift:continue
                    width=expected_image.width+(shift if axis=="horizontal" else 0)
                    height=expected_image.height+(shift if axis=="vertical" else 0)
                    merged=Image.new("RGB",(width,height))
                    if axis=="vertical":
                        piece=frame.crop((0,0,frame.width,shift)) if reverse else frame.crop((0,frame.height-shift,frame.width,frame.height))
                        merged.paste(expected_image,(0,shift if reverse else 0))
                        merged.paste(piece,(0,0 if reverse else expected_image.height))
                    else:
                        piece=frame.crop((0,0,shift,frame.height)) if reverse else frame.crop((frame.width-shift,0,frame.width,frame.height))
                        merged.paste(expected_image,(shift if reverse else 0,0))
                        merged.paste(piece,(0 if reverse else expected_image.width,0))
                    expected_image=merged
                    previous_offset=offset
                assert result.size==expected_image.size
                assert result.tobytes()==expected_image.tobytes(),"Web result differs from DOM-offset reconstruction"
            else:
                first_offset=min(start_offset,end_offset)
                for pixel in range(result_length):
                    band=(first_offset+pixel)//4
                    expected=((band*37)%256,(band*91+40)%256,(band*13+90)%256)
                    actual=result.getpixel((100,pixel) if axis=="vertical" else (pixel,100))
                    assert max(abs(a-b) for a,b in zip(actual,expected))<=1,(axis,reverse,pixel,actual,expected)
            output=directory/f"auto-{axis}-{reverse}.png"
            window.stitched_result.save(output)
            assert QImage(str(output)).width()>0
            results.append({"check":axis+(" reverse" if reverse else " forward"),"steps":3,"frames":4,"passed":True})
            window._on_cancel();window=None
        window=open_window()
        window._auto_scroll.start(AutoScrollOptions(max_steps=100,interval_ms=300,timeout_seconds=60))
        focus();wait(lambda:window._auto_scroll.steps>=1)
        keyboard.press(Key.esc);keyboard.release(Key.esc)
        wait(lambda:not window._auto_scroll.active)
        count=window._auto_scroll.steps
        pause(.5)
        assert window._auto_scroll.steps==count and window.stitched_result is not None
        results.append({"check":"global Esc cancels before further messages", "passed":True})
        window._on_cancel();window=None
        window=open_window()
        window._auto_scroll.start(AutoScrollOptions(max_steps=100,interval_ms=300))
        focus();wait(lambda:window._auto_scroll.steps>=1)
        window.toolbar.activateWindow();window.toolbar.raise_()
        wait(lambda:not window._auto_scroll.active)
        count=window._auto_scroll.steps
        pause(.5)
        assert window._auto_scroll.steps==count
        results.append({"check":"foreground switch stops without scrolling another target","passed":True})
        window._on_cancel();window=None
        window=open_window(offset=100000)
        window._auto_scroll.start(AutoScrollOptions(max_steps=10,interval_ms=300))
        focus();wait(lambda:not window._auto_scroll.active)
        assert window._auto_scroll.steps==1 and len(window.screenshots)==1,window.toolbar.auto_status.text()
        results.append({"check":"end-of-page unchanged frame stops after one addressed message","passed":True})
        (directory/"result.json").write_text(json.dumps(results,indent=2),encoding="utf-8")
        print(json.dumps(results,indent=2))
    finally:
        if window is not None:window._on_cancel()
        (directory/"command.json").write_text(json.dumps({"sequence":sequence+1,"quit":True}),encoding="utf-8")
        try:child.wait(timeout=5)
        except subprocess.TimeoutExpired:child.terminate();child.wait(timeout=5)
        target_log.close()
        win32api.SetCursorPos(pointer)
        if win32gui.IsWindow(previous):
            try:win32gui.SetForegroundWindow(previous)
            except Exception:pass
        assert registry_digest()==before_registry,"Real settings changed during native verification"


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--run",action="store_true")
    parser.add_argument("--target",action="store_true",help=argparse.SUPPRESS)
    parser.add_argument("--web",action="store_true",help="Use an isolated Chromium-rendered local page instead of a Qt scroll area")
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--language",default="zh")
    parser.add_argument("--scale",type=int,default=100)
    args=parser.parse_args()
    if not(args.run or args.target):parser.error("Native verification requires --run")
    args.output.mkdir(parents=True,exist_ok=True)
    os.environ["QT_QPA_PLATFORM"]="windows";os.environ["QT_ENABLE_HIGHDPI_SCALING"]="0";os.environ["QT_SCALE_FACTOR"]="1"
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
    from core.platform_utils import set_dpi_awareness
    set_dpi_awareness()
    if args.target:target(args.output,args.web)
    else:run(args.output,args.language,args.scale,args.web)
