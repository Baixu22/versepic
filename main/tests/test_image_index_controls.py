"""Persistent index controls with real SQLite, original formats and OCR races."""
import json
from pathlib import Path
import sqlite3
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QCoreApplication, QEvent

from clipboard.core.image_text import ImageTextStore
from clipboard.core.manager import ClipboardManager
from tests.test_screen_assistant import add_image, result


@pytest.fixture
def manager(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(ClipboardManager, "_instance", None)
    value = ClipboardManager(str(tmp_path / "history.db"))
    assert value.is_available
    yield value
    indexer = value._image_indexer
    thread = indexer._thread if indexer else None
    value.release_storage()
    if thread:
        assert thread.wait(30000)
        qapp.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def claim(manager):
    item = add_image(manager)
    token = manager.image_text_store.claim(item, "image-a")
    assert token
    return item, token


def test_exclude_clears_search_not_original_image_or_paste_formats(manager):
    item, token = claim(manager)
    store = manager.image_text_store
    assert store.save(item, "image-a", result("PRIVATE_INDEX"), expected_token=token)
    manager._manager.insert_formats(item, [(50001, "HTML Format", b"<b>original</b>"), (13, "CF_UNICODETEXT", b"original")])
    raw = manager._manager.get_raw_formats(item)
    original = manager.get_image_data("image-a")
    content = manager.get_item(item).content
    assert manager.get_history(search="PRIVATE_INDEX")
    assert manager.change_image_index(item, "exclude")
    assert store.state(item)["status"] == "excluded" and store.get_result(item) is None
    assert not manager.get_history(search="PRIVATE_INDEX")
    attached = manager.get_item(item)
    assert attached.ocr_text == "" and attached.ocr_status == "excluded"
    assert attached.content == content and manager.get_image_data("image-a") == original
    assert manager._manager.get_raw_formats(item) == raw
    assert not store.save(item, "image-a", result("STALE_DIRECT"))


def test_exclusion_persists_in_new_store_and_backfill_queue(manager):
    item = add_image(manager)
    assert manager.image_text_store.change(item, "exclude")
    reopened = ImageTextStore(manager.get_db_path())
    assert reopened.state(item)["status"] == "excluded"
    assert reopened.pending() is None
    assert reopened.claim(item, "image-a") is None


@pytest.mark.parametrize("action", ["exclude", "retry", "reindex", "restore"])
def test_repeated_commands_are_idempotent(manager, action):
    item, token = claim(manager)
    store = manager.image_text_store
    if action == "retry": store.finish(item, "image-a", token, "failed", "failed")
    elif action == "reindex": store.save(item, "image-a", result(), expected_token=token)
    elif action == "restore": store.change(item, "exclude")
    assert store.change(item, action)
    state = store.state(item)
    assert not store.change(item, action) and store.state(item) == state


def test_reindex_removes_old_search_text_and_rejects_old_token(manager):
    item, old_token = claim(manager)
    store = manager.image_text_store
    assert store.save(item, "image-a", result("OLD"), expected_token=old_token)
    assert store.change(item, "reindex") and not manager.search("OLD")
    fresh_token = store.claim(item, "image-a")
    assert fresh_token and fresh_token != old_token
    assert not store.save(item, "image-a", result("LATE"), expected_token=old_token)
    assert store.save(item, "image-a", result("NEW"), expected_token=fresh_token)
    assert [r.id for r in manager.search("NEW")] == [item]


def test_exclude_then_restore_cannot_resurrect_inflight_result(manager):
    item, token = claim(manager)
    store = manager.image_text_store
    assert store.change(item, "exclude") and store.change(item, "restore")
    assert store.state(item)["status"] == "pending"
    assert not store.save(item, "image-a", result("LATE"), expected_token=token)
    assert not store.finish(item, "image-a", token, "failed", "failed")
    new = store.claim(item, "image-a")
    assert store.save(item, "image-a", result("CURRENT"), expected_token=new)


@pytest.mark.parametrize("status", ["failed", "done", "no_text", "excluded"])
def test_terminal_states_do_not_auto_retry_after_restart(manager, status):
    item, token = claim(manager)
    store = manager.image_text_store
    if status == "failed": store.finish(item, "image-a", token, "failed", "invalid_image")
    elif status == "excluded": store.change(item, "exclude")
    else: store.save(item, "image-a", result("indexed") if status == "done" else {"code":100,"data":[]}, expected_token=token)
    reopened = ImageTextStore(manager.get_db_path())
    assert reopened.state(item)["status"] == status and reopened.pending() is None


def test_worker_stop_requeues_and_invalidates_current_token(manager):
    item, token = claim(manager)
    from clipboard.core.image_text import ImageTextIndexer
    indexer = ImageTextIndexer(manager)
    # Init recovers the interrupted claim from before this indexer instance.
    assert manager.image_text_store.state(item)["status"] == "pending"
    assert not manager.image_text_store.save(item,"image-a",result("OLD"),expected_token=token)
    new = manager.image_text_store.claim(item,"image-a")
    indexer._current = (item,"image-a",new)
    indexer.stop()
    assert manager.image_text_store.state(item)["status"] == "pending"
    assert not manager.image_text_store.save(item,"image-a",result("LATE"),expected_token=new)


def test_old_database_index_migrates_without_reinterpreting_images(manager):
    item = add_image(manager)
    path = manager.get_db_path()
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO image_text VALUES (?,?,?,?)", (item,"image-a","LEGACY",json.dumps(result("LEGACY"))))
        db.execute("DROP TABLE image_text_state")
    store = ImageTextStore(path)
    assert store.state(item)["status"] == "done" and store.get_result(item) == result("LEGACY")
    assert store.pending() is None


@pytest.mark.parametrize("change", ["delete", "image", "type"])
def test_removed_or_replaced_source_rejects_all_late_results(manager, change):
    item, token = claim(manager)
    store = manager.image_text_store
    if change == "delete": manager.delete_item(item)
    else:
        with store.connect() as db:
            if change == "image": db.execute("UPDATE clipboard SET image_id='replacement' WHERE id=?", (item,))
            else: db.execute("UPDATE clipboard SET content_type='text' WHERE id=?", (item,))
    assert not store.save(item,"image-a",result("LATE"),expected_token=token)
    assert not store.finish(item,"image-a",token,"failed","failed")
    with store.connect() as db:
        assert db.execute('SELECT count(*) FROM image_text_state').fetchone()[0] == 0
        assert db.execute('SELECT count(*) FROM image_text').fetchone()[0] == 0


def test_delete_and_reused_id_still_rejects_original_token(manager):
    item, token = claim(manager)
    store = manager.image_text_store
    manager.delete_item(item)
    replacement = manager.add_item("replacement", "image")
    with store.connect() as db:
        db.execute("UPDATE clipboard SET id=?, image_id=? WHERE id=?", (item, "image-a", replacement))
    assert not store.save(item,'image-a',result('OLD'),expected_token=token)


def test_excluded_item_stays_excluded_after_database_move(manager,tmp_path):
    item = add_image(manager)
    store = manager.image_text_store;store.change(item,'exclude')
    path = Path(manager.get_db_path());manager.release_storage()
    moved = tmp_path/'moved.db';path.rename(moved)
    assert manager.reset_storage(str(moved))
    assert manager.get_item(item).ocr_status == 'excluded'
    with pytest.raises(sqlite3.OperationalError):store.save(item,'image-a',result())
    assert not path.exists()


def test_failed_state_stores_only_safe_reason_not_engine_payload(manager,monkeypatch,qtbot):
    item = add_image(manager)
    monkeypatch.setattr('ocr.is_ocr_available',lambda:True)
    monkeypatch.setattr('ocr.recognize_text',lambda *a,**k:{'code':500,'message':'SECRET_ENGINE_PAYLOAD','data':[]})
    indexer = manager.start_image_indexing();indexer._next()
    qtbot.waitUntil(lambda:indexer._thread is None)
    state = manager.image_text_store.state(item)
    assert state['status']=='failed' and state['error']=='failed'
    with manager.image_text_store.connect() as db:
        assert 'SECRET_ENGINE_PAYLOAD' not in str(db.execute('SELECT * FROM image_text_state').fetchall())
    assert not manager.get_item(item).ocr_text


def test_unavailable_engine_failure_is_visible_and_explicitly_retryable(manager,monkeypatch,qtbot):
    item = add_image(manager)
    monkeypatch.setattr('ocr.is_ocr_available',lambda:False)
    indexer=manager.start_image_indexing();indexer._next()
    assert manager.get_item(item).ocr_status=='failed' and manager.get_item(item).ocr_error=='unavailable'
    assert manager.image_text_store.pending() is None
    monkeypatch.setattr('ocr.is_ocr_available',lambda:True)
    monkeypatch.setattr('ocr.recognize_text',lambda *a,**k:result('RETRIED'))
    assert manager.change_image_index(item,'retry')
    indexer._next();qtbot.waitUntil(lambda:indexer._thread is None)
    assert manager.get_item(item).ocr_status=='done' and manager.search('RETRIED')


def test_missing_image_fails_once_until_explicit_retry(manager):
    item=add_image(manager);Path(manager.get_images_dir(),'image-a.png').unlink()
    indexer=manager.start_image_indexing();indexer._next()
    assert manager.get_item(item).ocr_status=='failed' and manager.get_item(item).ocr_error=='invalid_image'
    indexer._next();assert indexer._thread is None and not indexer.busy


def test_real_thread_late_result_after_exclude_restore_cannot_write(manager,monkeypatch,qtbot):
    item=add_image(manager);started=threading.Event();release=threading.Event()
    monkeypatch.setattr('ocr.is_ocr_available',lambda:True)
    def recognize(*args,**kwargs):
        started.set();assert release.wait(10);return result('LATE_PRIVATE')
    monkeypatch.setattr('ocr.recognize_text',recognize)
    indexer=manager.start_image_indexing();indexer._next()
    qtbot.waitUntil(started.is_set)
    old=indexer._current
    try:
        assert manager.change_image_index(item,'exclude')
        assert manager.change_image_index(item,'restore')
        # Even an already queued details signal with the old token is rejected.
        indexer._recognized(result('LATE_PRIVATE'),'')
        assert manager.image_text_store.get_result(item) is None
    finally:release.set()
    qtbot.waitUntil(lambda:indexer._thread is None)
    indexer._timer.stop()
    assert manager.get_item(item).ocr_status=='pending' and not manager.search('LATE_PRIVATE')
    assert not manager.image_text_store.save(item,'image-a',result('LATE_PRIVATE'),expected_token=old[2])


def test_excluding_does_not_start_background_worker(manager):
    item=add_image(manager)
    assert manager._image_indexer is None
    assert manager.change_image_index(item,'exclude') and manager._image_indexer is None


def test_no_text_completion_is_not_an_infinite_retry(manager,monkeypatch,qtbot):
    item=add_image(manager);recognize=Mock(return_value={'code':100,'data':[]})
    monkeypatch.setattr('ocr.is_ocr_available',lambda:True);monkeypatch.setattr('ocr.recognize_text',recognize)
    indexer=manager.start_image_indexing();indexer._next();qtbot.waitUntil(lambda:indexer._thread is None)
    assert manager.get_item(item).ocr_status=='no_text'
    indexer._next();assert recognize.call_count==1


@pytest.mark.parametrize('state,keys', [
 ('excluded',['image_index_restore']), ('failed',['image_index_retry','image_index_reindex','image_index_exclude']),
 ('recognizing',['image_index_exclude']), ('pending',['image_index_exclude']),
 ('done',['image_index_reindex','image_index_exclude']), ('no_text',['image_index_reindex','image_index_exclude'])])
def test_context_menu_actions_follow_actual_state(state,keys):
    from clipboard.core import ClipboardItem
    from clipboard.controllers.context_menu_controller import _build_image_index_children
    item=ClipboardItem(id=1,content='image',content_type='image',ocr_status=state)
    actions=_build_image_index_children(SimpleNamespace(clipboard_item=item))
    assert actions[0].enabled is False
    assert [a.key for a in actions if a.enabled and not a.is_separator]==keys


def test_waiting_to_recognizing_to_done_emits_item_state_without_false_completion(manager,monkeypatch,qtbot):
    item=add_image(manager)
    monkeypatch.setattr('ocr.is_ocr_available',lambda:True);monkeypatch.setattr('ocr.recognize_text',lambda *a,**k:result('OK'))
    indexer=manager.start_image_indexing();states=[];done=[]
    indexer.item_state_changed.connect(lambda i:states.append(manager.get_item(i).ocr_status));indexer.updated.connect(done.append)
    indexer._next();qtbot.waitUntil(lambda:indexer._thread is None)
    assert states==['recognizing','done'] and done==[item]


def test_search_offsets_filters_and_original_formats_stable_after_exclusion(manager):
    ids=[]
    for i in range(8):
        item=manager.add_item(f'image {i}','image')
        with manager.image_text_store.connect() as db:db.execute('UPDATE clipboard SET image_id=? WHERE id=?',(f'p{i}',item))
        assert manager.image_text_store.save(item,f'p{i}',result('COMMON'))
        ids.append(item)
    manager.toggle_pin(ids[2]);before=[r.id for r in manager.get_history(search='COMMON',limit=100)]
    manager.image_text_store.change(ids[4],'exclude')
    expected=[i for i in before if i!=ids[4]]
    actual=[r.id for start in range(0,8,3) for r in manager.get_history(search='COMMON',offset=start,limit=3)]
    assert actual==expected and len(set(actual))==7
    assert len(manager.get_history(limit=100))==8


def test_index_state_refresh_updates_row_without_reloading_or_changing_selection(qapp,manager):
    from PySide6.QtWidgets import QListWidget,QListWidgetItem
    from clipboard.ui.windows.clipboard_window import ClipboardWindow
    from clipboard.ui.widgets.item_delegate import ROLE_ITEM_ID,ROLE_ITEM_DATA
    item=add_image(manager);old=manager.get_item(item);listing=QListWidget()
    entry=QListWidgetItem();entry.setData(ROLE_ITEM_ID,item);entry.setData(ROLE_ITEM_DATA,old);listing.addItem(entry);listing.setCurrentRow(0)
    owner=SimpleNamespace(manager=manager,controller=SimpleNamespace(current_items=[old]),list_widget=listing,tr=lambda text:text)
    manager.image_text_store.change(item,'exclude')
    ClipboardWindow._on_image_index_state(owner,item)
    assert listing.currentRow()==0 and listing.item(0) is entry and listing.count()==1
    assert entry.data(ROLE_ITEM_DATA).ocr_status=='excluded' and 'excluded' in entry.toolTip()
    assert owner.controller.current_items[0].ocr_status=='excluded'
    listing.deleteLater()


@pytest.mark.parametrize('action',['exclude','restore','retry','reindex'])
def test_non_image_or_missing_item_is_noop(manager,action):
    item=manager.add_item('text')
    assert not manager.image_text_store.change(item,action)
    assert not manager.image_text_store.change(9999,action)
    with manager.image_text_store.connect() as db:assert db.execute('SELECT count(*) FROM image_text_state').fetchone()[0]==0


def test_database_locked_control_does_not_partially_remove_index(manager):
    item=add_image(manager);store=manager.image_text_store;store.save(item,'image-a',result('KEEP'))
    with sqlite3.connect(store.path) as lock:
        lock.execute('BEGIN IMMEDIATE')
        with pytest.raises(sqlite3.OperationalError):store.change(item,'exclude')
        lock.rollback()
    assert store.get_result(item)==result('KEEP') and store.state(item)['status']=='done'


def test_excluded_item_cannot_be_retried_or_reindexed_without_restore(manager):
    item=add_image(manager);store=manager.image_text_store;store.change(item,'exclude')
    before=store.state(item)
    for action in ('retry','reindex'):
        assert not store.change(item,action) and store.state(item)==before


def test_manager_move_cancels_real_running_job_and_does_not_recreate_old_path(manager,monkeypatch,qtbot,tmp_path):
    item=add_image(manager);started=threading.Event();release=threading.Event()
    monkeypatch.setattr('ocr.is_ocr_available',lambda:True)
    def recognize(*a,**kw):
        started.set();assert release.wait(10);return result('DELETED_GENERATION')
    monkeypatch.setattr('ocr.recognize_text',recognize)
    indexer=manager.start_image_indexing();indexer._next();qtbot.waitUntil(started.is_set)
    old_store=indexer.store;old_path=Path(old_store.path);job=indexer._current
    try:
        manager.release_storage()
        moved=tmp_path/'relocated.db';old_path.rename(moved)
        assert manager.reset_storage(str(moved))
        indexer._recognized(result('DELETED_GENERATION'),'')
    finally:release.set()
    qtbot.waitUntil(lambda:indexer._thread is None)
    assert not old_path.exists() and not manager.search('DELETED_GENERATION')
    assert manager.image_text_store.state(item)['status']=='pending'
    assert not manager.image_text_store.save(item,'image-a',result('DELETED_GENERATION'),expected_token=job[2])


def test_two_store_connections_serialize_exclusion_and_stale_write(manager):
    item,token=claim(manager);other=ImageTextStore(manager.get_db_path())
    assert other.change(item,'exclude')
    assert not manager.image_text_store.save(item,'image-a',result('LATE'),expected_token=token)
    assert other.get_result(item) is None


@pytest.mark.parametrize('language',['en','zh','ja','ko'])
def test_index_status_and_action_translations_are_compiled(language):
    from PySide6.QtCore import QTranslator
    from clipboard.core.image_text import INDEX_LABELS,INDEX_ERRORS
    translator=QTranslator()
    main=Path(__file__).resolve().parents[1]
    assert translator.load(str(main/'translations'/f'app_{language}.qm'))
    for text in [*INDEX_LABELS.values(),*INDEX_ERRORS.values(),'Image text index','Restore image text indexing',
                 'Retry failed OCR','Recognize image text again','Exclude image from text index']:
        assert translator.translate('ClipboardWindow',text),(language,text)


def test_exclusion_cancel_does_not_call_manager(qapp):
    from clipboard.ui.windows.clipboard_window import ClipboardWindow
    from unittest.mock import patch
    owner=SimpleNamespace(manager=Mock(),tr=lambda text:text)
    with patch('ui.dialogs.show_confirm_dialog',return_value=False):
        ClipboardWindow._change_image_index(owner,10,'exclude')
    owner.manager.change_image_index.assert_not_called()


def test_new_indexer_recovers_interrupted_but_never_excluded_or_failed(manager,monkeypatch):
    item,token=claim(manager)
    other=manager.add_item('second','image')
    with manager.image_text_store.connect() as db:db.execute('UPDATE clipboard SET image_id=? WHERE id=?',('b',other))
    manager.image_text_store.change(other,'exclude')
    indexer=manager.start_image_indexing();indexer._timer.stop()
    assert manager.image_text_store.state(item)['status']=='pending'
    assert manager.image_text_store.state(item)['error']=='interrupted'
    assert manager.image_text_store.state(other)['status']=='excluded'
    assert not manager.image_text_store.save(item,'image-a',result('OLD'),expected_token=token)
