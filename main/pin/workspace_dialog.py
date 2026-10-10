"""Explicit save, restore and delete actions for local pin-workspace files."""
from pathlib import Path
import threading

from PySide6.QtCore import QFile, QThread, Qt
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QHBoxLayout, QListWidget, QListWidgetItem, QVBoxLayout

from core.save import SaveService
from core.ui_scale import configure_dialog_control, dialog_scaled, scale_dialog_font
from core.ui_theme import get_ui_theme
from pin.pin_manager import PinManager
from pin.workspace import (MAX_PINS, read_workspace, restore_workspace, snapshot_workspace, write_workspace)
from settings import get_tool_settings_manager
from ui.dialogs import show_confirm_dialog
from ui.fluent_lite import BodyLabel, CaptionLabel, LineEdit, PrimaryPushButton, PushButton


class _SaveWorkspace(QThread):
    def __init__(self,destination,manifest,projects,service,parent):
        super().__init__(parent)
        self.destination,self.manifest,self.projects,self.service=destination,manifest,projects,service
        self.cancel=threading.Event();self.ok=False

    def run(self):
        try:self.ok=write_workspace(self.destination,self.manifest,self.projects,self.service,cancelled=self.cancel.is_set)
        except Exception:self.ok=False
        finally:self.manifest=b"";self.projects={}


class PinWorkspaceDialog(QDialog):
    def __init__(self,manager=None,config=None):
        super().__init__()
        scale_dialog_font(self)
        self.setWindowTitle(self.tr("Pin Workspaces"))
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.manager=manager or PinManager.instance()
        self.config=config or get_tool_settings_manager()
        self.pins=[];self._worker=None;self._closing=False;self._shutdown=False
        layout=QVBoxLayout(self);layout.setContentsMargins(*[dialog_scaled(18)]*4)
        layout.setSpacing(dialog_scaled(10))
        self.hint=CaptionLabel(self.tr("Select the pins to keep. Saving is manual; workspaces contain original images and editable annotations. Restoring adds pins without closing existing ones."),self)
        configure_dialog_control(self.hint);layout.addWidget(self.hint)
        row=QHBoxLayout();label=BodyLabel(self.tr("Workspace name"),self);configure_dialog_control(label)
        self.name=LineEdit(self);configure_dialog_control(self.name);self.name.setMaxLength(80)
        self.name.setPlaceholderText(self.tr("Reference board"))
        row.addWidget(label);row.addWidget(self.name,1);layout.addLayout(row)
        self.list=QListWidget(self);self.list.setAccessibleName(self.tr("Pins to save"))
        layout.addWidget(self.list,1)
        row=QHBoxLayout();self.actions=[]
        for text,callback in (("Refresh pins",self.refresh),("Select all",lambda:self.select_all(True)),("Select none",lambda:self.select_all(False))):
            button=PushButton(self.tr(text),self);configure_dialog_control(button);button.clicked.connect(callback)
            row.addWidget(button);self.actions.append(button)
        layout.addLayout(row)
        self.status=CaptionLabel(self.tr("Up to 20 pins, 64 megapixels in total. Closing this dialog does not save anything automatically."),self)
        configure_dialog_control(self.status);layout.addWidget(self.status)
        row=QHBoxLayout()
        for text,callback,primary in (("Save selected…",self.save_dialog,True),("Open workspace…",self.open_dialog,False),("Delete workspace…",self.delete_dialog,False)):
            button=(PrimaryPushButton if primary else PushButton)(self.tr(text),self)
            configure_dialog_control(button);button.clicked.connect(callback);row.addWidget(button);self.actions.append(button)
        layout.addLayout(row)
        self.cancel_button=PushButton(self.tr("Cancel save"),self);configure_dialog_control(self.cancel_button)
        self.cancel_button.clicked.connect(self.cancel_save);self.cancel_button.hide();layout.addWidget(self.cancel_button)
        self.refresh();get_ui_theme().theme_changed.connect(self._theme);self._theme()
        QApplication.instance().aboutToQuit.connect(self.shutdown)
        self.resize(dialog_scaled(680),dialog_scaled(480))
        screen=QApplication.primaryScreen().availableGeometry()
        self.resize(min(self.width(),screen.width()-40),min(self.height(),screen.height()-40))

    def _theme(self,*_):
        t=get_ui_theme().tokens
        self.setStyleSheet(f"QDialog {{ background: {t.window}; }} QListWidget {{ background: {t.surface}; color: {t.text}; border: 1px solid {t.border}; }}")

    def refresh(self):
        if self._worker:return
        self.list.clear();self.pins=list(self.manager.get_all_pins())
        for index,pin in enumerate(self.pins):
            try:
                size=pin.canvas.base_size
                state=self.tr("Thumbnail") if pin._thumbnail.active else self.tr("Pinned image")
                row=QListWidgetItem(f"{index+1} · {state} · {size.width()} × {size.height()} · {round(pin.scale_factor*100)}%",self.list)
                row.setData(Qt.ItemDataRole.UserRole,index)
                row.setFlags(row.flags()|Qt.ItemFlag.ItemIsUserCheckable)
                row.setCheckState(Qt.CheckState.Unchecked)
            except (AttributeError,RuntimeError):continue

    def select_all(self,checked):
        if self._worker:return
        for index in range(self.list.count()):
            self.list.item(index).setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)

    def selected_pins(self):
        selected=[]
        for index in range(self.list.count()):
            row=self.list.item(index)
            if row.checkState()==Qt.CheckState.Checked:selected.append(self.pins[row.data(Qt.ItemDataRole.UserRole)])
        return selected

    def _busy(self,value):
        self.name.setEnabled(not value);self.list.setEnabled(not value)
        for button in self.actions:button.setEnabled(not value)
        self.cancel_button.setVisible(value)

    def save_dialog(self):
        if self._worker:return
        selected=self.selected_pins()
        if not selected or len(selected)>MAX_PINS or not self.name.text().strip():
            self.status.setText(self.tr("Enter a name and select between 1 and 20 pins."));return
        if not show_confirm_dialog(self,self.tr("Workspace contains original images"),
                self.tr("This file keeps original pixels and removable annotations. It is not a redacted sharing format. Save the selected pins?")):return
        from core.image_output import safe_filename_part
        destination,_=QFileDialog.getSaveFileName(self,self.tr("Save pin workspace"),safe_filename_part(self.name.text())+".vpins","Pin workspace (*.vpins)")
        if not destination:return
        if not Path(destination).suffix:destination+=".vpins"
        self.start_save(destination)

    def start_save(self,destination):
        if self._worker or self._shutdown:return False
        if Path(destination).suffix.lower()!=".vpins":
            self.status.setText(self.tr("Use the .vpins extension for pin workspaces."));return False
        try:manifest,projects=snapshot_workspace(self.selected_pins(),self.name.text())
        except Exception:
            self.status.setText(self.tr("Could not prepare workspace. Check selected pins, name and resource limits. Nothing was saved."));return False
        self._worker=_SaveWorkspace(str(destination),manifest,projects,SaveService(self.config),self)
        self._worker.finished.connect(self._finished);self._busy(True)
        self.status.setText(self.tr("Saving workspace…"));self._worker.start();return True

    def cancel_save(self):
        if self._worker:self._worker.cancel.set();self.status.setText(self.tr("Cancelling save…"))

    def _finished(self):
        worker=self._worker;self._worker=None
        if not self._shutdown:
            self._busy(False)
            self.status.setText(self.tr("Workspace saved. Source images and existing pins were not changed.") if worker.ok else
                                self.tr("Workspace save cancelled. Existing files were kept.") if worker.cancel.is_set() else
                                self.tr("Could not save workspace. Existing files and pins were kept."))
        worker.deleteLater()
        if self._closing:self.close()

    def open_dialog(self):
        if self._worker:return
        filename,_=QFileDialog.getOpenFileName(self,self.tr("Open pin workspace"),"","Pin workspace (*.vpins)")
        if filename:self.open_workspace(filename)

    def open_workspace(self,filename):
        if self._worker or self._shutdown:return False
        try:workspace=read_workspace(filename)
        except Exception:
            self.status.setText(self.tr("Workspace format or resource limits are invalid. Existing pins were not changed."));return False
        if not workspace.pins:
            details=self.tr("Failed entries: %1. Missing, invalid or over the resource limit.").replace("%1",", ".join(str(index+1) for index,_ in workspace.errors))
            self.status.setText(self.tr("No valid pins could be restored. The workspace may be missing or contain damaged projects.")+" "+details);return False
        message=self.tr("Restore %1 pins from '%2'? Existing pins stay open. The saved original images will be visible on screen.").replace("%1",str(len(workspace.pins))).replace("%2",workspace.name)
        if not show_confirm_dialog(self,self.tr("Restore pin workspace"),message,plain_text=True):return False
        screens=[screen.availableGeometry() for screen in QApplication.screens()]
        restored,errors,moved=restore_workspace(workspace,self.manager,self.config,screens)
        self.name.setText(workspace.name);self.refresh()
        text=self.tr("Restored %1 pins; %2 failed; %3 moved onto an available screen.").replace("%1",str(len(restored))).replace("%2",str(len(errors))).replace("%3",str(len(moved)))
        if errors:
            text+=" " + self.tr("Failed entries: %1. Missing, invalid or over the resource limit.").replace("%1",", ".join(str(index+1) for index,_ in errors))
        self.status.setText(text)
        return bool(restored)

    def delete_dialog(self):
        if self._worker:return
        filename,_=QFileDialog.getOpenFileName(self,self.tr("Delete pin workspace"),"","Pin workspace (*.vpins)")
        if filename:self.delete_workspace(filename)

    def delete_workspace(self,filename):
        if self._worker or self._shutdown or Path(filename).suffix.lower()!=".vpins" or not Path(filename).is_file():return False
        if not show_confirm_dialog(self,self.tr("Delete pin workspace"),
                self.tr("Move this workspace file to the Recycle Bin? Open pins and source image files will not be deleted.\n%1").replace("%1",str(Path(filename).absolute())),plain_text=True):return False
        result=QFile.moveToTrash(str(Path(filename).absolute()))
        success=result[0] if isinstance(result,tuple) else result
        self.status.setText(self.tr("Workspace moved to the Recycle Bin. Open pins were kept.") if success else
                            self.tr("Could not move the workspace to the Recycle Bin. Nothing was permanently deleted."))
        return bool(success)

    def shutdown(self):
        if self._shutdown:return
        self._shutdown=True
        if self._worker:self._worker.cancel.set();self._worker.wait()
        self.pins=[];self.list.clear()

    def reject(self):
        if self._worker and not self._shutdown:
            self._closing=True;self.cancel_save();return
        self.shutdown()
        super().reject()

    def closeEvent(self,event):
        if self._worker and not self._shutdown:
            self._closing=True;self.cancel_save();event.ignore();return
        self.shutdown();super().closeEvent(event)


def show_pin_workspaces():
    app=QApplication.instance();window=getattr(app,"_pin_workspace_dialog",None)
    if window is None:
        window=PinWorkspaceDialog();app._pin_workspace_dialog=window
        window.destroyed.connect(lambda:setattr(app,"_pin_workspace_dialog",None))
    elif window._worker is None:window.refresh()
    window.show();window.raise_();window.activateWindow()
    return window
