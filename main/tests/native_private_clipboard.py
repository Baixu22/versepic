"""Opt-in private clipboard protocol check in an isolated Windows window station.

Never use the user's interactive clipboard, even on failure. Before Qt/backend
imports, create and verify a noninteractive station and desktop. OS handles are
released on process exit; no desktop switch or visible helper window occurs.
"""
import argparse
import ctypes
from ctypes import wintypes
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
import uuid


def real_clipboard_snapshot():
    """Hash-only snapshot of the real WinSta0 clipboard; content is never persisted."""
    import win32clipboard as wc
    snapshot={'formats':[],'hashes':{}}
    deadline=time.monotonic()+5
    while True:
        try:
            wc.OpenClipboard(0);break
        except Exception:
            if time.monotonic()>deadline:raise
            time.sleep(.01)
    try:
        fmt=0
        while True:
            fmt=wc.EnumClipboardFormats(fmt)
            if not fmt:break
            snapshot['formats'].append(fmt)
        for fmt in snapshot['formats']:
            try:
                data=wc.GetClipboardData(fmt)
                raw=data if isinstance(data,(bytes,bytearray)) else (data.encode('utf-16le') if isinstance(data,str) else bytes(data))
                snapshot['hashes'][str(fmt)]={'len':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
            except Exception as error:
                snapshot['hashes'][str(fmt)]={'error':type(error).__name__}
    finally:
        wc.CloseClipboard()
    return snapshot


def isolate_clipboard():
    user=ctypes.WinDLL('user32',use_last_error=True)
    user.CreateWindowStationW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,ctypes.c_void_p]
    user.CreateWindowStationW.restype=wintypes.HANDLE
    user.SetProcessWindowStation.argtypes=[wintypes.HANDLE];user.SetProcessWindowStation.restype=wintypes.BOOL
    user.GetProcessWindowStation.restype=wintypes.HANDLE
    user.CreateDesktopW.argtypes=[wintypes.LPCWSTR,ctypes.c_void_p,ctypes.c_void_p,wintypes.DWORD,wintypes.DWORD,ctypes.c_void_p]
    user.CreateDesktopW.restype=wintypes.HANDLE
    user.SetThreadDesktop.argtypes=[wintypes.HANDLE];user.SetThreadDesktop.restype=wintypes.BOOL
    user.GetUserObjectInformationW.argtypes=[wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(wintypes.DWORD)]
    # A *named* station writes into the shared \WindowStations namespace and is
    # denied (WinError 5) on a restricted token. An *anonymous* station (NULL
    # name) still owns a private clipboard and needs no namespace permission, so
    # fall back to it instead of reporting the machine incapable of isolation.
    requested='VersePicPrivacyTest_'+uuid.uuid4().hex
    named_error=0
    ctypes.set_last_error(0)
    station=user.CreateWindowStationW(requested,0,0x37F,None)
    if station:
        mode='named'
    else:
        named_error=ctypes.get_last_error()
        ctypes.set_last_error(0)
        station=user.CreateWindowStationW(None,0,0x37F,None)
        if not station:raise ctypes.WinError(ctypes.get_last_error())
        mode='anonymous'
    if not user.SetProcessWindowStation(station):raise ctypes.WinError(ctypes.get_last_error())
    desktop=user.CreateDesktopW('PrivacyDesktop',None,None,0,0x1FF,None)
    if not desktop:raise ctypes.WinError(ctypes.get_last_error())
    if not user.SetThreadDesktop(desktop):raise ctypes.WinError(ctypes.get_last_error())
    actual=ctypes.create_unicode_buffer(256);needed=wintypes.DWORD()
    assert user.GetUserObjectInformationW(user.GetProcessWindowStation(),2,actual,ctypes.sizeof(actual),ctypes.byref(needed))
    station_name=actual.value
    assert station_name.lower()!='winsta0',station_name
    if mode=='named':assert station_name==requested
    return {'window_station':station_name,'mode':mode,'named_attempt_error':named_error,
            'distinct_from_winsta0':True,'interactive_clipboard_used':False}


def run(directory):
    isolation=isolate_clipboard()
    from PySide6.QtCore import QCoreApplication,QSettings
    from PySide6.QtGui import QImage
    app=QCoreApplication([])
    from settings import get_tool_settings_manager
    config=get_tool_settings_manager(QSettings(str(directory/'settings.ini'),QSettings.Format.IniFormat))
    assert Path(config.qsettings.fileName()).resolve()==(directory/'settings.ini').resolve()
    config.set_log_enabled(False);config.set_log_dir(str(directory/'logs'))
    config.set_clipboard_db_path(str(directory/'history.db'))
    from tests.native_image_editor import registry_digest
    registry_before=registry_digest()
    import pyclipboard
    import win32clipboard as wc
    from core.clipboard_utils import copy_image_to_clipboard,private_clipboard_supported,PRIVATE_CAPTURE_FORMAT
    assert private_clipboard_supported() and pyclipboard.PRIVATE_CAPTURE_PROTOCOL==1
    manager=pyclipboard.ClipboardManager(str(directory/'history.db'))
    callbacks=[]
    manager.start_monitor(callback=lambda item:callbacks.append(item.content))
    def wait(predicate,timeout=10):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            app.processEvents()
            if predicate():return
            time.sleep(.02)
        raise AssertionError('Native private clipboard condition timed out')
    def text(value,marker=None):
        # The Rust listener opens/closes the clipboard from its own thread. On
        # Windows a concurrent listener can tear down this thread's open
        # clipboard mid-transaction, so Empty/Set/Close may raise 1418
        # (ERROR_CLIPBOARD_NOT_OPEN). Retry the whole write a bounded number of
        # times: the assertions here are about persistence, not about winning a
        # clipboard race, and the race is itself driver-side evidence that the
        # live monitor is really running.
        deadline=time.monotonic()+10
        while True:
            try:
                wc.OpenClipboard(0)
            except Exception:
                if time.monotonic()>deadline:raise
                time.sleep(.01)
                continue
            try:
                wc.EmptyClipboard()
                if marker:wc.SetClipboardData(wc.RegisterClipboardFormat(marker),b'private')
                wc.SetClipboardData(13,value)
                return
            except Exception as error:
                code=getattr(error,'winerror',None)
                if code!=1418 or time.monotonic()>deadline:raise
                time.sleep(.01)
            finally:
                try:wc.CloseClipboard()
                except Exception:pass
    def snapshot():
        with sqlite3.connect(directory/'history.db') as db:
            counts={table:db.execute('SELECT count(*) FROM '+table).fetchone()[0] for table in ('clipboard','clipboard_formats')}
            rows=db.execute('SELECT content,thumbnail FROM clipboard ORDER BY id').fetchall()
        files={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(manager.get_images_dir()).glob('*') if p.is_file()}
        return {'counts':counts,'rows':rows,'image_files':files,'callbacks':list(callbacks)}
    checks=[]
    try:
        wait(manager.is_monitoring)
        time.sleep(.1)
        text('PUBLIC_BEFORE_PRIVATE')
        wait(lambda:'PUBLIC_BEFORE_PRIVATE' in callbacks)
        time.sleep(.2)
        baseline=snapshot()
        private=QImage(80,60,QImage.Format.Format_ARGB32);private.fill(0xffe23941)
        private.setText('Secret','SENSITIVE_METADATA_SENTINEL')
        for _ in range(4):
            copy_image_to_clipboard(private,sensitive=True)
            time.sleep(.2)
        assert snapshot()==baseline
        wc.OpenClipboard(0)
        try:
            assert wc.IsClipboardFormatAvailable(wc.RegisterClipboardFormat(PRIVATE_CAPTURE_FORMAT))
            assert wc.IsClipboardFormatAvailable(17) and not wc.IsClipboardFormatAvailable(15)
            assert wc.GetClipboardData(wc.RegisterClipboardFormat('CanIncludeInClipboardHistory'))==b'\0'*4
            png=wc.GetClipboardData(wc.RegisterClipboardFormat('PNG'))
            assert b'SENSITIVE_METADATA_SENTINEL' not in png
            image=QImage.fromData(png);assert image.size()==private.size() and image.pixelColor(0,0)==private.pixelColor(0,0)
        finally:wc.CloseClipboard()
        checks.append({'check':'private native image is pasteable but creates no DB rows, formats, thumbnail, file or callback','passed':True})
        manager.stop_monitor();manager.start_monitor(callback=lambda item:callbacks.append(item.content))
        time.sleep(.4)
        assert snapshot()==baseline
        checks.append({'check':'restarting monitor while clipboard remains private does not ingest it','passed':True})
        for marker in (PRIVATE_CAPTURE_FORMAT,'ExcludeClipboardContentFromMonitorProcessing'):
            text('SECRET_TEXT_MUST_NOT_PERSIST',marker);time.sleep(.25)
            assert snapshot()==baseline
        checks.append({'check':'both app and standard exclusion markers reject text before persistence','passed':True})
        public=QImage(80,60,QImage.Format.Format_ARGB32);public.fill(0xff278546)
        copy_image_to_clipboard(public)
        wait(lambda:len(snapshot()['image_files'])==1)
        time.sleep(.2)
        after=snapshot();assert after['counts']['clipboard']==baseline['counts']['clipboard']+1
        saved=QImage(str(next(Path(manager.get_images_dir()).glob('*.png'))));assert saved.pixelColor(0,0)==public.pixelColor(0,0)
        checks.append({'check':'next ordinary copy remains monitored and persisted normally without changing settings','passed':True})
        # Rapid mixed-format replacement exercises sequence consistency around
        # the separately opened high-level reads while the real listener stays
        # live. It is stress evidence, not a proof of every thread schedule; the
        # decision predicate also has a Rust unit check.
        for index in range(80):
            text('RACE_SECRET_SENTINEL_'+str(index),PRIVATE_CAPTURE_FORMAT)
            text('PUBLIC_RACE_'+str(index))
        text('PUBLIC_FINAL_BARRIER');wait(lambda:'PUBLIC_FINAL_BARRIER' in callbacks)
        time.sleep(.2)
        manager.stop_monitor()
        with sqlite3.connect(directory/'history.db') as db:
            rows=db.execute('SELECT content,thumbnail FROM clipboard').fetchall()
            assert all('SECRET' not in str(row) and 'SENSITIVE' not in str(row) for row in rows)
            formats=db.execute('SELECT data FROM clipboard_formats').fetchall()
            assert all(b'RACE_SECRET' not in bytes(row[0]) and 'RACE_SECRET'.encode('utf-16le') not in bytes(row[0]) for row in formats)
        for file in directory.rglob('*'):
            if file.is_file() and file.suffix in ('.db','.db-wal','.png','.log'):
                data=file.read_bytes()
                assert b'SECRET_TEXT_MUST_NOT_PERSIST' not in data and 'RACE_SECRET'.encode('utf-16le') not in data
        checks.append({'check':'rapid private/public replacement leaves no sensitive text in DB formats, images or callbacks','passed':True})
        assert all('SECRET' not in value for value in callbacks)
        assert registry_digest()==registry_before
        result={'isolation':isolation,'checks':checks,'real_registry_unchanged':True,
                'private_copy_cycles':4,'mixed_replacements':80,'final_rows':len(rows)}
        (directory/'result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
        print(json.dumps(result,indent=2))
    finally:
        manager.stop_monitor()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--run',action='store_true');parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--child',action='store_true',help=argparse.SUPPRESS)
    args=parser.parse_args()
    if not args.run:parser.error('Requires --run and a new isolated output directory')
    args.output=args.output.resolve()
    if args.child:
        # Child: switch to a private window station and run every persistence check.
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
        run(args.output)
    else:
        # Parent: stay on WinSta0 the whole time and prove the real clipboard is
        # byte-identical before and after the isolated child run.
        if args.output.exists() and any(args.output.iterdir()):parser.error('Output directory must be empty')
        args.output.mkdir(parents=True,exist_ok=True)
        before=real_clipboard_snapshot()
        (args.output/'real-clipboard-before.json').write_text(json.dumps(before,indent=2),encoding='utf-8')
        child=subprocess.run([sys.executable,str(Path(__file__).resolve()),'--run','--child','--output',str(args.output)],capture_output=True,text=True)
        (args.output/'child-stdout.log').write_text(child.stdout,encoding='utf-8')
        (args.output/'child-stderr.log').write_text(child.stderr,encoding='utf-8')
        after=real_clipboard_snapshot()
        (args.output/'real-clipboard-after.json').write_text(json.dumps(after,indent=2),encoding='utf-8')
        result_path=args.output/'result.json'
        if child.returncode!=0 or not result_path.exists():
            print(child.stdout);print(child.stderr,file=sys.stderr)
            raise SystemExit('isolated child failed with exit code %s' % child.returncode)
        result=json.loads(result_path.read_text(encoding='utf-8'))
        result['real_clipboard_unchanged']=before==after
        result['real_clipboard_before_sha256']=hashlib.sha256(json.dumps(before,sort_keys=True).encode()).hexdigest()
        result['real_clipboard_after_sha256']=hashlib.sha256(json.dumps(after,sort_keys=True).encode()).hexdigest()
        result['real_clipboard_exclusion_verified']=True
        result_path.write_text(json.dumps(result,indent=2),encoding='utf-8')
        print(json.dumps(result,indent=2))
        if not result['real_clipboard_unchanged']:raise SystemExit('real interactive clipboard changed during the isolated run')
