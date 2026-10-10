# -*- coding: utf-8 -*-
"""
_ComposeWorker (GIF 合成) 单元测试

覆盖 main/gif/composer.py 中 _ComposeWorker 的合成/导出逻辑：
- 路径模式：显式 path（导出到磁盘）vs None（导出到临时文件后读为 bytes）
- 尺寸计算：gif_width 缩放时的宽高比与偏移取整
- 取消：cancel() 后 _do_compose 应返回失败，且临时文件被清理
- 异常处理：export_gif 抛 "cancelled" 异常 vs 其它异常的不同处理
- cursor_sprites/cursor_infos 只在两者都提供时才传给 export_gif
- gifrecorder 不可用或 store 为 None 时直接失败

多数用例用 MagicMock 替身模拟 path/width/height/repeat 等接口；
末尾的原生回归使用真实 FrameStore，验证取消后保留目标文件，
并用 Pillow 独立打开再次成功导出的 GIF。
"""
import os
import pytest
from unittest.mock import MagicMock, patch

import gif.composer as composer_module
from gif.composer import _ComposeWorker


@pytest.fixture
def fake_store():
    """模拟 gifrecorder.FrameStore：width/height 属性 + export_gif()/cancel_export()"""
    store = MagicMock()
    store.width = 640
    store.height = 480
    store.export_gif = MagicMock()
    store.cancel_export = MagicMock()
    return store


@pytest.fixture(autouse=True)
def force_gifrecorder_available():
    with patch.object(composer_module, "_gifrecorder_available", True):
        yield


class TestComposeToExplicitPath:
    def test_do_compose_calls_export_gif_with_out_path(self, qapp, fake_store, tmp_path):
        out_path = str(tmp_path / "out.gif")
        worker = _ComposeWorker(path=out_path, store=fake_store)

        # export_gif 是 mock，不会真的写文件；手动创建让 getsize() 不炸
        def _fake_export(**kwargs):
            with open(out_path, "wb") as f:
                f.write(b"GIF89a")
        fake_store.export_gif.side_effect = _fake_export

        ok = worker._do_compose(out_path)

        assert ok is True
        fake_store.export_gif.assert_called_once()
        call_kwargs = fake_store.export_gif.call_args.kwargs
        assert call_kwargs["path"] == out_path
        assert call_kwargs["width"] == 640
        assert call_kwargs["height"] == 480

    def test_compose_returns_path_string_when_path_given(self, qapp, fake_store, tmp_path):
        out_path = str(tmp_path / "out.gif")

        def _fake_export(**kwargs):
            with open(kwargs["path"], "wb") as f:
                f.write(b"GIF89a")
        fake_store.export_gif.side_effect = _fake_export

        worker = _ComposeWorker(path=out_path, store=fake_store)
        result = worker._compose()

        assert result == out_path
        assert os.path.isfile(out_path)


class TestComposeToBytes:
    def test_compose_returns_bytes_when_path_is_none(self, qapp, fake_store):
        def _fake_export(**kwargs):
            with open(kwargs["path"], "wb") as f:
                f.write(b"GIF89a_PAYLOAD")
        fake_store.export_gif.side_effect = _fake_export

        worker = _ComposeWorker(path=None, store=fake_store)
        result = worker._compose()

        assert result == b"GIF89a_PAYLOAD"

    def test_temp_file_is_deleted_after_reading_bytes(self, qapp, fake_store):
        captured_path = {}

        def _fake_export(**kwargs):
            captured_path["path"] = kwargs["path"]
            with open(kwargs["path"], "wb") as f:
                f.write(b"X")
        fake_store.export_gif.side_effect = _fake_export

        worker = _ComposeWorker(path=None, store=fake_store)
        worker._compose()

        assert not os.path.isfile(captured_path["path"])


class TestGifWidthScaling:
    def test_no_gif_width_uses_store_native_size(self, qapp, fake_store):
        fake_store.export_gif.side_effect = lambda **kw: open(kw["path"], "wb").close()
        worker = _ComposeWorker(path="out.gif", store=fake_store, gif_width=0)
        worker._do_compose("out.gif")

        call_kwargs = fake_store.export_gif.call_args.kwargs
        assert call_kwargs["width"] == 640
        assert call_kwargs["height"] == 480
        os.unlink("out.gif") if os.path.isfile("out.gif") else None

    def test_scaled_width_computes_proportional_height(self, qapp, fake_store):
        # store: 640x480 (4:3) 缩放到 gif_width=320 → height 应约为 240
        fake_store.width = 640
        fake_store.height = 480
        fake_store.export_gif.side_effect = lambda **kw: open(kw["path"], "wb").close()

        worker = _ComposeWorker(path="scaled.gif", store=fake_store, gif_width=320)
        worker._do_compose("scaled.gif")

        call_kwargs = fake_store.export_gif.call_args.kwargs
        assert call_kwargs["width"] == 320
        assert call_kwargs["height"] == 240
        os.unlink("scaled.gif") if os.path.isfile("scaled.gif") else None

    def test_gif_keeps_nearest_odd_height_without_video_alignment(self, qapp, fake_store):
        fake_store.width = 100
        fake_store.height = 33
        fake_store.export_gif.side_effect = lambda **kw: open(kw["path"], "wb").close()

        worker = _ComposeWorker(path="odd.gif", store=fake_store, gif_width=50)
        worker._do_compose("odd.gif")

        call_kwargs = fake_store.export_gif.call_args.kwargs
        # GIF允许奇数尺寸，33 * .5 = 16.5，取最近整数17，不强制减为16。
        assert call_kwargs["height"] == 17
        os.unlink("odd.gif") if os.path.isfile("odd.gif") else None


class TestCursorSprites:
    def test_cursor_kwargs_omitted_when_either_missing(self, qapp, fake_store):
        fake_store.export_gif.side_effect = lambda **kw: open(kw["path"], "wb").close()

        # 只提供 sprites，没有 infos -> 不应传入
        worker = _ComposeWorker(
            path="a.gif", store=fake_store,
            cursor_sprites={"arrow": b"data"}, cursor_infos=None,
        )
        worker._do_compose("a.gif")
        assert "cursor_sprites" not in fake_store.export_gif.call_args.kwargs
        os.unlink("a.gif") if os.path.isfile("a.gif") else None

    def test_cursor_kwargs_included_when_both_present(self, qapp, fake_store):
        fake_store.export_gif.side_effect = lambda **kw: open(kw["path"], "wb").close()

        sprites = {"arrow": b"data"}
        infos = [(0, 0, 0, 0, 0, 0)]
        worker = _ComposeWorker(
            path="b.gif", store=fake_store,
            cursor_sprites=sprites, cursor_infos=infos,
        )
        worker._do_compose("b.gif")
        call_kwargs = fake_store.export_gif.call_args.kwargs
        assert call_kwargs["cursor_sprites"] is sprites
        assert call_kwargs["cursor_infos"] is infos
        os.unlink("b.gif") if os.path.isfile("b.gif") else None


class TestCancellation:
    def test_cancel_sets_flag_and_calls_store_cancel_export(self, qapp, fake_store):
        worker = _ComposeWorker(path="x.gif", store=fake_store)
        worker.cancel()
        assert worker._cancel is True
        fake_store.cancel_export.assert_called_once()

    def test_export_gif_raising_cancelled_returns_false_without_error_log(self, qapp, fake_store):
        fake_store.export_gif.side_effect = RuntimeError("export cancelled by user")
        worker = _ComposeWorker(path="cancelled.gif", store=fake_store)

        ok = worker._do_compose("cancelled.gif")

        assert ok is False

    def test_compose_cleans_up_temp_file_when_cancelled(self, qapp, fake_store):
        created_path = {}

        def _fake_export(**kwargs):
            created_path["path"] = kwargs["path"]
            # 模拟：文件被创建了一部分，但随后判定为取消
            with open(kwargs["path"], "wb") as f:
                f.write(b"partial")
            raise RuntimeError("cancelled")

        fake_store.export_gif.side_effect = _fake_export
        worker = _ComposeWorker(path=None, store=fake_store)  # None -> 走临时文件分支

        result = worker._compose()

        assert result is None
        assert not os.path.isfile(created_path["path"])


class TestExportGifGenericFailure:
    def test_non_cancel_exception_returns_false(self, qapp, fake_store):
        fake_store.export_gif.side_effect = ValueError("disk full")
        worker = _ComposeWorker(path="fail.gif", store=fake_store)

        ok = worker._do_compose("fail.gif")

        assert ok is False


class TestRunEntryPoint:
    def test_run_emits_finished_false_when_gifrecorder_unavailable(self, qapp, fake_store):
        with patch.object(composer_module, "_gifrecorder_available", False):
            worker = _ComposeWorker(path="x.gif", store=fake_store)
            received = []
            worker.finished.connect(lambda ok, result: received.append((ok, result)))
            worker.run()

        assert received == [(False, "gifrecorder_not_found")]

    def test_run_emits_finished_false_when_store_is_none(self, qapp):
        worker = _ComposeWorker(path="x.gif", store=None)
        received = []
        worker.finished.connect(lambda ok, result: received.append((ok, result)))
        worker.run()

        assert received == [(False, "gifrecorder_not_found")]

    def test_run_emits_finished_true_on_success(self, qapp, fake_store, tmp_path):
        out_path = str(tmp_path / "ok.gif")

        def _fake_export(**kwargs):
            with open(kwargs["path"], "wb") as f:
                f.write(b"GIF89a")
        fake_store.export_gif.side_effect = _fake_export

        worker = _ComposeWorker(path=out_path, store=fake_store)
        received = []
        worker.finished.connect(lambda ok, result: received.append((ok, result)))
        worker.run()

        assert len(received) == 1
        ok, result = received[0]
        assert ok is True
        assert result == out_path

    def test_generic_export_failure_is_handled_internally_not_as_crash(self, qapp, fake_store):
        """编码失败不是成功；仅提交了有效输出才发出 finished(True, result)。"""
        fake_store.export_gif.side_effect = Exception("boom, totally unexpected")
        worker = _ComposeWorker(path="boom.gif", store=fake_store)
        received = []
        worker.finished.connect(lambda ok, result: received.append((ok, result)))

        worker.run()  # 不应向外抛异常

        assert received == [(False, None)]

    def test_run_catches_exception_escaping_compose_entirely(self, qapp, fake_store):
        """当异常发生在 _compose() 自身（不是 export_gif 内部），run() 的外层
        try/except 应捕获并 emit (False, None)。"""
        worker = _ComposeWorker(path="x.gif", store=fake_store)
        with patch.object(worker, "_compose", side_effect=RuntimeError("unexpected bug")):
            received = []
            worker.finished.connect(lambda ok, result: received.append((ok, result)))
            worker.run()

        assert received == [(False, None)]


class TestSpeedMultiplierClamp:
    def test_speed_multiplier_clamped_to_minimum(self, qapp, fake_store):
        worker = _ComposeWorker(path="x.gif", store=fake_store, speed_multiplier=0.01)
        assert worker._speed_multiplier == 0.1

    def test_speed_multiplier_passed_through_when_valid(self, qapp, fake_store):
        worker = _ComposeWorker(path="x.gif", store=fake_store, speed_multiplier=2.5)
        assert worker._speed_multiplier == 2.5


@pytest.mark.parametrize("failure", ["cancel", "error", "empty", "late_cancel"])
def test_path_export_failure_keeps_existing_file_and_removes_staging(qapp, fake_store, tmp_path, failure):
    from pathlib import Path
    destination = tmp_path / "existing.gif"
    destination.write_bytes(b"ORIGINAL")
    worker = _ComposeWorker(str(destination), store=fake_store)
    stages = []

    def export(**kwargs):
        stage = Path(kwargs["path"])
        stages.append(stage)
        assert stage != destination and stage.parent == destination.parent
        assert destination.read_bytes() == b"ORIGINAL"
        if failure != "empty":
            stage.write_bytes(b"PARTIAL")
        if failure == "cancel":
            worker.cancel()
            raise ValueError("cancelled")
        if failure == "error":
            raise OSError("disk full")
        if failure == "late_cancel":
            worker.cancel()

    fake_store.export_gif.side_effect = export
    assert worker._compose() is None
    assert destination.read_bytes() == b"ORIGINAL"
    assert stages and all(not stage.exists() for stage in stages)
    assert list(tmp_path.iterdir()) == [destination]


@pytest.mark.parametrize("to_bytes", [False, True])
def test_cancel_before_export_does_not_start_encoder(qapp, fake_store, tmp_path, to_bytes):
    destination = tmp_path / "existing.gif"
    destination.write_bytes(b"ORIGINAL")
    worker = _ComposeWorker(None if to_bytes else str(destination), store=fake_store)
    worker.cancel()
    assert worker._compose() is None
    fake_store.export_gif.assert_not_called()
    assert destination.read_bytes() == b"ORIGINAL"
    assert list(tmp_path.iterdir()) == [destination]


def test_replace_failure_keeps_original_and_removes_staging(qapp, fake_store, tmp_path, monkeypatch):
    from pathlib import Path
    destination = tmp_path / "existing.gif"
    destination.write_bytes(b"ORIGINAL")
    fake_store.export_gif.side_effect = lambda **kw: Path(kw["path"]).write_bytes(b"NEW GIF")
    worker = _ComposeWorker(str(destination), store=fake_store)
    def denied(*args):
        raise PermissionError("destination locked")
    monkeypatch.setattr("core.save.os.replace", denied)
    assert worker._compose() is None
    assert destination.read_bytes() == b"ORIGINAL"
    assert list(tmp_path.iterdir()) == [destination]


def test_success_commits_only_after_encoder_finished(qapp, fake_store, tmp_path):
    from pathlib import Path
    destination = tmp_path / "existing.gif"
    destination.write_bytes(b"ORIGINAL")
    def export(**kw):
        Path(kw["path"]).write_bytes(b"COMPLETE GIF")
        assert destination.read_bytes() == b"ORIGINAL"
    fake_store.export_gif.side_effect = export
    worker = _ComposeWorker(str(destination), store=fake_store)
    assert worker._compose() == str(destination)
    assert destination.read_bytes() == b"COMPLETE GIF"
    assert list(tmp_path.iterdir()) == [destination]


def test_unexpected_compose_error_still_removes_bytes_staging(qapp, fake_store, monkeypatch):
    from pathlib import Path
    stages = []
    worker = _ComposeWorker(None, store=fake_store)
    def explode(filename):
        stages.append(Path(filename))
        raise RuntimeError("unexpected encoder bug")
    monkeypatch.setattr(worker, "_do_compose", explode)
    received = []
    worker.finished.connect(lambda ok, result: received.append((ok, result)))
    worker.run()
    assert received == [(False, None)]
    assert stages and all(not stage.exists() for stage in stages)


def test_empty_bytes_is_not_success(qapp, fake_store):
    worker = _ComposeWorker(None, store=fake_store)
    # Existing empty mkstemp file must not become a successful b"" result.
    assert worker._compose() is None


def test_native_cancel_preserves_file_and_leaves_store_reusable(qapp, tmp_path):
    import gifrecorder
    from PIL import Image
    destination = tmp_path / "existing.gif"
    destination.write_bytes(b"ORIGINAL")
    store = gifrecorder.FrameStore(81, 61, 10)
    for index in range(6):
        store.push_rgb(bytes((index * 40, 60, 180)) * (81 * 61), index * 100)
    worker = _ComposeWorker(str(destination), store=store)
    # Direct connection: deterministic cancellation inside the native progress callback.
    worker.progress.connect(lambda done, total: worker.cancel())
    assert worker._compose() is None
    assert destination.read_bytes() == b"ORIGINAL"
    assert list(tmp_path.iterdir()) == [destination]
    second = _ComposeWorker(str(destination), store=store)
    assert second._compose() == str(destination)
    with Image.open(destination) as image:
        assert image.size == (81, 61) and image.n_frames == 6
        image.seek(5)
        image.load()
    assert list(tmp_path.iterdir()) == [destination]
