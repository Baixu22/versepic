"""Capture the real Windows cursor and composite its native mask/alpha over pixels.

DrawIconEx runs over the captured background so monochrome XOR cursors retain
Windows semantics. Copied icon and GDI objects are owned only for one capture.
"""
import ctypes
from ctypes import wintypes
from contextlib import contextmanager
from dataclasses import dataclass

from PySide6.QtCore import QPoint, QRect
from PySide6.QtGui import QImage, QPainter
import win32con
import win32gui


class _BitmapInfoHeader(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]


class _Bitmap(ctypes.Structure):
    _fields_ = [("bmType", wintypes.LONG), ("bmWidth", wintypes.LONG), ("bmHeight", wintypes.LONG),
                ("bmWidthBytes", wintypes.LONG), ("bmPlanes", wintypes.WORD),
                ("bmBitsPixel", wintypes.WORD), ("bmBits", ctypes.c_void_p)]


_gdi = ctypes.windll.gdi32
_gdi.GetObjectW.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p]
_gdi.GetObjectW.restype = ctypes.c_int
_gdi.CreateCompatibleDC.argtypes = [wintypes.HDC]
_gdi.CreateCompatibleDC.restype = wintypes.HDC
_gdi.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.POINTER(_BitmapInfoHeader), wintypes.UINT,
                                 ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD]
_gdi.CreateDIBSection.restype = wintypes.HBITMAP
_gdi.SelectObject.argtypes = [wintypes.HDC, wintypes.HANDLE]
_gdi.SelectObject.restype = wintypes.HANDLE
_gdi.DeleteObject.argtypes = [wintypes.HANDLE]
_gdi.DeleteObject.restype = wintypes.BOOL
_gdi.DeleteDC.argtypes = [wintypes.HDC]
_gdi.DeleteDC.restype = wintypes.BOOL
_gdi.GdiFlush.argtypes = []
_gdi.GdiFlush.restype = wintypes.BOOL


@dataclass(frozen=True)
class CursorSnapshot:
    icon: int
    position: tuple
    hotspot: tuple
    size: tuple

    def desktop_rect(self):
        return QRect(self.position[0] - self.hotspot[0], self.position[1] - self.hotspot[1], *self.size)


@contextmanager
def cursor_snapshot(enabled):
    copied = None
    mask = color = None
    try:
        if not enabled:
            yield None
            return
        flags, handle, position = win32gui.GetCursorInfo()
        if not flags & win32con.CURSOR_SHOWING:
            yield None
            return
        copied = win32gui.CopyIcon(handle)
        if not copied:
            raise OSError("Could not freeze the cursor image")
        _, x, y, mask, color = win32gui.GetIconInfo(copied)
        bitmap = _Bitmap()
        if not _gdi.GetObjectW(int(color or mask), ctypes.sizeof(bitmap), ctypes.byref(bitmap)):
            raise OSError("Could not inspect cursor bitmap")
        width, height = bitmap.bmWidth, bitmap.bmHeight if color else bitmap.bmHeight // 2
        if width < 1 or height < 1 or max(width, height) > 1024:
            raise ValueError("Invalid cursor bitmap dimensions")
        yield CursorSnapshot(copied, position, (x, y), (width, height))
    finally:
        for bitmap in (mask, color):
            if bitmap:
                win32gui.DeleteObject(bitmap)
        if copied:
            win32gui.DestroyIcon(copied)


def _draw_native_cursor(background, snapshot, offset):
    """Return a cursor-sized opaque patch; never allocate a second desktop bitmap."""
    width, height = background.width(), background.height()
    source = background.convertToFormat(QImage.Format.Format_RGB32)
    info = _BitmapInfoHeader()
    info.biSize = ctypes.sizeof(info)
    info.biWidth, info.biHeight = width, -height  # top-down, like QImage
    info.biPlanes, info.biBitCount = 1, 32
    bits = ctypes.c_void_p()
    dc = bitmap = previous = None
    try:
        dc = _gdi.CreateCompatibleDC(None)
        if not dc:
            raise OSError("Could not create cursor drawing context")
        bitmap = _gdi.CreateDIBSection(dc, ctypes.byref(info), 0, ctypes.byref(bits), None, 0)
        if not bitmap or not bits.value:
            raise OSError("Could not allocate cursor patch")
        previous = _gdi.SelectObject(dc, bitmap)
        if not previous or previous == ctypes.c_void_p(-1).value:
            raise OSError("Could not select cursor patch")
        ctypes.memmove(bits.value, bytes(source.constBits()), width * height * 4)
        win32gui.DrawIconEx(int(dc), offset.x(), offset.y(), snapshot.icon, *snapshot.size, 0, None, win32con.DI_NORMAL)
        if not _gdi.GdiFlush():
            raise OSError("Could not finish native cursor drawing")
        data = ctypes.string_at(bits.value, width * height * 4)
        return QImage(data, width, height, width * 4, QImage.Format.Format_RGB32).copy()
    finally:
        if previous and previous != ctypes.c_void_p(-1).value:
            _gdi.SelectObject(dc, previous)
        if bitmap:
            _gdi.DeleteObject(bitmap)
        if dc:
            _gdi.DeleteDC(dc)


def composite_cursor(image, desktop, snapshot):
    if snapshot is None:
        return image
    bounds = QRect(round(desktop.x()), round(desktop.y()), image.width(), image.height())
    cursor = snapshot.desktop_rect()
    clipped = cursor.intersected(bounds)
    if clipped.isEmpty():
        return image
    local = clipped.translated(-bounds.x(), -bounds.y())
    patch = _draw_native_cursor(image.copy(local), snapshot, QPoint(cursor.x() - clipped.x(), cursor.y() - clipped.y()))
    # Shallow copy preserves caller ownership; writing detaches if shared.
    result = QImage(image)
    painter = QPainter(result)
    painter.drawImage(local.topLeft(), patch)
    painter.end()
    return result
