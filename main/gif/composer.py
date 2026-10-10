# -*- coding: utf-8 -*-
"""
GIF 合成器 + 进度对话框

技术路线：
  gifrecorder.FrameStore.export_gif()
  Rust 侧并行解码 → 缩放 → 光标叠加 → GIF 编码，进度通过回调报告。
  全部由 Rust gifrecorder 完成，无外部依赖。
"""

from __future__ import annotations

import inspect
import os
import tempfile
from typing import Optional

from PySide6.QtCore import QObject, QThread, Signal, Qt, QEventLoop
from PySide6.QtWidgets import QApplication, QDialog, QHBoxLayout, QProgressBar, QVBoxLayout
from core.ui_scale import dialog_scaled, scale_dialog_font
from core.ui_theme import get_ui_theme
from ui.fluent_lite import BodyLabel, PushButton
from ui.dialogs import show_warning_dialog

from ._widgets import PROGRESS_BAR_STYLE
from core.logger import log_info, log_error, log_exception, T
from core.save import SaveService

try:
    import gifrecorder
    _gifrecorder_available = True
except ImportError:
    gifrecorder = None
    _gifrecorder_available = False

# == 默认导出参数 ==
DEFAULT_GIF_WIDTH  = 0


def output_size(store, width=0):
    """GIF supports odd dimensions; only round to the nearest whole pixel."""
    if type(width) is not int or width < 0:
        raise ValueError("Invalid GIF width")
    w = width or store.width
    h = max(1, int(store.height * w / store.width + 0.5)) if store.width > 0 else 0
    if not 1 <= w <= 65535 or not 1 <= h <= 65535 or w * h > 16_000_000 or w > store.width * 16:
        raise ValueError("GIF output exceeds 16 megapixels, 65535 pixels per edge or 16x enlargement")
    return w, h


def timeline_encoder_available():
    try:
        return "fps" in inspect.signature(gifrecorder.FrameStore.export_gif).parameters
    except (AttributeError, TypeError, ValueError):
        return False


# ── 合成线程 Worker ──────────────────────────────────

class _ComposeWorker(QObject):
    progress = Signal(int, int)      # (done, total)
    finished = Signal(bool, object)  # (ok, result: str|bytes|None)

    def __init__(self,
                 path: Optional[str],
                 store=None,
                 gif_width: int = DEFAULT_GIF_WIDTH,
                 frame_start: int = 0,
                 frame_end: Optional[int] = None,
                 cursor_sprites: Optional[dict] = None,
                 cursor_infos: Optional[list] = None,
                 speed_multiplier: float = 1.0,
                 fps: int = 0,
                  output_format: str = "gif"):
        super().__init__()
        self._path = path
        self._store = store                     # gifrecorder.FrameStore 实例
        self._gif_width = gif_width
        self._frame_start = frame_start
        self._frame_end = frame_end
        self._fps = fps
        if output_format not in ("gif", "mp4"):
            raise ValueError("Unsupported recording export format")
        self._output_format = output_format
        self._cursor_sprites = cursor_sprites   # sprite 集合 dict
        self._cursor_infos = cursor_infos       # list of (x,y,press,scroll,burst_frame,burst_side)
        self._speed_multiplier = max(0.1, speed_multiplier)
        self._cancel = False
        # Construct on the submitting (GUI) thread; encoding never reads settings.
        self._save_service = SaveService()

    def cancel(self):
        self._cancel = True
        if self._store is not None:
            self._store.cancel_export()

    def run(self):
        try:
            if not _gifrecorder_available or self._store is None:
                self.finished.emit(False, "gifrecorder_not_found")
                return
            result = self._compose()
            # A non-None result is the commit point, not merely "not cancelled".
            self.finished.emit(result is not None, result)
        except Exception as e:
            log_error(T("GIF 合成失败: {e}", e=e), "GIF")
            self.finished.emit(False, None)

    def _compose(self):
        if self._cancel:
            return None
        if self._path is not None:
            # Never let the encoder open the user's destination: it truncates it
            # before encoding, and cancellation leaves a partial GIF behind.
            ok = self._save_service._atomic_save(
                self._path, self._do_compose, cancelled=lambda: self._cancel,
            )
            return self._path if ok else None

        tmp_fd, out_path = tempfile.mkstemp(suffix="." + self._output_format, prefix="jietuba_")
        os.close(tmp_fd)
        try:
            if self._cancel or not self._do_compose(out_path) or self._cancel:
                return None
            with open(out_path, "rb") as file:
                data = file.read()
            return data if data and not self._cancel else None
        finally:
            try:
                os.unlink(out_path)
            except OSError as exc:
                log_exception(exc, T("GIF 读取后删除临时文件"))

    def _do_compose(self, out_path: str) -> bool:
        """Use the format-specific encoder; all output still goes through staging."""
        if self._output_format == "mp4":
            from .mp4_export import export_mp4, Mp4Cancelled
            try:
                return export_mp4(out_path, self._store, width=self._gif_width,
                    frame_start=self._frame_start, frame_end=self._frame_end, speed=self._speed_multiplier,
                    cursor_sprites=self._cursor_sprites, cursor_infos=self._cursor_infos,
                    cancelled=lambda: self._cancel, progress=self.progress.emit)
            except Mp4Cancelled:
                return False
        gif_width, gif_height = output_size(self._store, self._gif_width)

        log_info(
            T("使用 gifrecorder export_gif: {gif_width}x{gif_height}",
              gif_width=gif_width, gif_height=gif_height),
            "GIF",
        )

        def _progress(done, total):
            self.progress.emit(done, total)
            return not self._cancel   # 返回 False 取消

        try:
            # 构建 cursor 导出参数
            export_kwargs = dict(
                path=out_path,
                width=gif_width,
                height=gif_height,
                repeat=0,
                frame_start=self._frame_start,
                frame_end=self._frame_end,
                progress_callback=_progress,
                speed=self._speed_multiplier,
                fps=self._fps,
            )
            if self._cursor_sprites and self._cursor_infos:
                export_kwargs["cursor_sprites"] = self._cursor_sprites
                export_kwargs["cursor_infos"] = self._cursor_infos

            self._store.export_gif(**export_kwargs)
        except Exception as e:
            err_str = str(e)
            if "cancelled" in err_str:
                return False
            log_error(T("export_gif 失败: {e}", e=e), "GIF")
            return False

        file_size = os.path.getsize(out_path) if os.path.isfile(out_path) else 0
        log_info(
            T("GIF 导出完成: {out_path} ({size_kb:.1f} KB)",
              out_path=out_path, size_kb=file_size / 1024),
            "GIF",
        )
        return True


# ── 进度浮层（无边框纯进度条） ──────────────────────────

class ComposerProgressDialog(QDialog):
    """
    无边框纯进度条浮层，样式与录制结束等待进度条保持一致。
    居中于 parent 窗口；合成完成/取消后 loop.quit() 解除阻塞。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(self.tr("Exporting GIF"))
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        scale_dialog_font(self)
        self._result = None
        self._ok = False
        self._finished = False
        self._cancelled = False
        self._loop = QEventLoop()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(*[dialog_scaled(18)] * 4)
        self._label = BodyLabel(self.tr("Encoding GIF…"), self)
        layout.addWidget(self._label)
        self._bar = QProgressBar(self)
        self._bar.setRange(0, 100)
        self._bar.setTextVisible(True)
        self._bar.setMinimumHeight(dialog_scaled(22))
        self._bar.setStyleSheet(PROGRESS_BAR_STYLE)
        layout.addWidget(self._bar)
        row = QHBoxLayout()
        row.addStretch()
        self._cancel_button = PushButton(self.tr("Cancel"), self)
        self._cancel_button.clicked.connect(self.cancel)
        row.addWidget(self._cancel_button)
        layout.addLayout(row)
        self._thread: Optional[QThread] = None
        self._worker: Optional[_ComposeWorker] = None
        get_ui_theme().theme_changed.connect(self._theme)
        self._theme()
        QApplication.instance().aboutToQuit.connect(self._shutdown)
        self.resize(dialog_scaled(420), self.sizeHint().height())

    def _theme(self, *_):
        self.setStyleSheet(f"ComposerProgressDialog {{ background: {get_ui_theme().tokens.window}; }}")

    def cancel(self):
        if self._finished:
            return
        self._cancelled = True
        self._cancel_button.setEnabled(False)
        self._label.setText(self.tr("Cancelling…"))
        if self._worker:
            self._worker.cancel()

    def reject(self):
        if self._thread:
            self.cancel()
        else:
            super().reject()

    def closeEvent(self, event):
        if self._thread:
            self.cancel()
            event.ignore()
        else:
            super().closeEvent(event)

    def _shutdown(self):
        if self._thread is not None:
            self.cancel()
            self._thread.quit()
            self._thread.wait()
            self._on_finished(False, None)

    def _center_on(self, parent, center_pos=None):
        if center_pos is not None:
            self.move(center_pos.x() - self.width() // 2,
                      center_pos.y() - self.height() // 2)
            return
        if parent is not None:
            try:
                c = parent.geometry().center()
                self.move(c.x() - self.width() // 2, c.y() - self.height() // 2)
                return
            except Exception as e:
                log_exception(e, T("居中进度对话框"))
        screen = QApplication.primaryScreen().geometry()
        self.move(screen.center().x() - self.width() // 2,
                  screen.center().y() - self.height() // 2)

    def start(self,
              path: Optional[str] = None,
              store=None,
              gif_width: int = DEFAULT_GIF_WIDTH,
              frame_start: int = 0,
              frame_end: Optional[int] = None,
              cursor_sprites: Optional[dict] = None,
              cursor_infos: Optional[list] = None,
              speed_multiplier: float = 1.0,
                 fps: int = 0,
                  output_format: str = "gif"):
        if output_format == "mp4":
            self.setWindowTitle(self.tr("Exporting silent MP4"))
            self._label.setText(self.tr("Encoding silent MP4…"))
        self._thread = QThread(self)
        self._worker = _ComposeWorker(
            path,
            store=store,
            gif_width=gif_width,
            frame_start=frame_start,
            frame_end=frame_end,
            cursor_sprites=cursor_sprites,
            cursor_infos=cursor_infos,
            speed_multiplier=speed_multiplier,
            fps=fps,
            output_format=output_format,
        )
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._worker.deleteLater)
        self._worker.finished.connect(self._on_finished)
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.start()

    def _on_progress(self, done: int, total: int):
        if total <= 0:
            if self._bar.maximum() != 0:
                self._bar.setRange(0, 0)
        else:
            if self._bar.maximum() == 0:
                self._bar.setRange(0, 100)
            self._bar.setValue(int(done / total * 100))

    def _on_finished(self, ok: bool, result):
        if self._finished:
            return
        self._finished = True
        self._ok = ok
        self._result = result
        # 先释放 worker 对 store 的引用，避免多余的 Arc 引用延迟释放
        if self._worker:
            self._worker._store = None
            self._worker._cursor_sprites = None
            self._worker._cursor_infos = None
        if self._thread:
            self._thread.quit()
            self._thread.wait()
            self._thread.deleteLater()
            self._thread = None
        self._worker = None
        self.hide()
        self._loop.quit()

        if not ok and result == "gifrecorder_not_found":
            show_warning_dialog(
                None,
                "gifrecorder 不可用",
                "未找到 gifrecorder 模块，无法导出 GIF。\n\n"
                "请确认 gifrecorder 已正确安装。",
            )

    @staticmethod
    def run_compose(path: Optional[str] = None,
                    store=None,
                    gif_width: int = DEFAULT_GIF_WIDTH,
                    parent=None,
                    center_pos=None,
                    frame_start: int = 0,
                    frame_end: Optional[int] = None,
                    cursor_sprites: Optional[dict] = None,
                    cursor_infos: Optional[list] = None,
                    speed_multiplier: float = 1.0,
                 fps: int = 0,
                  output_format: str = "gif"):
        """
        显示无边框进度条并阻塞直到合成完成/失败。
        返回 str(路径) / bytes / None(取消或失败)。
        center_pos: QPoint，直接指定进度条居中坐标（优先于 parent）。
        frame_start/frame_end: 修剪范围（含），None表示最后一帧，0只选首帧。
        speed_multiplier: 导出速度倍率（1.0=原速）。
        """
        dlg = ComposerProgressDialog(parent)
        dlg._center_on(parent, center_pos=center_pos)
        dlg.start(path,
                  store=store,
                  gif_width=gif_width,
                  frame_start=frame_start,
                  frame_end=frame_end,
                  cursor_sprites=cursor_sprites,
                  cursor_infos=cursor_infos,
                  speed_multiplier=speed_multiplier,
                  fps=fps,
                  output_format=output_format)
        dlg.show()
        QApplication.processEvents()
        if not dlg._finished:
            dlg._loop.exec()
        if not dlg._ok and not dlg._cancelled and dlg._result != "gifrecorder_not_found":
            if output_format == "mp4":
                show_warning_dialog(parent, dlg.tr("MP4 export failed"),
                    dlg.tr("The silent MP4 could not be exported. Check the H.264 encoder, output size, disk space and permissions. Existing files were kept."))
            else:
                show_warning_dialog(parent, dlg.tr("GIF export failed"),
                    dlg.tr("The GIF could not be exported. Check output size, encoder version, disk space and file permissions. Existing files were kept."))
        dlg.deleteLater()

        return dlg._result if dlg._ok else None
 