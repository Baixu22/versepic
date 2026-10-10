"""Versioned editable image projects. ZIP/JSON data only; no pickle, scripts or extraction.

Project files intentionally contain original pixels and editable overlays. They are
not a safe substitute for a flattened redaction/share image.
"""
from dataclasses import asdict, dataclass
from io import BytesIO
import hashlib
import json
import math
from pathlib import Path
import re
import zipfile

from PySide6.QtCore import QBuffer, QIODevice, QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QFont, QImage, QPainterPath, QPen, QTextCursor,
                           QTextCharFormat, QTextBlockFormat, QTransform)

from core.image_document import ImageGeometry, MAX_EDITOR_PIXELS
from core.image_layout import decode_image

MAX_PROJECT_BYTES = 128 * 1024 * 1024
MAX_MANIFEST_BYTES = 8 * 1024 * 1024
MAX_ITEMS = 1000
MAX_PATH_ELEMENTS = 100000
MAX_TEXT = 100000
MAX_CAPTION_CHARS = 2000
MAX_ASSETS = 128
ASSET_NAME = re.compile(r"assets/[0-9a-f]{64}\.png\Z")


class ProjectError(ValueError):
    pass


def number(value, low=-1_000_000, high=1_000_000):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ProjectError("Invalid or excessive numeric value")
    return value


def integer(value, low=0, high=MAX_TEXT):
    if type(value) is not int:
        raise ProjectError("Expected integer")
    return int(number(value, low, high))


def boolean(value):
    if type(value) is not bool:
        raise ProjectError("Expected boolean")
    return value


def string(value, limit=MAX_TEXT):
    if not isinstance(value, str) or len(value)>limit or "\x00" in value:
        raise ProjectError("Invalid or excessive string")
    return value


def fields(value, names):
    if not isinstance(value, dict) or set(value) != set(names.split()):
        raise ProjectError("Unknown or missing project fields")
    return value


def vector(value, count):
    if not isinstance(value, (list, tuple)) or len(value)!=count:
        raise ProjectError("Invalid coordinate vector")
    return [number(component) for component in value]


def point(p):
    return [p.x(), p.y()]


def rectangle(r):
    return [r.x(), r.y(), r.width(), r.height()]


def read_rect(data):
    values=vector(data,4)
    if values[2]<0 or values[3]<0:
        raise ProjectError("Negative rectangle size")
    return QRectF(*values)


def color(value):
    text=string(value,9)
    if not re.fullmatch(r"#[0-9a-fA-F]{8}",text):
        raise ProjectError("Invalid color")
    return QColor(text)


def dump_color(value):
    return value.name(QColor.NameFormat.HexArgb)


def dump_brush(brush):
    if brush.style() not in (Qt.BrushStyle.NoBrush,Qt.BrushStyle.SolidPattern):
        raise ProjectError("This brush type cannot be saved")
    return {"style":brush.style().value,"color":dump_color(brush.color())}


def load_brush(data):
    fields(data,"style color")
    if data["style"] not in (0,1):raise ProjectError("Unsupported brush")
    return QBrush(color(data["color"]),Qt.BrushStyle(integer(data["style"],0,1)))


def dump_pen(pen):
    return {"brush":dump_brush(pen.brush()),"width":pen.widthF(),"style":pen.style().value,
            "cap":pen.capStyle().value,"join":pen.joinStyle().value,"miter":pen.miterLimit(),
            "dash":pen.dashPattern(),"offset":pen.dashOffset(),"cosmetic":pen.isCosmetic()}


def load_pen(data):
    fields(data,"brush width style cap join miter dash offset cosmetic")
    style=integer(data["style"],0,6)
    if data["cap"] not in (0,16,32) or data["join"] not in (0,64,128,256):raise ProjectError("Invalid pen shape")
    pen=QPen(load_brush(data["brush"]),number(data["width"],0,2048),Qt.PenStyle(style),
             Qt.PenCapStyle(integer(data["cap"],0,32)),Qt.PenJoinStyle(integer(data["join"],0,256)))
    pen.setMiterLimit(number(data["miter"],0,100))
    pattern=data["dash"]
    if not isinstance(pattern,list) or len(pattern)>32 or len(pattern)%2:raise ProjectError("Invalid dash pattern")
    if style==6:
        if not pattern:raise ProjectError("Missing dash pattern")
        pen.setDashPattern([number(x,0.001,10000) for x in pattern])
    pen.setDashOffset(number(data["offset"],-10000,10000))
    pen.setCosmetic(boolean(data["cosmetic"]))
    return pen


def dump_path(path):
    if path.elementCount()>MAX_PATH_ELEMENTS:raise ProjectError("Too many path elements")
    return {"fill":path.fillRule().value,"elements":[[e.type.value,e.x,e.y] for e in (path.elementAt(i) for i in range(path.elementCount()))]}


def load_path(data):
    fields(data,"fill elements")
    elements=data["elements"]
    if not isinstance(elements,list) or len(elements)>MAX_PATH_ELEMENTS:raise ProjectError("Too many path elements")
    result=QPainterPath()
    result.setFillRule(Qt.FillRule(integer(data["fill"],0,1)))
    index=0
    while index<len(elements):
        entry=vector(elements[index],3);kind=integer(entry[0],0,3)
        if kind==0:result.moveTo(entry[1],entry[2])
        elif kind==1:
            if index==0:raise ProjectError("Path line without start")
            result.lineTo(entry[1],entry[2])
        elif kind==2:
            if index==0 or index+2>=len(elements):raise ProjectError("Incomplete curve")
            second,third=vector(elements[index+1],3),vector(elements[index+2],3)
            if second[0]!=3 or third[0]!=3:raise ProjectError("Invalid curve data")
            result.cubicTo(entry[1],entry[2],second[1],second[2],third[1],third[2]);index+=2
        else:raise ProjectError("Orphan curve data")
        index+=1
    return result


def dump_font(font):
    return {"description":font.toString(),"spacing_type":font.letterSpacingType().value,
            "letter_spacing":font.letterSpacing(),"word_spacing":font.wordSpacing(),
            "kerning":font.kerning(),"stretch":font.stretch(),"hinting":font.hintingPreference().value}


def load_font(data):
    font=QFont()
    fields(data,"description spacing_type letter_spacing word_spacing kerning stretch hinting")
    text=string(data["description"],1024)
    if text.count(",")<9 or not font.fromString(text):raise ProjectError("Invalid font")
    size=font.pixelSize() if font.pixelSize()>0 else font.pointSizeF()
    number(size,0.1,1024)
    font.setLetterSpacing(QFont.SpacingType(integer(data["spacing_type"],0,1)),number(data["letter_spacing"],-1024,10000))
    font.setWordSpacing(number(data["word_spacing"],-1024,1024))
    font.setKerning(boolean(data["kerning"]))
    font.setStretch(integer(data["stretch"],0,4000))
    font.setHintingPreference(QFont.HintingPreference(integer(data["hinting"],0,3)))
    return font


def dump_text(item):
    document=item.document()
    plain=item.toPlainText()
    if len(plain)>MAX_TEXT:raise ProjectError("Text too long")
    runs=[];blocks=[];block=document.begin()
    while block.isValid():
        fmt=block.blockFormat()
        blocks.append([block.position(),fmt.alignment().value,fmt.indent(),fmt.topMargin(),fmt.bottomMargin(),fmt.leftMargin(),fmt.rightMargin(),fmt.textIndent()])
        iterator=block.begin()
        while not iterator.atEnd():
            fragment=iterator.fragment();fmt=fragment.charFormat()
            if fmt.isImageFormat() or fmt.isAnchor():raise ProjectError("Embedded resources or links are not supported")
            if fragment.isValid():
                runs.append({"start":fragment.position(),"length":fragment.length(),"font":dump_font(fmt.font()),
                             "foreground":dump_brush(fmt.foreground()),"background":dump_brush(fmt.background()),
                             "vertical":fmt.verticalAlignment().value})
            iterator+=1
        block=block.next()
    return {"plain":plain,"font":dump_font(item.font()),"color":dump_color(item.defaultTextColor()),
            "width":item.textWidth(),"margin":document.documentMargin(),"runs":runs,"blocks":blocks,
            "outline":[item.has_outline,dump_color(item.outline_color),item.outline_width],
            "shadow":[item.has_shadow,dump_color(item.shadow_color)],
            "background":[item.has_background,dump_color(item.background_color)]}


def load_text(data):
    from canvas.items import TextItem
    fields(data,"plain font color width margin runs blocks outline shadow background")
    text=string(data["plain"])
    item=TextItem(text,QPointF(),load_font(data["font"]),color(data["color"]))
    item.setTextWidth(number(data["width"],-1,100000))
    document=item.document();document.setDocumentMargin(number(data["margin"],0,1000))
    if not isinstance(data["runs"],list) or len(data["runs"])>10000:raise ProjectError("Too many text runs")
    length=document.characterCount()-1
    end=0
    for run in data["runs"]:
        fields(run,"start length font foreground background vertical")
        start=integer(run["start"],0,length);count=integer(run["length"],1,length)
        if start<end or start+count>length:raise ProjectError("Invalid text range")
        cursor=QTextCursor(document);cursor.setPosition(start);cursor.setPosition(start+count,QTextCursor.MoveMode.KeepAnchor)
        fmt=QTextCharFormat();fmt.setFont(load_font(run["font"]))
        fmt.setForeground(load_brush(run["foreground"]));fmt.setBackground(load_brush(run["background"]))
        fmt.setVerticalAlignment(QTextCharFormat.VerticalAlignment(integer(run["vertical"],0,6)))
        cursor.setCharFormat(fmt);end=start+count
    if not isinstance(data["blocks"],list) or len(data["blocks"])>10000:raise ProjectError("Too many text paragraphs")
    last=-1
    for row in data["blocks"]:
        values=vector(row,8);pos=integer(values[0],0,length)
        if pos<=last or document.findBlock(pos).position()!=pos:raise ProjectError("Invalid paragraph start")
        last=pos
        fmt=QTextBlockFormat();fmt.setAlignment(Qt.AlignmentFlag(integer(values[1],0,511)))
        fmt.setIndent(integer(values[2],0,100))
        for setter,value in zip((fmt.setTopMargin,fmt.setBottomMargin,fmt.setLeftMargin,fmt.setRightMargin,fmt.setTextIndent),values[3:]):
            setter(number(value,-1000,1000))
        cursor=QTextCursor(document);cursor.setPosition(pos);cursor.setBlockFormat(fmt)
    for key,count in (("outline",3),("shadow",2),("background",2)):
        if not isinstance(data[key],list) or len(data[key])!=count:raise ProjectError("Invalid text effect")
    outline=data["outline"];number(outline[2],0,1)
    if outline[2] not in TextItem.OUTLINE_WIDTH_LEVELS:raise ProjectError("Invalid outline width")
    item.set_outline(boolean(outline[0]),color(outline[1]),outline[2])
    item.set_shadow(boolean(data["shadow"][0]),color(data["shadow"][1]))
    item.has_background=boolean(data["background"][0]);item.background_color=color(data["background"][1])
    return item


class Assets:
    def __init__(self):
        self.data={}
        self.pixels=0

    def add(self,image):
        if image.isNull():raise ProjectError("Empty image resource")
        buffer=QBuffer();buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        if not image.save(buffer,"PNG"):raise ProjectError("Could not encode image resource")
        data=bytes(buffer.data());name="assets/"+hashlib.sha256(data).hexdigest()+".png"
        if name not in self.data:
            self.pixels+=image.width()*image.height()
            if self.pixels>MAX_EDITOR_PIXELS*2 or len(self.data)>=MAX_ASSETS or sum(map(len,self.data.values()))+len(data)>MAX_PROJECT_BYTES-MAX_MANIFEST_BYTES:
                raise ProjectError("Project image budget exceeded")
            self.data[name]=data
        return name


def dump_item(item,assets,offset,canvas_bounds=None):
    from canvas.items import StrokeItem,RectItem,EllipseItem,ArrowItem,NumberItem,MosaicItem,TextItem,SpotlightItem,MagnifyCalloutItem,ImageStampItem
    t=item.transform()
    if item.transformations():raise ProjectError("Unsupported transform list")
    common={"pos":[item.pos().x()-offset.x(),item.pos().y()-offset.y()],"origin":point(item.transformOriginPoint()),
            "transform":[t.m11(),t.m12(),t.m21(),t.m22(),t.dx(),t.dy()],"rotation":item.rotation(),"scale":item.scale(),
            "z":item.zValue(),"opacity":item.opacity(),"visible":item.isVisible()}
    if not t.isAffine():raise ProjectError("Perspective transforms are not supported")
    kind=type(item).__name__
    if type(item) is StrokeItem:
        data={"path":dump_path(item.path()),"pen":dump_pen(item.pen()),"highlighter":item.is_highlighter}
    elif type(item) is RectItem:
        data={"rect":rectangle(item.rect()),"pen":dump_pen(item.pen()),"brush":dump_brush(item.brush()),
              "corner":item.get_corner_radius(),"highlighter":bool(getattr(item,"is_highlighter_rect",False))}
    elif type(item) is EllipseItem:
        data={"rect":rectangle(item.rect()),"pen":dump_pen(item.pen()),"brush":dump_brush(item.brush())}
    elif type(item) is ArrowItem:
        data={"start":point(item.start_pos),"end":point(item.end_pos),"control":point(item.control_pos),
              "curved":item._control_modified,"width":item.base_width,"color":dump_color(item.color),"style":item._arrow_style}
    elif type(item) is NumberItem:
        data={"number":item.number,"radius":item.radius,"color":dump_color(item.color),"style":item.style,"order":item.number_order,
              "caption":str(getattr(item,"caption",""))}
    elif type(item) is TextItem:data=dump_text(item)
    elif type(item) is MosaicItem:
        texture=item.reduced_image();anchor=item.background_rect()
        if canvas_bounds is not None:
            block=item.block_size()
            # Keep the native block grid; never include an entire desktop texture for a cropped project.
            left=max(0,math.floor((canvas_bounds.left()-anchor.x()+block)/block)-1)
            top=max(0,math.floor((canvas_bounds.top()-anchor.y()+block)/block)-1)
            right=min(texture.width(),math.ceil((canvas_bounds.right()-anchor.x()+block)/block)+1)
            bottom=min(texture.height(),math.ceil((canvas_bounds.bottom()-anchor.y()+block)/block)+1)
            if right<=left or bottom<=top:raise ProjectError("Mosaic texture does not cover the project canvas")
            texture=texture.copy(left,top,right-left,bottom-top)
            anchor=QRectF(anchor.x()+left*block,anchor.y()+top*block,anchor.width()-left*block,anchor.height()-top*block)
        data={"path":dump_path(item.path()),"brush_width":item.brush_width(),"block_size":item.block_size(),
              "image":assets.add(texture),"background":rectangle(anchor.translated(-offset)),
              "fill":item.fill_mode(),"smooth":item.smooth()}
    elif type(item) is SpotlightItem:
        data={"rect":rectangle(item.rect()),"corner":item.get_corner_radius()}
    elif type(item) is MagnifyCalloutItem:
        data={"source":rectangle(item.source_rect().translated(-offset.x(),-offset.y())),"rect":rectangle(item.rect()),"pen":dump_pen(item.pen())}
    elif type(item) is ImageStampItem:
        data={"rect":rectangle(item.rect()),"image":assets.add(item.image())}
    else:raise ProjectError("Unsupported annotation type: "+kind)
    return {"kind":kind,"common":common,"data":data}


def load_item(record,images):
    from canvas.items import StrokeItem,RectItem,EllipseItem,ArrowItem,NumberItem,MosaicItem,SpotlightItem,MagnifyCalloutItem,ImageStampItem
    fields(record,"kind common data")
    kind=string(record["kind"],32);data=record["data"]
    if kind=="StrokeItem":
        fields(data,"path pen highlighter");item=StrokeItem(load_path(data["path"]),load_pen(data["pen"]),boolean(data["highlighter"]))
    elif kind=="RectItem":
        fields(data,"rect pen brush corner highlighter")
        item=RectItem(read_rect(data["rect"]),load_pen(data["pen"]),number(data["corner"],0,10000));item.setBrush(load_brush(data["brush"]))
        if boolean(data["highlighter"]):item.is_highlighter=item.is_highlighter_rect=True
    elif kind=="EllipseItem":
        fields(data,"rect pen brush");item=EllipseItem(read_rect(data["rect"]),load_pen(data["pen"]));item.setBrush(load_brush(data["brush"]))
    elif kind=="ArrowItem":
        fields(data,"start end control curved width color style")
        if data["style"] not in ArrowItem.STYLES:raise ProjectError("Unknown arrow style")
        width=number(data["width"],0.1,2048)
        item=ArrowItem(QPointF(*vector(data["start"],2)),QPointF(*vector(data["end"],2)),QPen(color(data["color"]),width),data["style"])
        item.base_width=width
        if boolean(data["curved"]):item.set_control_point(QPointF(*vector(data["control"],2)))
        else:vector(data["control"],2)
        item.update_geometry()
    elif kind=="NumberItem":
        # caption 是后加的：旧工程没有这个键，必须当作空说明继续能打开
        fields({k:v for k,v in data.items() if k!="caption"},"number radius color style order")
        if data["style"] not in NumberItem.STYLES:raise ProjectError("Unknown number style")
        item=NumberItem(integer(data["number"],0,1000000),QPointF(),number(data["radius"],1,2048),color(data["color"]),data["style"])
        item.number_order=None if data["order"] is None else integer(data["order"],0,1000000)
        caption=data.get("caption","")
        if not isinstance(caption,str) or len(caption)>MAX_CAPTION_CHARS:raise ProjectError("Invalid number caption")
        item.set_caption(caption)
    elif kind=="TextItem":item=load_text(data)
    elif kind=="MosaicItem":
        fields(data,"path brush_width block_size image background fill smooth")
        if data["image"] not in images:raise ProjectError("Missing mosaic texture")
        item=MosaicItem(load_path(data["path"]),number(data["brush_width"],1,2048),integer(data["block_size"],2,1024),
                        images[data["image"]],read_rect(data["background"]),boolean(data["fill"]),boolean(data["smooth"]))
    elif kind=="SpotlightItem":
        fields(data,"rect corner");item=SpotlightItem(read_rect(data["rect"]),number(data["corner"],0,10000))
    elif kind=="MagnifyCalloutItem":
        fields(data,"source rect pen")
        item=MagnifyCalloutItem(read_rect(data["source"]),read_rect(data["rect"]),load_pen(data["pen"]))
    elif kind=="ImageStampItem":
        fields(data,"rect image")
        if data["image"] not in images:raise ProjectError("Missing stamp image")
        item=ImageStampItem(images[data["image"]],read_rect(data["rect"]))
    else:raise ProjectError("Unsupported annotation type or newer project version")
    common=fields(record["common"],"pos origin transform rotation scale z opacity visible")
    matrix=vector(common["transform"],6)
    if any(abs(value)>1000 for value in matrix[:4]):raise ProjectError("Excessive transform")
    transform=QTransform(*matrix)
    if not transform.isInvertible():raise ProjectError("Singular annotation transform")
    item.setTransform(transform);item.setTransformOriginPoint(QPointF(*vector(common["origin"],2)))
    item.setRotation(number(common["rotation"],-360000,360000));item.setScale(number(common["scale"],0.001,1000))
    item.setPos(QPointF(*vector(common["pos"],2)));item.setZValue(number(common["z"],-1000,1000))
    item.setOpacity(number(common["opacity"],0,1));item.setVisible(boolean(common["visible"]))
    return item


@dataclass
class EditableProject:
    image: QImage
    geometry: ImageGeometry
    items: list
    next_number: int
    darkness: float

    def populate(self,canvas):
        from canvas.items import SpotlightCurtain
        from canvas.undo import AddItemCommand
        from tools.number import NumberTool
        for item in self.items:
            canvas.undo_stack.push_command(AddItemCommand(canvas.scene,item))
        curtain=SpotlightCurtain.find(canvas.scene)
        if curtain:curtain.setOpacity(self.darkness)
        NumberTool.set_next_number(canvas.scene,self.next_number)
        canvas.undo_stack.clear()  # History starts at the restored state, not the original editing session.
        canvas.undo_stack.setClean()


def snapshot_project(scene,geometry, *, region=None):
    """Snapshot full editor/pin canvas; no selection overlays, widgets or disk paths."""
    from canvas.items import SpotlightCurtain
    from tools.number import NumberTool
    if getattr(scene, "sensitive_capture", False) is True:
        raise ProjectError("Sensitive content cannot be transferred to an editable project")
    image=scene.background.image()
    if region is not None:
        rect=QRectF(region)
        if rect.isEmpty() or not scene.sceneRect().contains(rect):raise ProjectError("Invalid project region")
        image=image.copy(rect.translated(-scene.sceneRect().topLeft()).toAlignedRect())
    geometry.validate(image.size())
    if image.width()*image.height()>MAX_EDITOR_PIXELS:raise ProjectError("Project canvas exceeds the editor pixel limit")
    assets=Assets();background=assets.add(image)
    origin=QRectF(region).topLeft() if region is not None else scene.sceneRect().topLeft()
    records=[]
    scene_items=scene.items(Qt.SortOrder.AscendingOrder)
    # parentItem() on an unparented item transfers ownership to Python in PySide6;
    # checking child relationships instead avoids deleting source annotations on return.
    if any(item.childItems() for item in scene_items):raise ProjectError("Unsupported parent/group transform")
    for item in scene_items:
        if item in (scene.background,scene.selection_item) or isinstance(item,SpotlightCurtain):continue
        if region is not None and not item.sceneBoundingRect().intersects(QRectF(region)):continue
        records.append(dump_item(item,assets,origin,QRectF(origin.x(),origin.y(),image.width(),image.height())))
    if len(records)>MAX_ITEMS:raise ProjectError("Too many annotations")
    curtain=SpotlightCurtain.find(scene)
    manifest={"format":"versepic-editable-image","version":1,"background":background,"geometry":asdict(geometry),
              "items":records,"next_number":NumberTool.get_next_number(scene),"darkness":curtain.opacity() if curtain else 0.7,
              "privacy":"contains-original-pixels-and-editable-overlays"}
    # Bound the complete manifest before writing; decoding validates every data field.
    encoded=json.dumps(manifest,ensure_ascii=False,allow_nan=False).encode("utf-8")
    if len(encoded)>MAX_MANIFEST_BYTES:raise ProjectError("Project manifest too large")
    return encoded,assets.data


def _unique_object(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise ProjectError("Duplicate JSON property")
        result[key]=value
    return result


def read_project_bytes(data, *, pixel_budget=MAX_EDITOR_PIXELS*2, item_budget=MAX_ITEMS):
    if not isinstance(data,bytes) or len(data)>MAX_PROJECT_BYTES:
        raise ProjectError("Project file too large")
    return read_project(BytesIO(data), pixel_budget=pixel_budget, item_budget=item_budget)


def read_project(filename, *, pixel_budget=MAX_EDITOR_PIXELS*2, item_budget=MAX_ITEMS):
    """Bounded reads only. ZIP members are never extracted or interpreted as paths."""
    try:
        size=filename.getbuffer().nbytes if isinstance(filename,BytesIO) else Path(filename).stat().st_size
        if size>MAX_PROJECT_BYTES:raise ProjectError("Project file too large")
        with zipfile.ZipFile(filename) as archive:
            entries=archive.infolist();names=[info.filename for info in entries]
            if len(names)>MAX_ASSETS+1 or len(names)!=len(set(names)) or "project.json" not in names:
                raise ProjectError("Invalid project archive members")
            if any(info.flag_bits&1 or info.is_dir() or info.compress_type not in (zipfile.ZIP_STORED,zipfile.ZIP_DEFLATED) for info in entries):
                raise ProjectError("Unsupported archive encoding")
            if any(name!="project.json" and not ASSET_NAME.fullmatch(name) for name in names):
                raise ProjectError("Unsafe or unknown archive member")
            if sum(info.file_size for info in entries)>MAX_PROJECT_BYTES or archive.getinfo("project.json").file_size>MAX_MANIFEST_BYTES:
                raise ProjectError("Project decompression budget exceeded")
            raw=archive.read("project.json")
            manifest=json.loads(raw,object_pairs_hook=_unique_object,parse_constant=lambda _:(_ for _ in ()).throw(ProjectError("Nonfinite JSON")))
            fields(manifest,"format version background geometry items next_number darkness privacy")
            if manifest["format"]!="versepic-editable-image" or type(manifest["version"]) is not int or manifest["version"]!=1:
                raise ProjectError("Unsupported project version")
            if manifest["privacy"]!="contains-original-pixels-and-editable-overlays":raise ProjectError("Unknown project privacy format")
            items=manifest["items"]
            if not isinstance(items,list) or len(items)>min(MAX_ITEMS,item_budget):raise ProjectError("Too many annotations")
            used={manifest["background"]}
            for record in items:
                fields(record,"kind common data")
                if record["kind"]=="MosaicItem":
                    if not isinstance(record["data"],dict):raise ProjectError("Invalid mosaic")
                    used.add(record["data"].get("image"))
            if used!=set(names)-{"project.json"}:raise ProjectError("Missing or unused project resource")
            images={};budget=min(MAX_EDITOR_PIXELS*2,pixel_budget)
            for name in sorted(used):
                data=archive.read(name)
                if hashlib.sha256(data).hexdigest()!=name[7:-4]:raise ProjectError("Resource hash mismatch")
                image=decode_image(data,remaining_pixels=budget)
                budget-=image.width()*image.height();images[name]=image
        return decode_manifest(manifest,images)
    except ProjectError:raise
    except Exception as exc:
        raise ProjectError("Invalid or unsupported editable project") from exc


def write_project(filename,manifest,assets,service,*,cancelled=None):
    def write(temporary):
        with zipfile.ZipFile(temporary,"w",compression=zipfile.ZIP_STORED) as archive:
            archive.writestr("project.json",manifest)
            for name,data in assets.items():
                if cancelled and cancelled():return False
                archive.writestr(name,data)
        return True
    return service._atomic_save(str(filename),write,cancelled=cancelled)


def decode_manifest(manifest,images):
    items=manifest["items"]
    base=images[manifest["background"]]
    if base.width()*base.height()>MAX_EDITOR_PIXELS:raise ProjectError("Editor image too large")
    geometry_data=fields(manifest["geometry"],"crop rotation flip_h flip_v output_width")
    geometry=ImageGeometry(tuple(geometry_data["crop"]),geometry_data["rotation"],geometry_data["flip_h"],geometry_data["flip_v"],geometry_data["output_width"])
    geometry.validate(base.size())
    # Every graph object is still detached here; malformed input cannot mutate an open editor.
    decoded=[load_item(record,images) for record in items]
    return EditableProject(base,geometry,decoded,integer(manifest["next_number"],0,1000000),number(manifest["darkness"],0,1))



def project_from_scene(scene,geometry,*,region=None):
    manifest,assets=snapshot_project(scene,geometry,region=region)
    return decode_manifest(json.loads(manifest),{name:decode_image(data,MAX_EDITOR_PIXELS*2) for name,data in assets.items()})
