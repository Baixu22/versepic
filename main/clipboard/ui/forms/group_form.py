"""Group settings: identity first, then explicit clipboard behaviour."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QVBoxLayout, QWidget
from ui.fluent_lite.theme import CONTROL_RADIUS, ui_tokens

from ui.fluent_lite import BodyLabel, CaptionLabel, LineEdit, RadioButton
from ..layout_scale import field_group_gap, scale_ui
from .group_icon_picker import create_group_icon_picker
from ...services.group_service import get_group_display_icon


class GroupTypeOption(QWidget):
    def __init__(self, radio):
        super().__init__()
        self.radio = radio
        self.setObjectName("GroupTypeOption")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        radio.toggled.connect(self._apply_theme)

    def _apply_theme(self, *_):
        tokens = ui_tokens(self)
        selected = self.radio.isChecked()
        border = tokens.border
        background = tokens.surface_subtle if selected else "transparent"
        self.setStyleSheet(
            f"QWidget#GroupTypeOption {{ background: {background}; border: 1px solid {border}; "
            f"border-radius: {scale_ui(CONTROL_RADIUS)}px; }}"
            f"QWidget#GroupTypeOption:hover {{ background: {tokens.surface_subtle}; }}"
        )

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.radio.setFocus(Qt.FocusReason.MouseFocusReason)
            self.radio.click()
            event.accept()
        else:
            super().mouseReleaseEvent(event)


def build_new_group_form(dialog):
    _build_form(dialog)


def build_edit_group_form(dialog, group):
    _build_form(dialog, group)


def _build_form(dialog, group=None):
    name_label = BodyLabel(dialog.tr("Group Name"))
    dialog.detail_layout.addWidget(name_label)
    row = QHBoxLayout()
    row.setSpacing(scale_ui(8))
    dialog.group_name_input = LineEdit()
    dialog.group_name_input.setAccessibleName(dialog.tr("Group Name"))
    dialog.group_name_input.setPlaceholderText(dialog.tr("Enter group name..."))
    if group:
        dialog.group_name_input.setText(group.name)
    name_label.setBuddy(dialog.group_name_input)
    icon = get_group_display_icon(group.icon, group.group_type == 1, is_hidden=group.group_type == 2) if group else "📁"
    button = create_group_icon_picker(dialog, icon)
    row.addWidget(dialog.icon_input)
    row.addWidget(button)
    row.addWidget(dialog.group_name_input, 1)
    dialog.detail_layout.addLayout(row)
    _build_group_type_section(dialog, bool(group and group.group_type == 1), bool(group and group.group_type == 2))


def _build_group_type_section(dialog, is_file_group, is_hidden=False):
    dialog.detail_layout.addSpacing(field_group_gap())
    dialog.detail_layout.addWidget(BodyLabel(dialog.tr("Group Type")))
    dialog._group_type_btn_group = QButtonGroup(dialog.detail_content)
    dialog.radio_normal = RadioButton(dialog.tr("General Group"))
    dialog.radio_file = RadioButton(dialog.tr("Quick Launch Group"))
    dialog.radio_hidden = RadioButton(dialog.tr("Hidden Group"))
    descriptions = (
        "General groups allow any content; selecting an item pastes content or files to the target",
        "Quick launch groups only allow file or folder paths; selecting an item opens them",
        "Hidden groups are not displayed on the clipboard panel; changing to normal group restores visibility",
    )
    token = dialog._detail_form_token
    for index, (radio, description) in enumerate(zip((dialog.radio_normal, dialog.radio_file, dialog.radio_hidden), descriptions)):
        option = GroupTypeOption(radio)
        layout = QVBoxLayout(option)
        layout.setContentsMargins(scale_ui(12), scale_ui(10), scale_ui(12), scale_ui(10))
        layout.setSpacing(scale_ui(3))
        layout.addWidget(radio)
        caption = CaptionLabel(dialog.tr(description))
        caption.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        caption.setWordWrap(True)
        caption.setContentsMargins(scale_ui(26), 0, 0, 0)
        layout.addWidget(caption)
        dialog._group_type_btn_group.addButton(radio, index)
        radio.toggled.connect(lambda checked, t=token: dialog._on_group_type_toggled(checked, t))
        dialog.detail_layout.addWidget(option)
    (dialog.radio_hidden if is_hidden else dialog.radio_file if is_file_group else dialog.radio_normal).setChecked(True)
