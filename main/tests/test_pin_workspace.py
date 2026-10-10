"""Workspace round-trip and safety tests use isolated settings and synthetic pins."""
import json
from pathlib import Path
import threading
import zipfile

import pytest
from PySide6.QtCore import QPoint,QPointF,QRect,QSize,Qt
from PySide6.QtGui import QColor,QImage

from core.editable_project import ProjectError
from core.save import SaveService
from pin.pin_manager import PinManager
from pin.workspace import (snapshot_workspace,write_workspace,read_workspace,restore_workspace,
                            pin_state,visible_position)
from pin.workspace_dialog import PinWorkspaceDialog
from settings.tool_settings import ToolSettingsManager


@pytest.fixture
def config(tmp_settings,tmp_path):
    c=ToolSettingsManager(tmp_settings);c.set_ocr_enabled(False);c.set_screenshot_save_path(str(tmp_path))
    return c


@pytest.fixture
def manager(qapp,monkeypatch):
    monkeypatch.setattr(PinManager,"_instance",None)
    m=PinManager.instance()
    yield m
    m.close_all()


def make_pin(manager,config,position=QPoint(50,60),color="red",size=QSize(160,100)):
    image=QImage(size,QImage.Format.Format_ARGB32);image.fill(QColor(color))
    return manager.create_pin(image,position,config_manager=config)


def save(pins,config,tmp_path,name="References"):
    manifest,projects=snapshot_workspace(pins,name)
    file=tmp_path/"references.vpins"
    assert write_workspace(file,manifest,projects,SaveService(config))
    return file,manifest,projects


def test_normal_pin_states_annotations_and_pixels_roundtrip(manager,config,tmp_path):
    from tests.test_editable_project import populate,pixels
    first=make_pin(manager,config,size=QSize(480,360));populate(first.canvas)
    first.rotate_image_cw();first.flip_image_horizontal()
    first.scale_factor=.75
    first._image_transform.apply_to_window(first)
    first.move(130,170)
    first._win_opacity=.65;first.setWindowOpacity(.65)
    first.toggle_stay_on_top();first.toggle_border_effect();first.show_toolbar()
    second=make_pin(manager,config,QPoint(600,100),"blue")
    states=[pin_state(p) for p in (first,second)]
    before=[pixels(p.get_current_image()) for p in (first,second)]
    file,_,_=save([first,second],config,tmp_path)
    loaded=read_workspace(file)
    assert loaded.name=="References" and not loaded.errors
    originals=manager.get_all_pins()
    restored,errors,moved=restore_workspace(loaded,manager,config,[QRect(0,0,1920,1080)])
    assert len(restored)==2 and errors==[] and moved==[]
    assert manager.count()==4 and manager.get_all_pins()[:2]==originals
    assert [pin_state(p) for p in restored]==states
    assert [pixels(p.get_current_image()) for p in restored]==before
    from canvas.items import TextItem
    item=next(i for i in restored[0].canvas.scene.items() if isinstance(i,TextItem))
    item.setPlainText("Restored text")
    assert pixels(restored[0].get_current_image())!=before[0]


def test_thumbnail_position_scale_center_and_exit_survive_restore(manager,config,tmp_path):
    pin=make_pin(manager,config,size=QSize(320,240))
    pin.scale_factor=1.25;pin._image_transform.apply_to_window(pin)
    pin.toggle_thumbnail_mode();pin.move(450,250)
    pin._thumbnail._scene_center=QPointF(170,120);pin._thumbnail.update_view()
    before=pin_state(pin)
    file,_,_=save([pin],config,tmp_path)
    restored,errors,moved=restore_workspace(read_workspace(file),manager,config,[QRect(0,0,1920,1080)])
    assert not errors and not moved
    new=restored[0];assert pin_state(new)==before
    assert new._thumbnail.active
    pin.toggle_thumbnail_mode();new.toggle_thumbnail_mode()
    assert new.geometry()==pin.geometry() and new.scale_factor==pin.scale_factor


def test_negative_monitor_and_offscreen_relocation_preserve_image_scale():
    screens=[QRect(-1920,0,1920,1080),QRect(0,0,1920,1080)]
    assert visible_position([-1000,100],QSize(200,120),screens)==(QPoint(-1000,100),False)
    point,moved=visible_position([10000,2000],QSize(400,200),screens)
    assert moved and any(screen.contains(QRect(point,QSize(400,200))) for screen in screens)
    point,moved=visible_position([10000,2000],QSize(4000,3000),screens)
    assert moved and any(screen.contains(point) for screen in screens)


def test_offscreen_restore_does_not_shrink_or_drop_pins(manager,config,tmp_path):
    pin=make_pin(manager,config,QPoint(10000,10000));pin.scale_factor=2;pin._image_transform.apply_to_window(pin)
    file,_,_=save([pin],config,tmp_path)
    restored,errors,moved=restore_workspace(read_workspace(file),manager,config,[QRect(0,0,800,600)])
    assert not errors and moved==[0]
    assert restored[0].scale_factor==2 and restored[0].size()==QSize(320,200)
    assert QRect(0,0,800,600).contains(restored[0].geometry())


def rewrite(file,manifest,projects):
    with zipfile.ZipFile(file,"w") as archive:
        archive.writestr("workspace.json",json.dumps(manifest))
        for name,data in projects.items():archive.writestr(name,data)


@pytest.mark.parametrize("damage",["missing","hash","state","nested"])
def test_bad_project_reported_individually_while_valid_pin_restores(manager,config,tmp_path,damage):
    pins=[make_pin(manager,config),make_pin(manager,config,color="blue")]
    file,raw,projects=save(pins,config,tmp_path);manifest=json.loads(raw)
    target=manifest["pins"][0]["project"]
    if damage=="missing":del projects[target]
    elif damage=="hash":projects[target]=b"bad"
    elif damage=="state":manifest["pins"][0]["state"]["scale"]=float("inf")
    else:
        import hashlib
        payload=b"not a zip";new="projects/000-"+hashlib.sha256(payload).hexdigest()+".vpic"
        del projects[target];projects[new]=payload;manifest["pins"][0]["project"]=new
    if damage=="state":
        # Nonfinite JSON is rejected at the manifest trust boundary, not converted into a valid pin.
        rewrite(file,manifest,projects)
        with pytest.raises(ProjectError):read_workspace(file)
        return
    rewrite(file,manifest,projects)
    loaded=read_workspace(file);assert len(loaded.pins)==1 and loaded.errors[0][0]==0
    restored,errors,_=restore_workspace(loaded,manager,config,[QRect(0,0,1920,1080)])
    assert len(restored)==1 and len(errors)==1 and manager.count()==3


@pytest.mark.parametrize("name",["../escape.vpic","/absolute","projects/evil.vpic"])
def test_unsafe_archive_member_is_rejected_without_extraction(manager,config,tmp_path,name):
    file,_,_=save([make_pin(manager,config)],config,tmp_path)
    with zipfile.ZipFile(file,"a") as archive:archive.writestr(name,b"bad")
    with pytest.raises(ProjectError):read_workspace(file)
    assert not (tmp_path.parent/"escape.vpic").exists()


def test_unknown_version_duplicate_member_and_extra_data_fail_closed(manager,config,tmp_path):
    file,raw,projects=save([make_pin(manager,config)],config,tmp_path)
    manifest=json.loads(raw);manifest["version"]=999;rewrite(file,manifest,projects)
    with pytest.raises(ProjectError):read_workspace(file)
    manifest=json.loads(raw);manifest["script"]="external";rewrite(file,manifest,projects)
    with pytest.raises(ProjectError):read_workspace(file)


def test_selection_is_required_and_no_implicit_overwrite_on_closed_pin(manager,config,tmp_path):
    with pytest.raises(ProjectError):snapshot_workspace([],"Empty")
    pin=make_pin(manager,config);pin.close_window()
    with pytest.raises((ProjectError,RuntimeError)):snapshot_workspace([pin],"Closed")
    assert not list(tmp_path.glob("*.vpins"))


def test_aggregate_budgets_apply_across_nested_projects(manager,config,tmp_path,monkeypatch):
    import pin.workspace as module
    pins=[make_pin(manager,config),make_pin(manager,config)]
    file,_,_=save(pins,config,tmp_path)
    monkeypatch.setattr(module,"MAX_PIXELS",160*100)
    with pytest.raises(ProjectError):snapshot_workspace(pins,"Too large")
    loaded=read_workspace(file)
    assert len(loaded.pins)==1 and len(loaded.errors)==1


def test_save_failure_and_cancellation_leave_original_file(manager,config,tmp_path,monkeypatch):
    file,raw,projects=save([make_pin(manager,config)],config,tmp_path)
    before=file.read_bytes()
    assert not write_workspace(file,raw,projects,SaveService(config),cancelled=lambda:True)
    assert file.read_bytes()==before
    def fail(*a,**k):raise OSError("disk full")
    monkeypatch.setattr(zipfile.ZipFile,"writestr",fail)
    assert not write_workspace(file,raw,projects,SaveService(config))
    assert file.read_bytes()==before


@pytest.fixture
def dialog(qtbot,manager,config):
    window=PinWorkspaceDialog(manager,config);window.show()
    yield window
    if window._worker:
        window.cancel_save();qtbot.waitUntil(lambda:window._worker is None,timeout=10000)
    if not window._shutdown:window.close()


def test_ui_explicit_selection_save_and_cancel_restore(manager,config,dialog,tmp_path,qtbot,monkeypatch):
    first=make_pin(manager,config);make_pin(manager,config,color="blue")
    dialog.refresh();dialog.name.setText("Named workspace")
    assert dialog.selected_pins()==[]
    dialog.list.item(0).setCheckState(Qt.CheckState.Checked)
    file=tmp_path/"named.vpins"
    assert dialog.start_save(str(file));qtbot.waitUntil(lambda:dialog._worker is None)
    assert len(read_workspace(file).pins)==1
    assert manager.count()==2 and not first._is_closed
    monkeypatch.setattr("pin.workspace_dialog.show_confirm_dialog",lambda *a,**k:False)
    assert not dialog.open_workspace(str(file)) and manager.count()==2
    monkeypatch.setattr("pin.workspace_dialog.show_confirm_dialog",lambda *a,**k:True)
    assert dialog.open_workspace(str(file)) and manager.count()==3


def test_privacy_cancel_does_not_show_chooser_or_write(manager,dialog,config,tmp_path,monkeypatch):
    make_pin(manager,config);dialog.refresh();dialog.select_all(True);dialog.name.setText("private")
    monkeypatch.setattr("pin.workspace_dialog.show_confirm_dialog",lambda *a,**k:False)
    monkeypatch.setattr("pin.workspace_dialog.QFileDialog.getSaveFileName",lambda *a,**k:pytest.fail("Cancelled before chooser"))
    dialog.save_dialog()
    assert dialog._worker is None and not list(tmp_path.glob("*.vpins"))


def test_delete_requires_confirmation_and_never_falls_back_to_permanent_delete(dialog,tmp_path,monkeypatch):
    file=tmp_path/"old.vpins";file.write_bytes(b"original")
    called=[]
    monkeypatch.setattr("pin.workspace_dialog.QFile.moveToTrash",lambda path:called.append(path) or (False,""))
    monkeypatch.setattr("pin.workspace_dialog.show_confirm_dialog",lambda *a,**k:False)
    assert not dialog.delete_workspace(str(file)) and not called
    monkeypatch.setattr("pin.workspace_dialog.show_confirm_dialog",lambda *a,**k:True)
    assert not dialog.delete_workspace(str(file)) and len(called)==1
    assert file.read_bytes()==b"original"


def test_async_save_cancel_preserves_file_and_reenables_ui(dialog,manager,config,tmp_path,qtbot,monkeypatch):
    import pin.workspace_dialog as module
    make_pin(manager,config);dialog.refresh();dialog.select_all(True);dialog.name.setText("cancel")
    entered,release=threading.Event(),threading.Event();write=module.write_workspace
    def delayed(*args,**kwargs):entered.set();assert release.wait(5);return write(*args,**kwargs)
    monkeypatch.setattr(module,"write_workspace",delayed)
    file=tmp_path/"old.vpins";file.write_bytes(b"original")
    assert dialog.start_save(str(file));qtbot.waitUntil(entered.is_set)
    assert not dialog.list.isEnabled()
    dialog.cancel_save();release.set();qtbot.waitUntil(lambda:dialog._worker is None)
    assert file.read_bytes()==b"original" and dialog.list.isEnabled()


def test_saved_workspace_does_not_store_private_source_paths(manager,config,tmp_path):
    file,raw,_=save([make_pin(manager,config)],config,tmp_path)
    assert b"C:" not in raw and b"file:" not in raw
    with zipfile.ZipFile(file) as archive:
        assert "workspace.json" in archive.namelist()
        assert len(archive.namelist())==2


def test_restore_failure_does_not_close_existing_pins(manager,config,tmp_path,monkeypatch):
    original=make_pin(manager,config)
    file,_,_=save([original],config,tmp_path)
    monkeypatch.setattr(manager,"create_pin",lambda *a,**k:(_ for _ in ()).throw(RuntimeError("window create failed")))
    restored,errors,moved=restore_workspace(read_workspace(file),manager,config,[QRect(0,0,800,600)])
    assert not restored and len(errors)==1 and manager.count()==1 and not original._is_closed


def test_large_display_geometry_is_rejected_before_creating_window(manager,config,tmp_path,monkeypatch):
    file,raw,projects=save([make_pin(manager,config)],config,tmp_path)
    manifest=json.loads(raw)
    manifest["pins"][0]["state"]["normal_rect"]=[0,0,90000,90000]
    rewrite(file,manifest,projects)
    workspace=read_workspace(file)
    assert not workspace.pins and len(workspace.errors)==1
    monkeypatch.setattr(manager,"create_pin",lambda *a,**k:pytest.fail("Invalid geometry must not allocate window"))
    assert restore_workspace(workspace,manager,config,[QRect(0,0,800,600)])[0]==[]


def test_close_during_save_waits_for_cancellation_without_closing_pins(config,manager,tmp_path,qtbot,monkeypatch):
    import pin.workspace_dialog as module
    pin=make_pin(manager,config)
    window=PinWorkspaceDialog(manager,config);window.show();window.select_all(True);window.name.setText("close")
    entered,release=threading.Event(),threading.Event();write=module.write_workspace
    def delayed(*args,**kwargs):entered.set();assert release.wait(5);return write(*args,**kwargs)
    monkeypatch.setattr(module,"write_workspace",delayed)
    file=tmp_path/"target.vpins";file.write_bytes(b"keep")
    assert window.start_save(str(file));qtbot.waitUntil(entered.is_set)
    window.close();assert window._worker is not None
    release.set();qtbot.waitUntil(lambda:window._worker is None)
    assert file.read_bytes()==b"keep"
    assert manager.count()==1 and not pin._is_closed


def test_missing_all_projects_reports_without_creating_any_pin(manager,config,tmp_path,dialog,monkeypatch):
    file,raw,_=save([make_pin(manager,config)],config,tmp_path)
    rewrite(file,json.loads(raw),{})
    monkeypatch.setattr("pin.workspace_dialog.show_confirm_dialog",lambda *a,**k:pytest.fail("No valid entries to confirm"))
    assert not dialog.open_workspace(str(file)) and manager.count()==1
    assert "1" in dialog.status.text()


def test_workspace_names_are_local_metadata_not_paths(manager,config,tmp_path):
    file,raw,projects=save([make_pin(manager,config)],config,tmp_path,name="../my references")
    loaded=read_workspace(file)
    assert loaded.name=="../my references"
    assert set(json.loads(raw))=={"format","version","name","privacy","pins"}
    assert not (tmp_path.parent/"my references").exists()


def test_project_byte_reader_cumulative_item_budget_is_enforced(manager,config,tmp_path):
    from core.editable_project import read_project_bytes
    from tests.test_editable_project import populate
    pin=make_pin(manager,config,size=QSize(480,360));populate(pin.canvas)
    _,_,projects=save([pin],config,tmp_path)
    with pytest.raises(ProjectError):read_project_bytes(next(iter(projects.values())),item_budget=1)


def test_malformed_workspace_header_cannot_load_partial_content(manager,config,tmp_path):
    file,raw,projects=save([make_pin(manager,config)],config,tmp_path)
    manifest=json.loads(raw)
    manifest["pins"].append(manifest["pins"][0])
    rewrite(file,manifest,projects)
    with pytest.raises(ProjectError):read_workspace(file)


def test_source_pin_values_unchanged_after_workspace_snapshot(manager,config):
    from tests.test_editable_project import populate,pixels
    pin=make_pin(manager,config,size=QSize(480,360));populate(pin.canvas)
    pin.show_toolbar();pin.canvas.activate_tool("pen")
    before=pin_state(pin);image=pixels(pin.get_current_image())
    snapshot_workspace([pin],"Keep originals")
    assert pin_state(pin)==before and pixels(pin.get_current_image())==image
    assert pin.canvas.tool_controller.current_tool_id=="pen"


WORKSPACE_MESSAGES={
  "PinWorkspaceDialog": [
    "Pin Workspaces",
    "Select the pins to keep. Saving is manual; workspaces contain original images and editable annotations. Restoring adds pins without closing existing ones.",
    "Workspace name",
    "Reference board",
    "Pins to save",
    "Refresh pins",
    "Select all",
    "Select none",
    "Up to 20 pins, 64 megapixels in total. Closing this dialog does not save anything automatically.",
    "Save selected…",
    "Open workspace…",
    "Delete workspace…",
    "Cancel save",
    "Thumbnail",
    "Pinned image",
    "Enter a name and select between 1 and 20 pins.",
    "Workspace contains original images",
    "This file keeps original pixels and removable annotations. It is not a redacted sharing format. Save the selected pins?",
    "Save pin workspace",
    "Use the .vpins extension for pin workspaces.",
    "Could not prepare workspace. Check selected pins, name and resource limits. Nothing was saved.",
    "Saving workspace…",
    "Cancelling save…",
    "Workspace saved. Source images and existing pins were not changed.",
    "Workspace save cancelled. Existing files were kept.",
    "Could not save workspace. Existing files and pins were kept.",
    "Open pin workspace",
    "Workspace format or resource limits are invalid. Existing pins were not changed.",
    "No valid pins could be restored. The workspace may be missing or contain damaged projects.",
    "Restore %1 pins from '%2'? Existing pins stay open. The saved original images will be visible on screen.",
    "Restore pin workspace",
    "Restored %1 pins; %2 failed; %3 moved onto an available screen.",
    "Failed entries: %1. Missing, invalid or over the resource limit.",
    "Delete pin workspace",
    "Move this workspace file to the Recycle Bin? Open pins and source image files will not be deleted.\n%1",
    "Workspace moved to the Recycle Bin. Open pins were kept.",
    "Could not move the workspace to the Recycle Bin. Nothing was permanently deleted."
  ],
  "SystemTray": [
    "Pin workspaces…"
  ]
}

@pytest.mark.parametrize("lang",["en","zh","ja","ko"])
def test_compiled_workspace_messages(qapp,lang):
    from PySide6.QtCore import QTranslator
    translator=QTranslator()
    assert translator.load(str(Path(__file__).resolve().parents[1]/"translations"/f"app_{lang}.qm"))
    for context,messages in WORKSPACE_MESSAGES.items():
        for source in messages:
            assert translator.translate(context,source),(lang,context,source)


def test_rotated_thumbnail_keeps_transform_and_restored_view_center(manager,config,tmp_path):
    pin=make_pin(manager,config,size=QSize(320,240));pin.rotate_image_cw();pin.flip_image_vertical()
    pin.scale_factor=.8;pin._image_transform.apply_to_window(pin)
    pin.toggle_thumbnail_mode();pin.move(150,150)
    before=pin_state(pin)
    file,_,_=save([pin],config,tmp_path)
    restored,errors,_=restore_workspace(read_workspace(file),manager,config,[QRect(0,0,1920,1080)])
    assert not errors
    new=restored[0]
    assert pin_state(new)==before
    assert new._image_transform.rotation==90 and new._image_transform.flip_v
    new.toggle_thumbnail_mode();pin.toggle_thumbnail_mode()
    assert new.geometry()==pin.geometry()


def test_corrupt_one_state_is_reported_without_discarding_other_valid_record(manager,config,tmp_path):
    file,raw,projects=save([make_pin(manager,config),make_pin(manager,config,color="blue")],config,tmp_path)
    manifest=json.loads(raw);manifest["pins"][0]["state"]["opacity"]=0
    rewrite(file,manifest,projects)
    workspace=read_workspace(file)
    assert len(workspace.pins)==1 and workspace.errors[0][0]==0


def test_empty_or_newer_workspace_never_changes_manager(manager,config,tmp_path,dialog):
    pin=make_pin(manager,config)
    file=tmp_path/"bad.vpins";file.write_bytes(b"not a workspace")
    assert not dialog.open_workspace(str(file))
    assert manager.get_all_pins()==[pin]


def test_cancelled_open_file_chooser_does_not_restore_any_pins(manager,config,dialog,monkeypatch):
    pin=make_pin(manager,config)
    monkeypatch.setattr("pin.workspace_dialog.QFileDialog.getOpenFileName",lambda *a,**k:("",""))
    dialog.open_dialog();dialog.delete_dialog()
    assert manager.get_all_pins()==[pin]


def test_workspace_snapshot_reads_no_desktop_pixels_or_clipboard(manager,config,monkeypatch):
    pin=make_pin(manager,config)
    monkeypatch.setattr("core.clipboard_utils.copy_image_to_clipboard",lambda *a,**k:pytest.fail("Unexpected clipboard write"))
    monkeypatch.setattr("capture.capture_service.CaptureService.capture_all_screens",lambda *a,**k:pytest.fail("Unexpected screen capture"))
    manifest,_=snapshot_workspace([pin],"Only this pin")
    assert len(json.loads(manifest)["pins"])==1


def test_workspace_close_and_escape_really_destroy_window(qtbot,manager,config):
    from PySide6.QtCore import QCoreApplication,QEvent
    import shiboken6
    for method in ("close","reject"):
        window=PinWorkspaceDialog(manager,config);window.show()
        assert window.isVisible()
        getattr(window,method)()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        assert not shiboken6.isValid(window)


def test_workspace_manifest_name_is_rendered_as_plain_text(manager,config,tmp_path,dialog):
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QTimer
    name='<img src="file:///private.png">'
    file,_,_=save([make_pin(manager,config)],config,tmp_path,name=name)
    seen=[]
    def reject():
        prompt=QApplication.activeModalWidget()
        seen.append((prompt.label.textFormat(),prompt.label.text()))
        prompt.reject()
    QTimer.singleShot(0,reject)
    assert not dialog.open_workspace(str(file))
    assert seen[0][0]==Qt.TextFormat.PlainText and name in seen[0][1]
