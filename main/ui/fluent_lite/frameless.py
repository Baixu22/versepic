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

    def _initFrameless(self):
        """初始化无边框窗口；只对第三方库那一次可选信号连接失败兜底。

        qframelesswindow 会执行 self.windowHandle().screenChanged.connect(...)。
        全量跑里出现过 PySide6 返回错误包装类型（QWidgetItem）的偶发情况，导致
        AttributeError 把整个对话框构造打断（偏差 TFD-6e1327a941）。这里先强制
        原生窗口存在，并且只吞 screenChanged 连接失败这一种异常，随后补上被跳过
        的收尾步骤；其它异常照旧抛出，不掩盖真实问题。
        """
        from core.logger import T, log_warning

        try:
            self.winId()  # 先建原生窗口，尽量让 windowHandle() 拿到正确的 QWindow
        except Exception:
            pass
        try:
            super()._initFrameless()
        except AttributeError as exc:
            if "screenChanged" not in str(exc):
                raise
            log_warning(
                T("frameless windowHandle 类型异常，跳过 screenChanged 连接: {exc}", exc=exc),
                "FramelessDialog",
            )
            self.resize(500, 500)
            self.titleBar.raise_()

    def _on_theme_changed(self, _tokens):
        self.update()

    def paintEvent(self, event):
        radius = 0 if self.isMaximized() or self.isFullScreen() else widget_scaled(self, self._frosted_corner_radius)
        paint_solid_background(self, radius)


__all__ = ["FramelessDialog", "FrostedFramelessDialog"]
