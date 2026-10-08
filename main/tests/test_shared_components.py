"""Behaviour across the public Qt component API and real application consumers."""
import pytest

from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QFocusEvent
from PySide6.QtWidgets import QDialogButtonBox, QVBoxLayout, QWidget

from core.ui_theme import DARK_TOKENS, get_ui_theme
from ui.dialogs import StandardDialog
from ui.fluent_lite import (
    Button, ComboBox, LineEdit, Menu, PrimaryPushButton, PushButton, SegmentedWidget,
    SwitchButton, TextEdit, ToolTip, TransparentPushButton,
)


@pytest.mark.parametrize("button_class", [Button, PushButton, PrimaryPushButton, TransparentPushButton])
def test_button_keyboard_and_caller_geometry_survive_theme_changes(qtbot, button_class):
    root = QWidget()
    qtbot.addWidget(root)
    root._ui_theme_tokens_override = DARK_TOKENS
    button = button_class("Keep open", root)
    button.setCheckable(True)
    button.setFixedWidth(180)
    button.setBaseIconSize(22)
    layout = QVBoxLayout(root)
    layout.addWidget(button)
    root.show()
    states = []
    button.toggled.connect(states.append)
    qtbot.keyClick(button, Qt.Key.Key_Space)
    assert states == [True]
    button._apply_theme()
    assert button.width() == 180
    assert button.maximumWidth() == 180
    assert button.iconSize().width() == 22
    button.setEnabled(False)
    qtbot.keyClick(button, Qt.Key.Key_Space)
    assert states == [True]


def test_tabs_use_visual_order_skip_disabled_and_keep_one_tab_stop(qtbot):
    tabs = SegmentedWidget()
    qtbot.addWidget(tabs)
    tabs.addItem("a", "A")
    tabs.addItem("c", "C")
    tabs.insertItem(1, "b", "B")
    tabs._items["b"].setEnabled(False)
    tabs.show()
    changes = []
    tabs.currentItemChanged.connect(changes.append)
    qtbot.keyClick(tabs._items["a"], Qt.Key.Key_Right)
    assert tabs.currentItem() == "c"
    qtbot.keyClick(tabs._items["c"], Qt.Key.Key_Home)
    assert tabs.currentItem() == "a"
    qtbot.keyClick(tabs._items["a"], Qt.Key.Key_End)
    assert tabs.currentItem() == "c"
    assert changes == ["c", "a", "c"]
    assert [key for key, item in tabs._items.items() if item.focusPolicy() & Qt.FocusPolicy.TabFocus] == ["c"]


@pytest.mark.parametrize("help_text", ["Keyboard help", "粘贴后保持打开"])
def test_keyboard_tooltip_dismisses_without_changing_focus(qtbot, qapp, help_text):
    root = QWidget()
    qtbot.addWidget(root)
    button = Button("Help", root)
    button.setToolTip(help_text)
    tip = ToolTip.install(root)
    root.show()
    button.setFocus()
    focus = qapp.focusWidget()
    qapp.sendEvent(button, QFocusEvent(QEvent.Type.FocusIn, Qt.FocusReason.TabFocusReason))
    assert tip.label.isVisible()
    assert tip.label.text() == help_text
    assert tip.label.width() >= tip.label.fontMetrics().horizontalAdvance(help_text) + 18
    assert qapp.focusWidget() is focus
    qtbot.keyClick(button, Qt.Key.Key_Escape)
    assert not tip.label.isVisible()
    qapp.sendEvent(button, QFocusEvent(QEvent.Type.FocusIn, Qt.FocusReason.MouseFocusReason))
    assert not tip.label.isVisible()


@pytest.mark.parametrize("editor_class", [LineEdit, TextEdit, ComboBox])
def test_validation_state_does_not_erase_content_on_theme_change(qtbot, editor_class):
    editor = editor_class()
    qtbot.addWidget(editor)
    if isinstance(editor, ComboBox):
        editor.addItems(["One", "Two"])
        editor.setCurrentIndex(1)
        content = editor.currentText
    elif isinstance(editor, TextEdit):
        editor.setPlainText("中文 input")
        content = editor.toPlainText
    else:
        editor.setText("中文 input")
        content = editor.text
    original = content()
    editor.setInvalid(True)
    editor._ui_theme_tokens_override = DARK_TOKENS
    editor._apply_theme()
    assert editor.property("invalid") is True
    assert content() == original
    editor.setInvalid(False)
    assert editor.property("invalid") is False
    assert content() == original


def test_real_dialog_uses_shared_buttons_and_preserves_rejection(qtbot):
    parent = QWidget()
    qtbot.addWidget(parent)
    parent._ui_theme_tokens_override = DARK_TOKENS
    dialog = StandardDialog(parent, "Confirm", "Save changes?")
    qtbot.addWidget(dialog)
    save = dialog.button_box.addButton("Save", QDialogButtonBox.ButtonRole.AcceptRole)
    cancel = dialog.button_box.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
    assert isinstance(save, Button) and isinstance(cancel, Button)
    assert save._colors()[2] == DARK_TOKENS.primary_foreground
    assert dialog.button_box.buttonRole(cancel) == QDialogButtonBox.ButtonRole.RejectRole
    assert DARK_TOKENS.window in dialog.styleSheet()
    accepted, rejected = [], []
    dialog.accepted.connect(lambda: accepted.append(True))
    dialog.rejected.connect(lambda: rejected.append(True))
    dialog.show()
    qtbot.keyClick(dialog, Qt.Key.Key_Escape)
    assert rejected == [True] and accepted == []


def test_reduced_motion_hides_immediately_without_a_late_callback(qtbot, qapp):
    from ui.motion import fade_hide
    widget = QWidget()
    qtbot.addWidget(widget)
    previous = qapp.property("uiReducedMotion")
    try:
        qapp.setProperty("uiReducedMotion", True)
        widget.show()
        fade_hide(widget)
        assert not widget.isVisible()
        widget.show()
        qtbot.wait(180)
        assert widget.isVisible()
    finally:
        qapp.setProperty("uiReducedMotion", previous)


def test_native_menu_skips_disabled_items_and_toggles_once(qtbot):
    menu = Menu()
    qtbot.addWidget(menu)
    first = menu.addAction("Copy")
    menu.addAction("Unavailable").setEnabled(False)
    pin = menu.addAction("Pinned")
    pin.setCheckable(True)
    toggles = []
    pin.toggled.connect(toggles.append)
    menu.popup(QPoint(40, 40))
    menu.setActiveAction(first)
    qtbot.keyClick(menu, Qt.Key.Key_Down)
    assert menu.activeAction() is pin
    qtbot.keyClick(menu, Qt.Key.Key_Return)
    assert toggles == [True]
    assert not menu.isVisible()


def test_switch_thumb_mirrors_in_rtl_at_scaled_size(qtbot):
    switch = SwitchButton()
    qtbot.addWidget(switch)
    switch.setProperty("dialog_scale_factor", 1.5)
    switch._apply_theme()
    switch.setChecked(True)
    left_to_right = switch.grab().toImage()
    switch.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    right_to_left = switch.grab().toImage()
    y = left_to_right.height() // 2
    left, right = left_to_right.width() // 4, left_to_right.width() * 3 // 4
    assert left_to_right.pixelColor(left, y) == right_to_left.pixelColor(right, y)
    assert left_to_right.pixelColor(right, y) == right_to_left.pixelColor(left, y)
    assert left_to_right.pixelColor(left, y) != left_to_right.pixelColor(right, y)


def test_gallery_reuses_production_components_and_switches_theme(qtbot):
    from ui.component_gallery import ComponentGallery
    manager = get_ui_theme()
    original = manager.mode
    gallery = ComponentGallery()
    qtbot.addWidget(gallery)
    try:
        gallery.show()
        gallery.dark.setChecked(True)
        assert manager.is_dark
        assert isinstance(gallery.input, LineEdit)
        qtbot.keyClicks(gallery.input, "query")
        gallery.dark.setChecked(False)
        assert not manager.is_dark
        assert gallery.input.text() == "query"
    finally:
        manager.set_mode(original, persist=False)
