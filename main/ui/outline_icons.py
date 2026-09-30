"""Official Lucide 1.49.0 SVG paths, rendered with Qt at the requested size.

Source assets and ISC attribution: svg/lucide. Keep the legacy Icon API so
all callers use the same upstream library without a web runtime.
"""
from enum import Enum

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QIconEngine, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

PATHS = {'plus': '<path d="M5 12h14" />\n  <path d="M12 5v14" />',
 'close': '<path d="M18 6 6 18" />\n  <path d="m6 6 12 12" />',
 'check': '<path d="M20 6 9 17l-5-5" />',
 'chevron-down': '<path d="m6 9 6 6 6-6" />',
 'chevron-right': '<path d="m9 18 6-6-6-6" />',
 'search': '<path d="m21 21-4.34-4.34" />\n  <circle cx="11" cy="11" r="8" />',
 'folder': '<path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 '
           '3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z" />',
 'file': '<path d="M6 22a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h8a2.4 2.4 0 0 1 1.704.706l3.588 3.588A2.4 2.4 0 0 1 '
         '20 8v12a2 2 0 0 1-2 2z" />\n'
         '  <path d="M14 2v5a1 1 0 0 0 1 1h5" />\n'
         '  <path d="M10 9H8" />\n'
         '  <path d="M16 13H8" />\n'
         '  <path d="M16 17H8" />',
 'copy': '<rect width="14" height="14" x="8" y="8" rx="2" ry="2" />\n'
         '  <path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2" />',
 'clipboard': '<rect width="8" height="4" x="8" y="2" rx="1" ry="1" />\n'
              '  <path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2" />',
 'image': '<rect width="18" height="18" x="3" y="3" rx="2" ry="2" />\n'
          '  <circle cx="9" cy="9" r="2" />\n'
          '  <path d="m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21" />',
 'link': '<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" />\n'
         '  <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" />',
 'code': '<path d="m16 18 6-6-6-6" />\n  <path d="m8 6-6 6 6 6" />',
 'star': '<path d="M11.525 2.295a.53.53 0 0 1 .95 0l2.31 4.679a2.123 2.123 0 0 0 1.595 1.16l5.166.756a.53.53 '
         '0 0 1 .294.904l-3.736 3.638a2.123 2.123 0 0 0-.611 1.878l.882 5.14a.53.53 0 0 '
         '1-.771.56l-4.618-2.428a2.122 2.122 0 0 0-1.973 0L6.396 21.01a.53.53 0 0 1-.77-.56l.881-5.139a2.122 '
         '2.122 0 0 0-.611-1.879L2.16 9.795a.53.53 0 0 1 .294-.906l5.165-.755a2.122 2.122 0 0 0 1.597-1.16z" '
         '/>',
 'pin': '<path d="M12 17v5" />\n'
        '  <path d="M9 10.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24V16a1 1 0 0 0 1 1h12a1 1 0 0 0 '
        '1-1v-.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V7a1 1 0 0 1 1-1 2 2 0 0 0 0-4H8a2 2 0 0 0 '
        '0 4 1 1 0 0 1 1 1z" />',
 'more': '<circle cx="12" cy="12" r="1" />\n'
         '  <circle cx="19" cy="12" r="1" />\n'
         '  <circle cx="5" cy="12" r="1" />',
 'filter': '<path d="M2 5h20" />\n  <path d="M6 12h12" />\n  <path d="M9 19h6" />',
 'edit': '<path d="M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 '
         '.623.622l4.353-1.32a2 2 0 0 0 .83-.497z" />\n'
         '  <path d="m15 5 4 4" />',
 'trash': '<path d="M10 11v6" />\n'
          '  <path d="M14 11v6" />\n'
          '  <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6" />\n'
          '  <path d="M3 6h18" />\n'
          '  <path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />',
 'download': '<path d="M12 15V3" />\n'
             '  <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />\n'
             '  <path d="m7 10 5 5 5-5" />',
 'upload': '<path d="M12 3v12" />\n'
           '  <path d="m17 8-5-5-5 5" />\n'
           '  <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />',
 'settings': '<path d="M10 5H3" />\n'
             '  <path d="M12 19H3" />\n'
             '  <path d="M14 3v4" />\n'
             '  <path d="M16 17v4" />\n'
             '  <path d="M21 12h-9" />\n'
             '  <path d="M21 19h-5" />\n'
             '  <path d="M21 5h-7" />\n'
             '  <path d="M8 10v4" />\n'
             '  <path d="M8 12H3" />',
 'sun': '<circle cx="12" cy="12" r="4" />\n'
        '  <path d="M12 2v2" />\n'
        '  <path d="M12 20v2" />\n'
        '  <path d="m4.93 4.93 1.41 1.41" />\n'
        '  <path d="m17.66 17.66 1.41 1.41" />\n'
        '  <path d="M2 12h2" />\n'
        '  <path d="M20 12h2" />\n'
        '  <path d="m6.34 17.66-1.41 1.41" />\n'
        '  <path d="m19.07 4.93-1.41 1.41" />',
 'moon': '<path d="M20.985 12.486a9 9 0 1 1-9.473-9.472c.405-.022.617.46.402.803a6 6 0 0 0 8.268 '
         '8.268c.344-.215.825-.004.803.401" />',
 'info': '<circle cx="12" cy="12" r="10" />\n  <path d="M12 16v-4" />\n  <path d="M12 8h.01" />',
 'history': '<path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />\n'
            '  <path d="M3 3v5h5" />\n'
            '  <path d="M12 7v5l4 2" />',
 'save': '<path d="M15.2 3a2 2 0 0 1 1.4.6l3.8 3.8a2 2 0 0 1 .6 1.4V19a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 '
         '0 1 2-2z" />\n'
         '  <path d="M17 21v-7a1 1 0 0 0-1-1H8a1 1 0 0 0-1 1v7" />\n'
         '  <path d="M7 3v4a1 1 0 0 0 1 1h7" />',
 'camera': '<path d="M13.997 4a2 2 0 0 1 1.76 1.05l.486.9A2 2 0 0 0 18.003 7H20a2 2 0 0 1 2 2v9a2 2 0 0 1-2 '
           '2H4a2 2 0 0 1-2-2V9a2 2 0 0 1 2-2h1.997a2 2 0 0 0 1.759-1.048l.489-.904A2 2 0 0 1 10.004 4z" />\n'
           '  <circle cx="12" cy="13" r="3" />',
 'message': '<path d="M22 17a2 2 0 0 1-2 2H6.828a2 2 0 0 0-1.414.586l-2.202 2.202A.71.71 0 0 1 2 21.286V5a2 '
            '2 0 0 1 2-2h16a2 2 0 0 1 2 2z" />',
 'eye-off': '<path d="M10.733 5.076a10.744 10.744 0 0 1 11.205 6.575 1 1 0 0 1 0 .696 10.747 10.747 0 0 '
            '1-1.444 2.49" />\n'
            '  <path d="M14.084 14.158a3 3 0 0 1-4.242-4.242" />\n'
            '  <path d="M17.479 17.499a10.75 10.75 0 0 1-15.417-5.151 1 1 0 0 1 0-.696 10.75 10.75 0 0 1 '
            '4.446-5.143" />\n'
            '  <path d="m2 2 20 20" />'}


class _OutlineEngine(QIconEngine):
    def __init__(self, name, color):
        super().__init__()
        self.name, self.color = name, QColor(color).name()

    def clone(self):
        return _OutlineEngine(self.name, self.color)

    def paint(self, painter, rect, mode, state):
        color = self.color
        opacity = ' opacity="0.45"' if mode == QIcon.Mode.Disabled else ''
        body = PATHS[self.name].replace("currentColor", color)
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
               f'fill="none" stroke="{color}" stroke-width="2" '
               f'stroke-linecap="round" stroke-linejoin="round"{opacity}>{body}</svg>')
        renderer = QSvgRenderer(QByteArray(svg.encode()))
        renderer.render(painter, QRectF(rect))

    def pixmap(self, size, mode, state):
        image = QPixmap(size)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        self.paint(painter, image.rect(), mode, state)
        painter.end()
        return image


def outline_icon(name, color="#171717"):
    if name not in PATHS:
        raise ValueError(f"Unknown outline icon: {name}")
    return QIcon(_OutlineEngine(name, color))


class Icon(str, Enum):
    PLUS = "plus"
    CLOSE = "close"
    CHECK = "check"
    CHEVRON_DOWN = "chevron-down"
    CHEVRON_RIGHT = "chevron-right"
    SEARCH = "search"
    FOLDER = "folder"
    FILE = "file"
    COPY = "copy"
    CLIPBOARD = "clipboard"
    IMAGE = "image"
    LINK = "link"
    CODE = "code"
    STAR = "star"
    PIN = "pin"
    MORE = "more"
    FILTER = "filter"
    EDIT = "edit"
    TRASH = "trash"
    DOWNLOAD = "download"
    UPLOAD = "upload"
    SETTINGS = "settings"
    SUN = "sun"
    MOON = "moon"
    INFO = "info"
    HISTORY = "history"
    SAVE = "save"
    CAMERA = "camera"
    MESSAGE = "message"
    EYE_OFF = "eye-off"

    def render_icon(self, color):
        return outline_icon(self.value, color)

    def icon(self):
        return self.render_icon("#171717")
