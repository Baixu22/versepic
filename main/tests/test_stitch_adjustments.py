"""Real engine replay, bounded checkpoints and native dialog controls for long screenshots."""
from io import BytesIO
from unittest.mock import Mock

from PIL import Image, ImageDraw
import pytest
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtWidgets import QDialog

from stitch.session import StitchSession, StitchLimitError, orient
from stitch.adjustment_dialog import StitchAdjustmentDialog
from tests.test_stitch_integration import _strip


def frames(axis="vertical", reverse=False):
    images = [_strip(i, 80) for i in (0, 30, 60)]
    if reverse:
        images.reverse()
    return [image.transpose(Image.Transpose.ROTATE_90) for image in images] if axis == "horizontal" else images


@pytest.mark.parametrize("axis", ["vertical", "horizontal"])
@pytest.mark.parametrize("reverse", [False, True])
def test_real_stitch_then_undo_and_recapture_matches_every_pixel(axis, reverse):
    session = StitchSession(axis)
    a, b, c = frames(axis, reverse)
    assert session.add(a) == "added"
    initial = session.state
    assert session.add(b, 120) == "added"
    second = session.state
    assert session.state.direction == ("up" if reverse else "down")
    assert session.add(c, 120) == "added"
    expected = _strip(0, 140)
    if axis == "horizontal":
        expected = expected.transpose(Image.Transpose.ROTATE_90)
    assert session.state.result.tobytes() == expected.tobytes()
    assert session.state.result.size == expected.size
    assert session.undo() and session.state is second
    assert session.undo() and session.state is initial
    assert not session.undo()
    assert session.add(b, 120) == "added"
    assert session.state.result.tobytes() == second.result.tobytes()
    assert session.state.distances == (0, 120)


@pytest.mark.parametrize("axis", ["vertical", "horizontal"])
@pytest.mark.parametrize("reverse", [False, True])
def test_manual_seam_correction_is_reversible_and_continues_with_real_engine(axis, reverse):
    session = StitchSession(axis)
    a, b, c = frames(axis, reverse)
    session.add(a)
    session.add(b)
    correct = session.state.result.copy()
    correct_overlap = session.state.overlap
    session.repair(correct_overlap - 8, session.state.direction)
    assert session.state.result.size != correct.size
    session.repair(correct_overlap, session.state.direction)
    assert session.state.result.tobytes() == correct.tobytes()
    assert session.state.count == 2 and len(session.checkpoints) == 1
    session.add(c)
    assert session.state.count == 3
    assert session.undo()
    assert session.state.result.tobytes() == correct.tobytes()


def test_failure_keeps_committed_state_and_can_be_manually_repaired(monkeypatch):
    session = StitchSession()
    a, b, _ = frames()
    session.add(a)
    original = session.state
    monkeypatch.setattr("stitch.session.detect_shift", lambda *args: None)
    assert session.add(b, 120) == "unmatched"
    assert session.state is original and session.seam()[-1] is True
    session.repair(200, "down")
    assert session.state.count == 2 and session.state.result.size == (120, 440)
    assert session.undo() and session.state is original


def test_engine_exception_does_not_change_committed_output(monkeypatch):
    session = StitchSession()
    a, b, _ = frames()
    session.add(a)
    original = session.state
    monkeypatch.setattr("stitch.session.detect_shift", Mock(side_effect=RuntimeError("engine failure")))
    with pytest.raises(RuntimeError):
        session.add(b)
    assert session.state is original
    assert session.pending is not None and session.retained_bytes <= session.budget


def test_checkpoints_have_count_and_byte_bounds_and_clear_releases_all():
    session = StitchSession(max_checkpoints=3, retained_bytes=200_000)
    for index in range(8):
        session.add(_strip(index*10, 80))
        assert len(session.checkpoints) <= 3
        assert session.retained_bytes <= session.budget
    assert session.state.count == 8
    session.clear()
    assert not session.checkpoints and session.pending is None
    assert session.state.result is None and session.retained_bytes == 0


def test_oversized_candidate_cannot_be_retained_outside_budget(monkeypatch):
    session = StitchSession(retained_bytes=100)
    session.add(_strip(0, 80))
    monkeypatch.setattr("stitch.session.detect_shift", lambda *args: None)
    assert session.add(_strip(30, 80)) == "unmatched"
    assert session.pending is None and session.retained_bytes == 0
    assert session.state.count == 1


def test_output_limit_and_bad_overlap_leave_original_state():
    session = StitchSession(max_pixels=120*400)
    session.add(_strip(0, 80))
    original = session.state
    with pytest.raises(StitchLimitError):
        session.add(_strip(30, 80))
    assert session.state is original
    with pytest.raises(ValueError):
        session.repair(320, "down")
    assert session.state is original


def test_direction_change_only_before_committed_seams_and_never_corrupts_result():
    session = StitchSession()
    a, b, _ = frames()
    session.add(a)
    session.set_axis("horizontal")
    assert session.state.result.size == a.size
    session.set_axis("vertical")
    session.add(b)
    before = session.state
    with pytest.raises(ValueError):
        session.set_axis("horizontal")
    assert session.state is before and session.axis == "vertical"
    session.undo()
    session.set_axis("horizontal")
    assert session.axis == "horizontal"


def test_duplicate_is_exact_pixels_not_same_ahash():
    session = StitchSession()
    a = _strip(0,80)
    session.add(a)
    assert session.add(a.copy()) == "duplicate"
    assert session.state.count == 1
    b = a.copy()
    b.putpixel((0,0), (0,0,0))
    assert session.add(b) != "duplicate"


@pytest.mark.parametrize("axis", ["vertical", "horizontal"])
@pytest.mark.parametrize("reverse", [False, True])
def test_ignore_crop_is_applied_in_original_screen_coordinates(axis, reverse, monkeypatch):
    import longstitch
    images = frames(axis, reverse)
    captured = []
    real = longstitch.stitch
    def inspect(a, b, **kwargs):
        with Image.open(BytesIO(a)) as first, Image.open(BytesIO(b)) as second:
            captured.append((first.copy(), second.copy(), kwargs))
        return real(a,b,**kwargs)
    monkeypatch.setattr(longstitch, "stitch", inspect)
    session = StitchSession(axis)
    session.set_ignore(12,7)
    session.add(images[0])
    session.add(images[1])
    expected = orient(images[0].crop((0,12,images[0].width-7,images[0].height)), axis)
    assert captured[0][0].size == expected.size
    assert captured[0][0].tobytes() == expected.tobytes()
    assert captured[0][2]["ignore_top_pixels"] == 0
    assert captured[0][2]["ignore_right_pixels"] == 0
    assert session.state.count == 2
    assert session.state.result.width == (images[0].width if axis == "vertical" else 440)


def test_fixed_header_and_scrollbar_excluded_but_not_removed_from_output():
    a, b, _ = frames()
    for i, frame in enumerate((a,b)):
        painter = ImageDraw.Draw(frame)
        painter.rectangle((0,0,119,11), fill=(240,50+i*60,40))
        painter.rectangle((113,0,119,319), fill=(10,150+i*50,20))
    session = StitchSession()
    session.set_ignore(12,7)
    session.add(a)
    session.add(b)
    assert session.state.result.size == (120,440)
    assert session.state.result.crop((0,0,120,320)).tobytes() == a.tobytes()
    assert session.state.result.crop((0,320,120,440)).tobytes() == b.crop((0,200,120,320)).tobytes()


@pytest.fixture
def session():
    result = StitchSession()
    result.add(_strip(0,80))
    result.add(_strip(30,80))
    return result


def test_seam_dialog_cancel_does_not_mutate_session(session, qtbot):
    before = session.state
    dialog = StitchAdjustmentDialog(session)
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.overlap.setValue(150)
    dialog.reject()
    assert session.state is before
    assert dialog.preview.pixmap() is not None


def test_ignore_dialog_clicks_and_reset_change_only_draft_values(session, qtbot):
    dialog = StitchAdjustmentDialog(session, ignore=True)
    qtbot.addWidget(dialog)
    dialog.show()
    rect = dialog.preview.image_rect()
    point = QPoint(round(rect.center().x()), round(rect.top()+rect.height()/4))
    qtbot.mouseClick(dialog.preview, Qt.MouseButton.LeftButton, pos=point)
    assert abs(dialog.top.value()-80) <= 1
    assert session.ignore_top == 0
    dialog.pick_axis.setCurrentIndex(1)
    point = QPoint(round(rect.right()-rect.width()/4), round(rect.center().y()))
    qtbot.mouseClick(dialog.preview, Qt.MouseButton.LeftButton, pos=point)
    assert abs(dialog.right.value()-30) <= 1
    dialog._reset()
    assert dialog.top.value() == dialog.right.value() == 0


@pytest.fixture
def window(qtbot, tmp_settings, monkeypatch):
    from stitch.scroll_window import ScrollCaptureWindow
    from settings.tool_settings import ToolSettingsManager
    config = ToolSettingsManager(tmp_settings)
    config.set_long_stitch_ignore_top_pixels(0)
    config.set_app_setting("long_stitch_ignore_right_pixels", 0)
    monkeypatch.setattr(ScrollCaptureWindow, "_setup_mouse_hook", lambda self: None)
    monkeypatch.setattr(ScrollCaptureWindow, "_start_keyboard_listener", lambda self: None)
    monkeypatch.setattr(ScrollCaptureWindow, "_force_fix_window_position", lambda self: None)
    result = ScrollCaptureWindow(QRect(0,0,120,320), config_manager=config)
    qtbot.addWidget(result)
    result._position_fix_timer.stop()
    yield result
    result._cleanup()


def test_window_undo_restores_counts_direction_and_last_frame(window):
    a,b,c = frames()
    window._append_frame(a)
    window.current_scroll_distance = 120
    window._append_frame(b)
    window.current_scroll_distance = 120
    window._append_frame(c)
    window._undo_stitch()
    assert len(window.screenshots) == 2
    assert window.scroll_distances == [0,120]
    assert window.scroll_locked_direction == "down"
    assert window._last_screenshot.tobytes() == b.tobytes()
    window._undo_stitch()
    assert len(window.screenshots) == 1 and window.scroll_locked_direction is None
    assert window.stitched_result.tobytes() == a.tobytes()


def test_window_accepts_manual_repair_pauses_capture_and_keeps_counts(window, monkeypatch):
    a,b,_ = frames()
    window._append_frame(a)
    window._append_frame(b)
    before = window.stitched_result.copy()
    def edit(dialog):
        assert window._adjustment_dialog is dialog
        window._handle_scroll_in_main_thread(30)
        assert not window.capture_timer.isActive()
        dialog.overlap.setValue(190)
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(StitchAdjustmentDialog, "exec", edit)
    window.toolbar.repair_btn.click()
    assert len(window.screenshots) == 2
    assert window.stitched_result.height == before.height+10
    assert window._adjustment_dialog is None
    window._undo_stitch()
    assert len(window.screenshots) == 1


def test_window_ignore_accept_persists_and_does_not_crop_existing_result(window, monkeypatch):
    window._append_frame(_strip(0,80))
    original = window.stitched_result
    def edit(dialog):
        dialog.top.setValue(12)
        dialog.right.setValue(7)
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(StitchAdjustmentDialog, "exec", edit)
    window.toolbar.ignore_btn.click()
    assert window._stitch_session.ignore_top == 12 and window._stitch_session.ignore_right == 7
    assert window.config_manager.get_long_stitch_ignore_top_pixels() == 12
    assert window.stitched_result is original


def test_cleanup_closes_adjustment_and_drops_checkpoints(window):
    from PySide6.QtCore import QTimer
    window._append_frame(_strip(0,80))
    window._append_frame(_strip(30,80))
    QTimer.singleShot(0, window._cleanup)
    window._repair_stitch()
    assert window._stitch_session.state.result is None
    assert window._stitch_session.retained_bytes == 0
    assert window._adjustment_dialog is None


STITCH_MESSAGES = {
  "StitchAdjustmentDialog": [
    "Matching exclusions",
    "Adjust latest seam",
    "Highlighted pixels are excluded from matching only, not removed from the output. Coordinates follow the original screen, even for horizontal or reverse capture.",
    "Review the two latest frames. Overlap counts pixels already present; adjust it to remove duplicate rows or restore missing content. Capturing is paused while this window is open.",
    "Click to set header height",
    "Click to set scrollbar width",
    "Top exclusion (px)",
    "Right exclusion (px)",
    "Preview action",
    "Append below / right",
    "Prepend above / left",
    "Overlap (px)",
    "New frame direction",
    "No exclusions",
    "Cancel",
    "Apply",
    "These settings affect future matching; the existing stitched image stays unchanged.",
    "New content: %1 px. Red line marks the join; only this preview includes it."
  ],
  "FloatingToolbar": [
    "Undo last stitch",
    "Adjust latest seam",
    "Ignore fixed header / scrollbar"
  ],
  "ScrollCaptureWindow": [
    "Undo last stitch (%1 retained; up to 3 checkpoints / 96 MiB)",
    "No reliable overlap. Scroll less and retry, or adjust the latest seam.",
    "The frame is unchanged. Scroll to new content before capturing again.",
    "Could not stitch this frame. Existing content was kept; reduce the region or repair the seam.",
    "Last stitch undone. Return the page to this preview before continuing.",
    "Undo all seams or start a new capture before switching direction.",
    "Matching exclusions updated. Existing output pixels were not cropped.",
    "Seam updated. Check the preview before continuing.",
    "Adjustment failed. Existing content was kept."
  ]
}

@pytest.mark.parametrize("lang", ["en", "zh", "ja", "ko"])
def test_compiled_stitch_messages(qapp, lang):
    from pathlib import Path
    from PySide6.QtCore import QTranslator
    translator = QTranslator()
    assert translator.load(str(Path(__file__).resolve().parents[1] / "translations" / f"app_{lang}.qm"))
    for context, messages in STITCH_MESSAGES.items():
        for source in messages:
            assert translator.translate(context, source), (lang, context, source)


def test_repair_keeps_later_direction_constraint_and_committed_state_on_error():
    session = StitchSession()
    for frame in frames():
        session.add(frame)
    before = session.state
    with pytest.raises(ValueError):
        session.repair(120, "up")
    assert session.state is before


def test_latest_undo_is_available_until_budget_cannot_retain_it():
    session = StitchSession(max_checkpoints=3, retained_bytes=3_000_000)
    for i in range(7):
        session.add(_strip(i*10,80))
    assert len(session.checkpoints) == 3
    assert [state.count for state in session.checkpoints] == [4,5,6]
    for count in (6,5,4):
        assert session.undo() and session.state.count == count
    assert not session.undo()


def test_seam_failure_after_undo_does_not_reuse_abandoned_frame(monkeypatch):
    session = StitchSession()
    a,b,c = frames()
    session.add(a)
    session.add(b)
    session.undo()
    monkeypatch.setattr("stitch.session.detect_shift", lambda *a: None)
    assert session.add(c) == "unmatched"
    assert session.seam()[0].count == 1 and session.seam()[1].tobytes() == c.tobytes()
    session.add(a)
    assert session.pending is None


def test_window_direction_switch_after_undo_preserves_first_frame(window):
    a,b,_ = frames()
    window._append_frame(a)
    window._append_frame(b)
    window._toggle_direction()
    assert window.scroll_direction == "vertical"
    window._undo_stitch()
    window._toggle_direction()
    assert window.scroll_direction == "horizontal"
    assert window._stitch_session.axis == "horizontal"
    assert window.stitched_result.tobytes() == a.tobytes()


def test_window_failed_frame_does_not_change_success_count_or_distance(window, monkeypatch):
    window._append_frame(_strip(0,80))
    monkeypatch.setattr("stitch.session.detect_shift", lambda *a: None)
    before = window.stitched_result
    window.current_scroll_distance = 500
    assert window._append_frame(_strip(100,80)) == "unmatched"
    assert len(window.screenshots) == 1 and window.scroll_distances == [0]
    assert window.stitched_result is before
    assert window.toolbar.repair_btn.isEnabled()
    assert window.current_scroll_distance == 0


def test_session_rejects_changed_frame_dimensions_before_mutating_state():
    session = StitchSession()
    session.add(_strip(0,80))
    before = session.state
    with pytest.raises(ValueError):
        session.add(Image.new("RGB", (121,320)))
    assert session.state is before and session.pending is None


def test_importing_scroll_window_has_no_settings_singleton_side_effect(tmp_path):
    import subprocess
    import sys
    from pathlib import Path
    source = Path(__file__).resolve().parents[1]
    code = "import sys; sys.path.insert(0, sys.argv[1]); from settings import tool_settings; assert tool_settings._tool_settings_manager is None; import stitch.scroll_window; assert tool_settings._tool_settings_manager is None"
    result = subprocess.run([sys.executable, "-B", "-c", code, str(source)], capture_output=True, text=True,
                            timeout=15, creationflags=subprocess.CREATE_NO_WINDOW)
    assert result.returncode == 0, result.stderr
