"""Shared themed and translated context menus for Qt text editors."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QStyleFactory

from core.i18n import make_tr
from core.ui_theme import UIThemeManager

from .theme import menu_qss, ui_tokens


_tr = make_tr("TextEditContextMenu")

_STANDARD_ACTION_LABELS = {
    "edit-undo": "Undo",
    "edit-redo": "Redo",
    "edit-cut": "Cut",
    "edit-copy": "Copy",
    "edit-paste": "Paste",
    "edit-delete": "Delete",
    "select-all": "Select All",
}


def _translate_standard_actions(menu) -> None:
    """Route Qt's built-in editor labels through the app translator."""
    for action in menu.actions():
        source = _STANDARD_ACTION_LABELS.get(action.objectName())
        if source is None:
            continue
        _old_label, separator, shortcut = action.text().partition("\t")
        translated = _tr(source)
        action.setText(
            f"{translated}{separator}{shortcut}"
            if separator
            else translated
        )


def create_text_context_menu(editor):
    """Create a standard editor menu using the active app theme and language."""
    menu = editor.createStandardContextMenu()
    menu.setProperty("dialog_scale_factor", editor.property("dialog_scale_factor"))
    _translate_standard_actions(menu)
    style_popup_menu(menu, ui_tokens(editor))
    return menu


def style_popup_menu(menu, tokens) -> None:
    """Give a popup menu the app theme regardless of its parent's stylesheet.

    A menu parented to a styled widget inherits that widget's stylesheet instead
    of the global QMenu rules, which renders it black.
    """
    # Standard editor menus are transient top-level windows. On Windows they
    # may otherwise retain the OS dark popup renderer while the app is light.
    fusion_style = QStyleFactory.create("Fusion")
    if fusion_style is not None:
        fusion_style.setParent(menu)
        menu.setStyle(fusion_style)
    menu.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
    menu.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    menu.setAutoFillBackground(True)
    menu.setPalette(UIThemeManager.build_palette(tokens))
    menu.setStyleSheet(menu_qss(menu, tokens=tokens))


def show_text_context_menu(editor, global_pos) -> None:
    menu = create_text_context_menu(editor)
    menu.exec(global_pos)
    menu.deleteLater()


def install_text_context_menu(editor) -> None:
    """Install the shared menu on an existing editor, such as a spin-box edit."""
    editor.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    editor.customContextMenuRequested.connect(
        lambda pos, target=editor: show_text_context_menu(
            target, target.mapToGlobal(pos)
        )
    )


class TextContextMenuMixin:
    """Mixin for QLineEdit/QTextEdit subclasses with the shared context menu."""

    def createThemedContextMenu(self):
        return create_text_context_menu(self)

    def contextMenuEvent(self, event):
        show_text_context_menu(self, event.globalPos())


__all__ = [
    "TextContextMenuMixin",
    "create_text_context_menu",
    "install_text_context_menu",
    "show_text_context_menu",
]
