"""Opt-in workspaces: native confirmations, fresh-process restoration and Recycle Bin deletion."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time


def run(directory,language,scale,reopen=None):
    from PySide6.QtCore import QPoint,QPointF,QSettings,QSize,QTimer,Qt
    from PySide6.QtGui import QColor,QImage
    from PySide6.QtWidgets import QApplication,QDialogButtonBox
    from PySide6.QtTest import QTest
    from settings import get_tool_settings_manager
    app=QApplication([]);app.setQuitOnLastWindowClosed(False)
    config=get_tool_settings_manager(QSettings(str(directory/"settings.ini"),QSettings.Format.IniFormat))
    assert Path(config.qsettings.fileName()).resolve()==(directory/"settings.ini").resolve()
    from tests.native_image_editor import registry_digest
    digest=registry_digest()
    from core.logger import setup_logger
    from core.i18n import I18nManager
    from core.ui_scale import get_dialog_scale,get_ui_scale
    from core.ui_theme import get_ui_theme
    from pin.pin_manager import PinManager
    from pin.workspace import pin_state,read_workspace
    from pin.workspace_dialog import PinWorkspaceDialog
    from tests.test_editable_project import populate,pixels
    config.set_clipboard_db_path(str(directory/"unused.db"));config.set_log_enabled(False)
    config.set_log_dir(str(directory/"logs"));config.set_ocr_enabled(False)
    config.set_app_setting("language",language);config.set_app_setting("dialog_scale_percent",scale)
    setup_logger(config);I18nManager.load_language(language)
    get_dialog_scale().init(config);get_ui_scale().init(config);theme=get_ui_theme().init(config,app)
    manager=PinManager.instance();dialog=PinWorkspaceDialog(manager,config);dialog.show()
    results=[]
    def wait(predicate,seconds=20):
        deadline=time.monotonic()+seconds
        while time.monotonic()<deadline:
            app.processEvents()
            if predicate():return
            time.sleep(.01)
        raise AssertionError("Workspace acceptance timed out")
    def pause(seconds):
        start=time.monotonic();wait(lambda:time.monotonic()-start>=seconds)
    def make(color,position,size=QSize(480,360)):
        image=QImage(size,QImage.Format.Format_ARGB32);image.fill(QColor(color))
        return manager.create_pin(image,position,config_manager=config)
    errors=[]
    def answer(yes,label):
        modal=QApplication.activeModalWidget()
        try:
            assert modal is not None and modal is not dialog
            modal.grab().save(str(directory/(label+".png")))
            role=QDialogButtonBox.ButtonRole.YesRole if yes else QDialogButtonBox.ButtonRole.NoRole
            button=next(b for b in modal.button_box.buttons() if modal.button_box.buttonRole(b)==role)
            QTest.mouseClick(button,Qt.MouseButton.LeftButton)
        except Exception:
            import traceback
            errors.append(traceback.format_exc())
            if modal:modal.reject()
    try:
        if reopen:
            sentinel=make("yellow",QPoint(120,120),QSize(80,60))
            QTimer.singleShot(100,lambda:answer(True,"restore-confirm"))
            assert dialog.open_workspace(str(reopen));assert not errors,errors
            restored=manager.get_all_pins()[1:]
            assert len(restored)==3 and manager.get_all_pins()[0] is sentinel
            expected=json.loads((reopen.parent/"expected.json").read_text(encoding="utf-8"))
            for index,pin in enumerate(restored):
                actual=pin.get_current_image()
                actual.save(str(directory/f"actual-pixels-{index+1}.png"))
                assert hashlib.sha256(pixels(actual)).hexdigest()==expected[index]["pixels"],index
                state=pin_state(pin)
                for key in ("scale","opacity","topmost","border","thumbnail","thumb_size","thumb_center","text_selection"):
                    assert state[key]==expected[index]["state"][key],(index,key,state[key],expected[index]["state"][key])
                if index<2:
                    assert state["position"]==expected[index]["state"]["position"]
                    assert state["normal_rect"]==expected[index]["state"]["normal_rect"]
                else:
                    assert any(screen.availableGeometry().intersects(pin.geometry()) for screen in app.screens())
                pin.grab().save(str(directory/f"restored-pin-{index+1}.png"))
            assert restored[1]._thumbnail.active
            restored[1].toggle_thumbnail_mode()
            from canvas.items import TextItem
            text=next(i for i in restored[0].canvas.scene.items() if isinstance(i,TextItem))
            text.setPlainText("Workspace restored and editable")
            assert hashlib.sha256(pixels(restored[0].get_current_image())).hexdigest()!=expected[0]["pixels"]
            results.append({"check":"fresh process restores scales, states, thumbnails and editable annotations; offscreen pin relocated","passed":True})
            dialog.grab().save(str(directory/"restore-summary.png"))
        else:
            first=make("#ddddee",QPoint(160,180));items=populate(first.canvas)
            first.rotate_image_cw();first.flip_image_horizontal();first.scale_factor=.8;first._image_transform.apply_to_window(first)
            first.move(160,180);first._win_opacity=.75;first.setWindowOpacity(.75);first.toggle_stay_on_top()
            second=make("#1366aa",QPoint(700,240),QSize(320,240));second.scale_factor=1.25;second._image_transform.apply_to_window(second)
            second.toggle_thumbnail_mode();second.move(740,270);second._thumbnail._scene_center=QPointF(180,120);second._thumbnail.update_view()
            third=make("#339955",QPoint(12000,12000),QSize(180,120))
            ignored=make("#aa5522",QPoint(900,400),QSize(160,120))
            selected=[first,second,third]
            pause(.35)  # Let deferred pin geometry/theme work settle before the baseline.
            expected=[{"state":pin_state(pin),"pixels":hashlib.sha256(pixels(pin.get_current_image())).hexdigest()} for pin in selected]
            for index,pin in enumerate(selected):pin.get_current_image().save(str(directory/f"expected-pixels-{index+1}.png"))
            (directory/"expected.json").write_text(json.dumps(expected,indent=2),encoding="utf-8")
            dialog.refresh();dialog.name.setText("Reference workspace")
            for index in range(3):dialog.list.item(index).setCheckState(Qt.CheckState.Checked)
            assert dialog.selected_pins()==selected
            for mode in ("light","dark"):
                theme.set_mode(mode,persist=False);pause(.1);dialog.grab().save(str(directory/f"workspace-{mode}.png"))
            file=directory/"references.vpins"
            import pin.workspace_dialog as module
            chooser=module.QFileDialog.getSaveFileName
            module.QFileDialog.getSaveFileName=lambda *a,**k:(str(file),"Pin workspace (*.vpins)")
            try:
                QTimer.singleShot(100,lambda:answer(False,"save-cancel"));dialog.save_dialog()
                assert not file.exists()
                QTimer.singleShot(100,lambda:answer(True,"save-confirm"));dialog.save_dialog()
                assert not errors,errors
                wait(lambda:dialog._worker is None)
            finally:module.QFileDialog.getSaveFileName=chooser
            assert len(read_workspace(file).pins)==3 and manager.count()==4 and not ignored._is_closed
            assert all(pin_state(pin)==record["state"] for pin,record in zip(selected,expected))
            assert all(hashlib.sha256(pixels(pin.get_current_image())).hexdigest()==record["pixels"] for pin,record in zip(selected,expected))
            assert len(items)==9
            results.append({"check":"native selection and privacy prompt save only selected pins; source state and pixels unchanged","passed":True})
            child_dir=directory/"fresh-process";child_dir.mkdir()
            manager.close_all()  # explicit test fixture cleanup, not production restore behavior
            child=subprocess.run([sys.executable,str(Path(__file__).resolve()),"--run","--output",str(child_dir),"--language",language,
                                  "--scale",str(scale),"--reopen",str(file)],capture_output=True,text=True,encoding="utf-8",timeout=30,
                                  creationflags=subprocess.CREATE_NO_WINDOW)
            (directory/"fresh-process.log").write_text(child.stdout+child.stderr,encoding="utf-8")
            assert child.returncode==0,child.stdout+child.stderr
            results.append({"check":"independent-process restore, relocation and editing passed","passed":True})
            sentinel=make("yellow",QPoint(120,120),QSize(80,60))
            import zipfile
            damaged=directory/"one-missing-project.vpins"
            with zipfile.ZipFile(file) as original_archive,zipfile.ZipFile(damaged,"w") as altered:
                manifest=json.loads(original_archive.read("workspace.json"))
                missing=manifest["pins"][1]["project"]
                for member in original_archive.namelist():
                    if member!=missing:altered.writestr(member,original_archive.read(member))
            QTimer.singleShot(100,lambda:answer(True,"partial-restore-confirm"))
            assert dialog.open_workspace(str(damaged))
            assert manager.count()==3 and manager.get_all_pins()[0] is sentinel
            dialog.grab().save(str(directory/"partial-restore-summary.png"))
            assert "2" in dialog.status.text() and "1" in dialog.status.text()
            for added in list(manager.get_all_pins())[1:]:added.close_window()
            results.append({"check":"missing child project is reported by index while valid pins and existing sentinel remain","passed":True})
            trash_copy=directory/"delete-this-test-workspace.vpins";shutil.copyfile(file,trash_copy)
            QTimer.singleShot(100,lambda:answer(False,"delete-cancel"))
            assert not dialog.delete_workspace(str(trash_copy)) and trash_copy.exists()
            QTimer.singleShot(100,lambda:answer(True,"delete-confirm"))
            assert dialog.delete_workspace(str(trash_copy))
            assert not trash_copy.exists() and file.exists() and manager.get_all_pins()==[sentinel]
            results.append({"check":"explicit test copy moved to Recycle Bin, cancelled deletion and open pin preserved","passed":True})
        assert not errors,errors
        (directory/"result.json").write_text(json.dumps(results,indent=2),encoding="utf-8")
        print(json.dumps(results,indent=2))
    finally:
        if dialog._worker:
            dialog.cancel_save();wait(lambda:dialog._worker is None)
        dialog.close();manager.close_all()
        assert registry_digest()==digest,"Real configuration changed"


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--run",action="store_true")
    parser.add_argument("--output",type=Path,required=True);parser.add_argument("--language",default="zh")
    parser.add_argument("--scale",type=int,default=100);parser.add_argument("--reopen",type=Path)
    args=parser.parse_args()
    if not args.run:parser.error("Native workspace acceptance requires --run")
    args.output.mkdir(parents=True,exist_ok=True)
    os.environ["QT_QPA_PLATFORM"]="windows";os.environ["QT_ENABLE_HIGHDPI_SCALING"]="0";os.environ["QT_SCALE_FACTOR"]="1"
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
    from core.platform_utils import set_dpi_awareness
    set_dpi_awareness()
    run(args.output,args.language,args.scale,args.reopen)
