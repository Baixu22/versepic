"""Automatic scrolling is explicitly bounded and never sends global wheel events."""
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PIL import Image
from PySide6.QtCore import QObject, QRect
import win32con

from stitch.auto_scroll import AutoScrollController, AutoScrollOptions, ScrollTarget, WM_MOUSEHWHEEL


@pytest.fixture
def controller(qapp, monkeypatch):
    clock=[100.0]
    monkeypatch.setattr("stitch.auto_scroll.time.monotonic",lambda:clock[0])
    window=QObject()
    window.capture_rect=QRect(0,0,200,200)
    window.scroll_direction="vertical"
    window.scroll_cooldown=0.15
    window._closing=False
    window._adjustment_dialog=None
    window.capture_timer=Mock()
    window.scroll_check_timer=Mock()
    window._stop_keyboard_listener=Mock()
    window._stitch_session=SimpleNamespace(state=SimpleNamespace(result=Image.new("RGB",(200,200)),direction=None))
    window._do_capture=Mock(return_value="added")
    controller=AutoScrollController(window)
    monkeypatch.setattr(controller,"_start_cancel_listener",lambda:None)
    target=Mock()
    monkeypatch.setattr("stitch.auto_scroll.ScrollTarget.bind",lambda _:target)
    yield controller,window,target,clock
    controller.stop()
    window.deleteLater()


def arm(controller, clock, **kwargs):
    assert controller.start(AutoScrollOptions(**kwargs))
    clock[0]+=3
    controller._tick()


@pytest.mark.parametrize("change",[{"wheel_steps":0},{"interval_ms":0},{"max_steps":201},{"timeout_seconds":181},
                                    {"max_length":1},{"direction":"sideways"},{"max_steps":True}])
def test_invalid_limits_are_rejected_without_starting(controller, change):
    control,window,target,clock=controller
    with pytest.raises(ValueError):
        control.start(replace(AutoScrollOptions(),**change))
    assert not control.active and not target.scroll.called


def test_arming_sends_nothing_until_deadline_and_freezes_limits(controller):
    control,window,target,clock=controller
    control.start(AutoScrollOptions(interval_ms=600))
    clock[0]+=2.9
    control._tick()
    assert not target.scroll.called and not window._do_capture.called
    assert not control.start(AutoScrollOptions(max_steps=1))
    clock[0]+=0.1
    control._tick()
    assert target.scroll.call_count==1
    assert window._do_capture.call_count==1  # baseline recheck precedes first input
    assert control.phase=="capture"
    clock[0]+=0.5
    control._tick()
    assert target.scroll.call_count==1
    clock[0]+=0.11
    control._tick()
    assert target.scroll.call_count==2 and window._do_capture.call_count==2


def test_step_limit_includes_final_capture_but_never_sends_extra_input(controller):
    control,window,target,clock=controller
    arm(control,clock,max_steps=2)
    clock[0]+=1
    control._tick()
    clock[0]+=1
    control._tick()
    assert not control.active
    assert target.scroll.call_count==2
    assert window._do_capture.call_count==3


@pytest.mark.parametrize("reason",["duplicate","unmatched","failed",None])
def test_unchanged_or_failed_frame_stops_and_keeps_result(controller,reason):
    control,window,target,clock=controller
    arm(control,clock)
    result=window._stitch_session.state.result
    window._do_capture.return_value=reason
    clock[0]+=1
    control._tick()
    assert not control.active and target.scroll.call_count==1
    assert window._stitch_session.state.result is result


def test_timeout_stops_before_any_more_messages(controller):
    control,window,target,clock=controller
    arm(control,clock,timeout_seconds=5)
    clock[0]+=6
    control._tick()
    assert not control.active and target.scroll.call_count==1


def test_existing_length_limit_stops_before_first_wheel(controller):
    control,window,target,clock=controller
    window._stitch_session.state.result=Image.new("RGB",(200,1000))
    arm(control,clock,max_length=1000)
    assert not control.active and not target.scroll.called


def test_cancel_between_messages_and_during_capture_prevents_further_scroll(controller):
    control,window,target,clock=controller
    arm(control,clock)
    window._do_capture.side_effect=lambda:(control._cancel.set(),"added")[1]
    clock[0]+=1
    control._tick()
    assert not control.active and target.scroll.call_count==1
    control._tick()
    assert target.scroll.call_count==1


def test_previous_listener_cancel_token_cannot_cancel_new_run(controller):
    control,window,target,clock=controller
    control.start(AutoScrollOptions())
    old=control._cancel
    control.stop()
    control.start(AutoScrollOptions())
    old.set()
    assert not control._cancel.is_set()
    control.stop()


def test_target_invalidated_during_wait_stops_without_grabbing_other_app(controller):
    control,window,target,clock=controller
    arm(control,clock)
    target.validate.side_effect=ValueError("focus changed")
    clock[0]+=0.1
    control._tick()
    assert not control.active and window._do_capture.call_count==1 and target.scroll.call_count==1


def test_closed_window_or_adjustment_stops_auto_loop(controller):
    control,window,target,clock=controller
    arm(control,clock)
    window._adjustment_dialog=object()
    control._tick()
    assert not control.active and not control._timer.isActive()


def test_input_failure_never_falls_back_to_global_wheel(controller):
    control,window,target,clock=controller
    target.scroll.side_effect=PermissionError("access denied")
    arm(control,clock)
    assert not control.active and target.scroll.call_count==1


def test_missing_cancel_listener_fails_closed(controller):
    control,window,target,clock=controller
    arm(control,clock)
    listener=Mock(is_alive=Mock(return_value=False))
    control._listener=listener
    control._tick()
    assert not control.active
    listener.stop.assert_called_once()
    listener.join.assert_called_once()


@pytest.fixture
def target_api(monkeypatch):
    import stitch.auto_scroll as mod
    monkeypatch.setattr(mod.os,"getpid",lambda:123)
    monkeypatch.setattr(mod.win32api,"GetCursorPos",lambda:(50,50))
    monkeypatch.setattr(mod.win32gui,"WindowFromPoint",lambda _:10)
    monkeypatch.setattr(mod.win32gui,"GetAncestor",lambda hwnd,flags:20)
    monkeypatch.setattr(mod.win32gui,"GetForegroundWindow",lambda:20)
    monkeypatch.setattr(mod.win32process,"GetWindowThreadProcessId",lambda hwnd:(1,456))
    monkeypatch.setattr(mod.win32gui,"IsWindow",lambda _:True)
    monkeypatch.setattr(mod.win32gui,"IsWindowVisible",lambda _:True)
    monkeypatch.setattr(mod.win32gui,"IsIconic",lambda _:False)
    monkeypatch.setattr(mod,"get_window_rect_no_shadow",lambda _: (0,0,500,400))
    send=Mock()
    monkeypatch.setattr(mod.win32gui,"SendMessageTimeout",send)
    return mod,send


@pytest.mark.parametrize("axis,direction,delta",[("vertical","down",-240),("vertical","up",240),
                                                ("horizontal","down",240),("horizontal","up",-240)])
def test_targeted_message_contains_correct_child_handle_direction_and_coordinates(target_api,axis,direction,delta):
    mod,send=target_api
    target=ScrollTarget.bind(QRect(0,0,200,200))
    target.scroll(QRect(0,0,200,200),axis,direction,2)
    args=send.call_args.args
    assert args[0]==10
    assert args[1]==(win32con.WM_MOUSEWHEEL if axis=="vertical" else WM_MOUSEHWHEEL)
    assert args[2]==((delta & 0xffff)<<16)
    assert args[3]==(50|(50<<16))
    assert args[-1]==100


@pytest.mark.parametrize("condition",["closed","hidden","minimized","moved","pid","focus","obscured","own","range"])
def test_changed_target_never_receives_another_message(target_api,monkeypatch,condition):
    mod,send=target_api
    target=ScrollTarget.bind(QRect(0,0,200,200))
    if condition=="closed":monkeypatch.setattr(mod.win32gui,"IsWindow",lambda _:False)
    elif condition=="hidden":monkeypatch.setattr(mod.win32gui,"IsWindowVisible",lambda _:False)
    elif condition=="minimized":monkeypatch.setattr(mod.win32gui,"IsIconic",lambda _:True)
    elif condition=="moved":monkeypatch.setattr(mod,"get_window_rect_no_shadow",lambda _: (1,0,501,400))
    elif condition=="pid":monkeypatch.setattr(mod.win32process,"GetWindowThreadProcessId",lambda _:(1,999))
    elif condition=="focus":monkeypatch.setattr(mod.win32gui,"GetAncestor",lambda hwnd,flags:30 if hwnd==20 else 20)
    elif condition=="obscured":monkeypatch.setattr(mod.win32gui,"WindowFromPoint",lambda _:11)
    elif condition=="own":target=replace(target,pid=123)
    else:target=replace(target,point=(40000,0))
    with pytest.raises(ValueError):
        target.scroll(QRect(0,0,200,200),"vertical","down",1)
    send.assert_not_called()


def test_target_binding_requires_pointer_and_full_region_inside_target(target_api):
    with pytest.raises(ValueError):ScrollTarget.bind(QRect(200,200,50,50))
    with pytest.raises(ValueError):ScrollTarget.bind(QRect(0,0,600,400))


def test_options_dialog_is_opt_in_and_keeps_valid_boundaries(qtbot):
    from stitch.auto_scroll_dialog import AutoScrollDialog
    dialog=AutoScrollDialog("up")
    qtbot.addWidget(dialog)
    assert dialog.options().direction=="up" and not dialog.direction.isEnabled()
    dialog.options().validate()
    for key,widget in dialog.inputs.items():
        widget.setValue(widget.minimum())
    dialog.options().validate()
    dialog.reject()
    assert dialog.result()==0


def test_scroll_length_budget_is_checked_before_committing_candidate():
    from stitch.session import StitchSession, StitchLimitError
    from tests.test_stitch_integration import _strip
    session=StitchSession()
    session.add(_strip(0,80))
    before=session.state
    with pytest.raises(StitchLimitError):
        session.add(_strip(30,80), max_length=400)
    assert session.state is before
    assert before.result.height==320


def test_capture_ui_is_excluded_even_when_only_its_shadow_overlaps(monkeypatch):
    from stitch.scroll_window import ScrollCaptureWindow
    calls=[]
    window=SimpleNamespace(isVisible=lambda:True,winId=lambda:1)
    window.toolbar=SimpleNamespace(isVisible=lambda:True,winId=lambda:2)
    window.preview_panel=SimpleNamespace(isVisible=lambda:True,winId=lambda:3)
    monkeypatch.setattr("core.platform_utils.set_window_exclude_from_capture",lambda hwnd,exclude:calls.append((hwnd,exclude)))
    ScrollCaptureWindow._exclude_overlapping_ui(window,True)
    assert calls==[(1,True),(2,True),(3,True)]


AUTO_MESSAGES = {
  "AutoScrollDialog": [
    "Automatic scrolling",
    "After Start, activate the intended app and put the pointer inside the selected capture area within 3 seconds. Scrolling is addressed only to that window. Keep it visible and focused. Esc stops; some applications may not support this input.",
    "Down / right",
    "Up / left",
    "Direction",
    "Cancel",
    "Start in 3 seconds",
    "Wheel notches per step",
    "Wait after each scroll (ms)",
    "Maximum scroll steps",
    "Maximum duration (seconds)",
    "Maximum image length (px)"
  ],
  "ScrollCaptureWindow": [
    "Automatic scrolling could not start: the cancel key is unavailable.",
    "Activate the target and put the pointer inside the capture region within 3 seconds. Esc stops.",
    "Automatic scrolling stopped because the cancel key became unavailable.",
    "Automatic scrolling stopped: the starting frame did not match the preview.",
    "Automatic scrolling reached the time limit.",
    "Automatic scrolling stopped: the frame did not change (end of page or unsupported target).",
    "Automatic scrolling stopped: overlap failed. Review or repair the last seam.",
    "Automatic scrolling is running. Esc or Stop ends it without discarding images.",
    "Automatic scrolling stopped: target focus, position, or input access changed.",
    "Automatic scrolling stopped. Existing content was kept.",
    "Stop",
    "Auto scroll",
    "Automatic scrolling could not start: check the current direction and starting frame.",
    "Automatic scrolling reached the frame limit.",
    "Automatic scrolling reached the image length limit."
  ],
  "FloatingToolbar": [
    "Auto scroll"
  ]
}

@pytest.mark.parametrize("lang", ["en", "zh", "ja", "ko"])
def test_compiled_auto_scroll_messages(qapp,lang):
    from pathlib import Path
    from PySide6.QtCore import QTranslator
    tr=QTranslator()
    assert tr.load(str(Path(__file__).resolve().parents[1]/"translations"/f"app_{lang}.qm"))
    for context,messages in AUTO_MESSAGES.items():
        for source in messages:
            assert tr.translate(context,source), (lang,context,source)


def test_auto_options_retheme_visible_labels_when_mode_changes(qtbot):
    from core.ui_theme import get_ui_theme
    from stitch.auto_scroll_dialog import AutoScrollDialog
    manager=get_ui_theme()
    original=manager.mode
    dialog=AutoScrollDialog()
    qtbot.addWidget(dialog)
    try:
        for mode in ("dark","light"):
            manager.set_mode(mode,persist=False)
            assert manager.tokens.window in dialog.styleSheet()
            assert all(manager.tokens.text in label.styleSheet() for label in dialog.labels)
    finally:
        manager.set_mode(original,persist=False)


def test_closed_session_cannot_restart_automatic_input(controller):
    control,window,target,clock=controller
    window._closing=True
    with pytest.raises(ValueError):control.start(AutoScrollOptions())
    assert not control.active and not target.scroll.called


def test_focus_change_during_capture_rejects_frame_before_committing(qapp,monkeypatch):
    from PySide6.QtGui import QImage,QPixmap
    from stitch.scroll_window import ScrollCaptureWindow
    image=QImage(20,20,QImage.Format.Format_RGB32)
    image.fill(0xff123456)
    target=Mock(validate=Mock(side_effect=ValueError("focus changed during grab")))
    window=SimpleNamespace(_adjustment_dialog=None,_closing=False,capture_rect=QRect(0,0,20,20),
                           _auto_scroll=SimpleNamespace(active=True,_cancel=Mock(is_set=Mock(return_value=False)),target=target),
                           _exclude_overlapping_ui=Mock(),_append_frame=Mock())
    screen=SimpleNamespace(geometry=lambda:QRect(0,0,100,100),grabWindow=lambda *args:QPixmap.fromImage(image))
    monkeypatch.setattr("stitch.scroll_window.QGuiApplication",SimpleNamespace(instance=lambda:SimpleNamespace(screenAt=lambda point:screen)))
    assert ScrollCaptureWindow._do_capture(window) is None
    window._append_frame.assert_not_called()
    assert window._exclude_overlapping_ui.call_args.args==(False,)
