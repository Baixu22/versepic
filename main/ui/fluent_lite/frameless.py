"""Shared frameless window foundation for application dialogs."""

from PySide6.QtCore import Qt
from qframelesswindow import FramelessDialog

from core.ui_theme import get_ui_theme

from core.ui_scale import widget_scaled
from .theme import WINDOW_RADIUS, paint_solid_background, ui_font


class FrostedFramelessDialog(FramelessDialog):
    """Frameless dialog with one consistent opaque solid background.

    The previous acrylic/blur detection has been removed in favour of a cheap,
    stable solid backdrop (see ``paint_solid_background``).
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFont(ui_font())
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._frosted_corner_radius = WINDOW_RADIUS
        get_ui_theme().theme_changed.connect(self._on_theme_changed)

    def _on_theme_changed(self, _tokens):
        self.update()

    def paintEvent(self, event):
        radius = 0 if self.isMaximized() or self.isFullScreen() else widget_scaled(self, self._frosted_corner_radius)
        paint_solid_background(self, radius)


__all__ = ["FramelessDialog", "FrostedFramelessDialog"]
