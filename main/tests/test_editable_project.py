"""Round-trip all existing annotations without executing code or extracting archives."""
import json
import zipfile

import pytest
from PySide6.QtCore import QPointF,QRectF,Qt
from PySide6.QtGui import QColor,QFont,QImage,QPainterPath,QPen,QBrush,QTransform,QTextCursor
from PySide6.QtWidgets import QWidget

from core.editable_project import snapshot_project,read_project,write_project,ProjectError,load_path
from core.image_document import ImageGeometry
from core.save import SaveService
from core.export import ExportService
from pin.pin_canvas import PinCanvas


def pixels(image):
    converted=image.convertToFormat(QImage.Format.Format_RGBA8888)
    return bytes(converted.constBits())


@pytest.fixture
def canvas(qtbot):
    parent=QWidget();qtbot.addWidget(parent)
    parent.toolbar=None;parent.view=None;parent._is_editing=False
    image=QImage(480,360,QImage.Format.Format_ARGB32);image.fill(QColor("#ddddee"))
    canvas=PinCanvas(parent,image.size(),image)
    yield canvas
    canvas.cleanup()


def populate(canvas):
    from canvas.items import StrokeItem,RectItem,EllipseItem,ArrowItem,NumberItem,TextItem,MosaicItem,SpotlightItem,SpotlightCurtain,MagnifyCalloutItem
    path=QPainterPath(QPointF(12,15));path.lineTo(70,40);path.cubicTo(85,70,100,20,130,60)
    pen=QPen(QColor("#e04433"),5,Qt.PenStyle.DashLine,Qt.PenCapStyle.RoundCap,Qt.PenJoinStyle.RoundJoin)
    stroke=StrokeItem(path,pen,False)
    highlight=StrokeItem(path,QPen(QColor(255,230,0,100),18),True);highlight.setPos(0,40)
    rect=RectItem(QRectF(180,20,75,50),pen,8);rect.setBrush(QBrush(QColor("#8044ccaa")))
    ellipse=EllipseItem(QRectF(290,20,75,50),pen);ellipse.setBrush(QBrush(QColor("#8044aaff")))
    arrow=ArrowItem(QPointF(30,160),QPointF(160,180),QPen(QColor("#ff33aa"),8),"line_double")
    arrow.set_control_point(QPointF(70,100))
    number=NumberItem(7,QPointF(230,155),20,QColor("red"),"hollow_all");number.number_order=5
    font=QFont("Arial");font.setPointSizeF(17);font.setItalic(True)
    text=TextItem("First line\n中文 text",QPointF(280,130),font,QColor("#123456"))
    text.setTextWidth(150);text.set_outline(True,QColor("white"),0.07);text.set_shadow(True,QColor("#99000000"))
    text.has_background=True;text.background_color=QColor("#9966ccff")
    p=QPainterPath();p.addRect(QRectF(20,250,90,45))
    background=canvas.scene.background
    mosaic=MosaicItem(p,16,8,background.reduced_image(8),canvas.scene.sceneRect(),True,False)
    spot=SpotlightItem(QRectF(165,230,100,60),10)
    magnify=MagnifyCalloutItem(QRectF(40,40,24,16),QRectF(0,0,48,32),QPen(QColor("#2266cc"),3))
    magnify.setPos(QPointF(300,250))
    items=[stroke,highlight,rect,ellipse,arrow,number,text,mosaic,spot,magnify]
    for item in items:canvas.scene.addItem(item)
    SpotlightCurtain.of(canvas.scene).setOpacity(0.35)
    rect.setTransformOriginPoint(QPointF(200,40));rect.setRotation(12);rect.setScale(0.9);rect.setOpacity(0.8)
    ellipse.setTransform(QTransform().shear(.1,.05));ellipse.setPos(2,3)
    from tools.number import NumberTool
    NumberTool.set_next_number(canvas.scene,20)
    return items


def roundtrip(canvas,tmp_path):
    geometry=ImageGeometry((5,5,450,330),90,True,False,165)
    manifest,assets=snapshot_project(canvas.scene,geometry)
    file=tmp_path/"example.vpic"
    assert write_project(file,manifest,assets,SaveService())
    restored=read_project(file)
    return file,restored,manifest,assets


def test_all_annotation_types_roundtrip_pixel_exact_and_remain_editable(canvas,qtbot,tmp_path):
    from tools.number import NumberTool
    from canvas.items import TextItem,NumberItem,SpotlightCurtain
    before_items=populate(canvas)
    image=ExportService(canvas.scene).export(canvas.scene.sceneRect())
    file,project,_,_=roundtrip(canvas,tmp_path)
    parent=QWidget();qtbot.addWidget(parent);parent.toolbar=None;parent.view=None
    restored=PinCanvas(parent,project.image.size(),project.image)
    try:
        project.populate(restored)
        actual=ExportService(restored.scene).export(restored.scene.sceneRect())
        assert pixels(actual)==pixels(image)
        assert project.geometry==ImageGeometry((5,5,450,330),90,True,False,165)
        assert NumberTool.get_next_number(restored.scene)==20
        assert SpotlightCurtain.find(restored.scene).opacity()==.35
        types=[type(item) for item in project.items]
        assert types==[type(item) for item in sorted(before_items,key=lambda i:i.zValue())]
        text=next(item for item in project.items if isinstance(item,TextItem))
        text.setPlainText("Still editable")
        number=next(item for item in project.items if isinstance(item,NumberItem));number.number=42
        number.setPos(number.pos()+QPointF(20,0))
        assert pixels(ExportService(restored.scene).export(restored.scene.sceneRect()))!=pixels(image)
        assert restored.undo_stack.count()==0
        with zipfile.ZipFile(file) as archive:
            assert set(archive.namelist())=={"project.json"}|set(_ for _ in archive.namelist() if _.startswith("assets/"))
            assert b"file:" not in archive.read("project.json")
    finally:restored.cleanup()


def test_text_run_formatting_roundtrips_without_html_or_external_resources(canvas,tmp_path,qtbot):
    from canvas.items import TextItem
    from PySide6.QtGui import QTextCharFormat
    font=QFont("Arial",16)
    text=TextItem("Red then blue",QPointF(15,20),font,QColor("red"))
    canvas.scene.addItem(text)
    cursor=QTextCursor(text.document());cursor.setPosition(4);cursor.setPosition(13,QTextCursor.MoveMode.KeepAnchor)
    fmt=QTextCharFormat();fmt.setForeground(QColor("blue"));fmt.setFontWeight(QFont.Weight.Bold)
    cursor.mergeCharFormat(fmt)
    before=ExportService(canvas.scene).export(canvas.scene.sceneRect())
    _,project,manifest,_=roundtrip(canvas,tmp_path)
    assert b"<html" not in manifest
    parent=QWidget();qtbot.addWidget(parent);parent.toolbar=None;parent.view=None
    restored=PinCanvas(parent,project.image.size(),project.image)
    try:
        project.populate(restored)
        assert pixels(before)==pixels(ExportService(restored.scene).export(restored.scene.sceneRect()))
    finally:restored.cleanup()


def mutate_archive(file,manifest,assets):
    with zipfile.ZipFile(file,"w",compression=zipfile.ZIP_STORED) as z:
        z.writestr("project.json",json.dumps(manifest))
        for name,data in assets.items():z.writestr(name,data)


@pytest.mark.parametrize("mutation",["version","unknown","nan","geometry","kind","resource","font","path","matrix"])
def test_corrupt_or_unsupported_project_is_rejected(canvas,tmp_path,mutation):
    populate(canvas)
    file,_,raw,assets=roundtrip(canvas,tmp_path);manifest=json.loads(raw)
    if mutation=="version":manifest["version"]=999
    elif mutation=="unknown":manifest["script"]="do something"
    elif mutation=="nan":manifest["darkness"]=float("nan")
    elif mutation=="geometry":manifest["geometry"]["crop"][2]=10000000
    elif mutation=="kind":manifest["items"][0]["kind"]="UntrustedPlugin"
    elif mutation=="resource":assets[manifest["background"]]=b"invalid"
    elif mutation=="font":next(i for i in manifest["items"] if i["kind"]=="TextItem")["data"]["font"]="invalid font"
    elif mutation=="path":next(i for i in manifest["items"] if i["kind"]=="StrokeItem")["data"]["path"]["elements"]=[[2,1,1]]
    elif mutation=="matrix":manifest["items"][0]["common"]["transform"]=[0,0,0,0,0,0]
    mutate_archive(file,manifest,assets)
    with pytest.raises(ProjectError):read_project(file)


@pytest.mark.parametrize("name",["../escape.png","/absolute.png","assets/wrong.png","unused.txt"])
def test_zip_members_are_never_extracted_or_followed(canvas,tmp_path,name):
    file,_,_,_=roundtrip(canvas,tmp_path)
    with zipfile.ZipFile(file,"a") as z:z.writestr(name,b"bad")
    with pytest.raises(ProjectError):read_project(file)
    assert not (tmp_path.parent/"escape.png").exists()


def test_duplicate_json_keys_fail_closed(canvas,tmp_path):
    file,_,raw,assets=roundtrip(canvas,tmp_path)
    with zipfile.ZipFile(file,"w") as archive:
        archive.writestr("project.json",raw.replace(b'"version": 1',b'"version": 1, "version": 2'))
        for name,data in assets.items():archive.writestr(name,data)
    with pytest.raises(ProjectError):read_project(file)


def test_unsupported_graphics_items_do_not_disappear_silently(canvas):
    canvas.scene.addRect(QRectF(10,10,30,20))
    with pytest.raises(ProjectError):snapshot_project(canvas.scene,ImageGeometry((0,0,480,360)))


def test_cancel_project_save_never_replaces_old_project(canvas,tmp_path):
    manifest,assets=snapshot_project(canvas.scene,ImageGeometry((0,0,480,360)))
    file=tmp_path/"keep.vpic";file.write_bytes(b"original")
    assert not write_project(file,manifest,assets,SaveService(),cancelled=lambda:True)
    assert file.read_bytes()==b"original"


def test_curve_structure_validation():
    for elements in ([[3,0,0]],[[1,0,0]],[[0,0,0],[2,1,1],[1,2,2],[3,3,3]]):
        with pytest.raises(ProjectError):load_path({"fill":0,"elements":elements})


def test_screenshot_region_roundtrip_moves_annotations_and_limits_background(canvas,qtbot):
    from core.editable_project import project_from_scene
    from canvas.items import MosaicItem,TextItem
    populate(canvas)
    # Simulate a physical desktop offset including a negative-coordinate monitor.
    canvas.scene.setSceneRect(QRectF(-100,-80,480,360))
    canvas.scene.background.setOffset(-100,-80)
    for item in canvas.scene.items():
        if item not in (canvas.scene.background,canvas.scene.selection_item) and type(item).__name__!="SpotlightCurtain":
            item.moveBy(-100,-80)
            if isinstance(item,MosaicItem):item.translate_background_anchor(-100,-80)
    region=QRectF(-95,-75,450,330)
    before=ExportService(canvas.scene).export(region)
    project=project_from_scene(canvas.scene,ImageGeometry((0,0,450,330)),region=region)
    assert project.image.width()==450 and project.image.height()==330
    parent=QWidget();qtbot.addWidget(parent);parent.toolbar=None;parent.view=None
    restored=PinCanvas(parent,project.image.size(),project.image)
    try:
        project.populate(restored)
        actual=ExportService(restored.scene).export(restored.scene.sceneRect())
        assert pixels(actual)==pixels(before)
        assert any(isinstance(i,TextItem) for i in project.items)
    finally:restored.cleanup()


@pytest.mark.parametrize("smooth",[False,True])
def test_cropped_project_keeps_mosaic_grid_without_full_desktop_texture(canvas,qtbot,smooth):
    from core.editable_project import project_from_scene
    from canvas.items import MosaicItem
    base=canvas.scene.background.image().copy()
    for y in range(base.height()):
        for x in range(base.width()):base.setPixelColor(x,y,QColor(x%256,y%256,(x+y)%256))
    canvas.scene.background.update_image(base)
    path=QPainterPath();path.addRect(QRectF(90,80,120,100))
    mosaic=MosaicItem(path,10,8,canvas.scene.background.reduced_image(8),canvas.scene.sceneRect(),True,smooth)
    canvas.scene.addItem(mosaic)
    region=QRectF(93,85,90,80)
    before=ExportService(canvas.scene).export(region)
    project=project_from_scene(canvas.scene,ImageGeometry((0,0,90,80)),region=region)
    assert project.items[0].reduced_image().width()<mosaic.reduced_image().width()
    parent=QWidget();qtbot.addWidget(parent);parent.toolbar=None;parent.view=None
    restored=PinCanvas(parent,project.image.size(),project.image)
    try:
        project.populate(restored)
        assert pixels(before)==pixels(ExportService(restored.scene).export(restored.scene.sceneRect()))
    finally:restored.cleanup()


@pytest.fixture
def editor(qtbot,tmp_settings):
    from settings.tool_settings import ToolSettingsManager
    from ui.image_editor import ImageEditor
    config=ToolSettingsManager(tmp_settings)
    window=ImageEditor(config);window.show()
    yield window
    if window._worker is not None:
        window.cancel_saving();qtbot.waitUntil(lambda:window._worker is None,timeout=10000)
    window._force_close=True;window.close()


def test_editor_save_close_reopen_project_preserves_shapes_and_geometry(editor,tmp_path,qtbot):
    image=QImage(480,360,QImage.Format.Format_ARGB32);image.fill(QColor("#ddddee"))
    source=tmp_path/"source.png";image.save(str(source))
    assert editor.open_file(str(source))
    populate(editor.canvas)
    state=ImageGeometry((5,5,450,330),90,True,False,165)
    editor.set_geometry(state,"Geometry")
    before=editor.render_image()
    project=tmp_path/"drawing.vpic"
    assert editor.start_project_save(str(project))
    qtbot.waitUntil(lambda:editor._worker is None)
    assert not editor.has_changes()
    assert editor.open_file(str(project))
    assert editor.geometry_state==state
    assert pixels(editor.render_image())==pixels(before)
    assert len(editor.canvas.scene.items())>=11
    item=next(i for i in editor.canvas.scene.items() if type(i).__name__=="NumberItem")
    from canvas.undo import EditItemCommand
    editor.canvas.undo_stack.push_command(EditItemCommand(item,{"pos":QPointF(item.pos())},{"pos":item.pos()+QPointF(20,0)}))
    assert editor.has_changes()
    editor.canvas.undo_stack.undo()
    assert pixels(editor.render_image())==pixels(before)
    assert editor.start_project_save(str(project))  # existing project may be explicitly saved again
    qtbot.waitUntil(lambda:editor._worker is None)
    assert read_project(project).geometry==state


def test_bad_project_keeps_existing_editor_and_never_prompts_to_discard(editor,tmp_path,monkeypatch):
    source=tmp_path/"source.png";QImage(10,10,QImage.Format.Format_ARGB32).save(str(source))
    editor.open_file(str(source));canvas=editor.canvas
    file=tmp_path/"bad.vpic";file.write_bytes(b"not zip")
    monkeypatch.setattr("ui.image_editor.show_confirm_dialog",lambda *a:pytest.fail("Should not discard"))
    assert not editor.open_file(str(file))
    assert editor.canvas is canvas


def test_project_save_warning_cancel_writes_nothing(editor,tmp_path,monkeypatch):
    source=tmp_path/"source.png";QImage(10,10,QImage.Format.Format_ARGB32).save(str(source));editor.open_file(str(source))
    seen=[]
    monkeypatch.setattr("ui.image_editor.show_confirm_dialog",lambda parent,title,body:seen.append(body) or False)
    monkeypatch.setattr("ui.image_editor.QFileDialog.getSaveFileName",lambda *a:pytest.fail("Must not open file chooser after cancellation"))
    editor.save_project_dialog()
    assert seen and not list(tmp_path.glob("*.vpic"))
    assert editor._worker is None


def test_cancel_async_project_save_preserves_old_file_and_edits(editor,tmp_path,qtbot,monkeypatch):
    import threading
    import core.editable_project as codec
    source=tmp_path/"source.png";QImage(20,20,QImage.Format.Format_ARGB32).save(str(source));editor.open_file(str(source))
    editor.set_geometry(ImageGeometry((0,0,10,10)),"crop")
    file=tmp_path/"old.vpic";file.write_bytes(b"original")
    started,release=threading.Event(),threading.Event();original=codec.write_project
    def write(*args,**kwargs):
        started.set();assert release.wait(5)
        return original(*args,**kwargs)
    monkeypatch.setattr(codec,"write_project",write)
    assert editor.start_project_save(str(file));qtbot.waitUntil(started.is_set)
    editor.cancel_saving();release.set();qtbot.waitUntil(lambda:editor._worker is None)
    assert file.read_bytes()==b"original" and editor.has_changes()


def test_project_file_alias_cannot_overwrite_image(editor,tmp_path):
    import os
    image=tmp_path/"source.png";QImage(20,20,QImage.Format.Format_ARGB32).save(str(image));editor.open_file(str(image))
    project=tmp_path/"alias.vpic";os.link(image,project)
    before=image.read_bytes()
    assert not editor.start_project_save(str(project))
    assert image.read_bytes()==before


def test_redacted_image_project_contains_only_already_flattened_base(canvas,tmp_path):
    from text_recognition.redaction import redact_image
    image=canvas.scene.background.image().copy();image.fill(QColor("red"))
    flattened=redact_image(image,[QRectF(0,0,480,360)])
    canvas.scene.background.update_image(flattened)
    file,project,manifest,assets=roundtrip(canvas,tmp_path)
    assert project.items==[]
    assert all(project.image.pixelColor(x,y)==QColor("black") for x,y in ((0,0),(200,200),(479,359)))
    assert len(assets)==1


def test_texture_hash_deduplicates_shared_mosaic_assets(canvas,tmp_path):
    from canvas.items import MosaicItem
    for x in (10,40):
        path=QPainterPath();path.addRect(QRectF(x,20,20,20))
        canvas.scene.addItem(MosaicItem(path,10,8,canvas.scene.background.reduced_image(8),canvas.scene.sceneRect(),True))
    _,_,raw,assets=roundtrip(canvas,tmp_path)
    records=json.loads(raw)["items"]
    assert records[0]["data"]["image"]==records[1]["data"]["image"]
    assert len(assets)==2


PROJECT_MESSAGES = {
  "ImageEditor": [
    "Save project…",
    "Untitled project",
    "Could not open image or project. Check the format, version and resource limits.",
    "Editable project contains original pixels",
    "Projects retain the original image, cropped-out pixels and removable annotations. Do not share them as redacted images. Continue?",
    "Save editable project",
    "Could not save this project: unsupported annotation or resource limit. Edits were kept.",
    "Saving editable project…",
    "Editable project saved. It contains original pixels; use image export for sharing.",
    "Output: %1 × %2 px · Images are flattened; projects retain original pixels and annotations."
  ],
  "PinWindow": [
    "Edit or save project…",
    "Project unavailable",
    "Could not transfer the editable image. Original content was kept."
  ],
  "ScreenshotWindow": [
    "Project unavailable",
    "Could not transfer the editable image. Original content was kept."
  ],
  "Toolbar": [
    "Edit or save project…"
  ],
  "ToolbarLayoutDialog": [
    "Edit or save project…"
  ]
}

@pytest.mark.parametrize("lang",["en","zh","ja","ko"])
def test_compiled_project_messages(qapp,lang):
    from pathlib import Path
    from PySide6.QtCore import QTranslator
    translator=QTranslator()
    assert translator.load(str(Path(__file__).resolve().parents[1]/"translations"/f"app_{lang}.qm"))
    for context,messages in PROJECT_MESSAGES.items():
        for source in messages:
            assert translator.translate(context,source),(lang,context,source)


def test_project_editor_render_ignores_hover_frames(editor,tmp_path):
    from canvas.items import RectItem
    file=tmp_path/"base.png";image=QImage(80,80,QImage.Format.Format_RGB32);image.fill(QColor("white"));image.save(str(file))
    editor.open_file(str(file))
    item=RectItem(QRectF(20,20,40,40),QPen(QColor("red"),2))
    editor.canvas.scene.addItem(item)
    normal=editor.render_image()
    item._hovered=True
    hovered=editor.render_image()
    assert pixels(normal)==pixels(hovered)


def test_oversized_manifest_and_unused_assets_fail_before_graph_creation(canvas,tmp_path,monkeypatch):
    import core.editable_project as codec
    file,_,raw,assets=roundtrip(canvas,tmp_path)
    monkeypatch.setattr(codec,"MAX_MANIFEST_BYTES",len(raw)-1)
    with pytest.raises(ProjectError):read_project(file)


def test_excess_item_count_rejected_without_allocating_graph_items(canvas,tmp_path,monkeypatch):
    import core.editable_project as codec
    populate(canvas)
    file,_,raw,assets=roundtrip(canvas,tmp_path)
    monkeypatch.setattr(codec,"MAX_ITEMS",1)
    monkeypatch.setattr(codec,"load_item",lambda *a:pytest.fail("Must validate count before creating items"))
    with pytest.raises(ProjectError):read_project(file)


def test_duplicate_archive_member_is_rejected(canvas,tmp_path):
    file,_,raw,_=roundtrip(canvas,tmp_path)
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore",UserWarning)
        with zipfile.ZipFile(file,"a") as archive:archive.writestr("project.json",raw)
    with pytest.raises(ProjectError):read_project(file)


def test_external_text_anchor_is_not_serialized(canvas):
    from canvas.items import TextItem
    from PySide6.QtGui import QTextCharFormat
    item=TextItem("linked text",QPointF(10,10),QFont("Arial",14),QColor("red"))
    cursor=QTextCursor(item.document());cursor.select(QTextCursor.SelectionType.Document)
    fmt=QTextCharFormat();fmt.setAnchor(True);fmt.setAnchorHref("file:///private/file")
    cursor.mergeCharFormat(fmt);canvas.scene.addItem(item)
    with pytest.raises(ProjectError):snapshot_project(canvas.scene,ImageGeometry((0,0,480,360)))


def test_snapshot_too_large_canvas_fails_even_if_visible_crop_is_small(canvas,monkeypatch):
    import core.editable_project as codec
    monkeypatch.setattr(codec,"MAX_EDITOR_PIXELS",100)
    with pytest.raises(ProjectError):snapshot_project(canvas.scene,ImageGeometry((0,0,10,10)))


def test_project_atomic_failure_retains_previous_project(canvas,tmp_path,monkeypatch):
    file,_,raw,assets=roundtrip(canvas,tmp_path)
    before=file.read_bytes()
    def fail(*a,**k):raise OSError("disk full")
    monkeypatch.setattr(zipfile.ZipFile,"writestr",fail)
    assert not write_project(file,raw,assets,SaveService())
    assert file.read_bytes()==before
    assert not list(tmp_path.glob(".versepic-*"))


def test_project_can_be_dropped_onto_editor_and_foreign_urls_are_refused(editor,canvas,tmp_path):
    from PySide6.QtCore import QMimeData,QUrl
    populate(canvas);file,project,_,_=roundtrip(canvas,tmp_path)
    data=QMimeData();data.setUrls([QUrl.fromLocalFile(str(file))])
    from pathlib import Path
    assert Path(editor._drop_path(data))==file
    assert editor.open_file(editor._drop_path(data))
    assert editor.geometry_state==project.geometry
    data.setUrls([QUrl("https://example.invalid/project.vpic")])
    assert editor._drop_path(data) is None


def test_font_spacing_and_paragraph_layout_survive_roundtrip(canvas,tmp_path,qtbot):
    from canvas.items import TextItem
    from PySide6.QtGui import QTextBlockFormat
    font=QFont("Arial",18);font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing,2.5)
    font.setWordSpacing(3);font.setKerning(False);font.setStretch(115)
    item=TextItem("Spaced words\nSecond paragraph",QPointF(20,30),font,QColor("blue"))
    item.setTextWidth(300)
    cursor=QTextCursor(item.document());fmt=QTextBlockFormat();fmt.setAlignment(Qt.AlignmentFlag.AlignRight);fmt.setBottomMargin(8)
    cursor.setBlockFormat(fmt);canvas.scene.addItem(item)
    before=ExportService(canvas.scene).export(canvas.scene.sceneRect())
    _,project,_,_=roundtrip(canvas,tmp_path)
    parent=QWidget();qtbot.addWidget(parent);parent.toolbar=None;parent.view=None
    restored=PinCanvas(parent,project.image.size(),project.image)
    try:
        project.populate(restored)
        assert pixels(before)==pixels(ExportService(restored.scene).export(restored.scene.sceneRect()))
        assert project.items[0].font().letterSpacing()==2.5
    finally:restored.cleanup()


def test_snapshot_does_not_transfer_scene_item_ownership(canvas):
    import shiboken6
    items=populate(canvas)
    assert all(not shiboken6.ownedByPython(item) for item in items)
    before=pixels(ExportService(canvas.scene).export(canvas.scene.sceneRect()))
    snapshot_project(canvas.scene,ImageGeometry((0,0,480,360)))
    assert all(not shiboken6.ownedByPython(item) for item in items)
    del items
    import gc
    gc.collect()
    assert len(canvas.scene.items())>=11
    assert pixels(ExportService(canvas.scene).export(canvas.scene.sceneRect()))==before


def test_parented_annotation_structure_is_rejected_without_reparenting(canvas):
    from canvas.items import RectItem
    parent=RectItem(QRectF(0,0,80,60),QPen(QColor("red"),2))
    child=RectItem(QRectF(10,10,30,20),QPen(QColor("blue"),2))
    canvas.scene.addItem(parent);child.setParentItem(parent)
    with pytest.raises(ProjectError):snapshot_project(canvas.scene,ImageGeometry((0,0,480,360)))
    assert parent.childItems()==[child]
