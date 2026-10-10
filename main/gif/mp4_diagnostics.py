"""Opt-in synthetic export check for installed/frozen applications.

Runs before normal bootstrap: no screen capture, clipboard monitoring, personal
settings, hotkeys or single-instance actions. The supplied directory must be empty.
"""
import hashlib
import json
from pathlib import Path
import sys
import traceback


def run(output_directory):
    directory = Path(output_directory).resolve()
    if directory.exists() and (not directory.is_dir() or any(directory.iterdir())):
        return 2
    directory.mkdir(parents=True, exist_ok=True)
    result = {"passed": False, "frozen": bool(getattr(sys, "frozen", False)), "cases": []}
    try:
        from PySide6.QtCore import QSettings
        from PySide6.QtWidgets import QApplication
        app = QApplication([])
        real = QSettings("Jietuba", "ToolSettings")
        before = {key: repr(real.value(key)) for key in real.allKeys()}
        from settings import get_tool_settings_manager
        settings_path = directory / "settings.ini"
        config = get_tool_settings_manager(QSettings(str(settings_path), QSettings.Format.IniFormat))
        assert Path(config.qsettings.fileName()).resolve() == settings_path
        config.set_log_enabled(False)
        config.set_log_dir(str(directory / "logs"))
        config.set_clipboard_db_path(str(directory / "unused-history.db"))
        import av
        import gifrecorder
        from .composer import _ComposeWorker
        result["av_version"] = av.__version__
        result["libraries"] = av.library_versions
        result["av_path"] = str(av.__file__)
        source = gifrecorder.FrameStore(81, 61, 30, jpeg_quality=100)
        for index in range(30):
            source.push_rgb(bytes((index * 7, 60, 180)) * (81 * 61), round(index * 1000 / 30))
        digest = lambda: hashlib.sha256(b"".join(source.get_frame_rgb(i) for i in range(30))).hexdigest()
        source_hash = digest()
        for name, first, last, speed, count, duration in (
            ("full", 0, None, 1, 30, 1001), ("trim-double", 6, 20, 2, 15, 250), ("first", 0, 0, 1, 1, 33)
        ):
            destination = directory / (name + ".mp4")
            worker = _ComposeWorker(str(destination), source, frame_start=first, frame_end=last,
                                    speed_multiplier=speed, output_format="mp4")
            received = []
            worker.finished.connect(lambda ok, path, received=received: received.append((ok, path)))
            worker.run()
            assert received == [(True, str(destination))]
            with av.open(str(destination)) as container:
                stream = container.streams.video[0]
                assert len(container.streams.audio) == 0
                assert (stream.width, stream.height) == (82, 62)
                decoded = sum(1 for _ in container.decode(stream))
                actual_ms = float(stream.duration * stream.time_base) * 1000
                assert decoded == count and abs(actual_ms - duration) < 1
            result["cases"].append({"name": name, "frames": decoded, "duration_ms": actual_ms,
                "dimensions": [82, 62], "audio_streams": 0, "sha256": hashlib.sha256(destination.read_bytes()).hexdigest()})
        destination = directory / "cancel.mp4"
        destination.write_bytes(b"ORIGINAL")
        worker = _ComposeWorker(str(destination), source, output_format="mp4")
        worker.progress.connect(lambda done, total: worker.cancel())
        assert worker._compose() is None and destination.read_bytes() == b"ORIGINAL"
        assert not list(directory.glob(".versepic-*.tmp"))
        assert digest() == source_hash
        # Same bundled frame store and GIF encoder must still support the prior format.
        gif = directory / "first.gif"
        assert _ComposeWorker(str(gif), source, frame_end=0)._compose() == str(gif)
        from PIL import Image
        with Image.open(gif) as image:
            assert image.n_frames == 1 and image.size == (81, 61)
        real.sync()
        assert before == {key: repr(real.value(key)) for key in real.allKeys()}
        result.update(passed=True, cancelled_file_preserved=True, source_unchanged=True,
                      gif_regression=True, real_settings_unchanged=True)
        app.quit()
    except Exception:
        result["error"] = traceback.format_exc()
    (directory / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return 0 if result["passed"] else 1
