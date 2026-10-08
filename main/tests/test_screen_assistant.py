"""Exercise local OCR actions, real storage/search, and flattened redaction output."""

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import Qt, QRect, QRectF
from PySide6.QtGui import QColor, QImage

from clipboard.core.manager import ClipboardManager
from clipboard.core.image_text import ImageTextStore
from text_recognition.result_window import TextRecognitionWindow
from text_recognition.redaction import redact_image, sensitive_lines
from text_recognition.redaction_window import RedactionWindow


def result(text="Contact demo@example.com", box=None):
    return {"code": 100, "data": [{"text": text, "box": box or [[10, 10], [150, 10], [150, 35], [10, 35]]}]}


def white_image():
    image = QImage(240, 100, QImage.Format.Format_ARGB32)
    image.fill(QColor("white"))
    return image


@pytest.fixture
def manager(tmp_path, monkeypatch):
    monkeypatch.setattr(ClipboardManager, "_instance", None)
    manager = ClipboardManager(str(tmp_path / "clipboard.db"))
    assert manager.is_available, "Tests require the installed pyclipboard backend"
    yield manager
    manager.release_storage()


def add_image(manager, image_id="image-a"):
    item_id = manager.add_item("[240x100]", "image")
    with manager.image_text_store.connect() as db:
        db.execute("UPDATE clipboard SET image_id=? WHERE id=?", (image_id, item_id))
    path = Path(manager.get_images_dir()) / f"{image_id}.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    assert white_image().save(str(path))
    return item_id


def finish(qapp, thread):
    assert thread.wait(30000)
    qapp.processEvents()


def test_ocr_actions_edit_current_text_and_can_be_undone(qapp):
    window = TextRecognitionWindow(white_image(), initial_result=result("first  line\nsecond"))
    window.action_buttons["merge"].click()
    assert window.text_edit.toPlainText() == "first  line second"
    window.text_edit.undo()
    assert window.text_edit.toPlainText() == "first  line\nsecond"
    window.action_buttons["clean"].click()
    assert window.text_edit.toPlainText() == "first line\nsecond"
    window.action_buttons["restore"].click()
    assert window.text_edit.toPlainText() == "first  line\nsecond"
    window.close()


def test_ocr_save_and_translation_use_edited_text(qapp, manager, monkeypatch):
    from translation import TranslationManager
    fake = MagicMock()
    monkeypatch.setattr(TranslationManager, "instance", lambda: fake)
    group = manager.create_group("Research")
    window = TextRecognitionWindow(white_image(), initial_result=result("old"))
    window.text_edit.setPlainText("Corrected 中文")
    window._translate()
    assert fake.translate.call_args.kwargs["text"] == "Corrected 中文"
    window._save_to_group(group)
    assert manager.get_by_group(group)[0].content == "Corrected 中文"
    window.close()


def test_cached_ocr_highlights_search_and_exports_utf8(qapp, tmp_path, monkeypatch):
    from text_recognition import result_window
    path = tmp_path / "text.txt"
    monkeypatch.setattr(result_window.QFileDialog, "getSaveFileName", lambda *args: (str(path), ""))
    window = TextRecognitionWindow(white_image(), initial_result=result("查找 ERROR-42"), query="ERROR-42")
    assert window._thread is None
    assert window.text_edit.textCursor().selectedText() == "ERROR-42"
    window._save_file()
    assert path.read_text(encoding="utf-8") == "查找 ERROR-42"
    window.close()


def test_web_search_encodes_image_text_as_query_not_url(qapp, monkeypatch):
    from urllib.parse import parse_qs, urlsplit
    from text_recognition import result_window
    opened = []
    monkeypatch.setattr(result_window.QDesktopServices, "openUrl", opened.append)
    text = "C++ & url=file:///private #中文"
    window = TextRecognitionWindow(white_image(), initial_result=result(text))
    window._search_web()
    url = urlsplit(opened[0].toString())
    assert (url.scheme, url.netloc, url.path) == ("https", "www.bing.com", "/search")
    assert parse_qs(url.query) == {"q": [text]}
    window.close()


def test_index_search_paginates_filters_and_preserves_image(manager):
    item_id = add_image(manager)
    store = manager.image_text_store
    before = manager.get_image_data("image-a")
    assert store.save(item_id, "image-a", result("费用 ERROR-42"))
    text_id = manager.add_item("ERROR-42 text")
    manager.toggle_pin(item_id)
    assert [i.id for i in manager.get_history(search="ERROR-42", limit=1)] == [item_id]
    assert [i.id for i in manager.get_history(search="ERROR-42", offset=1)] == [text_id]
    assert [i.id for i in manager.get_history(search="费用", content_type="image")] == [item_id]
    assert not manager.get_history(search="费用", content_type="text")
    timestamp = int(manager.get_item(item_id).created_at.timestamp())
    assert not manager.get_history(search="费用", end_time=timestamp)
    assert manager.get_history(search="费用", start_time=timestamp)
    assert manager.get_item(item_id).content == "[240x100]"
    assert manager.get_image_data("image-a") == before
    assert manager.get_item(item_id).ocr_text == "费用 ERROR-42"
    # An independent connection sees the index after restart; it isn't an in-memory cache.
    assert ImageTextStore(manager.get_db_path()).get_result(item_id) == result("费用 ERROR-42")


def test_index_cascades_deletes_and_rejects_stale_results(manager):
    item_id = add_image(manager)
    store = manager.image_text_store
    assert not store.save(item_id, "wrong-image", result())
    assert store.save(item_id, "image-a", result())
    manager.delete_item(item_id)
    assert not store.save(item_id, "image-a", result())
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM image_text").fetchone()[0] == 0


def test_failed_ocr_is_retryable_but_blank_images_are_indexed_once(manager):
    item_id = add_image(manager)
    store = manager.image_text_store
    assert not store.save(item_id, "image-a", {"code": 500, "data": []})
    assert store.pending(set()) == (item_id, "image-a")
    assert store.save(item_id, "image-a", {"code": 100, "data": []})
    assert store.pending(set()) is None


def test_index_follows_storage_move_without_recreating_old_database(manager, tmp_path):
    item_id = add_image(manager)
    store = manager.image_text_store
    assert store.save(item_id, "image-a", result())
    old_path = Path(manager.get_db_path())
    manager.release_storage()
    moved = tmp_path / "moved.db"
    old_path.rename(moved)
    assert manager.reset_storage(str(moved))
    assert manager.get_history(search="example.com")[0].id == item_id
    with pytest.raises(sqlite3.OperationalError):
        store.save(item_id, "image-a", result())
    assert not old_path.exists()


def test_background_indexer_processes_older_images_and_finishes(qapp, manager, monkeypatch):
    monkeypatch.setattr("ocr.is_ocr_available", lambda: True)
    monkeypatch.setattr("ocr.recognize_text", lambda *args, **kwargs: result("BACKFILL"))
    item_id = add_image(manager)
    indexer = manager.start_image_indexing()
    changed = []
    indexer.updated.connect(changed.append)
    indexer._next()
    finish(qapp, indexer._thread)
    assert changed == [item_id]
    assert manager.search("BACKFILL")[0].id == item_id
    indexer._next()
    assert indexer._thread is None


def test_cancelled_indexer_cannot_write_after_storage_release(qapp, manager, monkeypatch):
    import time
    monkeypatch.setattr("ocr.is_ocr_available", lambda: True)
    def recognize(*args, **kwargs):
        time.sleep(.1)
        return result("LATE")
    monkeypatch.setattr("ocr.recognize_text", recognize)
    add_image(manager)
    store = manager.image_text_store
    indexer = manager.start_image_indexing()
    indexer._next()
    thread = indexer._thread
    manager.release_storage()
    finish(qapp, thread)
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM image_text").fetchone()[0] == 0


@pytest.mark.parametrize("text", ["138 1234 5678", "+86 13812345678", "demo@example.com", "secret ABC"])
def test_redaction_matches_phone_email_and_custom_keywords(text):
    matches = sensitive_lines(result(text), white_image().rect(), keywords=["ABC"])
    assert len(matches) == 1
    assert matches[0][1].contains(QRect(10, 10, 140, 25))


def test_redaction_rejects_bad_boxes_and_covers_opaque_pixels(tmp_path):
    assert not sensitive_lines(result(box=[[float("nan"), 0]] * 4), white_image().rect())
    assert not sensitive_lines(result("Ordinary text"), white_image().rect())
    image = white_image()
    image.setDevicePixelRatio(2)
    image.setText("Description", "private original")
    output = redact_image(image, [QRectF(10.2, 10.2, 30.5, 20.5)])
    assert output.devicePixelRatio() == 1
    assert not output.textKeys()
    assert output.pixelColor(10, 10) == QColor("black")
    assert output.pixelColor(40, 30) == QColor("black")
    assert output.pixelColor(41, 31) == QColor("white")
    path = tmp_path / "redacted.png"
    assert output.save(str(path))
    assert QImage(str(path)).pixelColor(20, 20) == QColor("black")
    assert image.pixelColor(20, 20) == QColor("white")


def test_redaction_window_review_manual_area_and_copy(qapp, monkeypatch):
    monkeypatch.setattr("ocr.is_ocr_available", lambda: True)
    monkeypatch.setattr("ocr.recognize_text", lambda *args, **kwargs: result())
    copies = []
    monkeypatch.setattr("core.clipboard_utils.copy_image_to_clipboard", copies.append)
    window = RedactionWindow(white_image())
    finish(qapp, window._thread)
    assert window.candidates.count() == 1
    window.candidates.item(0).setCheckState(Qt.CheckState.Unchecked)
    assert not window.copy_button.isEnabled()
    window.keywords.setText("No match")
    assert window.candidates.item(0).checkState() == Qt.CheckState.Unchecked
    window._add_manual(QRect(180, 20, 20, 20))
    window.copy_button.click()
    assert copies[0].pixelColor(185, 25) == QColor("black")
    assert copies[0].pixelColor(15, 15) == QColor("white")
    window.close()


def test_capture_redaction_keeps_existing_annotations(qapp, monkeypatch):
    from tools.action import ActionTools
    tools = ActionTools.__new__(ActionTools)
    tools.scene = MagicMock()
    tools.scene.selection_model.is_confirmed = True
    tools.scene.selection_model.rect.return_value = QRectF(0, 0, 240, 100)
    tools.export_service = MagicMock()
    image = white_image()
    tools.export_service.export.return_value = image
    tools._remember_last_region = MagicMock()
    tools._cleanup_and_close = MagicMock()
    shown = []
    monkeypatch.setattr("text_recognition.redaction_window.show_redaction", shown.append)
    tools.handle_smart_redact()
    assert shown == [image]
    tools.export_service.export_base_image_only.assert_not_called()
    tools._cleanup_and_close.assert_called_once()
