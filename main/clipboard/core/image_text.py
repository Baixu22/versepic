"""Local OCR metadata in the clipboard database; original images/formats stay intact."""

import json
import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QImage

from core.logger import log_warning


class ImageTextStore:
    def __init__(self, db_path):
        self.path = str(db_path)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS image_text (
                    item_id INTEGER PRIMARY KEY, image_id TEXT NOT NULL,
                    text TEXT NOT NULL, result TEXT NOT NULL
                );
                CREATE TRIGGER IF NOT EXISTS image_text_delete
                AFTER DELETE ON clipboard BEGIN
                    DELETE FROM image_text WHERE item_id = OLD.id;
                END;
            """)

    @contextmanager
    def connect(self):
        # mode=rw prevents a late callback from recreating a moved/deleted database.
        uri = Path(self.path).resolve().as_uri() + "?mode=rw"
        with closing(sqlite3.connect(uri, uri=True, timeout=1.0)) as db, db:
            yield db

    def save(self, item_id, image_id, result):
        from ocr import format_ocr_result_text
        if not isinstance(result, dict) or result.get("code") != 100:
            return False
        text = format_ocr_result_text(result).strip()
        with self.connect() as db:
            cursor = db.execute("""
                INSERT OR REPLACE INTO image_text (item_id, image_id, text, result)
                SELECT id, image_id, ?, ? FROM clipboard
                WHERE id = ? AND image_id = ? AND content_type = 'image'
            """, (text, json.dumps(result, ensure_ascii=False), item_id, image_id))
            return cursor.rowcount == 1

    def get_result(self, item_id):
        with self.connect() as db:
            row = db.execute("""
                SELECT o.result FROM image_text o JOIN clipboard c
                ON c.id = o.item_id AND c.image_id = o.image_id
                WHERE c.id = ? AND c.content_type = 'image'
            """, (item_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def attach(self, items):
        ids = [item.id for item in items if item.content_type == "image"]
        if not ids:
            return
        with self.connect() as db:
            rows = db.execute(f"""
                SELECT c.id, o.text FROM clipboard c JOIN image_text o
                ON c.id = o.item_id AND c.image_id = o.image_id
                WHERE c.id IN ({','.join('?' for _ in ids)})
            """, ids).fetchall()
        texts = dict(rows)
        for item in items:
            item.ocr_text = texts.get(item.id, "")

    def search_ids(self, search, offset=0, limit=50, content_type=None, start_time=None, end_time=None,
                   sort_order="default"):
        # ponytail: LIKE matches existing search semantics; add FTS when library size warrants it.
        where = ["(c.content LIKE ? OR c.title LIKE ? OR o.text LIKE ?)"] if search else ["1=1"]
        params = [f"%{search}%"] * 3 if search else []
        order = {
            "default": "c.item_order DESC, c.id DESC",
            "newest": "c.created_at DESC, c.id DESC",
            "oldest": "c.created_at ASC, c.id ASC",
            "frequent": "c.paste_count DESC, c.created_at DESC, c.id DESC",
        }[sort_order]
        for clause, value in (("c.content_type = ?", content_type if content_type != "all" else None),
                              ("c.created_at >= ?", start_time), ("c.created_at < ?", end_time)):
            if value is not None:
                where.append(clause)
                params.append(value)
        with self.connect() as db:
            rows = db.execute(f"""
                SELECT c.id FROM clipboard c LEFT JOIN image_text o
                ON c.id = o.item_id AND c.image_id = o.image_id AND c.content_type = 'image'
                WHERE {' AND '.join(where)}
                ORDER BY c.is_pinned DESC, {order} LIMIT ? OFFSET ?
            """, (*params, limit, offset)).fetchall()
        return [row[0] for row in rows]

    def pending(self, attempted):
        with self.connect() as db:
            rows = db.execute("""
                SELECT c.id, c.image_id FROM clipboard c LEFT JOIN image_text o
                ON c.id = o.item_id AND c.image_id = o.image_id
                WHERE c.content_type = 'image' AND c.image_id IS NOT NULL AND o.item_id IS NULL
                ORDER BY c.item_order DESC
            """).fetchall()
        return next((row for row in rows if tuple(row) not in attempted), None)


class ImageTextIndexer(QObject):
    """One OCR job at a time, including older images; no OCR in the watcher callback."""

    updated = Signal(int)
    state_changed = Signal(bool)

    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.store = manager.image_text_store
        self._thread = None
        self._current = None
        self._attempted = set()
        self._stopped = False
        self.busy = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(350)
        self._timer.timeout.connect(self._next)
        self.kick()

    def kick(self):
        if not self._stopped and self._thread is None and not self._timer.isActive():
            self.busy = True
            self.state_changed.emit(True)
            self._timer.start()

    def stop(self):
        self._stopped = True
        self.busy = False
        self.state_changed.emit(False)
        self._timer.stop()
        if self._thread is not None:
            self._thread.cancel()
        else:
            self.deleteLater()

    def _next(self):
        if self._stopped or self._thread is not None:
            return
        try:
            from ocr import is_ocr_available
            from text_recognition.recognizer import recognize_async
            if not is_ocr_available() or self.manager.get_db_path() != self.store.path:
                self.busy = False
                self.state_changed.emit(False)
                return
            self._current = self.store.pending(self._attempted)
            if self._current is None:
                self.busy = False
                self.state_changed.emit(False)
                return
            self._attempted.add(tuple(self._current))
            data = self.manager.get_image_data(self._current[1])
            image = QImage.fromData(data) if data else QImage()
            if image.isNull():
                self.kick()
                return
            self._thread = recognize_async(image, on_details=self._recognized)
            self._thread.finished.connect(self._finished)
        except Exception as exc:
            self.busy = False
            self.state_changed.emit(False)
            log_warning(f"Image text indexing failed: {type(exc).__name__}", "Clipboard")

    def _recognized(self, result, reason):
        from text_recognition.recognizer import NO_TEXT
        if self._stopped or (reason and reason != NO_TEXT):
            return
        try:
            if self.manager.get_db_path() == self.store.path and self.store.save(*self._current, result):
                self.updated.emit(self._current[0])
        except Exception as exc:
            log_warning(f"Image text index write failed: {type(exc).__name__}", "Clipboard")

    def _finished(self):
        self._thread = None
        if self._stopped:
            self.deleteLater()
        else:
            self.kick()
