"""Local OCR metadata in the clipboard database; original images/formats stay intact."""

import json
import sqlite3
import uuid
from contextlib import closing, contextmanager
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QImage

from core.logger import log_warning


INDEX_LABELS = {
    "pending": "OCR: waiting", "recognizing": "OCR: recognizing", "failed": "OCR: failed",
    "excluded": "OCR: excluded", "done": "OCR: indexed", "no_text": "OCR: no text",
}
INDEX_ERRORS = {"unavailable": "OCR engine unavailable", "invalid_image": "Image could not be read",
                "failed": "OCR recognition failed", "interrupted": "OCR interrupted; waiting to retry"}


class ImageTextStore:
    def __init__(self, db_path):
        self.path = str(db_path)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS image_text (
                    item_id INTEGER PRIMARY KEY, image_id TEXT NOT NULL,
                    text TEXT NOT NULL, result TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS image_text_state (
                    item_id INTEGER PRIMARY KEY, image_id TEXT NOT NULL,
                    status TEXT NOT NULL, token TEXT NOT NULL, error TEXT NOT NULL DEFAULT ''
                );
                CREATE TRIGGER IF NOT EXISTS image_text_state_delete
                AFTER DELETE ON clipboard BEGIN
                    DELETE FROM image_text_state WHERE item_id = OLD.id;
                END;
                CREATE TRIGGER IF NOT EXISTS image_text_source_changed
                AFTER UPDATE OF image_id, content_type ON clipboard
                WHEN NEW.image_id IS NOT OLD.image_id OR NEW.content_type IS NOT OLD.content_type BEGIN
                    DELETE FROM image_text WHERE item_id = OLD.id;
                    DELETE FROM image_text_state WHERE item_id = OLD.id;
                END;
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

    def _state(self, db, item_id):
        return db.execute("""
            SELECT c.image_id,
                   COALESCE(s.status, CASE WHEN o.item_id IS NULL THEN 'pending'
                                         WHEN o.text = '' THEN 'no_text' ELSE 'done' END),
                   s.token, COALESCE(s.error, '')
            FROM clipboard c LEFT JOIN image_text_state s ON s.item_id=c.id AND s.image_id=c.image_id
            LEFT JOIN image_text o ON o.item_id=c.id AND o.image_id=c.image_id
            WHERE c.id=? AND c.content_type='image' AND c.image_id IS NOT NULL
        """, (item_id,)).fetchone()

    def state(self, item_id):
        with self.connect() as db:
            row = self._state(db, item_id)
        return {"image_id": row[0], "status": row[1], "token": row[2], "error": row[3]} if row else None

    def change(self, item_id, action):
        if action not in ("exclude", "restore", "retry", "reindex"):
            raise ValueError("Unknown image index action")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._state(db, item_id)
            if row is None:
                return False
            image_id, status, _, _ = row
            if action == "exclude":
                if status == "excluded": return False
                target = "excluded"
            else:
                allowed = {"restore": {"excluded"}, "retry": {"failed"},
                           "reindex": {"done", "no_text", "failed"}}[action]
                if status not in allowed: return False
                target = "pending"
            # Clearing the old search text and invalidating the job are atomic.
            db.execute("DELETE FROM image_text WHERE item_id=?", (item_id,))
            db.execute("INSERT OR REPLACE INTO image_text_state VALUES (?,?,?,?,?)",
                       (item_id, image_id, target, uuid.uuid4().hex, ""))
            return True

    def claim(self, item_id, image_id):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._state(db, item_id)
            if row is None or row[0] != image_id or row[1] != "pending":
                return None
            token = uuid.uuid4().hex
            db.execute("INSERT OR REPLACE INTO image_text_state VALUES (?,?,?,?,?)",
                       (item_id, image_id, "recognizing", token, ""))
            return token

    def finish(self, item_id, image_id, token, status, error=""):
        if status not in ("failed", "pending") or error not in ("", *INDEX_ERRORS):
            raise ValueError("Invalid image index completion")
        with self.connect() as db:
            changed = db.execute("""UPDATE image_text_state SET status=?, error=?, token=?
                WHERE item_id=? AND image_id=? AND token=? AND status='recognizing'
                AND EXISTS (SELECT 1 FROM clipboard c WHERE c.id=item_id
                            AND c.image_id=image_text_state.image_id AND c.content_type='image')""",
                (status, error, uuid.uuid4().hex, item_id, image_id, token))
            return changed.rowcount == 1

    def recover_interrupted(self):
        # Called only when a new single-manager indexer starts, not every read.
        with self.connect() as db:
            rows = db.execute("SELECT item_id FROM image_text_state WHERE status='recognizing'").fetchall()
            db.execute("UPDATE image_text_state SET status='pending', error='interrupted', token=? WHERE status='recognizing'",
                       (uuid.uuid4().hex,))
        return [r[0] for r in rows]

    def save(self, item_id, image_id, result, *, expected_token=None):
        from ocr import format_ocr_result_text
        if not isinstance(result, dict) or result.get("code") != 100:
            return False
        text = format_ocr_result_text(result).strip()
        encoded = json.dumps(result, ensure_ascii=False)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._state(db, item_id)
            if row is None or row[0] != image_id or row[1] == "excluded":
                return False
            if expected_token is not None and (row[2] != expected_token or row[1] != "recognizing"):
                return False
            db.execute("INSERT OR REPLACE INTO image_text VALUES (?,?,?,?)", (item_id, image_id, text, encoded))
            db.execute("INSERT OR REPLACE INTO image_text_state VALUES (?,?,?,?,?)",
                       (item_id, image_id, "done" if text else "no_text", uuid.uuid4().hex, ""))
            return True

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
                SELECT c.id, COALESCE(o.text, ''),
                       COALESCE(s.status, CASE WHEN o.item_id IS NULL THEN 'pending'
                                             WHEN o.text='' THEN 'no_text' ELSE 'done' END),
                       COALESCE(s.error, '')
                FROM clipboard c LEFT JOIN image_text o ON c.id=o.item_id AND c.image_id=o.image_id
                LEFT JOIN image_text_state s ON c.id=s.item_id AND c.image_id=s.image_id
                WHERE c.id IN ({','.join('?' for _ in ids)})
            """, ids).fetchall()
        values = {r[0]: r[1:] for r in rows}
        for item in items:
            item.ocr_text, item.ocr_status, item.ocr_error = values.get(item.id, ("", "pending", ""))
            if item.ocr_status == "excluded": item.ocr_text = ""

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

    def pending(self, attempted=()):
        with self.connect() as db:
            rows = db.execute("""
                SELECT c.id, c.image_id FROM clipboard c LEFT JOIN image_text o
                ON c.id = o.item_id AND c.image_id = o.image_id
                LEFT JOIN image_text_state s ON c.id=s.item_id AND c.image_id=s.image_id
                WHERE c.content_type = 'image' AND c.image_id IS NOT NULL
                  AND o.item_id IS NULL AND (s.status IS NULL OR s.status='pending')
                ORDER BY c.item_order DESC, c.id DESC
            """)
            return next((row for row in rows if tuple(row) not in attempted), None)


class ImageTextIndexer(QObject):
    """One cancellable OCR job at a time; SQLite token guards every late result."""

    updated = Signal(int)
    item_state_changed = Signal(int)
    state_changed = Signal(bool)

    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.store = manager.image_text_store
        self._thread = None
        self._current = None
        self._stopped = False
        self.busy = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(350)
        self._timer.timeout.connect(self._next)
        self.store.recover_interrupted()
        self.kick()

    def kick(self):
        if not self._stopped and self._thread is None and not self._timer.isActive():
            self.busy = True
            self.state_changed.emit(True)
            self._timer.start()

    def change(self, item_id, action):
        if self._stopped or self.manager.get_db_path() != self.store.path:
            return False
        changed = self.store.change(item_id, action)
        if changed:
            if self._current is not None and self._current[0] == item_id and self._thread is not None:
                self._thread.cancel()
            self.item_state_changed.emit(item_id)
            self.updated.emit(item_id)
            self.kick()
        return changed

    def stop(self):
        if self._stopped: return
        self._stopped = True
        self.busy = False
        self.state_changed.emit(False)
        self._timer.stop()
        if self._current is not None:
            try:
                self.store.finish(*self._current, "pending", "interrupted")
            except (sqlite3.Error, OSError):
                pass  # A moved DB is not recreated. Startup recovers interrupted state.
        if self._thread is not None:
            self._thread.cancel()
        else:
            self.deleteLater()

    def _idle(self):
        self.busy = False
        self.state_changed.emit(False)

    def _fail_current(self, error):
        if self._current is not None and self.store.finish(*self._current, "failed", error):
            self.item_state_changed.emit(self._current[0])
            self.updated.emit(self._current[0])

    def _next(self):
        if self._stopped or self._thread is not None: return
        self._timer.stop()
        try:
            from ocr import is_ocr_available
            from text_recognition.recognizer import recognize_async
            if self.manager.get_db_path() != self.store.path:
                self._idle(); return
            candidate = self.store.pending()
            if candidate is None:
                self._current = None
                self._idle(); return
            token = self.store.claim(*candidate)
            if token is None:
                self.kick(); return
            self._current = (*candidate, token)
            self.item_state_changed.emit(candidate[0])
            if not is_ocr_available():
                self._fail_current("unavailable")
                self._current = None
                self.kick(); return
            data = self.manager.get_image_data(candidate[1])
            image = QImage.fromData(data) if data else QImage()
            if image.isNull():
                self._fail_current("invalid_image")
                self._current = None
                self.kick(); return
            self._thread = recognize_async(image, on_details=self._recognized)
            self._thread.finished.connect(self._finished)
        except Exception as exc:
            try: self._fail_current("failed")
            except (sqlite3.Error, OSError): pass
            self._idle()
            log_warning(f"Image text indexing failed: {type(exc).__name__}", "Clipboard")

    def _recognized(self, result, reason):
        from text_recognition.recognizer import NO_TEXT
        if self._stopped or self._current is None or self.manager.get_db_path() != self.store.path:
            return
        try:
            if reason and reason != NO_TEXT:
                self._fail_current(reason if reason == "unavailable" else "failed")
                return
            if reason == NO_TEXT and (not isinstance(result, dict) or result.get("code") != 100):
                result = {"code": 100, "data": []}
            item_id, image_id, token = self._current
            if self.store.save(item_id, image_id, result, expected_token=token):
                self.item_state_changed.emit(item_id)
                self.updated.emit(item_id)
            else:
                self._fail_current("failed")
        except Exception as exc:
            try: self._fail_current("failed")
            except (sqlite3.Error, OSError): pass
            log_warning(f"Image text index write failed: {type(exc).__name__}", "Clipboard")

    def _finished(self):
        self._thread = None
        # An unexpected worker exit without a details callback must not leave a
        # permanent recognizing state. Token checks preserve exclusion/new jobs.
        if not self._stopped:
            try: self._fail_current("failed")
            except (sqlite3.Error, OSError): pass
        self._current = None
        if self._stopped: self.deleteLater()
        else: self.kick()
