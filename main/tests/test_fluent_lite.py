"""Regression tests for the project-owned UI compatibility layer."""

import ast
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QStyle, QStyleOptionButton

from ui.fluent_lite import (
    FluentIcon,
    NavigationInterface,
    NavigationItemPosition,
    LineEdit,
    RadioButton,
    SegmentedWidget,
    SettingCard,
    SettingCardGroup,
    SpinBox,
    SwitchSettingCard,
    TextEdit,
)


def test_all_declared_icons_exist():
    missing = [icon.path() for icon in FluentIcon if not Path(icon.path()).is_file()]
    assert missing == []


def test_hidden_tooltips_do_not_filter_unrelated_application_events(qapp, qtbot):
    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QWidget
    from ui.fluent_lite.popups import ToolTip

    probe = QWidget()
    qtbot.addWidget(probe)
    deliveries = []

    class CountingTip(ToolTip):
        def eventFilter(self, obj, event):
            if obj is probe and event.type() == QEvent.Type.User:
                deliveries.append(self)
            return super().eventFilter(obj, event)

    roots = [QWidget() for _ in range(24)]
    for root in roots:
        qtbot.addWidget(root)
        CountingTip.install(root)
    qapp.sendEvent(probe, QEvent(QEvent.Type.User))
    assert deliveries == []
    roots[0].show()
    qapp.sendEvent(probe, QEvent(QEvent.Type.User))
    assert deliveries == [roots[0]._kit_tooltip]
    deliveries.clear()
    roots[0].hide()
    qapp.sendEvent(probe, QEvent(QEvent.Type.User))
    assert deliveries == []


def test_tooltip_reactivates_after_hide_and_is_removed_on_destroy(qapp, qtbot):
    from PySide6.QtCore import QEvent, QPoint, Qt
    from PySide6.QtGui import QHelpEvent
    from PySide6.QtWidgets import QPushButton, QWidget
    from shiboken6 import isValid
    from ui.fluent_lite.popups import ToolTip

    root = QWidget()
    root.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    button = QPushButton("Button", root)
    button.setToolTip("Scoped help")
    tip = ToolTip.install(root)
    for _ in range(2):
        root.show()
        event = QHelpEvent(QEvent.Type.ToolTip, QPoint(1, 1), button.mapToGlobal(QPoint(1, 1)))
        qapp.sendEvent(button, event)
        assert tip.label is not None and tip.label.isVisible()
        assert tip.label.text() == "Scoped help"
        root.hide()
        assert not tip.label.isVisible()
    root.close()
    qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not isValid(tip)
    probe = QWidget()
    qtbot.addWidget(probe)
    qapp.sendEvent(probe, QEvent(QEvent.Type.User))


def test_setting_cards_keep_the_expected_api(qapp):
    card = SettingCard(FluentIcon.INFO, "Title", "Description")
    assert card.titleLabel.text() == "Title"
    assert card.contentLabel.text() == "Description"
    assert card.hBoxLayout is not None

    switch = SwitchSettingCard(FluentIcon.SETTING, "Enabled")
    states = []
    switch.checkedChanged.connect(states.append)
    switch.setChecked(True)
    assert switch.isChecked() is True
    assert states == [True]


def test_setting_card_group_height_tracks_available_text_width(qapp):
    group = SettingCardGroup("Group")
    card = SettingCard(
        FluentIcon.INFO,
        "Title",
        "A translated description that is deliberately long enough to wrap " * 4,
    )
    group.addSettingCard(card)

    narrow_height = group.cardLayout.heightForWidth(260)
    wide_height = group.cardLayout.heightForWidth(600)

    assert wide_height < narrow_height
    assert wide_height >= card.minimumHeight()


def test_navigation_selects_routes_without_firing_actions(qapp):
    nav = NavigationInterface()
    calls = []
    nav.addItem("top", FluentIcon.CAMERA, "Top", lambda: calls.append("top"))
    nav.addItem(
        "bottom", FluentIcon.INFO, "Bottom", lambda: calls.append("bottom"),
        position=NavigationItemPosition.BOTTOM,
    )
    nav.setCurrentItem("bottom")
    assert nav.widget("bottom").isChecked()
    assert nav.widget("top").toolTip() == ""
    assert calls == []
    nav.clearCurrentItem()
    assert not nav.widget("bottom").isChecked()


def test_segmented_widget_tracks_current_route(qapp):
    segmented = SegmentedWidget()
    segmented.addItem("one", "One")
    segmented.addItem("two", "Two")
    segmented.setCurrentItem("two")
    assert segmented.currentItem() == "two"


def test_radio_button_label_does_not_overlap_indicator(qapp):
    radio = RadioButton("常规组")
    radio.resize(radio.sizeHint())
    option = QStyleOptionButton()
    radio.initStyleOption(option)
    indicator = radio.style().subElementRect(
        QStyle.SubElement.SE_RadioButtonIndicator, option, radio
    )

    label_rect = radio._label_rect(indicator)
    assert label_rect.left() > indicator.right()

    _center, outer = radio._indicator_ellipse(indicator)
    # Half of the one-pixel pen extends beyond the ellipse path.
    assert outer.left() - 0.5 >= indicator.left()
    assert outer.top() - 0.5 >= indicator.top()
    assert outer.right() + 0.5 <= indicator.right() + 1
    assert outer.bottom() + 0.5 <= indicator.bottom() + 1


def test_shared_text_inputs_install_themed_context_menus(qapp):
    line_edit = LineEdit()
    text_edit = TextEdit()
    spin_box = SpinBox()

    for editor in (line_edit, text_edit):
        menu = editor.createThemedContextMenu()
        assert menu.autoFillBackground() is True
        assert "QMenu::item:disabled" in menu.styleSheet()
        menu.deleteLater()

    assert (
        spin_box.lineEdit().contextMenuPolicy()
        == Qt.ContextMenuPolicy.CustomContextMenu
    )


def test_line_edit_can_keep_a_caller_owned_body_style(qapp):
    line_edit = LineEdit(use_default_style=False)
    custom_style = "QLineEdit { background: #123456; }"
    line_edit.setStyleSheet(custom_style)

    assert line_edit.styleSheet() == custom_style
    menu = line_edit.createThemedContextMenu()
    assert "background-color:" in menu.styleSheet()
    menu.deleteLater()


def test_frontend_uses_shared_text_editor_controls():
    """Prevent new raw Qt editors from bypassing the shared context menu."""
    source_root = Path(__file__).parents[1]
    raw_editor_names = {"QLineEdit", "QTextEdit", "QPlainTextEdit"}
    offenders = []

    for path in source_root.rglob("*.py"):
        if path.parts[-2] == "tests":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in raw_editor_names
            ):
                offenders.append(f"{path.relative_to(source_root)}:{node.lineno}")

    assert offenders == []
def test_frosted_frameless_dialog_survives_bad_window_handle_wrapper(qapp, monkeypatch):
    """第三方 frameless 的 screenChanged 连接拿到错误包装类型时，构造不应被中断。

    对应偏差 TFD-6e1327a941：全量跑里 windowHandle() 偶发返回 QWidgetItem 而非 QWindow。
    """
    import pytest
    from qframelesswindow import FramelessDialog

    from ui.fluent_lite.frameless import FrostedFramelessDialog

    calls = {"broken": 0}

    class _StubButton:
        def hide(self):
            pass

    class _StubTitleBar:
        def __init__(self):
            self.minBtn = _StubButton()
            self.maxBtn = _StubButton()

        def raise_(self):
            pass

        def setDoubleClickEnabled(self, _enabled):
            pass

    class _StubWindowEffect:
        def disableMaximizeButton(self, *_args):
            pass

    def broken_init(self):
        # 复现第三方库失败时的真实partial状态：titleBar/windowEffect 已建，连接 screenChanged 时炸
        self.titleBar = _StubTitleBar()
        self.windowEffect = _StubWindowEffect()
        calls["broken"] += 1
        raise AttributeError("'PySide6.QtWidgets.QWidgetItem' object has no attribute 'screenChanged'")

    monkeypatch.setattr(FramelessDialog, "_initFrameless", broken_init, raising=True)
    dialog = FrostedFramelessDialog()
    try:
        assert calls["broken"] == 1
        assert dialog.titleBar is not None, "被跳过的收尾步骤要补上"
        assert (dialog.width(), dialog.height()) == (500, 500)
    finally:
        dialog.deleteLater()

    def other_error(self):
        raise AttributeError("unrelated failure")

    monkeypatch.setattr(FramelessDialog, "_initFrameless", other_error, raising=True)
    with pytest.raises(AttributeError):
        FrostedFramelessDialog()
