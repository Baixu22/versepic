"""Management workflow and lightweight rendering regressions."""
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QButtonGroup, QPushButton, QWidget

import clipboard.ui.dialogs.manage_dialog as mod
from clipboard.core import ClipboardItem
from clipboard.ui.forms.group_icon_picker import first_grapheme
from .test_clipboard_manage_dialog import DummyClipboardManager


@pytest.fixture
def editor(qapp):
    manager = DummyClipboardManager()
    manager.items = {1: ClipboardItem(id=1, content="<b>literal markup</b>\nsecond line", content_type="text", title="First")}
    manager.get_by_group = lambda group_id, offset=0, limit=50: list(manager.items.values())[offset:offset + limit] if group_id == 1 else []
    dialog = mod.ManageDialog(manager)
    yield dialog, manager
    dialog.hide()
    dialog.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_new_action_is_not_a_draggable_data_row(editor):
    dialog, manager = editor
    assert dialog.list_widget.count() == len(manager.groups)
    assert all(dialog.list_widget.item(i).data(Qt.ItemDataRole.UserRole)[0] == "group" for i in range(dialog.list_widget.count()))


def test_keyboard_selection_opens_matching_editor(editor):
    dialog, _ = editor
    dialog.show()
    dialog.list_widget.setFocus()
    dialog.list_widget.setCurrentRow(0)
    QTest.keyClick(dialog.list_widget, Qt.Key.Key_Down)
    assert dialog.editing_group_id == 2
    assert dialog.group_name_input.text() == "学习"


def test_cancel_dirty_selection_restores_both_list_and_form(editor, monkeypatch):
    dialog, _ = editor
    dialog.list_widget.setCurrentRow(0)
    dialog.group_name_input.setText("draft")
    monkeypatch.setattr(mod, "show_confirm_dialog", lambda *args: False)
    dialog.list_widget.setCurrentRow(1)
    assert dialog.list_widget.currentRow() == 0
    assert dialog.editing_group_id == 1
    assert dialog.group_name_input.text() == "draft"


def test_cancel_dirty_navigation_restores_checked_route(editor, monkeypatch):
    dialog, _ = editor
    dialog.group_name_input.setText("draft")
    monkeypatch.setattr(mod, "show_confirm_dialog", lambda *args: False)
    dialog.nav_interface.widget("content").click()
    assert dialog.current_mode == "group"
    assert dialog.nav_interface.widget("group").isChecked()
    assert dialog.group_name_input.text() == "draft"


def test_confirm_dirty_navigation_opens_requested_route(editor, monkeypatch):
    dialog, _ = editor
    dialog.group_name_input.setText("draft")
    monkeypatch.setattr(mod, "show_confirm_dialog", lambda *args: True)
    dialog.nav_interface.widget("content").click()
    assert dialog.current_mode == "content"
    assert not dialog._dirty
    assert dialog.list_column.graphicsEffect() is None
    assert dialog.detail_column.graphicsEffect() is None


def test_close_cancel_keeps_draft(editor, monkeypatch):
    dialog, _ = editor
    dialog.group_name_input.setText("draft")
    monkeypatch.setattr(mod, "show_confirm_dialog", lambda *args: False)
    event = QCloseEvent()
    dialog.closeEvent(event)
    assert not event.isAccepted()
    assert dialog._dirty


def test_group_combo_cancel_preserves_group_and_draft(editor, monkeypatch):
    dialog, _ = editor
    dialog._apply_mode("content")
    dialog.content_edit.setPlainText("draft")
    monkeypatch.setattr(mod, "show_confirm_dialog", lambda *args: False)
    dialog.group_combo.setCurrentIndex(1)
    assert dialog.group_combo.currentData() == 1
    assert dialog.selected_group_id == 1
    assert dialog.content_edit.toPlainText() == "draft"


@pytest.mark.parametrize("glyph", ["👩🏽‍💻", "🇨🇳", "❤️", "1️⃣", "👨‍👩‍👧‍👦", "é", "💼"])
def test_group_icons_preserve_complete_grapheme(editor, glyph):
    dialog, _ = editor
    assert first_grapheme(glyph + "more") == glyph
    dialog._on_preset_icon_clicked(glyph)
    assert dialog._get_selected_icon() == glyph


def test_picker_is_lazy_and_has_no_per_emoji_widgets(editor):
    dialog, _ = editor
    assert dialog._icon_popup is None
    dialog.icon_picker_button.click()
    popup = dialog._icon_popup
    assert popup.grid.count() > 100
    assert len(popup.findChildren(QPushButton)) < 12
    popup.choose("🇨🇳")
    assert dialog._get_selected_icon() == "🇨🇳"
    assert not popup.isVisible()


def test_rebuilding_forms_does_not_accumulate_hidden_controls(editor):
    dialog, _ = editor
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    initial = len(dialog.findChildren(QWidget))
    for _ in range(10):
        dialog._show_new_group_form()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert len(dialog.findChildren(QWidget)) == initial
    assert len(dialog.detail_content.findChildren(QButtonGroup)) == 1


def test_content_editing_preserves_plain_text_and_undo_cleans_dirty_state(editor):
    dialog, manager = editor
    dialog._apply_mode("content")
    dialog.list_widget.setCurrentRow(0)
    assert dialog.content_edit.toPlainText() == manager.items[1].content
    dialog.content_edit.insertPlainText("x")
    assert dialog._dirty
    dialog.content_edit.undo()
    assert not dialog._dirty


def test_saved_feedback_and_default_button_contract(editor):
    dialog, manager = editor
    dialog.list_widget.setCurrentRow(0)
    dialog.group_name_input.setText("renamed")
    dialog.save_btn.click()
    assert manager.updated_groups[-1][1] == "renamed"
    assert not dialog._dirty
    assert dialog.status_label.text() == dialog.tr("Saved")
    assert dialog.save_btn.isDefault()
    assert all(not button.autoDefault() for button in dialog.findChildren(QPushButton))


def test_transfer_has_no_orphan_footer_and_no_save_action(editor):
    dialog, manager = editor
    dialog._apply_mode("import_export")
    assert dialog.footer.isHidden()
    assert dialog.footer_separator.isHidden()
    dialog._on_save_clicked()
    assert not manager.created_groups


def test_discarding_on_close_restores_persisted_form(editor, monkeypatch):
    dialog, _ = editor
    dialog.list_widget.setCurrentRow(0)
    dialog.group_name_input.setText("draft")
    monkeypatch.setattr(mod, "show_confirm_dialog", lambda *args: True)
    dialog.closeEvent(QCloseEvent())
    assert not dialog._dirty
    assert dialog.group_name_input.text() == "工作"


def test_empty_content_has_actionable_group_creation(editor):
    dialog, manager = editor
    manager.groups = []
    dialog._apply_mode("content")
    assert dialog.list_widget.count() == 0
    assert dialog.footer.isHidden()
    assert not dialog.group_combo.isEnabled()
    create = next(button for button in dialog.detail_content.findChildren(QPushButton) if button.text() == dialog.tr("New Group"))
    create.click()
    assert dialog.current_mode == "group"
    assert dialog.new_btn.isEnabled()
    assert not dialog.footer.isHidden()


def test_group_type_option_accepts_click_outside_radio_text(editor):
    dialog, _ = editor
    dialog.show()
    option = dialog.radio_file.parentWidget()
    from PySide6.QtCore import QPoint
    QTest.mouseClick(option, Qt.MouseButton.LeftButton, pos=QPoint(option.width() - 10, option.height() - 10))
    assert dialog.radio_file.isChecked()
    assert dialog._dirty


def test_first_group_can_be_reordered(editor):
    dialog, manager = editor
    moves = []
    manager._manager = SimpleNamespace(move_group_between=lambda *args, **kwargs: moves.append((args, kwargs)))
    dialog._handle_group_reorder(0, 2)
    assert moves == [((1,), {"before_id": 2, "after_id": None})]


def test_returning_to_group_keeps_selection_and_editor_in_sync(editor):
    dialog, _ = editor
    dialog.list_widget.setCurrentRow(1)
    dialog._switch_mode("content")
    dialog._switch_mode("group")
    assert dialog.editing_group_id == 2
    assert dialog.list_widget.currentItem().data(Qt.ItemDataRole.UserRole) == ("group", 2)
    assert dialog.group_name_input.text() == "学习"


def test_cancel_button_restores_saved_content_without_writing(editor):
    dialog, manager = editor
    dialog._apply_mode("content")
    dialog.list_widget.setCurrentRow(0)
    assert not dialog.save_btn.isEnabled()
    dialog.content_edit.insertPlainText("draft")
    assert dialog.save_btn.isEnabled()
    assert not dialog.discard_btn.isHidden()
    dialog.discard_btn.click()
    assert dialog.content_edit.toPlainText() == manager.items[1].content
    assert not dialog._dirty
    assert dialog.discard_btn.isHidden()
    assert not dialog.save_btn.isEnabled()
    assert not manager.updated_items


def test_creating_group_keeps_new_record_selected_and_prevents_duplicate_save(editor):
    dialog, manager = editor
    dialog.group_name_input.setText("New workspace")
    dialog.save_btn.click()
    created = manager.created_groups[0]
    assert dialog.editing_group_id == created.id
    assert dialog.group_name_input.text() == created.name
    assert dialog.list_widget.currentItem().data(Qt.ItemDataRole.UserRole) == ("group", created.id)
    assert not dialog.save_btn.isEnabled()
    dialog._on_save_clicked()
    assert len(manager.created_groups) == 1
    dialog._new_entry()
    assert dialog.editing_group_id is None
    assert dialog.group_name_input.text() == ""


def test_creating_content_keeps_text_for_further_editing(editor):
    dialog, manager = editor
    dialog._apply_mode("content")
    dialog.title_input.setText("Saved title")
    dialog.content_edit.setPlainText("Keep this text")
    dialog.save_btn.click()
    assert dialog.editing_item_id == manager.added_items[-1][0]
    assert dialog.content_edit.toPlainText() == "Keep this text"
    assert dialog.title_input.text() == "Saved title"
    assert not dialog.save_btn.isEnabled()
    dialog._on_save_clicked()
    assert len(manager.added_items) == 1
