"""File editor tests use isolated config and synthetic source images only."""
import hashlib
import os
import threading
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QMimeData, QPoint, QPointF, QRectF, QSize, QUrl, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QImage, QPen, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import QGraphicsRectItem, QDialog
from PIL import Image

from core.image_document import ImageGeometry, load_editor_image, same_file
from settings.tool_settings import ToolSettingsManager
from ui.image_editor import ImageEditor, GeometryEditor


@pytest.fixture
def source(tmp_path):
    picture=QImage(160,100,QImage.Format.Format_ARGB32)
    picture.fill(QColor("#174873"))
    for x,y,color in ((0,0,"red"),(159,0,"green"),(0,99,"blue"),(159,99,"yellow")):
        picture.setPixelColor(x,y,QColor(color))
    file=tmp_path/"source.png"
    assert picture.save(str(file))
    return file


@pytest.fixture
def editor(qtbot,tmp_settings):
    config=ToolSettingsManager(tmp_settings)
    config.set_ocr_enabled(False)
    window=ImageEditor(config)
    window.show()
    yield window
    if window._worker is not None:
        window.cancel_saving()
        qtbot.waitUntil(lambda:window._worker is None,timeout=10000)
    window._force_close=True
    window.close()


def test_open_and_render_uses_existing_pin_canvas_without_changing_source(editor,source):
    from pin.pin_canvas import PinCanvas
    digest=hashlib.sha256(source.read_bytes()).hexdigest()
    assert editor.open_file(str(source))
    assert isinstance(editor.canvas,PinCanvas)
    assert editor.render_image().convertToFormat(QImage.Format.Format_ARGB32)==QImage(str(source))
    assert not editor.has_changes()
    assert hashlib.sha256(source.read_bytes()).hexdigest()==digest


@pytest.mark.parametrize("rotation",[0,90,180,270])
@pytest.mark.parametrize("flip_h,flip_v",[(False,False),(True,False),(False,True),(True,True)])
def test_geometry_matches_independent_pillow_transform(source,rotation,flip_h,flip_v):
    image=QImage(str(source)).copy(10,5,80,60)
    # Put asymmetric markers inside the cropped image, not just on its outside border.
    image.setPixelColor(2,3,QColor("red"))
    state=ImageGeometry((10,5,80,60),rotation,flip_h,flip_v)
    state.validate(QSize(160,100))
    result=state.apply_to_pixels(image)
    rgba=image.convertToFormat(QImage.Format.Format_RGBA8888)
    data=bytes(rgba.constBits())
    expected=Image.frombytes("RGBA",(80,60),data).rotate(-rotation,expand=True)
    if flip_h: expected=expected.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    if flip_v: expected=expected.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    actual=result.convertToFormat(QImage.Format.Format_RGBA8888)
    assert result.size()==QSize(*expected.size)
    assert bytes(actual.constBits())==expected.tobytes()


@pytest.mark.parametrize("crop,width",[((-1,0,10,10),0),((0,0,0,10),0),((0,0,170,10),0),((0,0,1,100),16384)])
def test_geometry_rejects_outside_and_excessive_output(crop,width):
    with pytest.raises(ValueError):ImageGeometry(crop,output_width=width).validate(QSize(160,100))


def add_rect(editor):
    from canvas.undo import AddItemCommand
    item=QGraphicsRectItem(QRectF(20,20,30,20))
    item.setBrush(QBrush(QColor("red")))
    item.setPen(QPen(Qt.PenStyle.NoPen))
    item.setZValue(20)
    editor.canvas.undo_stack.push_command(AddItemCommand(editor.canvas.scene,item))
    return item


def test_crop_resize_and_rotation_keep_live_annotation_objects_and_undo(editor,source):
    editor.open_file(str(source))
    item=add_rect(editor)
    state=ImageGeometry((10,10,80,60),rotation=90,output_width=120)
    assert editor.set_geometry(state,"Crop and rotate")
    result=editor.render_image()
    assert result.size()==QSize(120,160)
    assert item.scene() is editor.canvas.scene and item.rect()==QRectF(20,20,30,20)
    assert any(result.pixelColor(x,y).red()>240 for y in range(result.height()) for x in range(result.width()))
    editor.canvas.undo_stack.undo()
    assert editor.geometry_state.crop==(0,0,160,100)
    assert editor.render_image().pixelColor(25,25).name()=="#ff0000"
    editor.canvas.undo_stack.undo()
    assert editor.render_image().pixelColor(25,25).name()=="#174873"
    assert not editor.has_changes()
    editor.canvas.undo_stack.redo()
    editor.canvas.undo_stack.redo()
    assert editor.geometry_state==state


def test_failed_decode_and_cancelled_replace_keep_current_document(editor,source,tmp_path,monkeypatch):
    editor.open_file(str(source));add_rect(editor)
    canvas=editor.canvas
    invalid=tmp_path/"bad.png";invalid.write_bytes(b"invalid")
    assert not editor.open_file(str(invalid)) and editor.canvas is canvas
    other=tmp_path/"other.png";assert QImage(str(source)).save(str(other))
    monkeypatch.setattr("ui.image_editor.show_confirm_dialog",lambda *a:False)
    assert not editor.open_file(str(other)) and editor.canvas is canvas
    assert editor.has_changes()


def test_canvas_allocation_failure_does_not_discard_previous_edits(editor,source,tmp_path,monkeypatch):
    editor.open_file(str(source));add_rect(editor)
    canvas=editor.canvas
    monkeypatch.setattr("ui.image_editor.show_confirm_dialog",lambda *a:True)
    monkeypatch.setattr("ui.image_editor.PinCanvas",Mock(side_effect=MemoryError()))
    assert not editor.open_file(str(source))
    assert editor.canvas is canvas and editor.has_changes()


def test_source_and_hardlink_alias_cannot_be_overwritten(editor,source,tmp_path):
    editor.open_file(str(source));add_rect(editor)
    before=source.read_bytes()
    assert not editor.start_save(str(source))
    alias=tmp_path/"hardlink.png";os.link(source,alias)
    assert same_file(str(source),str(alias))
    assert not editor.start_save(str(alias))
    assert source.read_bytes()==before


@pytest.mark.parametrize("extension",["png","jpg","webp","bmp","pdf"])
def test_save_uses_explicit_editor_dimensions_and_atomic_export(editor,source,tmp_path,qtbot,extension):
    editor.config_manager.set_app_setting("screenshot_size_mode","half")
    editor.open_file(str(source));add_rect(editor)
    editor.set_geometry(ImageGeometry((10,10,80,60),output_width=40),"Crop")
    destination=tmp_path/("edited."+extension)
    assert editor.start_save(str(destination))
    qtbot.waitUntil(lambda:editor._worker is None,timeout=10000)
    assert destination.stat().st_size>0 and not editor.has_changes()
    if extension!="pdf":
        with Image.open(destination) as picture:assert picture.size==(40,30)
    else:
        from PySide6.QtPdf import QPdfDocument
        document=QPdfDocument();assert document.load(str(destination))==QPdfDocument.Error.None_
        assert document.pageCount()==1;document.close()
    assert QImage(str(source)).size()==QSize(160,100)


def test_save_failure_preserves_edits_and_existing_target(editor,source,tmp_path,qtbot,monkeypatch):
    from core.save import SaveService
    editor.open_file(str(source));add_rect(editor)
    destination=tmp_path/"old.png";destination.write_bytes(b"original")
    monkeypatch.setattr(SaveService,"_save_qimage_to_path",lambda *a,**k:False)
    assert editor.start_save(str(destination))
    qtbot.waitUntil(lambda:editor._worker is None)
    assert editor.has_changes() and destination.read_bytes()==b"original"
    assert editor.view.isEnabled()


def test_cancel_save_keeps_existing_file_and_refuses_new_edits(editor,source,tmp_path,qtbot,monkeypatch):
    from core.save import SaveService
    entered,release=threading.Event(),threading.Event()
    original=SaveService._save_qimage_to_path
    def delayed(self,*args,**kwargs):
        entered.set();assert release.wait(5)
        return original(self,*args,**kwargs)
    monkeypatch.setattr(SaveService,"_save_qimage_to_path",delayed)
    editor.open_file(str(source));add_rect(editor)
    destination=tmp_path/"old.png";destination.write_bytes(b"keep")
    assert editor.start_save(str(destination));qtbot.waitUntil(entered.is_set)
    before=editor.geometry_state
    editor.transform("right")
    assert editor.geometry_state==before and not editor.open_file(str(source))
    editor.cancel_saving();release.set()
    qtbot.waitUntil(lambda:editor._worker is None)
    assert destination.read_bytes()==b"keep" and editor.has_changes()


def test_same_undo_index_on_new_branch_is_still_dirty(editor,source,tmp_path,qtbot):
    editor.open_file(str(source));add_rect(editor)
    assert editor.start_save(str(tmp_path/"first.png"));qtbot.waitUntil(lambda:editor._worker is None)
    assert not editor.has_changes()
    editor.canvas.undo_stack.undo()
    add_rect(editor)
    assert editor.canvas.undo_stack.index()==1
    assert editor.has_changes()


def test_text_changes_without_outer_undo_index_are_detected(editor,source,tmp_path,qtbot):
    from canvas.items.text_item import TextItem
    from canvas.undo import AddItemCommand
    editor.open_file(str(source))
    item=TextItem("original",QPointF(5,5),QFont("Arial",12),QColor("white"))
    editor.canvas.undo_stack.push_command(AddItemCommand(editor.canvas.scene,item))
    assert editor.start_save(str(tmp_path/"text.png"));qtbot.waitUntil(lambda:editor._worker is None)
    assert not editor.has_changes()
    item.setPlainText("updated")
    assert editor.has_changes()


def test_real_annotation_toolbar_draws_on_shared_canvas_and_undo_works(editor,source,qtbot):
    editor.open_file(str(source))
    qtbot.waitUntil(lambda:editor.view.viewport().width()>200)
    editor.fit_view()
    editor.toolbar.select_tool("rect")
    start=editor.view.mapFromScene(QPointF(20,20));end=editor.view.mapFromScene(QPointF(60,50))
    qtbot.mousePress(editor.view.viewport(),Qt.MouseButton.LeftButton,pos=start)
    qtbot.mouseMove(editor.view.viewport(),end)
    qtbot.mouseRelease(editor.view.viewport(),Qt.MouseButton.LeftButton,pos=end)
    assert editor.canvas.undo_stack.count()>=1
    assert editor.has_changes()
    qtbot.keyClick(editor.view,Qt.Key.Key_Z,Qt.KeyboardModifier.ControlModifier)
    assert editor.canvas.undo_stack.index()==0


def test_crop_drag_after_rotation_maps_back_to_original_coordinates(editor,source,qtbot):
    editor.open_file(str(source));editor.transform("right")
    qtbot.waitUntil(lambda:editor.view.viewport().width()>200)
    editor.fit_view()
    editor.crop_button.setChecked(True)
    start=editor.view.mapFromScene(QPointF(20,10));end=editor.view.mapFromScene(QPointF(100,70))
    qtbot.mousePress(editor.view.viewport(),Qt.MouseButton.LeftButton,pos=start)
    qtbot.mouseMove(editor.view.viewport(),end)
    qtbot.mouseRelease(editor.view.viewport(),Qt.MouseButton.LeftButton,pos=end)
    x,y,w,h=editor.geometry_state.crop
    assert abs(x-20)<=1 and abs(y-10)<=1 and abs(w-80)<=2 and abs(h-60)<=2
    assert editor.geometry_state.rotation==90
    assert not editor.crop_button.isChecked()


def test_numeric_geometry_validation_keeps_selection_until_apply(editor,source,qtbot):
    editor.open_file(str(source))
    dialog=GeometryEditor(editor.geometry_state,editor.canvas.base_size,editor)
    qtbot.addWidget(dialog)
    dialog.fields["x"].setValue(150)
    assert not dialog.apply_button.isEnabled()
    dialog.accept();assert dialog.result()!=QDialog.DialogCode.Accepted
    assert editor.geometry_state.crop==(0,0,160,100)
    dialog.fields["width"].setValue(10)
    dialog.fields["output"].setValue(20)
    dialog.accept();assert dialog.result()==QDialog.DialogCode.Accepted
    assert dialog.state().output_size()==QSize(20,200)


def test_drop_one_local_image_only(editor,source):
    mime=QMimeData();mime.setUrls([QUrl.fromLocalFile(str(source))])
    event=QDragEnterEvent(QPoint(20,20),Qt.DropAction.CopyAction,mime,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier)
    editor.dragEnterEvent(event);assert event.isAccepted()
    drop=QDropEvent(QPointF(20,20),Qt.DropAction.CopyAction,mime,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier)
    editor.dropEvent(drop);assert drop.isAccepted() and editor.source_path==str(source.resolve())
    mime.setUrls([QUrl("https://example.com/a.png")]);assert editor._drop_path(mime) is None
    mime.setUrls([QUrl.fromLocalFile(str(source)),QUrl.fromLocalFile(str(source))]);assert editor._drop_path(mime) is None


def test_ocr_receives_final_transformed_image_not_stale_source(editor,source,monkeypatch):
    editor.open_file(str(source));editor.set_geometry(ImageGeometry((10,10,80,60),90,output_width=30),"Crop")
    captured=[]
    monkeypatch.setattr("text_recognition.show_text_recognition",lambda im,parent:captured.append(im))
    editor.recognize()
    assert captured[0].size()==QSize(30,40)


def test_unsupported_or_oversized_file_does_not_open(tmp_path):
    file=tmp_path/"fake.svg";file.write_text("<svg/>")
    with pytest.raises(ValueError):load_editor_image(str(file))
    big=tmp_path/"big.png"
    with big.open("wb") as stream:stream.truncate(64*1024*1024+1)
    with pytest.raises(ValueError):load_editor_image(str(big))


def test_exif_orientation_is_applied_before_geometry(source,tmp_path):
    original=Image.new("RGB",(100,60),"red")
    exif=Image.Exif();exif[274]=6
    file=tmp_path/"rotated.jpg";original.save(file,exif=exif)
    picture,_=load_editor_image(str(file))
    assert picture.size()==QSize(60,100)


def test_close_during_save_waits_and_preserves_dirty_document_on_cancel(editor,source,tmp_path,qtbot,monkeypatch):
    from core.save import SaveService
    entered,release=threading.Event(),threading.Event()
    original=SaveService._save_qimage_to_path
    def slow(self,*args,**kwargs):
        entered.set();assert release.wait(5)
        return original(self,*args,**kwargs)
    monkeypatch.setattr(SaveService,"_save_qimage_to_path",slow)
    editor.open_file(str(source));add_rect(editor)
    destination=tmp_path/"old.png";destination.write_bytes(b"old")
    assert editor.start_save(str(destination));qtbot.waitUntil(entered.is_set)
    monkeypatch.setattr("ui.image_editor.show_confirm_dialog",lambda *a:False)
    editor.close()
    assert editor._worker is not None and editor.isVisible()
    release.set();qtbot.waitUntil(lambda:editor._worker is None)
    assert editor.isVisible() and editor.has_changes()
    assert destination.read_bytes()==b"old"


def test_shutdown_with_queued_save_completion_does_not_touch_disposed_canvas(editor,source,tmp_path,qtbot):
    editor.open_file(str(source));add_rect(editor)
    assert editor.start_save(str(tmp_path/"saved.png"))
    assert editor._worker.wait(5000)
    editor.shutdown()
    qtbot.waitUntil(lambda:editor._worker is None)
    assert editor.canvas is None and editor.view is None and editor.toolbar is None
    editor.shutdown()  # idempotent


def test_switching_annotation_tool_exits_crop_mode(editor,source):
    editor.open_file(str(source))
    editor.crop_button.setChecked(True)
    editor.toolbar.select_tool("pen")
    assert not editor.crop_button.isChecked()
    assert editor.canvas.tool_controller.current_tool_id=="pen"


def test_view_allocation_failure_keeps_old_canvas(editor,source,monkeypatch):
    editor.open_file(str(source));add_rect(editor)
    before=editor.canvas
    monkeypatch.setattr("ui.image_editor.show_confirm_dialog",lambda *a:True)
    monkeypatch.setattr("ui.image_editor.EditorView",Mock(side_effect=MemoryError()))
    assert not editor.open_file(str(source))
    assert editor.canvas is before and editor.has_changes()


def test_numerical_crop_dialog_changes_do_not_apply_on_cancel(editor,source,monkeypatch):
    editor.open_file(str(source));before=editor.geometry_state
    def cancel(dialog):
        dialog.fields["width"].setValue(40)
        return QDialog.DialogCode.Rejected
    monkeypatch.setattr(GeometryEditor,"exec",cancel)
    editor.edit_geometry()
    assert editor.geometry_state==before and not editor.has_changes()


def test_ocr_and_clipboard_both_receive_final_geometry(editor,source,monkeypatch):
    editor.open_file(str(source));add_rect(editor)
    editor.set_geometry(ImageGeometry((10,10,80,60),90,True,False,30),"Geometry")
    ocr=[];copied=[]
    monkeypatch.setattr("text_recognition.show_text_recognition",lambda image,parent:ocr.append(image))
    monkeypatch.setattr("core.clipboard_utils.copy_image_to_clipboard",lambda image:copied.append(image))
    editor.copy_to_clipboard();editor.recognize()
    assert ocr[0]==copied[0]
    assert ocr[0].size()==QSize(30,40)


def test_small_source_still_has_one_pixel_crop_and_export(editor,tmp_path):
    image=QImage(2,2,QImage.Format.Format_ARGB32);image.fill(QColor("red"))
    file=tmp_path/"tiny.png";image.save(str(file))
    assert editor.open_file(str(file))
    assert editor.set_geometry(ImageGeometry((1,1,1,1)),"Crop")
    assert editor.render_image().size()==QSize(1,1)


def test_repeated_replace_disposes_old_canvas_and_keeps_one_view(editor,source,qtbot):
    import shiboken6
    from ui.image_editor import EditorView
    from PySide6.QtCore import QCoreApplication,QEvent
    previous=[]
    for _ in range(4):
        if editor.view:previous.append(editor.view)
        assert editor.open_file(str(source))
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    assert all(not shiboken6.isValid(view) for view in previous)
    assert len(editor.findChildren(EditorView))==1


EDITOR_MESSAGES = {
  "GeometryEditor": [
    "Crop and Resize",
    "Crop coordinates refer to the original image. Rotation and flipping preserve editable annotations. Output width 0 keeps the cropped image size.",
    "X",
    "Y",
    "Crop width",
    "Crop height",
    "Output width (0 = original)",
    "Cancel",
    "Apply",
    "Output: %1 × %2 px",
    "Crop or output dimensions are outside the image limits."
  ],
  "ImageEditor": [
    "Crop",
    "Crop or output dimensions are outside the image limits.",
    "Image Editor",
    "Crop by dragging",
    "Fit",
    "Open or drop one PNG, JPEG, BMP or WebP image. The source file is never overwritten.",
    "Cancel save",
    "Unsaved image",
    "Discard the unsaved edits? The source image will stay unchanged.",
    "Open image",
    "Open image…",
    "Save as…",
    "Recognize text",
    "Crop / resize…",
    "Rotate left",
    "Rotate right",
    "Flip horizontal",
    "Flip vertical",
    "Could not open image. Use one supported local image within 32 megapixels and 64 MiB.",
    "Could not allocate the editor canvas. Existing edits were kept.",
    "Output: %1 × %2 px · Cropping preserves hidden source pixels only in this session.",
    "Transform image",
    "Crop and resize",
    "Save edited image",
    "Choose a different file. The source image cannot be overwritten.",
    "Choose PNG, JPEG, WebP, BMP or PDF for the output.",
    "Could not render this image. Reduce the output dimensions.",
    "Saving…",
    "Cancelling save…",
    "Edited image saved. Source file unchanged.",
    "Save cancelled. Edits are still available.",
    "Save failed. Edits and the existing file were kept.",
    "Edited image copied."
  ],
  "SystemTray": [
    "Open image editor…"
  ]
}

@pytest.mark.parametrize("lang",["en","zh","ja","ko"])
def test_compiled_editor_messages(qapp,lang):
    from pathlib import Path
    from PySide6.QtCore import QTranslator
    tr=QTranslator()
    assert tr.load(str(Path(__file__).resolve().parents[1]/"translations"/f"app_{lang}.qm"))
    for context,messages in EDITOR_MESSAGES.items():
        for source in messages:
            assert tr.translate(context,source),(lang,context,source)


def test_click_outside_crop_cannot_edit_hidden_annotations(editor,source,qtbot):
    editor.open_file(str(source))
    qtbot.waitUntil(lambda:editor.view.viewport().width()>200)
    editor.set_geometry(ImageGeometry((20,20,80,60)),"Crop")
    editor.zoom.setCurrentIndex(editor.zoom.findData(1.0))
    editor.toolbar.select_tool("rect")
    before=editor.canvas.undo_stack.index()
    start=editor.view.mapFromScene(QPointF(0,0));end=editor.view.mapFromScene(QPointF(10,10))
    qtbot.mousePress(editor.view.viewport(),Qt.MouseButton.LeftButton,pos=start)
    qtbot.mouseMove(editor.view.viewport(),end)
    qtbot.mouseRelease(editor.view.viewport(),Qt.MouseButton.LeftButton,pos=end)
    assert editor.canvas.undo_stack.index()==before


def test_cancelled_file_dialogs_do_not_change_document(editor,source,monkeypatch):
    editor.open_file(str(source));add_rect(editor)
    canvas=editor.canvas;state=editor.geometry_state
    monkeypatch.setattr("ui.image_editor.QFileDialog.getOpenFileName",lambda *a,**k:("",""))
    monkeypatch.setattr("ui.image_editor.QFileDialog.getSaveFileName",lambda *a,**k:("",""))
    editor.open_dialog();editor.save_image()
    assert editor.canvas is canvas and editor.geometry_state==state and editor.has_changes()
    assert editor._worker is None


def test_save_dialog_adds_selected_extension_and_calls_real_writer(editor,source,tmp_path,qtbot,monkeypatch):
    editor.open_file(str(source));add_rect(editor)
    target=tmp_path/"named"
    monkeypatch.setattr("ui.image_editor.QFileDialog.getSaveFileName",lambda *a,**k:(str(target),"WebP (*.webp)"))
    editor.save_image()
    qtbot.waitUntil(lambda:editor._worker is None)
    assert QImage(str(target)+".webp").size()==QSize(160,100)


def test_geometry_dialog_theme_updates_labels(editor,source,qtbot):
    from core.ui_theme import get_ui_theme
    editor.open_file(str(source))
    dialog=GeometryEditor(editor.geometry_state,editor.canvas.base_size,editor)
    qtbot.addWidget(dialog)
    theme=get_ui_theme();mode=theme.mode
    try:
        for value in ("dark","light"):
            theme.set_mode(value,persist=False)
            assert theme.tokens.window in dialog.styleSheet()
    finally:
        theme.set_mode(mode,persist=False)


@pytest.mark.parametrize("kwargs",[{"rotation":90.0},{"rotation":True},{"flip_h":1},{"flip_v":"false"},{"output_width":True}])
def test_geometry_rejects_noncanonical_types(kwargs):
    with pytest.raises(ValueError):ImageGeometry((0,0,80,60),**kwargs).validate(QSize(160,100))
