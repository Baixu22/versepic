"""Local editable table preview with source-image correspondence and explicit export."""
from PySide6.QtCore import QIODevice, QRectF, QSaveFile, Qt
from PySide6.QtGui import QColor, QImage, QPen, QPixmap
from PySide6.QtWidgets import (QApplication, QDialog, QFileDialog, QGraphicsScene, QGraphicsView,
    QGridLayout, QHBoxLayout, QHeaderView, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout)

from core.ui_scale import configure_dialog_control, dialog_scaled, scale_dialog_font
from core.ui_theme import get_ui_theme
from ui.dialogs import show_confirm_dialog, track_modeless_dialog
from ui.fluent_lite import CaptionLabel, CheckBox, ComboBox, PrimaryPushButton, PushButton, TextEdit
from .table import (MAX_CELLS, MAX_COLUMNS, MAX_ROWS, TableError, reconstruct_table, to_markdown, to_tsv)


class TableSourceView(QGraphicsView):
    def __init__(self, image, parent):
        super().__init__(parent)
        scene = QGraphicsScene(self)
        scene.addPixmap(QPixmap.fromImage(image))
        scene.setSceneRect(QRectF(image.rect()))
        self.setScene(scene)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setMinimumSize(dialog_scaled(180),dialog_scaled(160))
        self._selection = scene.addRect(QRectF(), QPen(QColor("#f59e0b"), 2), QColor(245,158,11,55))
        self._selection.setVisible(False)

    def fit(self):
        self.fitInView(self.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def resizeEvent(self,event):
        super().resizeEvent(event)
        self.fit()

    def wheelEvent(self,event):
        factor = 1.2 if event.angleDelta().y()>0 else 1/1.2
        if .02 <= self.transform().m11()*factor <= 16:
            self.scale(factor,factor)
        event.accept()

    def select_box(self, box):
        self._selection.setVisible(box is not None)
        if box is not None:
            left,top,right,bottom=box
            self._selection.setRect(QRectF(left,top,right-left,bottom-top))


class TableRecognitionWindow(QDialog):
    def __init__(self,image,result,parent=None):
        super().__init__(parent)
        if image is None or image.isNull() or image.width()*image.height()>32_000_000:
            raise TableError("Table preview requires an image up to 32 megapixels")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose,True)
        self.setWindowTitle(self.tr("Review recognized table"))
        scale_dialog_font(self)
        self.image=QImage(image);self.image.setDevicePixelRatio(1)
        self.ocr_result=result
        self._closed=False;self._updating=False;self._dirty=False
        root=QVBoxLayout(self);root.setContentsMargins(*[dialog_scaled(16)]*4);root.setSpacing(dialog_scaled(10))
        hint=CaptionLabel(self.tr("For clear, regular tables with separated OCR cells only. Merged cells, wrapped rows, missing cells and joined OCR lines need manual correction. Click a cell to compare its source region; edit in the cell or the editor below. No cloud upload."),self)
        hint.setWordWrap(True);root.addWidget(hint)
        row=QHBoxLayout()
        self.grouping=ComboBox(self)
        for label,value in ((self.tr("Tight row grouping"),.3),(self.tr("Normal row grouping"),.5),(self.tr("Loose row grouping"),.8)):
            self.grouping.addItem(label,value)
        self.grouping.setCurrentIndex(1)
        self.rebuild_button=PushButton(self.tr("Rebuild from OCR"),self)
        self.fit_button=PushButton(self.tr("Fit source"),self)
        row.addWidget(self.grouping);row.addWidget(self.rebuild_button);row.addWidget(self.fit_button);row.addStretch()
        root.addLayout(row)
        splitter=QSplitter(self)
        self.source=TableSourceView(self.image,self);splitter.addWidget(self.source)
        self.table=QTableWidget(self)
        self.table.setAccessibleName(self.tr("Editable recognized table"))
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setDefaultSectionSize(dialog_scaled(135))
        self.table.verticalHeader().setDefaultSectionSize(dialog_scaled(34))
        splitter.addWidget(self.table);splitter.setStretchFactor(0,1);splitter.setStretchFactor(1,2)
        root.addWidget(splitter,1)
        edit_row=QHBoxLayout()
        self.cell_editor=TextEdit(self);self.cell_editor.setAcceptRichText(False)
        self.cell_editor.setAccessibleName(self.tr("Selected cell text"))
        self.cell_editor.setPlaceholderText(self.tr("Select a cell to edit multiline text"))
        self.cell_editor.setFixedHeight(dialog_scaled(80));edit_row.addWidget(self.cell_editor,1)
        buttons=QGridLayout()
        self.row_add=PushButton(self.tr("Insert row"),self);self.row_remove=PushButton(self.tr("Delete row"),self)
        self.col_add=PushButton(self.tr("Insert column"),self);self.col_remove=PushButton(self.tr("Delete column"),self)
        for index,widget in enumerate((self.row_add,self.row_remove,self.col_add,self.col_remove)):
            buttons.addWidget(widget,index//2,index%2)
        edit_row.addLayout(buttons);root.addLayout(edit_row)
        self.warning=CaptionLabel("",self);self.warning.setWordWrap(True);root.addWidget(self.warning)
        self.protect=CheckBox(self.tr("Protect spreadsheet formula prefixes"),self);self.protect.setChecked(True)
        self.protect.setToolTip(self.tr("TSV cells starting with =, +, - or @ are prefixed with an apostrophe. Spreadsheets may auto-convert dates and leading zeros; format destination cells as text when needed."))
        self.header=CheckBox(self.tr("First row is Markdown header"),self);self.header.setChecked(True)
        root.addWidget(self.protect);root.addWidget(self.header)
        footer=QHBoxLayout();self.status=CaptionLabel("",self);self.status.setWordWrap(True);footer.addWidget(self.status,1)
        self.copy_button=PrimaryPushButton(self.tr("Copy TSV"),self)
        self.save_button=PushButton(self.tr("Save Markdown…"),self)
        self.close_button=PushButton(self.tr("Close"),self)
        for b in (self.copy_button,self.save_button,self.close_button):footer.addWidget(b)
        root.addLayout(footer)
        for b in (self.grouping,self.rebuild_button,self.fit_button,self.row_add,self.row_remove,self.col_add,self.col_remove,self.copy_button,self.save_button,self.close_button):configure_dialog_control(b)
        for widget in (hint,self.warning,self.status,self.table,self.cell_editor,self.protect,self.header):
            configure_dialog_control(widget)
        self.rebuild_button.clicked.connect(self.rebuild);self.fit_button.clicked.connect(self.source.fit)
        self.table.currentCellChanged.connect(self._select);self.table.itemChanged.connect(self._item_changed)
        self.cell_editor.textChanged.connect(self._edit_cell)
        self.row_add.clicked.connect(lambda:self._structure("row",True));self.row_remove.clicked.connect(lambda:self._structure("row",False))
        self.col_add.clicked.connect(lambda:self._structure("column",True));self.col_remove.clicked.connect(lambda:self._structure("column",False))
        self.copy_button.clicked.connect(self.copy_tsv);self.save_button.clicked.connect(self.save_markdown);self.close_button.clicked.connect(self.close)
        get_ui_theme().theme_changed.connect(self._theme);self._theme()
        self.resize(dialog_scaled(1100),dialog_scaled(820))
        bounds=self.screen().availableGeometry();self.resize(min(self.width(),bounds.width()-30),min(self.height(),bounds.height()-30))
        self.rebuild()
        splitter.setSizes([dialog_scaled(360),dialog_scaled(680)])

    def _theme(self,*_):
        if self._closed:return
        t=get_ui_theme().tokens
        self.setStyleSheet(f"TableRecognitionWindow {{background:{t.window};}} QTableWidget, QGraphicsView {{background:{t.surface_subtle};color:{t.text};gridline-color:{t.border};}} QHeaderView::section {{background:{t.surface_subtle};color:{t.text};padding:5px;}}")

    def rebuild(self):
        if self._dirty and not show_confirm_dialog(self,self.tr("Rebuild table"),self.tr("Discard table edits and reconstruct from the original OCR boxes?")):return
        try:
            result=reconstruct_table(self.ocr_result,self.image.width(),self.image.height(),row_tolerance=self.grouping.currentData())
        except TableError:
            self.status.setText(self.tr("Could not reconstruct a table: no valid positioned text or table limits exceeded."))
            self.copy_button.setEnabled(False);self.save_button.setEnabled(False);return
        self._updating=True
        try:
            self.table.clear();self.table.setRowCount(len(result.cells));self.table.setColumnCount(len(result.cells[0]))
            for r,row in enumerate(result.cells):
                for c,text in enumerate(row):
                    item=QTableWidgetItem(text);item.setData(Qt.ItemDataRole.UserRole,result.boxes[r][c])
                    if (r,c) in result.uncertain:
                        item.setBackground(QColor("#fff0ba"));item.setForeground(QColor("#352500"))
                        item.setToolTip(self.tr("Low confidence or ambiguous geometry. Check the source image."))
                    self.table.setItem(r,c,item)
        finally:self._updating=False
        self._dirty=False
        self.warning.setText(self.tr("Review required: %1 warning categories, %2 uncertain cells. Complex layouts are not reconstructed reliably.").replace("%1",str(len(result.warnings))).replace("%2",str(len(result.uncertain))))
        reasons={"invalid_boxes":self.tr("Invalid OCR boxes skipped"), "rotated":self.tr("Rotated text"),
                 "not_grid":self.tr("Too few rows or columns"), "overlap":self.tr("Overlapping columns"),
                 "spanning":self.tr("Text spans column boundaries"), "collision":self.tr("Multiple boxes in one cell"),
                 "missing_cells":self.tr("Missing or uneven cells"), "review_cells":self.tr("Uncertain cells highlighted")}
        if result.warnings:
            self.warning.setText(self.warning.text()+"\n"+" · ".join(reasons[k] for k in sorted(result.warnings)))
        self.status.setText(self.tr("%1 rows × %2 columns · source image is unchanged").replace("%1",str(self.table.rowCount())).replace("%2",str(self.table.columnCount())))
        self.copy_button.setEnabled(True);self.save_button.setEnabled(True)
        self.table.setCurrentCell(0,0);self._select(0,0)

    def _select(self,row,column,*_):
        item=self.table.item(row,column)
        self._updating=True
        try:self.cell_editor.setPlainText(item.text() if item else "")
        finally:self._updating=False
        self.cell_editor.setEnabled(row>=0 and column>=0)
        self.source.select_box(item.data(Qt.ItemDataRole.UserRole) if item else None)

    def _edit_cell(self):
        if self._updating:return
        r,c=self.table.currentRow(),self.table.currentColumn()
        if r<0 or c<0:return
        text=self.cell_editor.toPlainText()
        self._updating=True
        try:
            item=self.table.item(r,c)
            if item is None:
                item=QTableWidgetItem()
                self.table.setItem(r,c,item)
            item.setText(text);self._dirty=True
        finally:self._updating=False

    def _item_changed(self,item):
        if self._updating:return
        self._dirty=True
        if item is self.table.currentItem():self._select(item.row(),item.column())

    def _structure(self,axis,insert):
        rows,cols=self.table.rowCount(),self.table.columnCount()
        next_rows=rows+(1 if insert else -1) if axis=="row" else rows
        next_cols=cols+(1 if insert else -1) if axis=="column" else cols
        if not 1<=next_rows<=MAX_ROWS or not 1<=next_cols<=MAX_COLUMNS or next_rows*next_cols>MAX_CELLS:return
        index=self.table.currentRow() if axis=="row" else self.table.currentColumn()
        index=max(0,index)
        if axis=="row":
            if insert:self.table.insertRow(index+1)
            else:self.table.removeRow(index)
        else:
            if insert:self.table.insertColumn(index+1)
            else:self.table.removeColumn(index)
        self._dirty=True
        self.status.setText(self.tr("Table structure changed. Review empty and shifted cells before export."))

    def cells(self):
        return [[self.table.item(r,c).text() if self.table.item(r,c) else "" for c in range(self.table.columnCount())] for r in range(self.table.rowCount())]

    def copy_tsv(self):
        try:data=to_tsv(self.cells(),protect_formulas=self.protect.isChecked())
        except TableError:self.status.setText(self.tr("Export exceeds table limits."));return
        QApplication.clipboard().setText(data)
        self.status.setText(self.tr("TSV copied. Verify cell placement and data types in the destination spreadsheet."))

    def save_markdown(self):
        filename,_=QFileDialog.getSaveFileName(self,self.tr("Save Markdown table"),"table.md","Markdown (*.md)")
        if not filename:return
        try:data=to_markdown(self.cells(),first_row_header=self.header.isChecked()).encode("utf-8")
        except TableError:self.status.setText(self.tr("Export exceeds table limits."));return
        file=QSaveFile(filename);ok=file.open(QIODevice.OpenModeFlag.WriteOnly)
        if ok:
            ok=file.write(data)==len(data)
            if ok:ok=file.commit()
            else:file.cancelWriting()
        self.status.setText(self.tr("Markdown saved") if ok else self.tr("Markdown save failed"))

    def closeEvent(self,event):
        self._closed=True;self.image=QImage();self.ocr_result=None
        super().closeEvent(event)


def show_table_recognition(image,result):
    window=TableRecognitionWindow(image,result)
    track_modeless_dialog(window);window.show();window.raise_();window.activateWindow()
    return window
