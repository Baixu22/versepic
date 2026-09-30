# -*- coding: utf-8 -*-
"""标签存储：与 pyclipboard 的 clipboard.db 同目录的 tags.db。

不改 Rust 表结构，用独立 SQLite 管 tags / item_tags，
按 item_id 关联剪贴板历史。路径由 ClipboardManager 解析后注入。
"""

from __future__ import annotations

import os
import sqlite3
import threading
from typing import Dict, Iterable, List, Optional, Sequence

from core.logger import T, log_exception

from .models import TAG_CHIP_COLORS, Tag

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    color TEXT,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS item_tags (
    item_id INTEGER NOT NULL,
    tag_id INTEGER NOT NULL,
    PRIMARY KEY (item_id, tag_id),
    FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_item_tags_item ON item_tags(item_id);
"""


def default_tags_db_path(clipboard_db_path: Optional[str]) -> str:
    """tags.db 放在 clipboard.db 旁边。"""
    if clipboard_db_path:
        folder = os.path.dirname(clipboard_db_path) or "."
    else:
        folder = os.path.join(os.path.expanduser("~"), "AppData", "Local", "jietuba")
    return os.path.join(folder, "tags.db")


class TagStore:
    """线程安全的标签库。"""

    _instance: Optional["TagStore"] = None
    _lock = threading.Lock()

    def __init__(self, db_path: str):
        self._db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None
        self._local = threading.local()
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self._ensure_schema()

    @classmethod
    def instance(cls, db_path: Optional[str] = None) -> "TagStore":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls(default_tags_db_path(db_path))
            return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        with cls._lock:
            if cls._instance is not None:
                try:
                    cls._instance.close()
                except Exception:
                    pass
            cls._instance = None

    def _get_conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self._db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            self._local.conn = conn
        return conn

    def _ensure_schema(self) -> None:
        try:
            conn = self._get_conn()
            conn.executescript(_SCHEMA)
            conn.commit()
        except Exception as e:
            log_exception(e, T("初始化标签库"))

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
            self._local.conn = None

    # ---------- 查询 ----------

    def list_tags(self) -> List[Tag]:
        try:
            rows = self._get_conn().execute(
                "SELECT id, name, color FROM tags ORDER BY name"
            ).fetchall()
            return [Tag(id=r["id"], name=r["name"], color=r["color"]) for r in rows]
        except Exception as e:
            log_exception(e, T("读取标签列表"))
            return []

    def get_tags_for_items(self, item_ids: Sequence[int]) -> Dict[int, List[Tag]]:
        if not item_ids:
            return {}
        placeholders = ",".join("?" for _ in item_ids)
        try:
            rows = self._get_conn().execute(
                f"""
                SELECT it.item_id, t.id, t.name, t.color
                FROM item_tags it
                JOIN tags t ON t.id = it.tag_id
                WHERE it.item_id IN ({placeholders})
                ORDER BY t.name
                """,
                tuple(item_ids),
            ).fetchall()
            result: Dict[int, List[Tag]] = {}
            for r in rows:
                result.setdefault(r["item_id"], []).append(
                    Tag(id=r["id"], name=r["name"], color=r["color"])
                )
            return result
        except Exception as e:
            log_exception(e, T("读取条目标签"))
            return {}

    def get_tags(self, item_id: int) -> List[Tag]:
        return self.get_tags_for_items([item_id]).get(item_id, [])

    def item_ids_with_tag(self, tag_id: int) -> List[int]:
        try:
            rows = self._get_conn().execute(
                "SELECT item_id FROM item_tags WHERE tag_id = ?", (tag_id,)
            ).fetchall()
            return [r["item_id"] for r in rows]
        except Exception as e:
            log_exception(e, T("按标签查条目"))
            return []

    # ---------- 写入 ----------

    def ensure_tag(self, name: str, color: Optional[str] = None) -> Optional[Tag]:
        name = (name or "").strip()
        if not name:
            return None
        try:
            conn = self._get_conn()
            row = conn.execute(
                "SELECT id, name, color FROM tags WHERE name = ?", (name,)
            ).fetchone()
            if row:
                return Tag(id=row["id"], name=row["name"], color=row["color"])
            if color not in TAG_CHIP_COLORS:
                color = TAG_CHIP_COLORS[hash(name) % len(TAG_CHIP_COLORS)]
            cur = conn.execute(
                "INSERT INTO tags (name, color, created_at) VALUES (?, ?, strftime('%s','now'))",
                (name, color),
            )
            conn.commit()
            return Tag(id=cur.lastrowid, name=name, color=color)
        except Exception as e:
            log_exception(e, T("创建标签"))
            return None

    def rename_tag(self, tag_id: int, name: str) -> bool:
        name = (name or "").strip()
        if not name:
            return False
        try:
            conn = self._get_conn()
            conn.execute("UPDATE tags SET name = ? WHERE id = ?", (name, tag_id))
            conn.commit()
            return True
        except Exception as e:
            log_exception(e, T("重命名标签"))
            return False

    def delete_tag(self, tag_id: int) -> bool:
        try:
            conn = self._get_conn()
            conn.execute("DELETE FROM item_tags WHERE tag_id = ?", (tag_id,))
            conn.execute("DELETE FROM tags WHERE id = ?", (tag_id,))
            conn.commit()
            return True
        except Exception as e:
            log_exception(e, T("删除标签"))
            return False

    def add_tag_to_item(self, item_id: int, tag_id: int) -> bool:
        try:
            conn = self._get_conn()
            conn.execute(
                "INSERT OR IGNORE INTO item_tags (item_id, tag_id) VALUES (?, ?)",
                (item_id, tag_id),
            )
            conn.commit()
            return True
        except Exception as e:
            log_exception(e, T("打标签"))
            return False

    def remove_tag_from_item(self, item_id: int, tag_id: int) -> bool:
        try:
            conn = self._get_conn()
            conn.execute(
                "DELETE FROM item_tags WHERE item_id = ? AND tag_id = ?",
                (item_id, tag_id),
            )
            conn.commit()
            return True
        except Exception as e:
            log_exception(e, T("移除标签"))
            return False

    def toggle_tag_on_item(self, item_id: int, tag_id: int) -> bool:
        """返回切换后是否已打上该标签。"""
        current = {t.id for t in self.get_tags(item_id)}
        if tag_id in current:
            self.remove_tag_from_item(item_id, tag_id)
            return False
        self.add_tag_to_item(item_id, tag_id)
        return True

    def delete_items(self, item_ids: Iterable[int]) -> None:
        ids = list(item_ids)
        if not ids:
            return
        try:
            conn = self._get_conn()
            placeholders = ",".join("?" for _ in ids)
            conn.execute(f"DELETE FROM item_tags WHERE item_id IN ({placeholders})", ids)
            conn.commit()
        except Exception as e:
            log_exception(e, T("清理条目标签"))
