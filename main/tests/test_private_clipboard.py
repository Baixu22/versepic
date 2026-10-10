"""Private-copy primitives must fail closed without touching the real clipboard."""
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtGui import QImage

from core import clipboard_utils as module


def image():
    value=QImage(16,12,QImage.Format.Format_ARGB32);value.fill(0xff123456);return value


@pytest.fixture
def fake_clipboard(monkeypatch):
    events=[];formats={};payloads={}
    def register(name):
        formats.setdefault(name,50000+len(formats));return formats[name]
    def set_data(fmt,data):
        events.append(('set',fmt));payloads[fmt]=data
    fake=SimpleNamespace(RegisterClipboardFormat=register,OpenClipboard=lambda _:events.append(('open',)),
        CloseClipboard=lambda:events.append(('close',)),EmptyClipboard=lambda:events.append(('empty',)),
        SetClipboardData=set_data)
    monkeypatch.setitem(sys.modules,'win32clipboard',fake)
    monkeypatch.setattr(module,'private_clipboard_supported',lambda:True)
    return fake,events,formats,payloads


def test_sensitive_markers_are_written_before_pixels_in_one_transaction(fake_clipboard):
    _,events,formats,payloads=fake_clipboard
    source=image();source.setText('Secret','never encode this metadata')
    module.copy_image_to_clipboard(source,sensitive=True)
    assert events[0]==('open',) and events[1]==('empty',) and events[-1]==('close',)
    writes=[e[1] for e in events if e[0]=='set']
    names=[module.PRIVATE_CAPTURE_FORMAT,'ExcludeClipboardContentFromMonitorProcessing',
           'CanIncludeInClipboardHistory','CanUploadToCloudClipboard']
    assert writes==[formats[n] for n in names]+[formats['PNG'],17]
    assert payloads[formats[names[2]]]==b'\0'*4 and payloads[formats[names[3]]]==b'\0'*4
    assert 15 not in writes
    decoded=QImage.fromData(payloads[formats['PNG']]);assert not decoded.isNull()
    assert decoded.pixelColor(0,0)==source.pixelColor(0,0)


@pytest.mark.parametrize('failure_index',[0,1,2,3])
def test_failed_marker_write_never_publishes_pixels_or_falls_back(fake_clipboard,monkeypatch,failure_index):
    fake,events,formats,_=fake_clipboard
    calls=[]
    def fail(fmt,data):
        calls.append(fmt)
        if len(calls)==failure_index+1:raise RuntimeError('marker failure')
    fake.SetClipboardData=fail
    fallback=Mock();monkeypatch.setattr(module,'_copy_qt_fallback',fallback)
    with pytest.raises(RuntimeError):module.copy_image_to_clipboard(image(),sensitive=True)
    assert 17 not in calls and formats['PNG'] not in calls
    assert events[-1]==('close',)
    fallback.assert_not_called()


def test_missing_registration_aborts_before_emptying_clipboard(fake_clipboard):
    fake,events,_,_=fake_clipboard
    fake.RegisterClipboardFormat=lambda name:50000 if name=='PNG' else 0
    with pytest.raises(RuntimeError):module.copy_image_to_clipboard(image(),sensitive=True)
    assert not events


def test_no_private_protocol_never_changes_clipboard(fake_clipboard,monkeypatch):
    _,events,_,_=fake_clipboard
    monkeypatch.setattr(module,'private_clipboard_supported',lambda:False)
    with pytest.raises(RuntimeError):module.copy_image_to_clipboard(image(),sensitive=True)
    assert events==[]


def test_private_file_reference_rejected_before_any_write(fake_clipboard):
    _,events,_,_=fake_clipboard
    with pytest.raises(ValueError):module.copy_image_to_clipboard(image(),'private.png',sensitive=True)
    assert events==[]


def test_private_native_failure_never_degrades_to_public_qt(fake_clipboard,monkeypatch):
    fake,events,_,_=fake_clipboard
    fake.OpenClipboard=Mock(side_effect=OSError('denied'))
    fallback=Mock();monkeypatch.setattr(module,'_copy_qt_fallback',fallback)
    with pytest.raises(OSError):module.copy_image_to_clipboard(image(),sensitive=True)
    fallback.assert_not_called();assert events==[]


def test_public_copy_does_not_emit_privacy_markers(fake_clipboard):
    _,events,formats,_=fake_clipboard
    module._copy_win32_legacy(image(),None)
    assert set(formats)=={'PNG'}
    assert [e[1] for e in events if e[0]=='set']==[formats['PNG'],17]


@pytest.mark.parametrize('protocol',[None,0,2,True,'1'])
def test_capability_is_exact_protocol_version(monkeypatch,protocol):
    monkeypatch.setitem(sys.modules,'pyclipboard',SimpleNamespace(PRIVATE_CAPTURE_PROTOCOL=protocol))
    assert not module.private_clipboard_supported()


def test_no_metadata_in_private_png(fake_clipboard,monkeypatch):
    monkeypatch.setitem(sys.modules,'pyclipboard',SimpleNamespace(PRIVATE_CAPTURE_PROTOCOL=1))
    # Guard implementation tested separately from fake_clipboard's injected guard.
    source=image();source.setText('Private','not for clipboard history')
    module.copy_image_to_clipboard(source,sensitive=True)
    _,_,formats,payloads=fake_clipboard
    assert b'not for clipboard history' not in payloads[formats['PNG']]


def test_sensitive_delivery_does_not_even_read_save_settings_or_reserve_file(monkeypatch):
    service=Mock();copied=Mock();source=image()
    monkeypatch.setattr(module,'copy_image_to_clipboard',copied)
    assert module.deliver_image_async(source,sensitive=True,save_service=service,
        save_kwargs={'directory':'unused'},write_file_reference=True) is None
    copied.assert_called_once_with(source,sensitive=True)
    assert service.mock_calls==[]


def test_sensitive_delivery_without_explicit_copy_is_a_noop(monkeypatch):
    service=Mock();copied=Mock();monkeypatch.setattr(module,'copy_image_to_clipboard',copied)
    assert module.deliver_image_async(image(),sensitive=True,copy_to_clipboard=False,save_service=service) is None
    copied.assert_not_called();assert service.mock_calls==[]


def test_private_delivery_does_not_persist_into_next_ordinary_call(monkeypatch):
    copied=Mock();monkeypatch.setattr(module,'copy_image_to_clipboard',copied)
    source=image()
    module.deliver_image_async(source,sensitive=True)
    module.deliver_image_async(source)
    assert copied.call_args_list[0].kwargs=={'sensitive':True}
    assert copied.call_args_list[1].kwargs=={'file_reference':None}


def test_sensitive_delivery_failure_is_not_reported_as_success(monkeypatch):
    copied=Mock(side_effect=RuntimeError('private protocol unavailable'))
    monkeypatch.setattr(module,'copy_image_to_clipboard',copied)
    with pytest.raises(RuntimeError):module.deliver_image_async(image(),sensitive=True)


def test_actual_installed_private_protocol_is_supported():
    import pyclipboard
    assert type(pyclipboard.PRIVATE_CAPTURE_PROTOCOL) is int and pyclipboard.PRIVATE_CAPTURE_PROTOCOL==1
    assert module.private_clipboard_supported()
