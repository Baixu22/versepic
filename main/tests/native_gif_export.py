"""Opt-in native GIF controls acceptance. Synthetic frames and isolated INI only."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace


def run(directory, language, scale):
    from PySide6.QtCore import QCoreApplication, QEvent, QRect, QSettings, QTimer, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QLabel
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    from settings import get_tool_settings_manager
    config = get_tool_settings_manager(QSettings(str(directory / 'settings.ini'), QSettings.Format.IniFormat))
    assert Path(config.qsettings.fileName()).resolve() == (directory / 'settings.ini').resolve()
    from tests.native_image_editor import registry_digest
    baseline = registry_digest()
    config.set_log_enabled(False)
    config.set_log_dir(str(directory / 'logs'))
    config.set_clipboard_db_path(str(directory / 'unused-history.db'))
    config.set_screenshot_save_path(str(directory / 'output'))
    config.set_app_setting('language', language)
    config.set_app_setting('dialog_scale_percent', scale)
    from core.i18n import I18nManager
    from core.ui_scale import get_dialog_scale, get_ui_scale
    from core.ui_theme import get_ui_theme
    I18nManager.load_language(language)
    get_dialog_scale().init(config)
    get_ui_scale().init(config)
    theme = get_ui_theme().init(config, app)
    import gifrecorder
    from PIL import Image, ImageDraw, ImageSequence
    from gif.composer import ComposerProgressDialog, _ComposeWorker
    from gif.export_dialog import GifExportDialog
    from gif.frame_recorder import FrameData, CursorSnapshot
    from gif.playback_controller import PlaybackController
    from gif import playback_controller as module
    records = []
    store = gifrecorder.FrameStore(640, 359, 30, jpeg_quality=100)
    for index in range(60):
        image = Image.new('RGB', (640, 359), '#e8f0ff')
        draw = ImageDraw.Draw(image)
        draw.rectangle((200 + index, 80, 400 + index, 240), fill='#1d4ed8')
        draw.text((30, 30), f'GIF FRAME {index:02d} - SYNTHETIC FIXTURE', fill='#172554')
        store.push_rgb(image.tobytes(), round(index * 1000 / 30))
    hashes = [hashlib.sha256(store.get_frame_rgb(i)).hexdigest() for i in range(store.frame_count)]
    controller = PlaybackController()
    recorder = SimpleNamespace(store=store, frames=[FrameData(round(i * 1000 / 30), 640, 359,
        cursor=CursorSnapshot(100 + i, 130, 0)) for i in range(60)], total_duration_ms=1967)
    controller.set_context(QRect(120, 120, 640, 359), recorder,
        SimpleNamespace(get_current_fps=lambda: 30), lambda toolbar: toolbar.move(120, 500))
    controller.start_playback(recorder.frames)
    toolbar = controller.playback_toolbar
    toolbar._slider.set_trim(6, 35)
    controller._on_speed_changed(2.0)
    target = directory / 'trimmed-321.gif'
    old_dialog = module.QFileDialog.getSaveFileName
    module.QFileDialog.getSaveFileName = lambda *a, **k: (str(target), 'GIF (*.gif)')
    errors = []
    states = set()
    def pump():
        try:
            modal = QApplication.activeModalWidget()
            if isinstance(modal, GifExportDialog) and 'options' not in states:
                states.add('options')
                modal.size_mode.setCurrentIndex(1)
                modal.width.setFocus()
                modal.width.selectAll()
                QTest.keyClicks(modal.width, '321')
                modal.fps.setCurrentIndex(modal.fps.findData(10))
                assert modal.options() == {'gif_width': 321, 'fps': 10}
                assert modal.export_button.isEnabled()
                for color in ('light', 'dark'):
                    theme.set_mode(color, persist=False)
                    app.processEvents()
                    QTest.mouseMove(modal.export_button, modal.export_button.rect().center())
                    assert modal.grab().save(str(directory / f'options-{color}.png'))
                QTest.mouseClick(modal.export_button, Qt.MouseButton.LeftButton)
            elif isinstance(modal, ComposerProgressDialog) and 'progress' not in states:
                states.add('progress')
                assert modal.grab().save(str(directory / 'progress.png'))
            elif modal is not None and not isinstance(modal, (GifExportDialog, ComposerProgressDialog)):
                text = '\n'.join(label.text() for label in modal.findChildren(QLabel))
                assert target.exists(), text
                assert f'{target.stat().st_size:,}' in text, text
                assert modal.grab().save(str(directory / 'actual-size.png'))
                states.add('actual_size')
                modal.accept()
        except Exception:
            import traceback
            errors.append(traceback.format_exc())
            if QApplication.activeModalWidget():
                QApplication.activeModalWidget().reject()
    timer = QTimer()
    timer.timeout.connect(pump)
    timer.start(35)
    try:
        QTest.mouseClick(toolbar._save_btn, Qt.MouseButton.LeftButton)
        assert not errors, errors
        assert {'options', 'actual_size'} <= states, states
        with Image.open(target) as image:
            duration = sum(frame.info.get('duration', 0) for frame in ImageSequence.Iterator(image))
            assert image.size == (321, 180) and duration == 500
            assert image.n_frames <= 6
            image.seek(0)
            image.convert('RGB').save(directory / 'decoded-first-frame.png')
        records.append({'check': 'real playback save entry, inclusive trim, 2x speed, width321/fps10 and actual byte count', 'passed': True})
        timer.stop()
        # Actual visible Cancel and Escape must preserve an existing destination.
        for action in ('button', 'escape'):
            destination = directory / f'cancel-{action}.gif'
            destination.write_bytes(b'ORIGINAL FILE')
            dialog = ComposerProgressDialog()
            dialog.show()
            dialog.start(str(destination), store=store)
            if action == 'button':
                QTest.mouseClick(dialog._cancel_button, Qt.MouseButton.LeftButton)
            else:
                QTest.keyClick(dialog, Qt.Key.Key_Escape)
            deadline = time.monotonic() + 20
            while not dialog._finished and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(.01)
            assert dialog._finished and not dialog._ok and destination.read_bytes() == b'ORIGINAL FILE'
            dialog.deleteLater()
        assert not list(directory.glob('.versepic-*.tmp'))
        records.append({'check': 'visible Cancel and Escape stop native encoder and keep original files', 'passed': True})
        # Original dimensions and explicit [0,0] really export only the first frame.
        first = directory / 'first-only.gif'
        assert _ComposeWorker(str(first), store, frame_start=0, frame_end=0)._compose() == str(first)
        with Image.open(first) as image:
            assert image.n_frames == 1 and image.size == (640, 359) and image.info['duration'] == 30
        assert hashes == [hashlib.sha256(store.get_frame_rgb(i)).hexdigest() for i in range(store.frame_count)]
        records.append({'check': 'first-only keeps original odd dimensions and all source RGB hashes remain unchanged', 'passed': True})
    finally:
        timer.stop()
        module.QFileDialog.getSaveFileName = old_dialog
        controller.teardown()
        controller.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        assert registry_digest() == baseline, 'Real application settings changed'
    (directory / 'result.json').write_text(json.dumps(records, indent=2), encoding='utf-8')
    print(json.dumps(records, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--language', default='zh')
    parser.add_argument('--scale', type=int, default=100)
    args = parser.parse_args()
    if not args.run:
        parser.error('Native GIF acceptance requires --run')
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    os.environ['QT_QPA_PLATFORM'] = 'windows'
    os.environ['QT_ENABLE_HIGHDPI_SCALING'] = '0'
    os.environ['QT_SCALE_FACTOR'] = '1'
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from core.platform_utils import set_dpi_awareness
    set_dpi_awareness()
    run(args.output, args.language, args.scale)
