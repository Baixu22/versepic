import pytest
from PySide6.QtCore import QEvent, QPoint
from PySide6.QtWidgets import QApplication
from clipboard.ui.windows.clipboard_window import ClipboardWindow
from settings.tool_settings import get_tool_settings_manager


@pytest.fixture
def window(qtbot, tmp_path):
    config = get_tool_settings_manager()
    config.set_app_setting("clipboard_db_path", str(tmp_path / "clipboard.db"))
    config.set_clipboard_close_after_paste(False)
    window = ClipboardWindow()
    qtbot.addWidget(window)
    window.show()
    qtbot.wait(300)
    yield window
    window.hide()


def test_search_animation_keeps_header_geometry_and_query(window, qtbot):
    assert window.title_label.isVisible()
    geometry = (window.toolbar.height(), window.close_btn.geometry(), window.list_widget.geometry())
    window._expand_search()
    qtbot.wait(70)
    assert 0 < window._search_progress < 1
    qtbot.wait(180)
    assert not window.title_label.isVisible()
    assert geometry == (window.toolbar.height(), window.close_btn.geometry(), window.list_widget.geometry())
    window.search_input.setText("query")
    window._search_idle_timer.setInterval(30)
    window._search_idle_timer.start()
    qtbot.wait(280)
    assert window.search_input.isHidden()
    assert window.search_input.text() == "query"
    assert window.title_label.isVisible()
    assert "query" in window.title_label.text()
    assert geometry == (window.toolbar.height(), window.close_btn.geometry(), window.list_widget.geometry())
    QApplication.sendEvent(window.search_btn, QEvent(QEvent.Type.Leave))
    QApplication.sendEvent(window.search_btn, QEvent(QEvent.Type.Enter))
    qtbot.wait(200)
    assert window.search_input.isHidden()
    # Restore the normal idle period for the hover expansion.
    window._search_idle_timer.setInterval(5000)
    qtbot.wait(480)
    assert not window.search_input.isHidden()


def test_opacity_survives_move_without_stacked_backgrounds(window, qtbot):
    if QApplication.platformName() == "offscreen":
        pytest.skip("Layered-window alpha requires the native Windows Qt platform")
    for transparency in (0, 50, 90):
        window._set_window_opacity(transparency)
        qtbot.wait(20)
        blank = window.search_host.mapTo(window, QPoint(window.search_host.width() - 10, 10))
        point = (blank.x(), blank.y())
        before = window.grab().toImage().pixelColor(*point).alpha()
        assert abs(before - round(255 * (1 - transparency / 100))) <= 2
        window.move(window.pos().x() + 10, window.pos().y())
        qtbot.wait(30)
        assert window.grab().toImage().pixelColor(*point).alpha() == before


def test_reduced_motion_can_hide_and_reopen_clipboard(window, qtbot):
    app = QApplication.instance()
    previous = app.property("uiReducedMotion")
    try:
        app.setProperty("uiReducedMotion", True)
        window.hide()
        assert not window.isVisible()
        window.show()
        qtbot.wait(220)
        assert window.isVisible()
    finally:
        app.setProperty("uiReducedMotion", previous)
