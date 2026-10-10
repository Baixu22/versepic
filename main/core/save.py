"""异步保存服务 - 处理截图文件的异步写入

提供 SaveService 类，负责将截图写入默认目录或自定义路径，
支持多线程后台保存以避免阻塞 UI。
"""

import os
import threading
import tempfile
from core.image_output import ImageOutputOptions

from PySide6.QtCore import QCoreApplication, QMarginsF, QObject, QRectF, QSizeF, QThread, Qt, Signal
from PySide6.QtGui import QImage, QPageLayout, QPageSize, QPainter, QPdfWriter
from PIL import Image

from settings import get_tool_settings_manager
from core.logger import log_info, log_error, log_exception, T


class _SaveNotifications(QObject):
    failed = Signal(str)


def save_notifications():
    """One GUI-owned failure signal, also safe to emit from encoding workers."""
    app = QCoreApplication.instance()
    if app is None:
        return None
    notifier = getattr(app, "_image_save_notifications", None)
    if notifier is None and QThread.currentThread() == app.thread():
        notifier = app._image_save_notifications = _SaveNotifications(app)
    return notifier


class SaveService:
    """Async save service for screenshots."""

    DEFAULT_PDF_DPI = 300

    def __init__(self, config_manager=None):
        self.config_manager = config_manager or get_tool_settings_manager()
        self._reserved_paths = set()
        self._notifications = save_notifications()

    def output_options(self):
        """Snapshot settings on the submitting thread, never in an encoding worker."""
        return ImageOutputOptions.from_config(self.config_manager)

    def _report_failure(self, target_path):
        if self._notifications is not None:
            try:
                self._notifications.failed.emit(str(target_path or ""))
            except RuntimeError:
                pass  # QApplication may already have destroyed its notifier during shutdown.

    def _atomic_save(self, target_path, writer, *, cancelled=None):
        if cancelled and cancelled():
            self._cleanup_failed_placeholder(target_path)
            return False
        temporary = None
        try:
            directory = os.path.dirname(os.path.abspath(target_path))
            with tempfile.NamedTemporaryFile(prefix=".versepic-", suffix=".tmp", dir=directory, delete=False) as handle:
                temporary = handle.name
            if cancelled and cancelled():
                self._cleanup_failed_placeholder(target_path)
                return False
            written = writer(temporary)
            if cancelled and cancelled():
                self._cleanup_failed_placeholder(target_path)
                return False
            if not written or os.path.getsize(temporary) == 0:
                self._report_failure(target_path)
                self._cleanup_failed_placeholder(target_path)
                return False
            os.replace(temporary, target_path)
            temporary = None
            self._reserved_paths.discard(os.path.abspath(target_path))
            log_info(T("已保存文件: {target_path}", target_path=target_path), "Save")
            return True
        except Exception as exc:
            log_error(T("保存失败 {target_path}: {exc}", target_path=target_path, exc=exc), "Save")
            self._report_failure(target_path)
            self._cleanup_failed_placeholder(target_path)
            return False
        finally:
            if temporary is not None:
                try:
                    os.unlink(temporary)
                except OSError as exc:
                    log_exception(exc, "Remove failed image staging file")

    def get_default_directory(self) -> str:
        """Return default directory based on current config."""
        return self.config_manager.get_screenshot_save_path()

    def save_qimage_async(self, image, *, directory=None, prefix="截图", suffix="", image_format="PNG",
                          pdf_dpi=DEFAULT_PDF_DPI, callback=None, output_options=None):
        if image is None or image.isNull():
            return None
        options = output_options or self.output_options()
        return self._save_qimage_async(image.copy(), directory=directory, prefix=prefix, suffix=suffix,
                                      image_format=image_format, pdf_dpi=pdf_dpi, callback=callback,
                                      output_options=options)

    def save_qimage(self, image, *, directory=None, prefix="截图", suffix="", image_format="PNG",
                    pdf_dpi=DEFAULT_PDF_DPI, target_path=None, output_options=None):
        if image is None or image.isNull():
            return False, None
        options = output_options or self.output_options()
        try:
            target_path = target_path or self._compose_path(directory, prefix, suffix, image_format, output_options=options)
        except Exception as exc:
            log_exception(exc, "Prepare screenshot save path")
            self._report_failure(directory or options.directory)
            return False, None
        success = self.save_qimage_to_path(image, target_path, image_format=image_format,
                                          pdf_dpi=pdf_dpi, output_options=options)
        return success, target_path

    def reserve_save_path(self, *, directory=None, prefix="截图", suffix="", image_format="PNG", output_options=None):
        return self._compose_path(directory, prefix, suffix, image_format, output_options=output_options)

    def save_qimage_to_path(self, image, target_path, *, image_format=None, pdf_dpi=DEFAULT_PDF_DPI, output_options=None, cancelled=None):
        if image is None or image.isNull():
            return False
        try:
            options = output_options or self.output_options()
            fmt = self._normalize_format(image_format or os.path.splitext(target_path)[1] or "PNG")
            width, height = options.output_size(image.width(), image.height())
            if (width, height) != (image.width(), image.height()):
                image = image.scaled(width, height, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
            elif image.devicePixelRatio() != 1:
                image = image.copy()
            if image.devicePixelRatio() != 1:
                image.setDevicePixelRatio(1)
            if image.isNull():
                raise ValueError("Output image could not be allocated")
            if fmt == "PDF":
                return self._atomic_save(target_path, lambda temporary: self._save_qimage_to_pdf_path(image, temporary, pdf_dpi=pdf_dpi), cancelled=cancelled)
            if fmt in ("JPG", "BMP"):
                image = self._flatten_for_pdf(image)
            return self._atomic_save(target_path, lambda temporary: self._save_qimage_to_path(image, temporary, fmt, quality=options.quality), cancelled=cancelled)
        except Exception as exc:
            log_error(T("保存失败 {target_path}: {exc}", target_path=target_path, exc=exc), "Save")
            self._report_failure(target_path)
            self._cleanup_failed_placeholder(target_path)
            return False

    def save_image_pages(self, images, target_path, page_options, *, cancelled=None, progress=None, searchable=False, text_report=None):
        from core.image_layout import ExportCancelled, write_pdf_pages

        def write(temporary):
            try:
                if searchable:
                    from core.searchable_pdf import write_searchable_pdf
                    return write_searchable_pdf(images, temporary, page_options, cancelled=cancelled, progress=progress, report=text_report)
                return write_pdf_pages(images, temporary, page_options, cancelled=cancelled, progress=progress)
            except ExportCancelled:
                return False
        return self._atomic_save(target_path, write, cancelled=cancelled)

    def save_pil_async(self, pil_image, *, directory=None, prefix="截图", suffix="", image_format="PNG",
                       pdf_dpi=DEFAULT_PDF_DPI, callback=None, output_options=None):
        if pil_image is None:
            return None
        options = output_options or self.output_options()
        image_copy = pil_image.copy()
        try:
            target_path = self._compose_path(directory, prefix, suffix, image_format, output_options=options)
        except Exception as exc:
            log_exception(exc, "Prepare asynchronous screenshot path")
            self._report_failure(directory or options.directory)
            return None
        def worker():
            success = self._save_pil_to_path(image_copy, target_path, image_format, pdf_dpi=pdf_dpi, output_options=options)
            if callback:
                callback(success, target_path)
        threading.Thread(target=worker, daemon=True).start()
        return target_path

    def _save_qimage_async(self, image, *, directory=None, prefix, suffix, image_format, pdf_dpi,
                           callback=None, output_options=None):
        options = output_options or self.output_options()
        try:
            target_path = self._compose_path(directory, prefix, suffix, image_format, output_options=options)
        except Exception as exc:
            log_exception(exc, "Prepare asynchronous screenshot path")
            self._report_failure(directory or options.directory)
            return None
        def worker():
            success = self.save_qimage_to_path(image, target_path, image_format=image_format,
                                              pdf_dpi=pdf_dpi, output_options=options)
            if callback:
                callback(success, target_path)
        threading.Thread(target=worker, daemon=True).start()
        return target_path

    def _save_qimage_to_path(self, image, target_path, image_format, *, quality=85):
        if image_format in ("JPG", "WEBP"):
            return image.save(target_path, image_format, quality)
        return image.save(target_path, image_format)

    def _save_qimage_to_pdf_path(self, image: QImage, target_path: str, *, pdf_dpi: int) -> bool:
        try:
            pdf_dpi = max(72, int(pdf_dpi))
            pdf_image = self._flatten_for_pdf(image)

            writer = QPdfWriter(target_path)
            writer.setResolution(pdf_dpi)
            writer.setPageSize(QPageSize(
                QSizeF(pdf_image.width() * 72.0 / pdf_dpi, pdf_image.height() * 72.0 / pdf_dpi),
                QPageSize.Unit.Point,
                "Screenshot",
            ))
            writer.setPageMargins(QMarginsF(0, 0, 0, 0), QPageLayout.Unit.Point)
            writer.setCreator("VersePic")

            painter = QPainter(writer)
            try:
                painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
                painter.drawImage(
                    QRectF(0, 0, writer.width(), writer.height()),
                    pdf_image,
                    QRectF(0, 0, pdf_image.width(), pdf_image.height()),
                )
            finally:
                painter.end()

            log_info(T("已保存PDF: {target_path}", target_path=target_path), "Save")
            return True
        except Exception as exc:
            log_error(T("保存PDF失败 {target_path}: {exc}", target_path=target_path, exc=exc), "Save")
            self._cleanup_failed_placeholder(target_path)
            return False

    def _save_pil_to_path(self, pil_image, target_path, image_format, *, pdf_dpi, output_options=None):
        try:
            options = output_options or self.output_options()
            fmt = self._normalize_format(image_format)
            size = options.output_size(*pil_image.size)
            if size != pil_image.size:
                pil_image = pil_image.resize(size, Image.Resampling.LANCZOS)
            if fmt == "PDF":
                rgba = pil_image.convert("RGBA")
                data = rgba.tobytes("raw", "RGBA")
                image = QImage(data, rgba.width, rgba.height, rgba.width * 4, QImage.Format.Format_RGBA8888).copy()
                return self._atomic_save(target_path, lambda temporary: self._save_qimage_to_pdf_path(image, temporary, pdf_dpi=pdf_dpi))
            if fmt in ("JPG", "BMP"):
                rgba = pil_image.convert("RGBA")
                opaque = Image.new("RGB", rgba.size, "white")
                opaque.paste(rgba, mask=rgba.getchannel("A"))
                pil_image = opaque
            def write(temporary):
                kwargs = {"quality": options.quality} if fmt in ("JPG", "WEBP") else {}
                pil_image.save(temporary, format="JPEG" if fmt == "JPG" else fmt, **kwargs)
                return True
            return self._atomic_save(target_path, write)
        except Exception as exc:
            log_error(T("保存失败 {target_path}: {exc}", target_path=target_path, exc=exc), "Save")
            self._report_failure(target_path)
            self._cleanup_failed_placeholder(target_path)
            return False

    def _flatten_for_pdf(self, image: QImage) -> QImage:
        if not image.hasAlphaChannel():
            return image.convertToFormat(QImage.Format.Format_RGB32)

        flattened = QImage(image.size(), QImage.Format.Format_RGB32)
        flattened.fill(0xFFFFFFFF)
        painter = QPainter(flattened)
        try:
            painter.drawImage(0, 0, image)
        finally:
            painter.end()
        return flattened

    def _compose_path(self, directory, prefix, suffix, image_format, *, output_options=None):
        options = output_options or self.output_options()
        target_dir = directory or options.directory
        if not os.path.isabs(target_dir):
            target_dir = options.directory
        if not os.path.isabs(target_dir):
            raise ValueError("Save directory must be absolute")
        if options.date_folders:
            target_dir = os.path.join(target_dir, options.moment.strftime("%Y-%m-%d"))
        os.makedirs(target_dir, exist_ok=True)
        return self._reserve_unique_path(target_dir, prefix, suffix, image_format, output_options=options)

    def _build_filename(self, prefix, suffix, image_format, *, output_options=None, index=1):
        options = output_options or self.output_options()
        return options.filename(prefix, suffix, self._normalize_format(image_format), index)

    def _normalize_format(self, image_format):
        fmt = (image_format or "PNG").strip().lstrip(".").upper()
        fmt = "JPG" if fmt == "JPEG" else fmt
        if fmt not in ("PNG", "JPG", "BMP", "WEBP", "PDF"):
            raise ValueError("Unsupported screenshot format")
        return fmt

    def _reserve_unique_path(self, target_dir, prefix, suffix, image_format, *, output_options=None):
        options = output_options or self.output_options()
        base = self._build_filename(prefix, suffix, image_format, output_options=options)
        stem, ext = os.path.splitext(base)
        seen = set()
        for index in range(10000):
            if options.uses_index:
                filename = self._build_filename(prefix, suffix, image_format, output_options=options, index=index + 1)
                if filename in seen:
                    filename = f"{stem}_{index}{ext}"
            else:
                filename = base if index == 0 else f"{stem}_{index}{ext}"
            seen.add(filename)
            target = os.path.join(target_dir, filename)
            try:
                fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.close(fd)
                self._reserved_paths.add(os.path.abspath(target))
                return target
            except FileExistsError:
                continue
        raise RuntimeError("Unable to reserve a unique screenshot filename")

    def _cleanup_failed_placeholder(self, path):
        if not path:
            return
        key = os.path.abspath(path)
        if key not in self._reserved_paths:
            return
        try:
            if os.path.exists(path) and os.path.getsize(path) == 0:
                os.remove(path)
        except OSError as exc:
            log_exception(exc, "Remove failed screenshot placeholder")
        finally:
            self._reserved_paths.discard(key)
