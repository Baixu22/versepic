"""Opt-in editable project acceptance with process-independent restore and native controls."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def run(directory,language,scale,reopen=None):
    from PySide6.QtCore import QPoint,QPointF,QRectF,QSettings,QTimer,Qt
    from PySide6.QtGui import QColor,QImage
    from PySide6.QtWidgets import QApplication,QDialogButtonBox
    from PySide6.QtTest import QTest
    from settings import get_tool_settings_manager
    app=QApplication([]);app.setQuitOnLastWindowClosed(False)
    config=get_tool_settings_manager(QSettings(str(directory/"settings.ini"),QSettings.Format.IniFormat))
    assert Path(config.qsettings.fileName()).resolve()==(directory/"settings.ini").resolve()
    from tests.native_image_editor import registry_digest
    registry_before=registry_digest()
    from core.logger import setup_logger
    from core.i18n import I18nManager
    from core.ui_theme import get_ui_theme
    from core.ui_scale import get_dialog_scale,get_ui_scale
    from core.image_document import ImageGeometry
    from core.editable_project import read_project
    from ui.image_editor import ImageEditor
    from tests.test_editable_project import populate,pixels
    config.set_clipboard_db_path(str(directory/"unused.db"))
    config.set_log_enabled(False);config.set_log_dir(str(directory/"logs"))
    config.set_ocr_enabled(False);config.set_screenshot_save_enabled(False)
    config.set_app_setting("language",language);config.set_app_setting("dialog_scale_percent",scale)
    setup_logger(config);I18nManager.load_language(language)
    get_dialog_scale().init(config);get_ui_scale().init(config)
    theme=get_ui_theme().init(config,app)
    editor=ImageEditor(config);editor.show()
    results=[]
    def wait(predicate,seconds=15):
        deadline=time.monotonic()+seconds
        while time.monotonic()<deadline:
            app.processEvents()
            if predicate():return
            time.sleep(.01)
        raise AssertionError("Native project verification timed out")
    def pause(seconds):
        start=time.monotonic();wait(lambda:time.monotonic()-start>=seconds)
    try:
        if reopen:
            assert editor.open_file(str(reopen))
            actual=editor.render_image()
            expected=QImage(str(directory.parent/"before-project.png"))
            actual.save(str(directory/"actual-reopened.png"))
            assert pixels(actual)==pixels(expected)
            from canvas.items import TextItem,NumberItem
            text=next(i for i in editor.canvas.scene.items() if isinstance(i,TextItem))
            number=next(i for i in editor.canvas.scene.items() if isinstance(i,NumberItem))
            text.setPlainText("Restored and edited")
            number.number=42;number.setPos(number.pos()+QPointF(10,0))
            assert pixels(editor.render_image())!=pixels(actual)
            assert editor.start_project_save(str(directory/"resaved.vpic"))
            wait(lambda:editor._worker is None)
            restored=read_project(directory/"resaved.vpic")
            assert any(isinstance(i,TextItem) and i.toPlainText()=="Restored and edited" for i in restored.items)
            assert editor.grab().save(str(directory/"restored-editor.png"))
            print(json.dumps({"fresh_process_roundtrip":True,"editable_after_reopen":True}))
            return
        source=QImage(480,360,QImage.Format.Format_ARGB32);source.fill(QColor("#ddddee"))
        filename=directory/"source.png";source.save(str(filename))
        digest=hashlib.sha256(filename.read_bytes()).hexdigest()
        assert editor.open_file(str(filename))
        populate(editor.canvas)
        state=ImageGeometry((5,5,450,330),90,True,False,165)
        assert editor.set_geometry(state,"Geometry")
        before=editor.render_image();before.save(str(directory/"before-project.png"))
        project_file=directory/"editable.vpic"
        # Exercise the actual privacy confirmation; isolate only the platform file chooser path.
        import ui.image_editor as module
        chooser=module.QFileDialog.getSaveFileName
        module.QFileDialog.getSaveFileName=lambda *a,**k:(str(project_file),"VersePic project (*.vpic)")
        errors=[]
        def confirm(accept=True):
            dialog=QApplication.activeModalWidget()
            try:
                assert dialog is not None and dialog.windowTitle()==editor.tr("Editable project contains original pixels")
                dialog.grab().save(str(directory/("privacy-confirm.png" if accept else "privacy-cancel.png")))
                box=dialog.button_box
                role=QDialogButtonBox.ButtonRole.YesRole if accept else QDialogButtonBox.ButtonRole.NoRole
                button=next(b for b in box.buttons() if box.buttonRole(b)==role)
                QTest.mouseClick(button,Qt.MouseButton.LeftButton)
            except Exception:
                import traceback
                errors.append(traceback.format_exc())
                if dialog:dialog.reject()
        try:
            QTimer.singleShot(100,lambda:confirm(False));editor.save_project_dialog()
            assert not project_file.exists() and editor._worker is None
            QTimer.singleShot(100,confirm);editor.save_project_dialog()
            assert not errors,errors
            wait(lambda:editor._worker is None)
        finally:module.QFileDialog.getSaveFileName=chooser
        assert project_file.exists() and not editor.has_changes()
        results.append({"check":"native project privacy prompt cancels without writing and explicitly accepts save","passed":True})
        assert editor.open_file(str(project_file))
        assert pixels(editor.render_image())==pixels(before)
        assert editor.geometry_state==state
        for mode in ("light","dark"):
            theme.set_mode(mode,persist=False);pause(.1)
            editor.grab().save(str(directory/f"project-{mode}.png"))
        child_dir=directory/"fresh-process";child_dir.mkdir()
        child=subprocess.run([sys.executable,str(Path(__file__).resolve()),"--run","--output",str(child_dir),
                              "--language",language,"--scale",str(scale),"--reopen",str(project_file)],
                             capture_output=True,text=True,encoding="utf-8",timeout=30,creationflags=subprocess.CREATE_NO_WINDOW)
        (directory/"fresh-process.log").write_text(child.stdout+child.stderr,encoding="utf-8")
        assert child.returncode==0,child.stderr
        results.append({"check":"fresh process restores all annotation types, identical pixels, and edits/resaves restored text and number","passed":True})
        assert hashlib.sha256(filename.read_bytes()).hexdigest()==digest
        results.append({"check":"original source file remains byte-identical","passed":True})
        # Use real screenshot menu transfer; ensure only selected pixels enter the new editor.
        from ui.screenshot_window import ScreenshotWindow
        config.set_smart_selection(False)
        screenshot=ScreenshotWindow(config,prefetched_image=source,prefetched_rect=QRectF(-100,-60,480,360))
        screenshot.scene.selection_model.initialize_confirmed_rect(QRectF(-60,-20,200,150))
        screenshot.toolbar.more_btn.click();pause(.05)
        assert screenshot.toolbar.editable_project_btn.isVisible()
        QTest.mouseClick(screenshot.toolbar.editable_project_btn,Qt.MouseButton.LeftButton)
        transferred=getattr(app,"_file_image_editor",None)
        assert transferred is not None and transferred.canvas.base_size.width()==200
        assert transferred.canvas.base_size.height()==150 and not screenshot._session_active
        screenshot.full_destroy();transferred._force_close=True;transferred.close();pause(.1)
        results.append({"check":"actual screenshot menu transfers only the chosen region into a new editable project","passed":True})
        from pin.pin_manager import PinManager
        pin=PinManager.instance().create_pin(source,QPoint(100,100),config_manager=config)
        pin.rotate_image_cw();pin.flip_image_horizontal()
        pin.open_editable_project()
        transferred=getattr(app,"_file_image_editor",None)
        assert transferred.geometry_state.rotation==90 and transferred.geometry_state.flip_h
        assert pixels(transferred.render_image())==pixels(pin.get_current_image())
        pin.close_window();transferred._force_close=True;transferred.close();pause(.1)
        results.append({"check":"live pin transfer preserves image rotation and flip in project editor","passed":True})
        (directory/"result.json").write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding="utf-8")
        print(json.dumps(results,ensure_ascii=False,indent=2))
    finally:
        editor._force_close=True
        editor.close()
        if editor._worker:wait(lambda:editor._worker is None)
        assert registry_digest()==registry_before,"Real settings were modified"


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--run",action="store_true")
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--language",default="zh")
    parser.add_argument("--scale",type=int,default=100)
    parser.add_argument("--reopen",type=Path)
    args=parser.parse_args()
    if not args.run:parser.error("Native project acceptance requires --run")
    args.output.mkdir(parents=True,exist_ok=True)
    os.environ["QT_QPA_PLATFORM"]="windows";os.environ["QT_ENABLE_HIGHDPI_SCALING"]="0";os.environ["QT_SCALE_FACTOR"]="1"
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
    from core.platform_utils import set_dpi_awareness
    set_dpi_awareness()
    run(args.output,args.language,args.scale,args.reopen)
