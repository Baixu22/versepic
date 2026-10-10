"""File image editor reusing the existing PinCanvas, CanvasView and annotation tools."""
from dataclasses import replace
from pathlib import Path
import threading

from PySide6.QtCore import QRectF, QSizeF, QThread, QTimer, Qt
from PySide6.QtGui import QColor, QImage, QPainterPath, QPen, QUndoCommand
from PySide6.QtWidgets import (QApplication, QDialog, QFormLayout, QHBoxLayout, QScrollArea,
                               QFileDialog, QVBoxLayout, QWidget)

from canvas import CanvasView
from core.export import ExportService
from core.image_document import ImageGeometry, load_editor_image, same_file
from core.save import SaveService
from core.ui_scale import configure_dialog_control, dialog_scaled, scale_dialog_font
from core.ui_theme import get_ui_theme
from pin.pin_canvas import PinCanvas
from pin.pin_toolbar import PinToolbar
from settings import get_tool_settings_manager
from ui.dialogs import show_confirm_dialog
from ui.fluent_lite import BodyLabel, CaptionLabel, ComboBox, PrimaryPushButton, PushButton, SpinBox


class EditorToolbar(PinToolbar):
    """The same annotation toolbar, embedded in a normal window rather than a floating pin."""
    def position_near_window(self, pin_window):
        pass

    def _reposition_self(self):
        pass


class EditorView(CanvasView):
    def __init__(self, scene, editor):
        super().__init__(scene, editor, cross_tool_select=editor.config_manager.get_cross_tool_selection_enabled())
        self.editor = editor
        self.crop_start = None
        self.crop_inverse = None
        self.crop_preview = QRectF()
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setAcceptDrops(False)
        self.viewport().setAcceptDrops(False)

    def mousePressEvent(self, event):
        if not self.editor.geometry_state.scene_rect().contains(self.mapToScene(event.position().toPoint())):
            event.accept()
            return
        if self.editor.crop_button.isChecked() and event.button() == Qt.MouseButton.LeftButton:
            self.crop_inverse = self.viewportTransform().inverted()[0]
            self.crop_start = self.crop_inverse.map(event.position())
            self.crop_preview = QRectF()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.crop_start is not None:
            self.crop_preview = QRectF(self.crop_start, self.crop_inverse.map(event.position())).normalized().intersected(self.editor.geometry_state.scene_rect())
            self.viewport().update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.crop_start is not None and event.button() == Qt.MouseButton.LeftButton:
            rect = QRectF(self.crop_start, self.crop_inverse.map(event.position())).normalized().intersected(self.editor.geometry_state.scene_rect()).toAlignedRect()
            self.crop_start = None
            self.crop_preview = QRectF()
            if rect.width() > 0 and rect.height() > 0:
                self.editor.set_geometry(replace(self.editor.geometry_state, crop=(rect.x(),rect.y(),rect.width(),rect.height()), output_width=0), self.editor.tr("Crop"))
            self.editor.crop_button.setChecked(False)
            self.viewport().update()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def drawForeground(self, painter, rect):
        super().drawForeground(painter, rect)
        if self.editor.geometry_state is not None:
            outside = QPainterPath()
            outside.addRect(rect)
            inside = QPainterPath()
            inside.addRect(self.editor.geometry_state.scene_rect())
            painter.fillPath(outside.subtracted(inside), QColor(get_ui_theme().tokens.surface_subtle))
        if not self.crop_preview.isEmpty():
            pen = QPen(QColor("#22d3ee"), 2, Qt.PenStyle.DashLine)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(self.crop_preview)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "editor"):
            self.editor.fit_view()

    def keyPressEvent(self, event):
        if self._is_text_editing():
            super().keyPressEvent(event)
            return
        self.editor.handle_editor_key(event)


class _GeometryCommand(QUndoCommand):
    def __init__(self, editor, state, label):
        super().__init__(label)
        self.editor, self.before, self.after = editor, editor.geometry_state, state

    def redo(self):
        self.editor._apply_geometry(self.after)

    def undo(self):
        self.editor._apply_geometry(self.before)


class GeometryEditor(QDialog):
    def __init__(self, state, size, parent):
        super().__init__(parent)
        scale_dialog_font(self)
        self.setWindowTitle(self.tr("Crop and Resize"))
        self.original, self.size = state, size
        layout = QVBoxLayout(self)
        hint = CaptionLabel(self.tr("Crop coordinates refer to the original image. Rotation and flipping preserve editable annotations. Output width 0 keeps the cropped image size."), self)
        configure_dialog_control(hint)
        layout.addWidget(hint)
        form = QFormLayout()
        self.fields = {}
        for key, label, value, low, high in (
            ("x", "X", state.crop[0], 0, size.width()-1), ("y", "Y", state.crop[1], 0, size.height()-1),
            ("width", "Crop width", state.crop[2], 1, size.width()), ("height", "Crop height", state.crop[3], 1, size.height()),
            ("output", "Output width (0 = original)", state.output_width, 0, 16384),
        ):
            control = SpinBox(self)
            configure_dialog_control(control)
            control.setRange(low, high)
            control.setValue(value)
            control.setKeyboardTracking(False)
            text = BodyLabel(self.tr(label), self)
            configure_dialog_control(text)
            form.addRow(text, control)
            self.fields[key] = control
            control.valueChanged.connect(self.validate)
        layout.addLayout(form)
        self.status = CaptionLabel(self)
        configure_dialog_control(self.status)
        layout.addWidget(self.status)
        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = PushButton(self.tr("Cancel"), self)
        self.apply_button = PrimaryPushButton(self.tr("Apply"), self)
        for button in (cancel, self.apply_button):
            configure_dialog_control(button)
            buttons.addWidget(button)
        cancel.clicked.connect(self.reject)
        self.apply_button.clicked.connect(self.accept)
        layout.addLayout(buttons)
        get_ui_theme().theme_changed.connect(self._theme)
        self._theme()
        self.resize(dialog_scaled(460), self.sizeHint().height())
        self.validate()

    def _theme(self,*_):
        self.setStyleSheet(f"QDialog {{ background: {get_ui_theme().tokens.window}; }}")

    def state(self):
        return replace(self.original, crop=tuple(self.fields[k].value() for k in ("x","y","width","height")), output_width=self.fields["output"].value())

    def validate(self, *_):
        if not hasattr(self, "apply_button"):
            return
        try:
            state = self.state()
            state.validate(self.size)
            size = state.output_size()
            self.status.setText(self.tr("Output: %1 × %2 px").replace("%1", str(size.width())).replace("%2", str(size.height())))
            self.apply_button.setEnabled(True)
        except ValueError:
            self.status.setText(self.tr("Crop or output dimensions are outside the image limits."))
            self.apply_button.setEnabled(False)

    def accept(self):
        for field in self.fields.values():
            field.interpretText()
        self.validate()
        if self.apply_button.isEnabled():
            super().accept()


class _SaveProject(QThread):
    def __init__(self,destination,manifest,assets,service,parent):
        super().__init__(parent)
        self.destination,self.manifest,self.assets,self.service=destination,manifest,assets,service
        self.cancel=threading.Event()
        self.ok=False
        self.image=QImage()  # common completion cleanup

    def run(self):
        from core.editable_project import write_project
        try:
            self.ok=write_project(self.destination,self.manifest,self.assets,self.service,cancelled=self.cancel.is_set)
        except Exception:
            self.ok=False
        finally:
            self.assets={}
            self.manifest=b""


class _SaveEditedImage(QThread):
    def __init__(self, image, destination, source, service, options, parent):
        super().__init__(parent)
        self.image, self.destination, self.source = image, destination, source
        self.service, self.options = service, options
        self.cancel = threading.Event()
        self.ok = False

    def run(self):
        try:
            if not same_file(self.source, self.destination):
                self.ok = self.service.save_qimage_to_path(self.image, self.destination, output_options=self.options, cancelled=self.cancel.is_set)
        except Exception:
            self.ok = False


class ImageEditor(QWidget):
    def __init__(self, config=None):
        super().__init__()
        scale_dialog_font(self)
        self.setWindowTitle(self.tr("Image Editor"))
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setAcceptDrops(True)
        self.config_manager = config or get_tool_settings_manager()
        self.canvas = self.view = self.toolbar = None
        self.source_path = None
        self.geometry_state = None
        self._is_editing = False
        self._loading = False
        self._worker = None
        self._close_pending = False
        self._geometry_dialog = None
        self._force_close = False
        self._shutdown = False
        self._saved_token = None
        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(*[dialog_scaled(14)]*4)
        self._root.setSpacing(dialog_scaled(10))
        self.file_controls = QWidget(self)
        row = QHBoxLayout(self.file_controls)
        row.setContentsMargins(0,0,0,0)
        for label, callback in (("Open image…", self.open_dialog), ("Save as…", self.save_image), ("Save project…", self.save_project_dialog), ("Recognize text", self.recognize)):
            button = PushButton(self.tr(label), self)
            configure_dialog_control(button)
            button.clicked.connect(callback)
            row.addWidget(button)
        self._root.addWidget(self.file_controls)
        self.geometry_controls = QWidget(self)
        row = QHBoxLayout(self.geometry_controls)
        row.setContentsMargins(0,0,0,0)
        self.crop_button = PushButton(self.tr("Crop by dragging"), self)
        configure_dialog_control(self.crop_button)
        self.crop_button.setCheckable(True)
        self.crop_button.toggled.connect(self._crop_mode)
        row.addWidget(self.crop_button)
        for label, callback in (("Crop / resize…", self.edit_geometry), ("Rotate left", lambda: self.transform("left")),
                                ("Rotate right", lambda: self.transform("right")), ("Flip horizontal", lambda: self.transform("horizontal")),
                                ("Flip vertical", lambda: self.transform("vertical"))):
            button = PushButton(self.tr(label), self)
            configure_dialog_control(button)
            button.clicked.connect(callback)
            row.addWidget(button)
        self.zoom = ComboBox(self)
        configure_dialog_control(self.zoom)
        self.zoom.addItem(self.tr("Fit"), "fit")
        for percent in (50,100,200,400):
            self.zoom.addItem(str(percent)+"%", percent/100)
        self.zoom.currentIndexChanged.connect(self.fit_view)
        row.addWidget(self.zoom)
        self._root.addWidget(self.geometry_controls)
        self.toolbar_area = QScrollArea(self)
        self.toolbar_area.setWidgetResizable(False)
        self.toolbar_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.toolbar_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._root.addWidget(self.toolbar_area)
        self.view_host = QVBoxLayout()
        self.placeholder = CaptionLabel(self.tr("Open or drop one PNG, JPEG, BMP or WebP image. The source file is never overwritten."), self)
        configure_dialog_control(self.placeholder)
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.placeholder.setAcceptDrops(False)
        self.view_host.addWidget(self.placeholder, 1)
        self._root.addLayout(self.view_host, 1)
        self.status = CaptionLabel(self)
        configure_dialog_control(self.status)
        self._root.addWidget(self.status)
        self.cancel_save = PushButton(self.tr("Cancel save"), self)
        configure_dialog_control(self.cancel_save)
        self.cancel_save.clicked.connect(self.cancel_saving)
        self.cancel_save.hide()
        self._root.addWidget(self.cancel_save)
        self.geometry_controls.setEnabled(False)
        self.toolbar_area.hide()
        self.resize(dialog_scaled(1120), dialog_scaled(760))
        bounds = QApplication.primaryScreen().availableGeometry()
        self.resize(min(self.width(),bounds.width()-40),min(self.height(),bounds.height()-40))
        get_ui_theme().theme_changed.connect(self._theme)
        QApplication.instance().aboutToQuit.connect(self.shutdown)
        self._theme()

    def _theme(self,*_):
        tokens=get_ui_theme().tokens
        self.setStyleSheet(f"ImageEditor {{ background: {tokens.window}; }} QScrollArea {{ border: 1px solid {tokens.border}; background: {tokens.surface}; }}")
        if self.view:
            self.view.setBackgroundBrush(QColor(tokens.surface_subtle))

    def _dispose_canvas(self):
        if self.view:
            self.view.cleanup()
            self.view_host.removeWidget(self.view)
            self.view.setScene(None)
            self.view.deleteLater()
            self.view = None
        if self.toolbar:
            self.toolbar._hide_all_panels()
            self.toolbar.hide()
        if self.canvas:
            self.canvas.cleanup()
            self.canvas.deleteLater()
            self.canvas = None
        if self.toolbar:
            for name in ("paint_panel","shape_panel","arrow_panel","number_panel","text_panel","mosaic_panel"):
                panel=getattr(self.toolbar,name,None)
                if panel:
                    panel.close()
                    panel.deleteLater()
            toolbar=self.toolbar_area.takeWidget()
            if toolbar:
                toolbar.deleteLater()
            self.toolbar=None

    def _end_edit(self):
        if self.canvas:
            self.canvas.deactivate_tool()
            self.canvas.scene.editing_cleanup_requested.emit()
            self.canvas.scene.clearFocus()
            if self.toolbar:
                self.toolbar._hide_all_panels()
                for button in self.toolbar.tool_buttons.values():
                    button.setChecked(False)
                self.toolbar.current_tool=None
        self.crop_button.setChecked(False)

    def _token(self):
        if not self.canvas:
            return None
        from PySide6.QtWidgets import QGraphicsTextItem
        texts = tuple(sorted((id(item), item.document().toHtml()) for item in self.canvas.scene.items()
                             if isinstance(item, QGraphicsTextItem)))
        return (self.canvas.undo_stack.index(),texts,self.geometry_state)

    def has_changes(self):
        return self.canvas is not None and (not self.canvas.undo_stack.isClean() or self._token()!=self._saved_token)

    def confirm_discard(self):
        self._end_edit()
        return not self.has_changes() or show_confirm_dialog(self,self.tr("Unsaved image"),
                self.tr("Discard the unsaved edits? The source image will stay unchanged."))

    def open_dialog(self):
        if self._worker:
            return
        filename,_=QFileDialog.getOpenFileName(self,self.tr("Open image"),"","Images and projects (*.png *.jpg *.jpeg *.bmp *.webp *.vpic);;Editable project (*.vpic)")
        if filename:
            self.open_file(filename)

    def open_file(self,filename):
        if self._worker or self._loading or self._shutdown:
            return False
        # Validate bytes before asking to discard edits; prepare the replacement off-screen.
        try:
            project=None
            if Path(filename).suffix.lower()==".vpic":
                from core.editable_project import read_project
                project=read_project(filename)
                image,resolved=project.image,str(Path(filename).resolve())
            else:
                image, resolved=load_editor_image(filename)
        except Exception:
            self.status.setText(self.tr("Could not open image or project. Check the format, version and resource limits."))
            return False
        return self._load_document(image,resolved,project)

    def _load_document(self,image,resolved,project=None):
        if self._worker or self._loading or self._shutdown or not self.confirm_discard():
            return False
        self._loading=True
        canvas=view=toolbar=None
        try:
            try:
                canvas=PinCanvas(self,image.size(),image)
                canvas.scene.selection_model.min_size=QSizeF(1,1)
                canvas.scene.selection_model.initialize_confirmed_rect(QRectF(0,0,image.width(),image.height()))
                canvas.scene.selection_item.hide()
                canvas.scene.selection_item.setEnabled(False)
                if project is not None:
                    project.populate(canvas)
                view=EditorView(canvas.scene,self)
                view.hide()
                toolbar=EditorToolbar(self,self.config_manager)
                toolbar.hide()
            except Exception:
                if view:
                    view.cleanup()
                    view.setScene(None)
                    view.deleteLater()
                if canvas:
                    canvas.cleanup()
                    canvas.deleteLater()
                if toolbar:
                    toolbar.deleteLater()
                self.status.setText(self.tr("Could not allocate the editor canvas. Existing edits were kept."))
                return False
            self._dispose_canvas()
            self.source_path=resolved
            self.geometry_state=project.geometry if project is not None else ImageGeometry((0,0,image.width(),image.height()))
            self.canvas,self.view,self.toolbar=canvas,view,toolbar
            self.view_host.addWidget(view,1)
            self.placeholder.hide()
            toolbar.setParent(self.toolbar_area)
            toolbar.setWindowFlags(Qt.WindowType.Widget)
            self.toolbar_area.setWidget(toolbar)
            self.toolbar_area.setFixedHeight(toolbar.height()+dialog_scaled(24))
            self.toolbar_area.show()
            toolbar.show()
            canvas.connect_toolbar(toolbar,view)
            toolbar.tool_changed.connect(lambda *_:self.crop_button.setChecked(False))
            canvas.undo_stack.indexChanged.connect(self._changed)
            self._apply_geometry(self.geometry_state)
            self._saved_token=self._token()
            canvas.undo_stack.setClean()
            self.geometry_controls.setEnabled(True)
            self._theme()
            self.setWindowTitle(self.tr("Image Editor")+" — "+(Path(resolved).name if resolved else self.tr("Untitled project")))
            view.show()
            view.setFocus()
            QTimer.singleShot(0,self,self.fit_view)
            return True
        finally:
            self._loading=False

    def _changed(self,*_):
        if self.canvas:
            size=self.geometry_state.output_size()
            self.status.setText(self.tr("Output: %1 × %2 px · Images are flattened; projects retain original pixels and annotations.").replace("%1",str(size.width())).replace("%2",str(size.height())))

    def _apply_geometry(self,state):
        self.geometry_state=state
        if self.canvas:
            self.canvas.scene.selection_model.set_rect(state.scene_rect())
            self.view.setSceneRect(state.scene_rect())
            self.fit_view()
            self._changed()

    def set_geometry(self,state,label):
        if not self.canvas or self._worker:
            return False
        try:
            state.validate(self.canvas.base_size)
        except ValueError:
            self.status.setText(self.tr("Crop or output dimensions are outside the image limits."))
            return False
        if state==self.geometry_state:
            return False
        self._end_edit()
        self.canvas.undo_stack.push_command(_GeometryCommand(self,state,label))
        return True

    def transform(self,kind):
        if not self.canvas or self._worker:
            return
        state=self.geometry_state
        if kind in ("left","right"):
            state=replace(state,rotation=(state.rotation+(90 if kind=="right" else -90))%360,output_width=0)
        elif kind=="horizontal":
            state=replace(state,flip_h=not state.flip_h)
        elif kind=="vertical":
            state=replace(state,flip_v=not state.flip_v)
        self.set_geometry(state,self.tr("Transform image"))

    def _crop_mode(self,enabled):
        if not self.canvas:
            return
        if enabled:
            self.canvas.deactivate_tool()
            self.toolbar._hide_all_panels()
            self.canvas.scene.editing_cleanup_requested.emit()
            self.view.setCursor(Qt.CursorShape.CrossCursor)
        else:
            self.view.crop_start=None
            self.view.crop_inverse=None
            self.view.crop_preview=QRectF()
            self.view.viewport().update()
            self.view.setCursor(Qt.CursorShape.ArrowCursor)

    def edit_geometry(self):
        if not self.canvas or self._worker:
            return
        self._end_edit()
        dialog=GeometryEditor(self.geometry_state,self.canvas.base_size,self)
        self._geometry_dialog=dialog
        try:
            if dialog.exec()==QDialog.DialogCode.Accepted:
                self.set_geometry(dialog.state(),self.tr("Crop and resize"))
        finally:
            self._geometry_dialog=None
            dialog.deleteLater()

    def fit_view(self,*_):
        if self._loading:
            return
        if not self.view or not self.geometry_state or self.view.crop_start is not None:
            return
        state=self.geometry_state
        base=self.canvas.base_size
        display=state.transform().display_size(base)
        transform=state.transform().build_view_transform(display.width(),display.height(),base.width(),base.height())
        self.view.setTransform(transform)
        if self.zoom.currentData()=="fit":
            self.view.fitInView(state.scene_rect(),Qt.AspectRatioMode.KeepAspectRatio)
        else:
            factor=float(self.zoom.currentData())
            self.view.scale(factor,factor)
        self.view.centerOn(state.scene_rect().center())

    def render_image(self):
        if not self.canvas:
            raise ValueError("No image loaded")
        self._end_edit()
        state=self.geometry_state
        state.validate(self.canvas.base_size)
        image=ExportService(self.canvas.scene).export_with_legend(state.scene_rect())
        return state.apply_to_pixels(image)

    def save_image(self):
        if not self.canvas or self._worker:
            return
        default=str(Path(self.source_path).with_name(Path(self.source_path).stem+"-edited.png")) if self.source_path else "image-edited.png"
        destination,selected=QFileDialog.getSaveFileName(self,self.tr("Save edited image"),default,
                       "PNG (*.png);;JPEG (*.jpg);;WebP (*.webp);;BMP (*.bmp);;PDF (*.pdf)")
        if not destination:
            return
        if not Path(destination).suffix:
            destination+="."+selected.split("*.")[1].split(")")[0]
        self.start_save(destination)

    def save_project_dialog(self):
        if not self.canvas or self._worker:
            return
        # A project intentionally retains original pixels. Never label this as redaction-safe export.
        if not show_confirm_dialog(self,self.tr("Editable project contains original pixels"),
                self.tr("Projects retain the original image, cropped-out pixels and removable annotations. Do not share them as redacted images. Continue?")):
            return
        default=str(Path(self.source_path).with_suffix(".vpic")) if self.source_path else "image.vpic"
        destination,_=QFileDialog.getSaveFileName(self,self.tr("Save editable project"),default,"VersePic project (*.vpic)")
        if destination:
            if not Path(destination).suffix:destination+=".vpic"
            self.start_project_save(destination)

    def start_project_save(self,destination):
        if not self.canvas or self._worker or Path(destination).suffix.lower()!=".vpic":
            return False
        if self.source_path and Path(self.source_path).suffix.lower()!=".vpic" and same_file(self.source_path,destination):
            self.status.setText(self.tr("Choose a different file. The source image cannot be overwritten."))
            return False
        try:
            from core.editable_project import snapshot_project
            self._end_edit()
            manifest,assets=snapshot_project(self.canvas.scene,self.geometry_state)
        except Exception:
            self.status.setText(self.tr("Could not save this project: unsupported annotation or resource limit. Edits were kept."))
            return False
        self._worker=_SaveProject(str(destination),manifest,assets,SaveService(self.config_manager),self)
        self._worker.finished.connect(self._save_finished)
        self._set_busy(True)
        self.status.setText(self.tr("Saving editable project…"))
        self._worker.start()
        return True

    def start_save(self,destination):
        if not self.canvas or self._worker:
            return False
        if same_file(self.source_path,destination):
            self.status.setText(self.tr("Choose a different file. The source image cannot be overwritten."))
            return False
        if Path(destination).suffix.lower() not in (".png",".jpg",".jpeg",".webp",".bmp",".pdf"):
            self.status.setText(self.tr("Choose PNG, JPEG, WebP, BMP or PDF for the output."))
            return False
        try:
            image=self.render_image()
        except Exception:
            self.status.setText(self.tr("Could not render this image. Reduce the output dimensions."))
            return False
        service=SaveService(self.config_manager)
        options=replace(service.output_options(),size_mode="original")
        self._worker=_SaveEditedImage(image,str(destination),self.source_path,service,options,self)
        self._worker.finished.connect(self._save_finished)
        self._set_busy(True)
        self.status.setText(self.tr("Saving…"))
        self._worker.start()
        return True

    def _set_busy(self,busy):
        self.file_controls.setEnabled(not busy)
        self.geometry_controls.setEnabled(not busy)
        self.toolbar_area.setEnabled(not busy)
        if self.view:self.view.setEnabled(not busy)
        self.cancel_save.setVisible(busy)

    def cancel_saving(self):
        if self._worker:
            self._worker.cancel.set()
            self.status.setText(self.tr("Cancelling save…"))

    def _save_finished(self):
        worker=self._worker
        self._worker=None
        if self._shutdown:
            worker.image=QImage()
            worker.deleteLater()
            return
        self._set_busy(False)
        if worker.ok:
            self._saved_token=self._token()
            self.canvas.undo_stack.setClean()
            self.status.setText(self.tr("Editable project saved. It contains original pixels; use image export for sharing.") if isinstance(worker,_SaveProject) else self.tr("Edited image saved. Source file unchanged."))
        else:
            self.status.setText(self.tr("Save cancelled. Edits are still available.") if worker.cancel.is_set() else self.tr("Save failed. Edits and the existing file were kept."))
        worker.image=QImage()
        worker.deleteLater()
        if self._close_pending:
            self._close_pending=False
            self.close()

    def copy_to_clipboard(self):
        if self.canvas and not self._worker:
            from core.clipboard_utils import copy_image_to_clipboard
            copy_image_to_clipboard(self.render_image())
            self.status.setText(self.tr("Edited image copied."))

    def recognize(self):
        if self.canvas and not self._worker:
            from text_recognition import show_text_recognition
            show_text_recognition(self.render_image(),self)

    def handle_editor_key(self,event):
        if QApplication.activeModalWidget() is not None or self._worker:
            event.ignore()
            return
        ctrl=bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
        shift=bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        if ctrl and event.key()==Qt.Key.Key_O:self.open_dialog()
        elif ctrl and event.key()==Qt.Key.Key_S:self.save_image()
        elif self.canvas and ctrl and event.key()==Qt.Key.Key_Z:
            self.canvas.undo_stack.redo() if shift else self.canvas.undo_stack.undo()
        elif self.canvas and ctrl and event.key()==Qt.Key.Key_Y:self.canvas.undo_stack.redo()
        elif self.canvas and ctrl and event.key()==Qt.Key.Key_C:self.copy_to_clipboard()
        elif self.canvas and event.key()==Qt.Key.Key_Delete:self.view.smart_edit_controller.delete_selected()
        elif event.key()==Qt.Key.Key_Escape:self._end_edit()
        else:
            event.ignore()
            return
        event.accept()

    def keyPressEvent(self,event):
        self.handle_editor_key(event)

    def _drop_path(self,mime):
        urls=mime.urls()
        if len(urls)==1 and urls[0].isLocalFile() and Path(urls[0].toLocalFile()).suffix.lower() in (".png",".jpg",".jpeg",".webp",".bmp",".vpic"):
            return urls[0].toLocalFile()
        return None

    def dragEnterEvent(self,event):
        if not self._worker and self._drop_path(event.mimeData()):event.acceptProposedAction()
        else:event.ignore()

    def dropEvent(self,event):
        filename=self._drop_path(event.mimeData())
        if filename and self.open_file(filename):event.acceptProposedAction()
        else:event.ignore()

    def shutdown(self):
        if self._shutdown:
            return
        self._shutdown=True
        self._force_close=True
        if self._geometry_dialog:self._geometry_dialog.reject()
        if self._worker:
            self._worker.cancel.set()
            self._worker.wait()
            self._worker.image=QImage()
        self._dispose_canvas()

    def closeEvent(self,event):
        if self._shutdown:
            super().closeEvent(event)
            return
        if self._worker is not None:
            self._close_pending=True
            self.cancel_saving()
            event.ignore()
            return
        if not self._force_close and not self.confirm_discard():
            event.ignore()
            return
        self.shutdown()
        super().closeEvent(event)


def show_image_editor(filename=None):
    app=QApplication.instance()
    editor=getattr(app,"_file_image_editor",None)
    if editor is None:
        editor=ImageEditor()
        app._file_image_editor=editor
        editor.destroyed.connect(lambda:setattr(app,"_file_image_editor",None))
    editor.show()
    editor.raise_()
    editor.activateWindow()
    if filename:editor.open_file(filename)
    return editor


def open_scene_as_project(scene, *, region=None, geometry=None):
    """Transfer snapshot data to the shared editor; never auto-write an editable file."""
    from core.editable_project import project_from_scene
    if region is None:
        size=scene.background.image().size()
    else:
        size=region.toAlignedRect().size()
    geometry=geometry or ImageGeometry((0,0,size.width(),size.height()))
    project=project_from_scene(scene,geometry,region=region)
    editor=show_image_editor()
    if not editor._load_document(project.image,None,project):
        return None
    editor._saved_token=None  # the imported scene has not been saved anywhere
    return editor
