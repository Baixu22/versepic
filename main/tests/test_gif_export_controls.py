"""Actual native GIF decoding and UI-to-encoder acceptance for output controls."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import gifrecorder
import pytest
from PIL import Image, ImageSequence
from PySide6.QtCore import QCoreApplication, QEvent, QTimer

from gif.composer import _ComposeWorker, ComposerProgressDialog, output_size, timeline_encoder_available
from gif.export_dialog import GifExportDialog
from gif.playback_controller import PlaybackController


def make_store(width=81, height=61, count=30, fps=30):
    store = gifrecorder.FrameStore(width, height, fps, jpeg_quality=100)
    for index in range(count):
        store.push_rgb(bytes((index * 7 % 256, 60, 180)) * (width * height), round(index * 1000 / fps))
    return store


def inspect_gif(filename):
    with Image.open(filename) as image:
        frames = [(frame.copy().convert("RGB"), frame.info.get("duration", 0)) for frame in ImageSequence.Iterator(image)]
        return image.size, frames


@pytest.mark.parametrize("speed,fps,expected_ms", [(1, 0, 1000), (2, 0, 500), (.5, 0, 2000),
    (1, 10, 1000), (2, 5, 500), (.5, 20, 2000)])
def test_real_gif_preserves_total_time_while_dropping_frames(tmp_path, speed, fps, expected_ms):
    store = make_store()
    target = tmp_path / "timing.gif"
    store.export_gif(str(target), speed=speed, fps=fps)
    size, frames = inspect_gif(target)
    assert size == (81, 61)
    assert sum(duration for _, duration in frames) == expected_ms
    assert all(duration >= 20 for _, duration in frames)
    assert len(frames) <= 30
    if fps:
        assert len(frames) <= int(expected_ms * fps / 1000) + 1


@pytest.mark.parametrize("start,end,expected_ms", [(0, 0, 30), (1, 1, 30), (8, 14, 230), (29, 29, 30)])
def test_inclusive_trim_including_first_only(tmp_path, start, end, expected_ms):
    store = make_store()
    target = tmp_path / "trim.gif"
    store.export_gif(str(target), frame_start=start, frame_end=end)
    _, frames = inspect_gif(target)
    assert len(frames) == end - start + 1
    assert sum(d for _, d in frames) == expected_ms
    assert abs(frames[0][0].getpixel((30, 30))[0] - start * 7) <= 8


def test_long_clip_has_no_per_frame_rounding_drift(tmp_path):
    store = make_store(width=9, height=7, count=3000)
    target = tmp_path / "long.gif"
    store.export_gif(str(target), speed=2, fps=10)
    _, frames = inspect_gif(target)
    assert sum(d for _, d in frames) == 50000
    assert len(frames) <= 501


@pytest.mark.parametrize("kwargs", [{"fps": 51}, {"speed": float("nan")}, {"speed": 0},
    {"frame_start": 3, "frame_end": 1}, {"frame_end": 30}, {"width": 65536}, {"width": 10000, "height": 10000}])
def test_native_rejects_bad_options_before_opening_existing_file(tmp_path, kwargs):
    store = make_store()
    target = tmp_path / "existing.gif"
    target.write_bytes(b"ORIGINAL")
    with pytest.raises(ValueError):
        store.export_gif(str(target), **kwargs)
    assert target.read_bytes() == b"ORIGINAL"


def test_scaled_odd_dimensions_are_real_and_fps_reaches_native(qapp, tmp_path):
    store = make_store(width=100, height=33)
    target = tmp_path / "odd.gif"
    worker = _ComposeWorker(str(target), store, gif_width=50, fps=5, frame_end=29)
    assert worker._compose() == str(target)
    size, frames = inspect_gif(target)
    assert size == (50, 17) and len(frames) == 5
    assert sum(d for _, d in frames) == 1000


@pytest.mark.parametrize("width", [-1, True, 65536, 10000])
def test_output_size_bounds(width):
    with pytest.raises(ValueError):
        output_size(SimpleNamespace(width=80, height=60), width)


def test_export_dialog_original_custom_fps_and_outdated_encoder(qtbot, monkeypatch):
    dialog = GifExportDialog(make_store(), 0, 29, 2, True)
    qtbot.addWidget(dialog)
    assert timeline_encoder_available()
    assert dialog.options() == {"gif_width": 0, "fps": 0}
    assert not dialog.width.isEnabled()
    dialog.size_mode.setCurrentIndex(1)
    dialog.width.setValue(41)
    dialog.fps.setCurrentIndex(dialog.fps.findData(10))
    assert dialog.width.isEnabled() and dialog.options() == {"gif_width": 41, "fps": 10}
    assert "41" in dialog.output.text() and "31" in dialog.output.text()
    dialog.width.setValue(65535)
    assert not dialog.export_button.isEnabled()
    monkeypatch.setattr("gif.export_dialog.timeline_encoder_available", lambda: False)
    dialog.width.setValue(81)
    assert not dialog.export_button.isEnabled() and "outdated" in dialog.output.text()


def test_controller_passes_options_trim_speed_and_scaled_cursor(qapp, monkeypatch, tmp_path):
    from PySide6.QtCore import QRect
    from gif.frame_recorder import CursorSnapshot, FrameData
    import gif.playback_controller as module
    controller = PlaybackController()
    store = make_store(width=100, height=33)
    controller._recorder = SimpleNamespace(store=store, frames=[FrameData(i * 100, cursor=CursorSnapshot(20, 10, 1)) for i in range(30)])
    controller._rect = QRect(0, 0, 100, 33)
    controller._export_speed = 2
    controller._get_trim_range = lambda: (4, 9)
    controller._engine = Mock()
    options = Mock()
    options.DialogCode.Accepted = 1
    options.exec.return_value = 1
    options.options.return_value = {"gif_width": 50, "fps": 10}
    monkeypatch.setattr(module, "GifExportDialog", lambda *a: options)
    raster = Mock(return_value={"sprite": "fixture"})
    monkeypatch.setattr("gif.cursor_overlay.rasterize_cursor_sprites", raster)
    monkeypatch.setattr("gif.cursor_overlay.compute_burst_states", lambda cursors: [(1, 1)] * len(cursors))
    target = tmp_path / "controlled.gif"
    def compose(**kwargs):
        assert kwargs["frame_start"] == 4 and kwargs["frame_end"] == 9
        assert kwargs["gif_width"] == 50 and kwargs["fps"] == 10 and kwargs["speed_multiplier"] == 2
        assert kwargs["cursor_infos"][4] == (10, 5, 1, 0, 1, 1)
        target.write_bytes(b"known size")
        return str(target)
    monkeypatch.setattr(module.ComposerProgressDialog, "run_compose", compose)
    notify = Mock()
    monkeypatch.setattr(module, "show_info_dialog", notify)
    closed = Mock()
    controller.close_requested.connect(closed)
    controller._compose_and_export(str(target), False)
    raster.assert_called_once_with(.5)
    controller._engine.pause.assert_called_once()
    assert "10 bytes" in notify.call_args.args[2]
    closed.assert_called_once()


def test_controller_options_cancel_does_not_encode_or_close(qapp, monkeypatch, tmp_path):
    import gif.playback_controller as module
    controller = PlaybackController()
    controller._recorder = SimpleNamespace(store=make_store(), frames=[SimpleNamespace(cursor=None)] * 30)
    controller._get_trim_range = lambda: (0, 29)
    dialog = Mock()
    dialog.DialogCode.Accepted = 1
    dialog.exec.return_value = 0
    monkeypatch.setattr(module, "GifExportDialog", lambda *a: dialog)
    encode = Mock()
    monkeypatch.setattr(module.ComposerProgressDialog, "run_compose", encode)
    closed = Mock()
    controller.close_requested.connect(closed)
    controller._compose_and_export(str(tmp_path / "cancelled.gif"), False)
    encode.assert_not_called()
    closed.assert_not_called()


def test_copy_path_reuses_isolated_settings_and_is_unique(qapp, monkeypatch, tmp_path):
    config = SimpleNamespace(get_screenshot_save_path=lambda: str(tmp_path))
    monkeypatch.setattr("settings.get_tool_settings_manager", lambda: config)
    first, second = PlaybackController._make_save_path(), PlaybackController._make_save_path()
    assert Path(first).parent == tmp_path and Path(second).parent == tmp_path and first != second
    assert list(tmp_path.iterdir()) == []


def test_thread_progress_cancel_keeps_original_and_cleans_worker(qtbot, tmp_path):
    import shiboken6
    target = tmp_path / "cancel.gif"
    target.write_bytes(b"ORIGINAL")
    dialog = ComposerProgressDialog()
    qtbot.addWidget(dialog)
    # Enough work that the 0-progress callback reaches the event loop before commit.
    store = make_store(width=600, height=400, count=50)
    dialog.start(str(target), store=store, fps=10)
    worker = dialog._worker
    dialog.cancel()
    qtbot.waitUntil(lambda: dialog._finished, timeout=20000)
    assert not dialog._ok and dialog._thread is None
    assert target.read_bytes() == b"ORIGINAL"
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not shiboken6.isValid(worker)
    assert list(tmp_path.iterdir()) == [target]


def test_fast_export_cannot_hang_nested_event_loop(qapp, monkeypatch, tmp_path):
    import gif.composer as module
    def immediate(self, path, **kwargs):
        self._on_finished(True, path)
    monkeypatch.setattr(module.ComposerProgressDialog, "start", immediate)
    # With the old unconditional exec(), this would wait until the timer (or hang).
    fired = []
    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(lambda: fired.append(True))
    timer.start(300)
    assert module.ComposerProgressDialog.run_compose(str(tmp_path / "fast.gif")) == str(tmp_path / "fast.gif")
    assert not fired
    timer.stop()


def test_rasterized_alpha_is_straight_not_double_premultiplied(qapp):
    from PySide6.QtGui import QColor
    from gif.cursor_overlay import _rasterize_qimage
    data = _rasterize_qimage(4, 4, lambda painter, w, h: painter.fillRect(0, 0, w, h, QColor(200, 100, 50, 128)))
    assert all(abs(actual - expected) <= 1 for actual, expected in zip(data[:4], (200, 100, 50, 128), strict=True))


@pytest.mark.parametrize("scale", [.125, .5, 1.5, 2])
def test_cursor_and_effect_sprites_scale_together(qapp, scale):
    from gif.cursor_overlay import rasterize_cursor_sprites
    original = rasterize_cursor_sprites()
    scaled = rasterize_cursor_sprites(scale)
    assert scaled.keys() == original.keys()
    for name, (data, w, h) in scaled.items():
        _, ow, oh = original[name]
        assert (w, h) == (max(1, int(ow * scale + .5)), max(1, int(oh * scale + .5)))
        assert len(data) == w * h * 4


@pytest.mark.parametrize("scale", [0, -1, 17, float("nan"), float("inf")])
def test_invalid_sprite_scale_fails_before_allocation(qapp, scale):
    from gif.cursor_overlay import rasterize_cursor_sprites
    with pytest.raises(ValueError):
        rasterize_cursor_sprites(scale)


def test_scaled_click_and_scroll_are_at_their_scaled_source_positions(tmp_path):
    store = gifrecorder.FrameStore(200, 120, 10)
    store.push_rgb(bytes((0, 0, 0)) * (200 * 120), 0)
    def sprite(color):
        return bytes(color) * 16, 4, 4
    sprites = {"cursor": sprite((255, 255, 255, 255)),
               "scroll_up": sprite((0, 255, 0, 255)), "scroll_down": sprite((0, 255, 0, 255))}
    for side in ("left", "right"):
        for frame in (1, 2, 3):
            sprites[f"burst_{side}_{frame}"] = sprite((255, 0, 0, 255))
    destination = tmp_path / "cursor.gif"
    store.export_gif(str(destination), width=100, height=60, cursor_sprites=sprites,
                     cursor_infos=[(20, 20, 1, 1, 1, 1)])
    _, frames = inspect_gif(destination)
    image = frames[0][0]
    # At .5 scale the click center offset is 3px, scroll gap is 5px.
    # Test geometry, not lossless RGB: the existing 255-color quantizer may
    # map these tiny rare accents to gray. These pixels were black with the
    # old unscaled +6/+10 offsets. Cursor covers only (20..23,20..23).
    assert max(image.getpixel((21, 24))) > 60
    assert max(image.getpixel((28, 21))) > 60
    assert max(image.getpixel((35, 21))) < 10


def test_application_shutdown_joins_encoder_and_keeps_destination(qtbot, tmp_path):
    target = tmp_path / "quit.gif"
    target.write_bytes(b"ORIGINAL")
    dialog = ComposerProgressDialog()
    qtbot.addWidget(dialog)
    dialog.start(str(target), store=make_store(width=600, height=400, count=50))
    dialog._shutdown()
    assert dialog._finished and dialog._thread is None and not dialog._ok
    assert target.read_bytes() == b"ORIGINAL"
    assert list(tmp_path.iterdir()) == [target]


@pytest.mark.parametrize("language", ["en", "zh", "ja", "ko"])
def test_compiled_export_translations_cover_every_literal(language):
    import ast
    from PySide6.QtCore import QTranslator
    main = Path(__file__).resolve().parents[1]
    translator = QTranslator()
    assert translator.load(str(main / "translations" / f"app_{language}.qm"))
    for filename, context in (("export_dialog.py", "GifExportDialog"), ("composer.py", "ComposerProgressDialog"),
                              ("playback_controller.py", "PlaybackController")):
        tree = ast.parse((main / "gif" / filename).read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "tr":
                if node.args and isinstance(node.args[0], ast.Constant):
                    source = node.args[0].value
                    assert translator.translate(context, source), (language, context, source)


def test_extreme_enlargement_rejected_before_huge_cursor_sprites(qapp):
    with pytest.raises(ValueError):
        output_size(SimpleNamespace(width=1, height=1), 4000)
