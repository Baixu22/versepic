"""Real PyAV output, cancellation and UI integration for silent MP4 exports."""
from types import SimpleNamespace
from unittest.mock import Mock

import av
import gifrecorder
import pytest
from PySide6.QtCore import QCoreApplication, QEvent

from gif.composer import _ComposeWorker, ComposerProgressDialog
from gif.export_dialog import GifExportDialog
from gif.mp4_export import encoder_available, export_mp4, frame_timeline, output_geometry
from gif.playback_controller import PlaybackController


def store(width=81, height=61, count=30, fps=30):
    value = gifrecorder.FrameStore(width, height, fps, jpeg_quality=100)
    for index in range(count):
        value.push_rgb(bytes((index * 7 % 256, 60, 180)) * (width * height), round(index * 1000 / fps))
    return value


def inspect_mp4(path):
    with av.open(str(path)) as container:
        video = container.streams.video[0]
        images = [frame.to_image() for frame in container.decode(video)]
        return SimpleNamespace(size=(video.width, video.height), frames=images,
            duration_ms=float(video.duration * video.time_base) * 1000,
            audio=len(container.streams.audio), codec=video.codec_context.name)


@pytest.mark.parametrize("start,end,speed,expected_count,expected_ms", [
    (0, None, 1, 30, 1001), (0, 0, 1, 1, 33), (1, 1, 2, 1, 17),
    (6, 20, 2, 15, 250), (6, 20, .5, 15, 1000), (29, 29, 1, 1, 34)])
def test_real_encoded_timing_trim_and_silent_track(tmp_path, start, end, speed, expected_count, expected_ms):
    target = tmp_path / "clip.mp4"
    source = store()
    original = [source.get_frame_rgb(i) for i in range(source.frame_count)]
    progress = []
    assert export_mp4(target, source, frame_start=start, frame_end=end, speed=speed,
                      progress=lambda done, total: progress.append((done, total)))
    result = inspect_mp4(target)
    assert result.size == (82, 62) and result.audio == 0 and result.codec == "h264"
    assert len(result.frames) == expected_count and abs(result.duration_ms - expected_ms) < 1
    assert progress[0] == (0, expected_count) and progress[-1] == (expected_count, expected_count)
    assert original == [source.get_frame_rgb(i) for i in range(source.frame_count)]
    assert abs(result.frames[0].getpixel((30, 30))[0] - start * 7) < 12


def test_scaled_size_and_last_interval_from_source(qapp, tmp_path):
    source = store(100, 33)
    assert output_geometry(source, 50) == (50, 17, 50, 18)
    target = tmp_path / "scaled.mp4"
    worker = _ComposeWorker(str(target), source, gif_width=50, frame_end=9, output_format="mp4")
    assert worker._compose() == str(target)
    result = inspect_mp4(target)
    assert result.size == (50, 18) and abs(result.duration_ms - 333) < 1


@pytest.mark.parametrize("width,height,output", [(81, 61, (81,61,82,62)), (80,60,(80,60,80,60)), (1,1,(1,1,2,2))])
def test_even_padding_rules(width, height, output):
    assert output_geometry(SimpleNamespace(width=width, height=height)) == output


@pytest.mark.parametrize("w,h,target", [(0,20,0), (81,61,-1), (81,61,True), (1,1,4000), (9000,20,0), (8000,8000,0)])
def test_invalid_size_rejected_before_allocation(w,h,target):
    with pytest.raises(ValueError):
        output_geometry(SimpleNamespace(width=w,height=h),target)


def test_equal_timestamps_are_merged_without_changing_total():
    source = SimpleNamespace(frame_timestamps=[0, 0, 1, 1, 10], fps=30)
    assert frame_timeline(source) == [(0,0,1), (2,1,9), (4,10,9)]


@pytest.mark.parametrize("times,start,end,speed", [([],0,None,1), ([0,30],1,0,1), ([30,0],0,1,1),
    ([0],0,0,float('nan')), ([0],0,0,0), ([0],0,0,17), ([0,-1],0,1,1)])
def test_invalid_timing_rejected(times,start,end,speed):
    with pytest.raises(ValueError):
        frame_timeline(SimpleNamespace(frame_timestamps=times,fps=30),start,end,speed)


@pytest.mark.parametrize("failure", ["before", "progress", "encode", "replace"])
def test_cancel_and_failure_keep_existing_file(qapp,tmp_path,monkeypatch,failure):
    target=tmp_path/'existing.mp4';target.write_bytes(b'ORIGINAL')
    worker=_ComposeWorker(str(target),store(),output_format='mp4')
    if failure=='before':worker.cancel()
    elif failure=='progress':worker.progress.connect(lambda done,total:worker.cancel())
    elif failure=='encode':
        def bad(*args,**kwargs):raise RuntimeError('codec unavailable')
        monkeypatch.setattr('gif.mp4_export.export_mp4',bad)
    else:
        def denied(*args):raise PermissionError('locked')
        monkeypatch.setattr('core.save.os.replace',denied)
    # run() catches unexpected encoder exceptions and always emits failure.
    received=[];worker.finished.connect(lambda ok,result:received.append((ok,result)))
    worker.run()
    assert received==[(False,None)] and target.read_bytes()==b'ORIGINAL'
    assert list(tmp_path.iterdir())==[target]


def test_mp4_without_extension_uses_explicit_format(qapp,tmp_path):
    target=tmp_path/'file.tmp'
    worker=_ComposeWorker(str(target),store(),frame_end=0,output_format='mp4')
    assert worker._compose()==str(target) and inspect_mp4(target).audio==0


def test_invalid_geometry_does_not_truncate_direct_target(tmp_path):
    target=tmp_path/'direct.mp4';target.write_bytes(b'ORIGINAL')
    with pytest.raises(ValueError):export_mp4(target,store(),width=65535)
    assert target.read_bytes()==b'ORIGINAL'


def test_dialog_mp4_uses_padding_and_checks_encoder(qtbot,monkeypatch):
    dialog=GifExportDialog(store(),0,29,2,True,output_format='mp4');qtbot.addWidget(dialog)
    assert encoder_available() and dialog.export_button.isEnabled()
    assert dialog.fps.count()==1 and dialog.options()['fps']==0
    assert '82' in dialog.output.text() and '62' in dialog.output.text()
    monkeypatch.setattr('gif.mp4_export.encoder_available',lambda:False)
    dialog._update()
    assert not dialog.export_button.isEnabled() and 'H.264' in dialog.output.text()


def test_save_filter_routes_to_mp4(qapp,monkeypatch,tmp_path):
    import gif.playback_controller as module
    target=str(tmp_path/'clip')
    monkeypatch.setattr(module.QFileDialog,'getSaveFileName',lambda *args:(target,'MP4 (*.mp4)'))
    controller=PlaybackController();controller._compose_and_export=Mock()
    controller._on_save()
    controller._compose_and_export.assert_called_once_with(target+'.mp4',copy_to_clipboard=False,output_format='mp4')


def test_controller_mp4_preserves_content_coordinates_before_padding(qapp,monkeypatch,tmp_path):
    import gif.playback_controller as module
    from gif.frame_recorder import FrameData,CursorSnapshot
    controller=PlaybackController();source=store(100,33)
    controller._recorder=SimpleNamespace(store=source,frames=[FrameData(i*100,cursor=CursorSnapshot(20,10,0)) for i in range(30)])
    controller._get_trim_range=lambda:(0,9)
    dialog=Mock();dialog.DialogCode.Accepted=1;dialog.exec.return_value=1
    dialog.options.return_value={'gif_width':50,'fps':0}
    def options(*args,**kwargs):
        assert kwargs['output_format']=='mp4'
        return dialog
    monkeypatch.setattr(module,'GifExportDialog',options)
    target=tmp_path/'clip.mp4'
    def encode(**kwargs):
        assert kwargs['output_format']=='mp4' and kwargs['frame_end']==9
        assert kwargs['cursor_infos'][0][:2]==(10,5)
        target.write_bytes(b'fixture')
        return str(target)
    monkeypatch.setattr(module.ComposerProgressDialog,'run_compose',encode)
    notify=Mock();monkeypatch.setattr(module,'show_info_dialog',notify)
    controller._compose_and_export(str(target),False,output_format='mp4')
    assert '50 × 18' in notify.call_args.args[2] and '7 bytes' in notify.call_args.args[2]


def test_native_thread_cancel_destroys_worker(qtbot,tmp_path):
    import shiboken6
    target=tmp_path/'thread.mp4';target.write_bytes(b'ORIGINAL')
    dialog=ComposerProgressDialog();qtbot.addWidget(dialog)
    dialog.start(str(target),store=store(640,359,60),output_format='mp4')
    worker=dialog._worker;dialog.cancel()
    qtbot.waitUntil(lambda:dialog._finished,timeout=20000)
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    assert not shiboken6.isValid(worker) and dialog._thread is None
    assert not dialog._ok and target.read_bytes()==b'ORIGINAL'


def test_long_recording_streams_without_cumulative_timing_error(tmp_path):
    source=store(32,18,3000)
    target=tmp_path/'long.mp4'
    export_mp4(target,source,speed=2)
    with av.open(str(target)) as container:
        video=container.streams.video[0]
        assert sum(1 for _ in container.decode(video))==3000
        assert abs(float(video.duration*video.time_base)*1000-50000)<1


def test_alpha_cursor_export_is_visible_at_expected_location(tmp_path):
    source=gifrecorder.FrameStore(200,120,10);source.push_rgb(bytes((0,0,0))*(200*120),0)
    sprites={'cursor':(bytes((255,0,0,128))*400,20,20)}
    target=tmp_path/'cursor.mp4'
    export_mp4(target,source,cursor_sprites=sprites,cursor_infos=[(60,40,0,0,0,0)])
    image=inspect_mp4(target).frames[0]
    r,g,b=image.getpixel((70,50))
    assert 110<=r<=145 and g<15 and b<15
    assert max(image.getpixel((40,40)))<15


def test_diagnostics_refuses_existing_data(tmp_path):
    from gif.mp4_diagnostics import run
    sentinel=tmp_path/'keep.txt';sentinel.write_text('original')
    assert run(tmp_path)==2
    assert sentinel.read_text()=='original' and list(tmp_path.iterdir())==[sentinel]


def test_build_keeps_pyav_and_its_license_notice():
    import ast
    from pathlib import Path
    root=Path(__file__).resolve().parents[2]
    tree=ast.parse((root/'build_with_ocr_onefile.py').read_text(encoding='utf-8-sig'))
    values={}
    for node in tree.body:
        if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id in ('excludes','hidden_imports') for t in node.targets):
            values[node.targets[0].id]=ast.literal_eval(node.value)
    assert 'av' in values['hidden_imports'] and 'av' not in values['excludes']
    assert 'licenses/PyAV' in (root/'build_with_ocr_onefile.py').read_text(encoding='utf-8-sig')


def test_cancel_after_last_frame_before_commit_keeps_existing(qapp,tmp_path):
    target=tmp_path/'late.mp4';target.write_bytes(b'ORIGINAL')
    worker=_ComposeWorker(str(target),store(),output_format='mp4')
    worker.progress.connect(lambda done,total:worker.cancel() if done==total else None)
    assert worker._compose() is None and target.read_bytes()==b'ORIGINAL'
    assert list(tmp_path.iterdir())==[target]


def test_odd_padding_remains_black_when_cursor_crosses_content_edge(tmp_path):
    source=gifrecorder.FrameStore(81,61,10);source.push_rgb(bytes((0,0,0))*(81*61),0)
    sprites={'cursor':(bytes((255,255,255,255))*400,20,20)}
    target=tmp_path/'padding.mp4'
    export_mp4(target,source,cursor_sprites=sprites,cursor_infos=[(75,55,0,0,0,0)])
    image=inspect_mp4(target).frames[0]
    assert min(image.getpixel((78,58)))>180
    assert max(image.getpixel((81,61)))<45


def test_malformed_diagnostics_flag_never_falls_through_to_real_app():
    import subprocess
    import sys
    from pathlib import Path
    main=Path(__file__).resolve().parents[1]
    result=subprocess.run([sys.executable,'-B',str(main/'main_app.py'),'--verify-mp4-export'],
                          capture_output=True,timeout=10)
    assert result.returncode==2
