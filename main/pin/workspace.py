"""Explicit, bounded pin workspaces containing existing editable-project archives.

No archive member is extracted. Opening adds new pins; it never closes current pins.
Only the user-requested workspace file is saved or moved to the Recycle Bin.
"""
from dataclasses import dataclass
from io import BytesIO
import hashlib
import json
from pathlib import Path
import re
import zipfile

from PySide6.QtCore import QPoint, QPointF, QRect, Qt

from core.editable_project import (ProjectError, MAX_PROJECT_BYTES, _unique_object,
                                   boolean, fields, integer, number, read_project_bytes,
                                   snapshot_project, string, vector)
from core.image_document import ImageGeometry

MAX_PINS = 20
MAX_WORKSPACE_BYTES = 128 * 1024 * 1024
MAX_MANIFEST_BYTES = 256 * 1024
MAX_PIXELS = 64_000_000
MAX_ANNOTATIONS = 5000
PROJECT_NAME = re.compile(r"projects/[0-9]{3}-[0-9a-f]{64}\.vpic\Z")


def _rect(value):
    values=vector(value,4)
    if any(type(v) is not int for v in values) or min(values[2:])<1 or max(values[2:])>100000:
        raise ProjectError("Invalid workspace window bounds")
    return QRect(*values)


def validate_pin_state(state):
    fields(state,"position normal_rect scale opacity topmost border toolbar thumbnail thumb_size thumb_center text_selection")
    position=vector(state["position"],2)
    if any(type(v) is not int for v in position):raise ProjectError("Invalid window position")
    normal=_rect(state["normal_rect"])
    if normal.width()*normal.height()>32_000_000:raise ProjectError("Pin display size exceeds 32 megapixels")
    number(state["scale"],.01,50)
    number(state["opacity"],.15,1)
    for key in ("topmost","border","toolbar","thumbnail","text_selection"):boolean(state[key])
    integer(state["thumb_size"],16,1024)
    if state["thumb_center"] is not None:vector(state["thumb_center"],2)
    if state["thumbnail"] and state["thumb_center"] is None:raise ProjectError("Missing thumbnail center")
    return state


def pin_state(pin):
    thumb=pin._thumbnail
    normal=thumb._prev_geometry if thumb.active else pin.geometry()
    center=thumb._scene_center
    state={"position":[pin.x(),pin.y()],"normal_rect":[normal.x(),normal.y(),normal.width(),normal.height()],
           "scale":pin.scale_factor,"opacity":pin._win_opacity,
           "topmost":bool(pin.windowFlags() & Qt.WindowType.WindowStaysOnTopHint),"border":pin.halo_enabled,
           "toolbar":bool(pin.toolbar and pin.toolbar.isVisible()),"thumbnail":thumb.active,
           "thumb_size":thumb.size,"thumb_center":[center.x(),center.y()] if center is not None else None,
           "text_selection":pin._text_selection_enabled}
    return validate_pin_state(state)


def pack_project(manifest,assets):
    output=BytesIO()
    with zipfile.ZipFile(output,"w",compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("project.json",manifest)
        for name,data in assets.items():archive.writestr(name,data)
    data=output.getvalue()
    if len(data)>MAX_PROJECT_BYTES:raise ProjectError("Project exceeds workspace limits")
    return data


def snapshot_workspace(pins,name):
    pins=list(pins)
    if any(getattr(pin, "sensitive_capture", False) is True for pin in pins):
        raise ProjectError("Sensitive pins cannot be saved in a workspace")
    name=string(name,80).strip()
    if not name or not 1<=len(pins)<=MAX_PINS:raise ProjectError("Choose 1 to 20 pins and a workspace name")
    entries=[];projects={};pixels=0;annotations=0;bytes_used=0;display_pixels=0
    for index,pin in enumerate(pins):
        if getattr(pin,"_is_closed",False) or pin.canvas is None:raise ProjectError("A selected pin is no longer available")
        state=pin_state(pin)
        display_pixels+=state["normal_rect"][2]*state["normal_rect"][3]
        if display_pixels>MAX_PIXELS:raise ProjectError("Workspace display pixel limit exceeded")
        # Serialize model data without changing the source pin's active tool or selection.
        t=pin._image_transform;size=pin.canvas.base_size
        geometry=ImageGeometry((0,0,size.width(),size.height()),t.rotation,t.flip_h,t.flip_v)
        manifest,assets=snapshot_project(pin.canvas.scene,geometry)
        record=json.loads(manifest)
        # Account before copying PNG assets into a nested archive.
        annotations+=len(record["items"])
        unique_images={}
        base=pin.canvas.scene.background.image();unique_images[base.cacheKey()]=base
        for item in pin.canvas.scene.items():
            if type(item).__name__=="MosaicItem":
                texture=item.reduced_image();unique_images[texture.cacheKey()]=texture
        pixels+=sum(im.width()*im.height() for im in unique_images.values())
        bytes_used+=len(manifest)+sum(map(len,assets.values()))
        if pixels>MAX_PIXELS or annotations>MAX_ANNOTATIONS or bytes_used>MAX_WORKSPACE_BYTES-MAX_MANIFEST_BYTES:
            raise ProjectError("Workspace exceeds aggregate resource limits")
        data=pack_project(manifest,assets)
        project=f"projects/{index:03d}-{hashlib.sha256(data).hexdigest()}.vpic"
        projects[project]=data
        if sum(map(len,projects.values()))>MAX_WORKSPACE_BYTES-MAX_MANIFEST_BYTES:
            raise ProjectError("Workspace file is too large")
        entries.append({"label":f"{index+1}","project":project,"state":state})
    manifest={"format":"versepic-pin-workspace","version":1,"name":name,
              "privacy":"contains-original-pixels-and-editable-overlays","pins":entries}
    encoded=json.dumps(manifest,ensure_ascii=False,allow_nan=False).encode("utf-8")
    if len(encoded)>MAX_MANIFEST_BYTES:raise ProjectError("Workspace manifest is too large")
    return encoded,projects


def write_workspace(destination,manifest,projects,service,*,cancelled=None):
    def write(temporary):
        with zipfile.ZipFile(temporary,"w",compression=zipfile.ZIP_STORED) as archive:
            archive.writestr("workspace.json",manifest)
            for name,data in projects.items():
                if cancelled and cancelled():return False
                archive.writestr(name,data)
        return True
    return service._atomic_save(str(destination),write,cancelled=cancelled)


@dataclass
class Workspace:
    name: str
    pins: list
    errors: list


def _project_pixels(project):
    images={project.image.cacheKey():project.image}
    for item in project.items:
        if type(item).__name__=="MosaicItem":
            image=item.reduced_image();images[image.cacheKey()]=image
    return sum(im.width()*im.height() for im in images.values())


def read_workspace(filename):
    try:
        if Path(filename).stat().st_size>MAX_WORKSPACE_BYTES:raise ProjectError("Workspace file is too large")
        with zipfile.ZipFile(filename) as archive:
            infos=archive.infolist();names=[i.filename for i in infos]
            if len(infos)>MAX_PINS+1 or len(names)!=len(set(names)) or "workspace.json" not in names:
                raise ProjectError("Invalid workspace members")
            if any(i.flag_bits&1 or i.is_dir() or i.compress_type not in (zipfile.ZIP_STORED,zipfile.ZIP_DEFLATED) for i in infos):
                raise ProjectError("Unsupported workspace archive encoding")
            if any(n!="workspace.json" and not PROJECT_NAME.fullmatch(n) for n in names):raise ProjectError("Unsafe workspace member")
            if sum(i.file_size for i in infos)>MAX_WORKSPACE_BYTES or archive.getinfo("workspace.json").file_size>MAX_MANIFEST_BYTES:
                raise ProjectError("Workspace decompression limit exceeded")
            manifest=json.loads(archive.read("workspace.json"),object_pairs_hook=_unique_object,
                                parse_constant=lambda _:(_ for _ in ()).throw(ProjectError("Nonfinite JSON")))
            fields(manifest,"format version name privacy pins")
            if manifest["format"]!="versepic-pin-workspace" or type(manifest["version"]) is not int or manifest["version"]!=1:
                raise ProjectError("Unsupported workspace version")
            if manifest["privacy"]!="contains-original-pixels-and-editable-overlays":raise ProjectError("Invalid workspace privacy format")
            name=string(manifest["name"],80)
            pins=manifest["pins"]
            if not isinstance(pins,list) or not 1<=len(pins)<=MAX_PINS:raise ProjectError("Invalid workspace pin count")
            referenced=set()
            for entry in pins:
                fields(entry,"label project state")
                string(entry["label"],80)
                project=entry["project"]
                if not isinstance(project,str) or not PROJECT_NAME.fullmatch(project) or project in referenced:raise ProjectError("Invalid project reference")
                referenced.add(project)
            if set(names)-{"workspace.json"}-referenced:raise ProjectError("Unused workspace resource")
            restored=[];errors=[];pixels=MAX_PIXELS;items=MAX_ANNOTATIONS;expanded=0
            for index,entry in enumerate(pins):
                try:
                    state=validate_pin_state(entry["state"])
                    data=archive.read(entry["project"])
                    if hashlib.sha256(data).hexdigest()!=entry["project"].split("-")[-1][:-5]:raise ProjectError("Project hash mismatch")
                    with zipfile.ZipFile(BytesIO(data)) as nested:
                        expanded+=sum(i.file_size for i in nested.infolist())
                    if expanded>MAX_WORKSPACE_BYTES:raise ProjectError("Aggregate nested project limit exceeded")
                    project=read_project_bytes(data,pixel_budget=pixels,item_budget=items)
                    size=project.image.size()
                    if project.geometry.crop!=(0,0,size.width(),size.height()) or project.geometry.output_width:
                        raise ProjectError("Workspace pins require a complete editable image")
                    native=project.geometry.native_output_size()
                    normal=_rect(state["normal_rect"])
                    if abs(normal.width()-round(native.width()*state["scale"]))>1 or abs(normal.height()-round(native.height()*state["scale"]))>1:
                        raise ProjectError("Saved pin scale does not match its image dimensions")
                    pixels-=_project_pixels(project);items-=len(project.items)
                    if pixels<0 or items<0:raise ProjectError("Workspace decoded resource budget exceeded")
                    restored.append((index,project,state))
                except Exception as exc:
                    errors.append((index,str(exc)))
        return Workspace(name,restored,errors)
    except ProjectError:raise
    except Exception as exc:raise ProjectError("Invalid or unsupported pin workspace") from exc


def visible_position(position,size,screens):
    """Keep size/scale unchanged; relocate unreachable pins into a real available screen."""
    if not screens:raise ProjectError("No screen is available for workspace restoration")
    requested=QRect(QPoint(*position),size)
    for screen in screens:
        visible=requested.intersected(screen)
        if visible.width()>=min(64,size.width()) and visible.height()>=min(48,size.height()):
            return requested.topLeft(),False
    screen=min(screens,key=lambda s:abs(s.center().x()-requested.center().x())+abs(s.center().y()-requested.center().y()))
    x=screen.left()+max(0,(screen.width()-size.width())//2)
    y=screen.top()+max(0,(screen.height()-size.height())//2)
    return QPoint(x,y),True


def restore_workspace(workspace,manager,config,screens):
    """Add valid records, report each failure, and never touch pre-existing pins."""
    restored=[];errors=list(workspace.errors);moved=[];display_pixels=0
    for index,project,state in workspace.pins:
        pin=None
        try:
            normal=_rect(state["normal_rect"])
            if display_pixels+normal.width()*normal.height()>MAX_PIXELS:
                raise ProjectError("Workspace display pixel limit exceeded")
            pos,relocated=visible_position([normal.x(),normal.y()],normal.size(),screens)
            pin=manager.create_pin(project.image,pos,config_manager=config)
            # Constructor schedules OCR later; restore its saved preference before the timer can run.
            pin._ocr_mgr._text_selection_enabled=state["text_selection"]
            project.populate(pin.canvas)
            t=project.geometry.transform();pin._image_transform=t
            pin.scale_factor=state["scale"]
            pin.halo_enabled=state["border"]
            pin._win_opacity=state["opacity"];pin.setWindowOpacity(state["opacity"])
            top=bool(pin.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
            if top!=state["topmost"]:pin.toggle_stay_on_top()
            pin.setGeometry(pos.x(),pos.y(),normal.width(),normal.height())
            pin._update_view_transform();pin._refresh_background_for_scale();pin._image_transform._refresh_border(pin)
            pin.update_button_positions()
            if state["thumbnail"]:
                thumb=pin._thumbnail
                thumb._size=state["thumb_size"]
                thumb._prev_geometry=QRect(pos,normal.size())
                thumb._scene_center=QPointF(*state["thumb_center"])
                thumb._active=True
                from PySide6.QtCore import QSize
                point,shifted=visible_position(state["position"],QSize(thumb.size,thumb.size),screens)
                pin.setGeometry(point.x(),point.y(),thumb.size,thumb.size)
                thumb.update_view();pin._ocr_mgr.set_enabled(False);pin._set_control_buttons_visible(False)
                relocated=relocated or shifted
            elif state["toolbar"]:
                pin.show_toolbar()
            pin.show()
            restored.append(pin)
            display_pixels+=normal.width()*normal.height()
            if relocated:moved.append(index)
        except Exception as exc:
            if pin is not None:
                pin.close_window()
            errors.append((index,str(exc)))
    return restored,errors,moved
