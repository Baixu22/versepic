"""In-memory, per-owner sensitive capture policy. Never changes user settings."""
from contextvars import ContextVar
from core.i18n import make_tr

sensitive_ocr = ContextVar("sensitive_ocr", default=False)

_tr = make_tr("CapturePrivacy")


def is_sensitive(owner):
    return getattr(owner, "sensitive_capture", False) is True


def notice():
    return _tr("Sensitive capture · memory only. Only Copy writes to the system clipboard. Save, collection, projects, recording, text extraction and translation are unavailable. Pins and redaction keep this policy. Other apps may read copied pixels; no secure-erasure guarantee.")


def blocked(owner):
    if not is_sensitive(owner):
        return False
    from ui.dialogs import show_warning_dialog
    show_warning_dialog(owner, _tr("Sensitive capture"), notice())
    return True


def ensure_supported(parent=None):
    from core.clipboard_utils import private_clipboard_supported
    if private_clipboard_supported():
        return True
    from ui.dialogs import show_warning_dialog
    show_warning_dialog(parent, _tr("Sensitive capture unavailable"),
        _tr("The private clipboard protocol is unavailable. Rebuild/install this checkout's pyclipboard module. No sensitive capture was started."))
    return False


def copy_private(image, parent=None):
    from core.clipboard_utils import deliver_image_async
    try:
        deliver_image_async(image, sensitive=True, copy_to_clipboard=True)
        return True
    except Exception:
        # Never expose exception payloads or retry as a normal copy.
        from ui.dialogs import show_warning_dialog
        show_warning_dialog(parent, _tr("Sensitive copy failed"),
            _tr("The image was not copied successfully. It was not saved or retried as an ordinary copy."))
        return False


def install_text_guard(owner):
    """Block native text-copy/cut/context menus inside a sensitive owner only.

    Image Copy buttons still go through copy_private. No global clipboard hook,
    settings change or interception of another application's input is installed.
    """
    if getattr(owner, "_private_text_guard", None) is not None:
        return
    from PySide6.QtCore import QEvent, QObject
    from PySide6.QtGui import QKeySequence
    from PySide6.QtWidgets import QApplication, QGraphicsView, QLineEdit, QPlainTextEdit, QTextEdit, QWidget

    class Guard(QObject):
        def eventFilter(self, obj, event):
            import shiboken6
            # Qt may deliver events while parent destruction precedes child
            # filter deletion. Never dereference the already-destroyed owner.
            if not shiboken6.isValid(owner) or not shiboken6.isValid(obj):
                return False
            if not is_sensitive(owner) or not isinstance(obj, QWidget):
                return False
            if obj is not owner and not owner.isAncestorOf(obj):
                return False
            if event.type() not in (QEvent.Type.KeyPress, QEvent.Type.ShortcutOverride, QEvent.Type.ContextMenu):
                return False
            widget = obj
            editing = False
            while widget is not None and widget is not owner:
                if isinstance(widget, (QLineEdit, QPlainTextEdit, QTextEdit)):
                    editing = True
                    break
                if isinstance(widget, QGraphicsView):
                    focus = widget.scene().focusItem() if widget.scene() else None
                    editing = focus is not None and hasattr(focus, "textCursor")
                    break
                widget = widget.parentWidget()
            if editing and (event.type() == QEvent.Type.ContextMenu
                    or event.matches(QKeySequence.StandardKey.Copy) or event.matches(QKeySequence.StandardKey.Cut)):
                event.accept()
                return True
            return False

    owner._private_text_guard = Guard(owner)
    QApplication.instance().installEventFilter(owner._private_text_guard)


def remove_text_guard(owner):
    from PySide6.QtWidgets import QApplication
    guard = getattr(owner, "_private_text_guard", None)
    if guard is not None:
        QApplication.instance().removeEventFilter(guard)
        owner._private_text_guard = None
        guard.deleteLater()


def badge_text():
    return _tr("Sensitive capture · no files or history · only explicit Copy")
