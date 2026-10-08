# -*- coding: utf-8 -*-
"""Small Qt Widgets motion helpers (fade, rise, hover) used by the Apple-style UI."""

from __future__ import annotations

from PySide6.QtCore import (
    QEasingCurve,
    QObject,
    QPropertyAnimation,
    QRect,
    QVariantAnimation,
)
from PySide6.QtWidgets import QWidget

_ANIMS_ATTR = "_motion_anims"
_OPENING_ATTR = "_motion_opening"
_CLOSING_ATTR = "_motion_closing"


def _remember(widget: QWidget, anim) -> None:
    """Parent the animation to the widget and keep a strong ref so GC can't kill it."""
    anim.setParent(widget)
    anims = getattr(widget, _ANIMS_ATTR, None)
    if anims is None:
        anims = []
        setattr(widget, _ANIMS_ATTR, anims)
    anims.append(anim)
    anim.finished.connect(lambda: _forget(widget, anim))


def _forget(widget: QObject, anim) -> None:
    try:
        anims = getattr(widget, _ANIMS_ATTR, None)
        if anims is not None and anim in anims:
            anims.remove(anim)
    except (RuntimeError, ValueError):
        pass


def reset_opacity(widget: QWidget) -> None:
    """Restore full opacity; call before re-showing a window that was fade_hidden."""
    try:
        widget.setWindowOpacity(1.0)
    except RuntimeError:
        pass
    setattr(widget, _CLOSING_ATTR, False)


def cancel_motion(widget: QWidget) -> None:
    """Stop pending fade_show/fade_hide animations and restore full opacity.

    `finished` signals are blocked while stopping so their hide/finalize
    callbacks never fire (a fade_hide in flight would otherwise hide the
    window right after a re-show).
    """
    anims = list(getattr(widget, _ANIMS_ATTR, None) or [])
    for anim in anims:
        try:
            anim.blockSignals(True)
            anim.stop()
            anim.blockSignals(False)
            anim.deleteLater()
        except RuntimeError:
            pass
    try:
        if hasattr(widget, _ANIMS_ATTR):
            setattr(widget, _ANIMS_ATTR, [])
        widget.setWindowOpacity(1.0)
    except RuntimeError:
        pass
    setattr(widget, _OPENING_ATTR, False)
    setattr(widget, _CLOSING_ATTR, False)


def fade_show(widget: QWidget, duration: int = 200, rise_px: int = 10) -> None:
    """Fade the window in from transparent while rising a few pixels into place.

    Recoding the final geometry first; a repeated call while one is running is a no-op.
    Callers showing the window again after fade_hide may either call reset_opacity()
    first or rely on this function, which also restores opacity.
    """
    from PySide6.QtWidgets import QApplication
    if QApplication.instance().property("uiReducedMotion"):
        widget.setWindowOpacity(1.0)
        return
    if getattr(widget, _OPENING_ATTR, False):
        return
    setattr(widget, _OPENING_ATTR, True)

    final_geo = QRect(widget.geometry())
    start_geo = QRect(final_geo)
    start_geo.translate(0, rise_px)

    opacity = QPropertyAnimation(widget, b"windowOpacity", widget)
    opacity.setDuration(duration)
    opacity.setStartValue(0.0)
    opacity.setEndValue(1.0)
    opacity.setEasingCurve(QEasingCurve.Type.OutCubic)

    geometry = QPropertyAnimation(widget, b"geometry", widget)
    geometry.setDuration(duration)
    geometry.setStartValue(start_geo)
    geometry.setEndValue(final_geo)
    geometry.setEasingCurve(QEasingCurve.Type.OutCubic)

    def _done():
        setattr(widget, _OPENING_ATTR, False)
        try:
            widget.setGeometry(final_geo)
            widget.setWindowOpacity(1.0)
        except RuntimeError:
            pass

    geometry.finished.connect(_done)
    widget.setWindowOpacity(0.0)
    widget.setGeometry(start_geo)
    _remember(widget, opacity)
    _remember(widget, geometry)
    opacity.start()
    geometry.start()


def fade_hide(widget: QWidget, duration: int = 160) -> None:
    """Fade the window out and hide it when the animation finishes."""
    from PySide6.QtWidgets import QApplication
    if QApplication.instance().property("uiReducedMotion"):
        cancel_motion(widget)
        QWidget.hide(widget)  # A window's hide() override may route back to fade_hide.
        return
    if getattr(widget, _CLOSING_ATTR, False):
        return
    setattr(widget, _CLOSING_ATTR, True)

    opacity = QPropertyAnimation(widget, b"windowOpacity", widget)
    opacity.setDuration(duration)
    opacity.setStartValue(1.0)
    opacity.setEndValue(0.0)
    opacity.setEasingCurve(QEasingCurve.Type.OutCubic)

    def _done():
        try:
            widget.hide()
            widget.setWindowOpacity(1.0)
        except RuntimeError:
            pass
        setattr(widget, _CLOSING_ATTR, False)

    opacity.finished.connect(_done)
    _remember(widget, opacity)
    opacity.start()


class HoverAnimator(QObject):
    """Drive a 0..1 hover progress value on a widget, repainting it each frame.

    Tolerates rapid enter/leave sequences and silently stops if the target
    widget is deleted.
    """

    def __init__(self, target: QWidget, duration: int = 150):
        super().__init__(target)
        self._target = target
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(duration)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._on_value)
        self._value = 0.0
        try:
            target.destroyed.connect(self.stop)
        except (RuntimeError, TypeError):
            pass

    def value(self) -> float:
        return float(self._value)

    def _on_value(self, v) -> None:
        self._value = float(v)
        try:
            self._target.update()
        except RuntimeError:
            self.stop()

    def _run(self, end: float) -> None:
        try:
            self._anim.stop()
            from PySide6.QtWidgets import QApplication
            app = QApplication.instance()
            if app is not None and app.property("uiReducedMotion"):
                self._on_value(end)
                return
            self._anim.setStartValue(self._value)
            self._anim.setEndValue(end)
            self._anim.start()
        except RuntimeError:
            pass

    def enter(self) -> None:
        self._run(1.0)

    def leave(self) -> None:
        self._run(0.0)

    def stop(self) -> None:
        try:
            self._anim.stop()
            self.deleteLater()
        except RuntimeError:
            pass


def apply_frost(window: QWidget, tokens=None, blur_radius: int = 24) -> bool:
    """Best-effort acrylic-style backdrop: only enables translucency.

    Returns True if translucent background was (or already is) enabled.

    There is deliberately no QGraphicsBlurEffect here: applying a graphics
    effect to a top-level window re-renders the whole window into an offscreen
    bitmap, which breaks native input (mouse grabs, IME, child native windows)
    and kills resizing performance.  The container should instead paint a
    semi-opaque rounded background from `tokens` in paintEvent; on platforms
    where the compositor supports it the OS will blend whatever is behind.
    On Windows the fallback look is simply a flat semi-opaque window.
    """
    try:
        from PySide6.QtCore import Qt

        if not window.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground):
            window.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        return True
    except RuntimeError:
        return False
