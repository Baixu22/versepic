"""Two read-only image views: synchronized pan/zoom, wipe and pixel difference."""
import threading
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QThread, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QFileDialog, QFrame, QGraphicsItem,
                               QGraphicsScene, QGraphicsView, QHBoxLayout, QSlider, QVBoxLayout, QWidget)

from core.image_compare import CompareCancelled, MAX_COMPARE_PIXELS, difference_overlay, validate_pair
from core.image_layout import MAX_ENCODED_BYTES, decode_image
from core.ui_scale import configure_dialog_control, dialog_scaled, scale_dialog_font
from core.ui_theme import get_ui_theme
from ui.fluent_lite import BodyLabel, CaptionLabel, ComboBox, PushButton, SpinBox
from ui.image_layout_dialog import ImageSourcePicker


class ComparisonItem(QGraphicsItem):
    def __init__(self,window,side):
        super().__init__();self.window=window;self.side=side

    def boundingRect(self):
        return QRectF(self.window.canvas_rect)

    def refresh_geometry(self):
        self.prepareGeometryChange()

    def paint(self,painter,option,widget=None):
        window=self.window;rect=self.boundingRect()
        if rect.isEmpty():return
        painter.fillRect(rect,QColor(get_ui_theme().tokens.surface_subtle))
        # Texture represents transparency and absent source pixels, not image content.
        painter.fillRect(rect,QColor(128,128,128,70))
        brush=QColor(128,128,128,60)
        from PySide6.QtGui import QBrush
        painter.fillRect(rect,QBrush(brush,Qt.BrushStyle.Dense4Pattern))
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform,False)
        def draw(index):
            image=window.images[index]
            if image is None:return
            target=QRectF(0,0,image.width(),image.height())
            if index==1 and window.alignment.currentData()=="scale_b" and window.images[0] is not None:
                target=QRectF(0,0,window.images[0].width(),window.images[0].height())
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform,index==1 and window.alignment.currentData()=="scale_b")
            painter.drawImage(target,image,QRectF(0,0,image.width(),image.height()))
        mode=window.mode.currentData()
        if mode=="side":draw(self.side)
        elif mode=="wipe":
            boundary=rect.width()*window.split.value()/100
            painter.save();painter.setClipRect(QRectF(0,0,boundary,rect.height()));draw(0);painter.restore()
            painter.save();painter.setClipRect(QRectF(boundary,0,rect.width()-boundary,rect.height()));draw(1);painter.restore()
            pen=QPen(QColor("#0ea5e9"),2);pen.setCosmetic(True);painter.setPen(pen)
            painter.drawLine(QPointF(boundary,0),QPointF(boundary,rect.height()))
        else:
            draw(1)
            if window.result is not None:
                painter.drawImage(QPointF(0,0),window.result.overlay)


class ComparisonView(QGraphicsView):
    navigated=Signal(object)
    zoom_requested=Signal(float)

    def __init__(self,window,side):
        super().__init__(window);self.owner=window;self._wiping=False
        scene=QGraphicsScene(self);self.setScene(scene)
        self.item=ComparisonItem(window,side);scene.addItem(self.item)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.NoAnchor)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.NoAnchor)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(dialog_scaled(150),dialog_scaled(180))
        self.horizontalScrollBar().valueChanged.connect(self._navigated)
        self.verticalScrollBar().valueChanged.connect(self._navigated)
        self.setAccessibleName(window.tr("Image A") if side==0 else window.tr("Image B"))

    def _navigated(self,*_):
        if not self.owner._syncing:
            self.navigated.emit(self.mapToScene(self.viewport().rect().center()))

    def wheelEvent(self,event):
        if event.angleDelta().y():
            self.zoom_requested.emit(1.25 if event.angleDelta().y()>0 else 0.8)
        event.accept()

    def mousePressEvent(self,event):
        if self.owner.mode.currentData()=="wipe" and event.button()==Qt.MouseButton.LeftButton:
            edge=self.mapFromScene(QPointF(self.owner.canvas_rect.width()*self.owner.split.value()/100,0)).x()
            if abs(event.position().x()-edge)<=10:
                self._wiping=True;event.accept();return
        super().mousePressEvent(event)

    def mouseMoveEvent(self,event):
        if self._wiping:
            point=self.mapToScene(event.position().toPoint())
            if self.owner.canvas_rect.width()>0:
                self.owner.split.setValue(max(0,min(100,round(point.x()*100/self.owner.canvas_rect.width()))))
            event.accept();return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self,event):
        if self._wiping:
            self._wiping=False;event.accept();return
        super().mouseReleaseEvent(event)


class _CompareWorker(QThread):
    def __init__(self,images,alignment,threshold,revision,parent):
        super().__init__(parent)
        self.images=images;self.alignment=alignment;self.threshold=threshold;self.revision=revision
        self.cancel=threading.Event();self.result=None;self.error=False

    def run(self):
        try:self.result=difference_overlay(*self.images,self.alignment,self.threshold,cancelled=self.cancel.is_set)
        except CompareCancelled:pass
        except Exception:self.error=True
        finally:self.images=[]


class ImageCompareWindow(QWidget):
    def __init__(self):
        super().__init__();scale_dialog_font(self)
        self.setWindowTitle(self.tr("Image Comparison"))
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.images=[None,None];self.names=["",""];self.canvas_rect=QRectF()
        self.result=None;self._worker=None;self._revision=0;self._result_revision=-1;self._invalid_geometry=False
        self._syncing=False;self._scale=1.;self._fit=True;self._closing=False;self._shutdown=False
        self._timer=QTimer(self);self._timer.setSingleShot(True);self._timer.setInterval(80)
        self._timer.timeout.connect(self._start_diff)
        root=QVBoxLayout(self);root.setContentsMargins(*[dialog_scaled(16)]*4);root.setSpacing(dialog_scaled(10))
        row=QHBoxLayout()
        self.slot=ComboBox(self);self.slot.addItem(self.tr("Replace image A"),0);self.slot.addItem(self.tr("Replace image B"),1)
        configure_dialog_control(self.slot);row.addWidget(self.slot)
        for text,callback in (("Choose file…",self.choose_file),("Choose history image…",self.choose_history),
                              ("Choose pinned image…",self.choose_pin),("Swap A / B",self.swap),("Clear images",self.clear)):
            button=PushButton(self.tr(text),self);configure_dialog_control(button);button.clicked.connect(callback);row.addWidget(button)
        root.addLayout(row)
        row=QHBoxLayout();self.mode=ComboBox(self)
        for title,value in (("Side by side","side"),("Slider comparison","wipe"),("Difference overlay","difference")):
            self.mode.addItem(self.tr(title),value)
        self.alignment=ComboBox(self)
        self.alignment.addItem(self.tr("Original pixels, align top-left"),"original")
        self.alignment.addItem(self.tr("Resize B to A (may distort)"),"scale_b")
        for control in (self.mode,self.alignment):configure_dialog_control(control);row.addWidget(control)
        self.threshold=SpinBox(self);configure_dialog_control(self.threshold);self.threshold.setRange(0,255)
        self.threshold.setAccessibleName(self.tr("Pixel difference threshold"))
        label=BodyLabel(self.tr("Threshold"),self);configure_dialog_control(label);row.addWidget(label);row.addWidget(self.threshold)
        fit=PushButton(self.tr("Fit"),self);configure_dialog_control(fit);fit.clicked.connect(self.fit);row.addWidget(fit)
        original=PushButton("100%",self);configure_dialog_control(original);original.clicked.connect(lambda:self.set_zoom(1));row.addWidget(original)
        self.zoom_label=CaptionLabel("100%",self);configure_dialog_control(self.zoom_label);row.addWidget(self.zoom_label)
        root.addLayout(row)
        self.hint=CaptionLabel(self.tr("Read-only comparison. Original pixels align at the top-left; missing areas are differences. Wheel zooms both views; drag pans. Resizing B may introduce interpolation differences. Pixel differences are not a correctness verdict."),self)
        configure_dialog_control(self.hint);root.addWidget(self.hint)
        self.split=QSlider(Qt.Orientation.Horizontal,self);self.split.setRange(0,100);self.split.setValue(50)
        self.split.setAccessibleName(self.tr("A / B split position"));root.addWidget(self.split)
        pair=QHBoxLayout();self.panes=[];self.labels=[];self.views=[]
        for index in range(2):
            pane=QWidget(self);layout=QVBoxLayout(pane);layout.setContentsMargins(0,0,0,0)
            label=BodyLabel(self.tr("Image A") if index==0 else self.tr("Image B"),pane)
            configure_dialog_control(label);label.setWordWrap(True);layout.addWidget(label)
            view=ComparisonView(self,index);layout.addWidget(view,1)
            view.navigated.connect(lambda center,source=index:self._pan(source,center))
            view.zoom_requested.connect(lambda factor:self.set_zoom(self._scale*factor))
            pair.addWidget(pane,1);self.panes.append(pane);self.labels.append(label);self.views.append(view)
        root.addLayout(pair,1)
        self.status=CaptionLabel(self.tr("Choose two images to compare. No source files are changed."),self)
        self.status.setTextFormat(Qt.TextFormat.PlainText);configure_dialog_control(self.status);root.addWidget(self.status)
        self.mode.currentIndexChanged.connect(self._mode_changed)
        self.alignment.currentIndexChanged.connect(self._alignment_changed)
        self.threshold.valueChanged.connect(self._invalidate_diff)
        self.split.valueChanged.connect(self._repaint)
        get_ui_theme().theme_changed.connect(self._theme)
        QApplication.instance().aboutToQuit.connect(self.shutdown)
        self.resize(dialog_scaled(1150),dialog_scaled(730))
        bounds=QApplication.primaryScreen().availableGeometry();self.resize(min(self.width(),bounds.width()-40),min(self.height(),bounds.height()-40))
        self._theme();self._mode_changed()

    def _theme(self,*_):
        if self._shutdown:return
        tokens=get_ui_theme().tokens
        self.setStyleSheet(f"ImageCompareWindow {{ background: {tokens.window}; }} QGraphicsView {{ border: 1px solid {tokens.border}; background: {tokens.surface_subtle}; }}")
        self._repaint()

    def _error(self):
        self.status.setText(self.tr("Could not load image: missing data, unsupported format or comparison limit (32 megapixels total). Existing images were kept."))

    def set_image(self,index,image,name):
        if self._shutdown or self._closing:return False
        if index not in (0,1):raise ValueError("Invalid comparison slot")
        proposed=list(self.images);proposed[index]=image
        try:
            validate_pair(image)
            if all(im is not None for im in proposed):validate_pair(*proposed,self.alignment.currentData())
        except ValueError:
            self._error();return False
        self.images[index]=QImage(image)
        self.images[index].setDevicePixelRatio(1)
        self.names[index]=str(name)
        self._update_labels()
        if index==0 and self.images[1] is None:self.slot.setCurrentIndex(1)
        self._geometry_changed();return True

    def _remaining(self,index):
        other=self.images[1-index]
        return MAX_COMPARE_PIXELS-(other.width()*other.height() if other is not None else 0)

    def load_file(self,filename,index=None):
        index=self.slot.currentData() if index is None else index
        try:
            path=Path(filename)
            if path.suffix.lower() not in (".png",".jpg",".jpeg",".bmp",".webp") or path.stat().st_size>MAX_ENCODED_BYTES:raise ValueError()
            with path.open("rb") as file:data=file.read(MAX_ENCODED_BYTES+1)
            image=decode_image(data,self._remaining(index))
            return self.set_image(index,image,path.name)
        except Exception:self._error();return False

    def choose_file(self):
        filename,_=QFileDialog.getOpenFileName(self,self.tr("Choose comparison image"),"","Images (*.png *.jpg *.jpeg *.bmp *.webp)")
        if filename:self.load_file(filename)

    def load_history(self,manager,identifier,index=None):
        index=self.slot.currentData() if index is None else index
        try:
            record=manager.get_item(identifier)
            if record is None or record.content_type!="image" or not record.image_id:raise ValueError()
            image=decode_image(manager.get_image_data(record.image_id),self._remaining(index))
            return self.set_image(index,image,record.title or self.tr("History image %1").replace("%1",str(identifier)))
        except Exception:self._error();return False

    def choose_history(self):
        from clipboard.core import ClipboardManager
        manager=ClipboardManager();picker=ImageSourcePicker(manager=manager,parent=self)
        picker.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        try:
            if picker.exec()==picker.DialogCode.Accepted and len(picker.selected())==1:self.load_history(manager,picker.selected()[0])
        finally:picker.deleteLater()

    def load_pin(self,pin,index=None):
        index=self.slot.currentData() if index is None else index
        try:
            if pin._is_closed:raise ValueError()
            size=pin.canvas.base_size if pin.canvas else pin.size();dpr=pin.devicePixelRatioF()
            if round(size.width()*dpr)*round(size.height()*dpr)>self._remaining(index):raise ValueError()
            images=[]
            pin._with_edit_paused(lambda:images.append(pin.get_current_image()))
            return self.set_image(index,images[0],self.tr("Pinned image"))
        except Exception:self._error();return False

    def choose_pin(self):
        from pin.pin_manager import PinManager
        pins=list(PinManager.instance().get_all_pins());picker=ImageSourcePicker(pins=pins,parent=self)
        picker.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        try:
            if picker.exec()==picker.DialogCode.Accepted and len(picker.selected())==1:self.load_pin(pins[picker.selected()[0]])
        finally:picker.deleteLater()

    def swap(self):
        if self._shutdown:return
        self.images.reverse();self.names.reverse()
        self._update_labels();self._geometry_changed()

    def clear(self):
        if self._shutdown:return
        self.images=[None,None];self.names=["",""];self._update_labels();self._geometry_changed()

    def _update_labels(self):
        for index,image in enumerate(self.images):
            self.labels[index].setText(("A" if index==0 else "B")+(" · "+self.names[index]+f" · {image.width()} × {image.height()} px" if image is not None else ""))
        if self.mode.currentData()!="side":
            first=self.tr("Image A")+" · "+self.names[0] if self.images[0] is not None else self.tr("Image A")
            second=self.tr("Image B")+" · "+self.names[1] if self.images[1] is not None else self.tr("Image B")
            self.labels[0].setText(first+"  ↔  "+second)

    def _alignment_changed(self):
        self._geometry_changed()

    def _geometry_changed(self):
        for view in self.views:view.item.refresh_geometry()
        present=[im for im in self.images if im is not None]
        self._invalid_geometry=False
        try:
            if len(present)==2:size=validate_pair(*self.images,self.alignment.currentData())
            elif present:size=validate_pair(present[0])
            else:size=None
            self.canvas_rect=QRectF(0,0,size.width(),size.height()) if size else QRectF()
        except ValueError:
            self.canvas_rect=QRectF();self._invalid_geometry=True
        self._syncing=True
        try:
            for view in self.views:view.scene().setSceneRect(self.canvas_rect)
        finally:self._syncing=False
        self._invalidate_diff();self.fit()

    def _mode_changed(self,*_):
        side=self.mode.currentData()=="side"
        self._update_labels()
        self.panes[1].setVisible(side);self.split.setVisible(self.mode.currentData()=="wipe")
        self.threshold.setEnabled(self.mode.currentData()=="difference")
        if self.mode.currentData()=="difference":self._timer.start()
        elif self._worker:self._worker.cancel.set()
        self._repaint();QTimer.singleShot(0,self,self.fit)
        self._status()

    def _invalidate_diff(self,*_):
        self._revision+=1;self.result=None;self._result_revision=-1
        if self._worker:self._worker.cancel.set()
        self._timer.start();self._status();self._repaint()

    def _status(self):
        if self._invalid_geometry:
            self.status.setText(self.tr("Comparison canvas exceeds 32 megapixels. Use another image pair or resize B to A."));return
        if self.canvas_rect.isEmpty() or any(image is None for image in self.images):
            self.status.setText(self.tr("Choose two images to compare. No source files are changed."));return
        if self.mode.currentData()=="difference":
            if self.result is None:self.status.setText(self.tr("Comparing pixels…"))
            else:self.status.setText(self.tr("%1 of %2 pixels differ (%3%). Alpha is compared; invisible RGB is ignored.")
                .replace("%1",str(self.result.changed_pixels)).replace("%2",str(self.result.compared_pixels))
                .replace("%3",f"{self.result.changed_pixels*100/self.result.compared_pixels:.2f}"))
        else:self.status.setText(self.tr("Read-only · %1 × %2 comparison pixels · A on the left, B on the right.").replace("%1",str(int(self.canvas_rect.width()))).replace("%2",str(int(self.canvas_rect.height()))))

    def _start_diff(self):
        if self._shutdown or self._closing or self._worker is not None:return
        if self.mode.currentData()!="difference" or self.canvas_rect.isEmpty() or any(image is None for image in self.images):return
        if self._result_revision==self._revision:return
        self._worker=_CompareWorker([QImage(im) for im in self.images],self.alignment.currentData(),self.threshold.value(),self._revision,self)
        self._worker.finished.connect(self._diff_finished);self._worker.start()

    def _diff_finished(self):
        worker=self._worker;self._worker=None
        if not self._shutdown and not self._closing and worker.revision==self._revision and not worker.cancel.is_set():
            self.result=worker.result;self._result_revision=worker.revision
            self._status()
            if worker.error:self.status.setText(self.tr("Comparison failed. Reduce image sizes or choose another pair."))
            self._repaint()
        worker.result=None;worker.deleteLater()
        if self._closing:self.close()
        elif not self._shutdown and self._result_revision!=self._revision:self._timer.start()

    def _repaint(self,*_):
        if self._shutdown:return
        for view in getattr(self,"views",[]):view.item.update()

    def fit(self):
        if self._shutdown or self.canvas_rect.isEmpty():return
        self._fit=True
        visible=[v for index,v in enumerate(self.views) if index==0 or self.mode.currentData()=="side"]
        factor=min(min(max(1,v.viewport().width()-8)/self.canvas_rect.width(),max(1,v.viewport().height()-8)/self.canvas_rect.height()) for v in visible)
        self._apply_zoom(max(.001,min(16.,factor)),self.canvas_rect.center())

    def set_zoom(self,factor):
        if self.canvas_rect.isEmpty() or self._shutdown:return
        self._fit=False
        center=self.views[0].mapToScene(self.views[0].viewport().rect().center())
        self._apply_zoom(max(.01,min(16.,factor)),center)

    def _apply_zoom(self,factor,center):
        self._syncing=True;self._scale=factor
        try:
            for view in self.views:view.resetTransform();view.scale(factor,factor);view.centerOn(center)
        finally:self._syncing=False
        self.zoom_label.setText(f"{factor*100:.1f}%")

    def _pan(self,index,center):
        if self._syncing or self._shutdown:return
        self._syncing=True
        try:self.views[1-index].centerOn(center)
        finally:self._syncing=False

    def resizeEvent(self,event):
        super().resizeEvent(event)
        if hasattr(self,"views") and self._fit:QTimer.singleShot(0,self,self.fit)

    def shutdown(self):
        if self._shutdown:return
        self._shutdown=True;self._timer.stop()
        if self._worker:self._worker.cancel.set();self._worker.wait();self._worker.result=None
        self.result=None;self.images=[None,None]

    def closeEvent(self,event):
        if self._worker is not None and not self._shutdown:
            self._closing=True;self._worker.cancel.set();event.ignore();return
        self.shutdown()
        for view in self.views:view.scene().clear()
        super().closeEvent(event)


def show_image_compare():
    app=QApplication.instance();window=getattr(app,"_image_compare_window",None)
    if window is None:
        window=ImageCompareWindow();app._image_compare_window=window
        window.destroyed.connect(lambda:setattr(app,"_image_compare_window",None))
    window.show();window.raise_();window.activateWindow()
    return window
