from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .util import now

SCHEMA = """
CREATE TABLE IF NOT EXISTS books (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid TEXT NOT NULL UNIQUE,
    path TEXT NOT NULL UNIQUE,
    format TEXT NOT NULL,
    size INTEGER NOT NULL,
    mtime REAL NOT NULL,
    title TEXT NOT NULL,
    authors TEXT NOT NULL,
    language TEXT,
    publisher TEXT,
    description TEXT,
    pubdate REAL,
    isbn TEXT,
    series TEXT,
    series_index REAL,
    cover TEXT,
    kepub_path TEXT,
    created REAL NOT NULL,
    modified REAL NOT NULL,
    archived INTEGER NOT NULL DEFAULT 0,
    archived_reason TEXT,
    archived_at REAL
);
CREATE INDEX IF NOT EXISTS books_modified ON books (modified, id);

CREATE TABLE IF NOT EXISTS reading_states (
    book_id INTEGER PRIMARY KEY REFERENCES books(id) ON DELETE CASCADE,
    created REAL NOT NULL,
    last_modified REAL NOT NULL,
    priority_timestamp REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'ReadyToRead',
    status_last_modified REAL NOT NULL,
    times_started_reading INTEGER NOT NULL DEFAULT 0,
    last_time_started_reading REAL,
    statistics_last_modified REAL NOT NULL,
    spent_reading_minutes INTEGER,
    remaining_time_minutes INTEGER,
    bookmark_last_modified REAL NOT NULL,
    progress_percent REAL,
    content_source_progress_percent REAL,
    location_value TEXT,
    location_type TEXT,
    location_source TEXT
);
CREATE INDEX IF NOT EXISTS reading_states_modified ON reading_states (last_modified);

CREATE TABLE IF NOT EXISTS tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL UNIQUE,
    source TEXT NOT NULL DEFAULT 'folder',
    items TEXT NOT NULL DEFAULT '[]',
    created REAL NOT NULL,
    modified REAL NOT NULL,
    deleted INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS devices (
    device_id TEXT PRIMARY KEY,
    user_agent TEXT,
    first_seen REAL NOT NULL,
    last_seen REAL NOT NULL,
    last_sync REAL
);
"""

BOOK_COLUMNS = (
    "uuid", "path", "format", "size", "mtime", "title", "authors", "language", "publisher",
    "description", "pubdate", "isbn", "series", "series_index", "cover", "kepub_path", "processed_path", "proc_key", "content_hash",
    "created", "modified", "archived", "archived_reason", "archived_at",
)

STATE_COLUMNS = (
    "created", "last_modified", "priority_timestamp", "status", "status_last_modified",
    "times_started_reading", "last_time_started_reading", "statistics_last_modified",
    "spent_reading_minutes", "remaining_time_minutes", "bookmark_last_modified",
    "progress_percent", "content_source_progress_percent", "location_value",
    "location_type", "location_source",
)


def _row_to_dict(row: Optional[sqlite3.Row]) -> Optional[Dict[str, Any]]:
    if row is None:
        return None
    data = dict(row)
    if "authors" in data and isinstance(data["authors"], str):
        try:
            data["authors"] = json.loads(data["authors"])
        except ValueError:
            data["authors"] = [data["authors"]]
    return data


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.init_schema()

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(str(self.path), timeout=30, isolation_level=None)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA foreign_keys=ON")
        return con

    # Columns added after the first release; added to older databases on start.
    MIGRATIONS = (
        ("books", "processed_path", "TEXT"),
        ("books", "proc_key", "TEXT"),
        ("books", "content_hash", "TEXT"),
    )

    def init_schema(self) -> None:
        with closing(self._connect()) as con:
            con.executescript(SCHEMA)
            for table, column, kind in self.MIGRATIONS:
                existing = {r["name"] for r in con.execute(f"PRAGMA table_info({table})")}
                if column not in existing:
                    con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")

    # ------------------------------------------------------------------ books

    def all_books(self, include_archived: bool = True) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM books"
        if not include_archived:
            sql += " WHERE archived = 0"
        sql += " ORDER BY title COLLATE NOCASE, id"
        with closing(self._connect()) as con:
            return [_row_to_dict(r) for r in con.execute(sql)]

    def book_by_id(self, book_id: int) -> Optional[Dict[str, Any]]:
        with closing(self._connect()) as con:
            return _row_to_dict(con.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone())

    def book_by_uuid(self, uuid: str) -> Optional[Dict[str, Any]]:
        with closing(self._connect()) as con:
            return _row_to_dict(con.execute("SELECT * FROM books WHERE uuid = ?", (uuid,)).fetchone())

    def book_by_path(self, path: str) -> Optional[Dict[str, Any]]:
        with closing(self._connect()) as con:
            return _row_to_dict(con.execute("SELECT * FROM books WHERE path = ?", (path,)).fetchone())

    def insert_book(self, **fields) -> int:
        fields = dict(fields)
        if isinstance(fields.get("authors"), list):
            fields["authors"] = json.dumps(fields["authors"], ensure_ascii=False)
        ts = now()
        fields.setdefault("created", ts)
        fields.setdefault("modified", ts)
        cols = [c for c in BOOK_COLUMNS if c in fields]
        sql = "INSERT INTO books ({}) VALUES ({})".format(
            ", ".join(cols), ", ".join("?" for _ in cols))
        with closing(self._connect()) as con:
            cur = con.execute(sql, [fields[c] for c in cols])
            book_id = int(cur.lastrowid)
            self._ensure_state(con, book_id)
            return book_id

    def update_book(self, book_id: int, touch: bool = True, **fields) -> None:
        fields = dict(fields)
        if isinstance(fields.get("authors"), list):
            fields["authors"] = json.dumps(fields["authors"], ensure_ascii=False)
        if touch:
            fields["modified"] = now()
        cols = [c for c in BOOK_COLUMNS if c in fields]
        if not cols:
            return
        sql = "UPDATE books SET {} WHERE id = ?".format(", ".join(f"{c} = ?" for c in cols))
        with closing(self._connect()) as con:
            con.execute(sql, [fields[c] for c in cols] + [book_id])

    def changed_books(self, since_modified: float, since_id: int, limit: int) -> List[Dict[str, Any]]:
        """Books changed after (since_modified, since_id), oldest first."""
        sql = ("SELECT * FROM books WHERE modified > ? OR (modified = ? AND id > ?) "
               "ORDER BY modified, id LIMIT ?")
        with closing(self._connect()) as con:
            return [_row_to_dict(r) for r in con.execute(sql, (since_modified, since_modified, since_id, limit))]

    def archive_book(self, book_id: int, reason: str) -> None:
        ts = now()
        with closing(self._connect()) as con:
            con.execute(
                "UPDATE books SET archived = 1, archived_reason = ?, archived_at = ?, modified = ? WHERE id = ?",
                (reason, ts, ts, book_id))

    def restore_book(self, book_id: int) -> None:
        with closing(self._connect()) as con:
            con.execute(
                "UPDATE books SET archived = 0, archived_reason = NULL, archived_at = NULL, modified = ? WHERE id = ?",
                (now(), book_id))

    def delete_book(self, book_id: int) -> None:
        with closing(self._connect()) as con:
            con.execute("DELETE FROM books WHERE id = ?", (book_id,))

    # --------------------------------------------------------- reading states

    @staticmethod
    def _ensure_state(con: sqlite3.Connection, book_id: int) -> None:
        ts = now()
        con.execute(
            "INSERT OR IGNORE INTO reading_states (book_id, created, last_modified, priority_timestamp, "
            "status_last_modified, statistics_last_modified, bookmark_last_modified) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (book_id, ts, ts, ts, ts, ts, ts))

    def get_or_create_state(self, book_id: int) -> Dict[str, Any]:
        with closing(self._connect()) as con:
            self._ensure_state(con, book_id)
            return _row_to_dict(con.execute("SELECT * FROM reading_states WHERE book_id = ?", (book_id,)).fetchone())

    def update_state(self, book_id: int, **fields) -> None:
        cols = [c for c in STATE_COLUMNS if c in fields]
        if not cols:
            return
        sql = "UPDATE reading_states SET {} WHERE book_id = ?".format(", ".join(f"{c} = ?" for c in cols))
        with closing(self._connect()) as con:
            self._ensure_state(con, book_id)
            con.execute(sql, [fields[c] for c in cols] + [book_id])

    def changed_states(self, since: float, exclude_ids: Iterable[int], limit: int) -> List[Dict[str, Any]]:
        exclude = [int(i) for i in exclude_ids]
        sql = "SELECT * FROM reading_states WHERE last_modified > ?"
        params: List[Any] = [since]
        if exclude:
            sql += " AND book_id NOT IN ({})".format(", ".join("?" for _ in exclude))
            params.extend(exclude)
        sql += " ORDER BY last_modified, book_id LIMIT ?"
        params.append(limit)
        with closing(self._connect()) as con:
            return [_row_to_dict(r) for r in con.execute(sql, params)]

    def overview(self) -> List[Dict[str, Any]]:
        sql = ("SELECT b.*, s.status, s.progress_percent, s.last_modified AS state_modified, "
               "s.spent_reading_minutes FROM books b LEFT JOIN reading_states s ON s.book_id = b.id "
               "ORDER BY s.last_modified DESC, b.title COLLATE NOCASE")
        with closing(self._connect()) as con:
            return [_row_to_dict(r) for r in con.execute(sql)]

    # ------------------------------------------------------------------- tags

    @staticmethod
    def _tag(row: Optional[sqlite3.Row]) -> Optional[Dict[str, Any]]:
        if row is None:
            return None
        data = dict(row)
        data["items"] = json.loads(data["items"] or "[]")
        return data

    def all_tags(self, source: Optional[str] = None) -> List[Dict[str, Any]]:
        sql, params = "SELECT * FROM tags", []
        if source:
            sql += " WHERE source = ?"
            params.append(source)
        with closing(self._connect()) as con:
            return [self._tag(r) for r in con.execute(sql + " ORDER BY name COLLATE NOCASE", params)]

    def tag_by_uuid(self, uuid: str) -> Optional[Dict[str, Any]]:
        with closing(self._connect()) as con:
            return self._tag(con.execute("SELECT * FROM tags WHERE uuid = ?", (uuid,)).fetchone())

    def insert_tag(self, uuid: str, name: str, items: List[str], source: str = "folder") -> None:
        ts = now()
        with closing(self._connect()) as con:
            con.execute("INSERT INTO tags (uuid, name, source, items, created, modified) VALUES (?, ?, ?, ?, ?, ?)",
                        (uuid, name, source, json.dumps(items), ts, ts))

    def update_tag(self, tag_id: int, **fields) -> None:
        fields = dict(fields)
        if "items" in fields:
            fields["items"] = json.dumps(fields["items"])
        fields["modified"] = now()
        cols = [c for c in ("name", "items", "deleted", "created", "modified") if c in fields]
        sql = "UPDATE tags SET {} WHERE id = ?".format(", ".join(f"{c} = ?" for c in cols))
        with closing(self._connect()) as con:
            con.execute(sql, [fields[c] for c in cols] + [tag_id])

    def changed_tags(self, since: float) -> List[Dict[str, Any]]:
        with closing(self._connect()) as con:
            return [self._tag(r) for r in con.execute(
                "SELECT * FROM tags WHERE modified > ? ORDER BY modified, id", (since,))]

    def bump_tags(self, source: str = "folder") -> int:
        with closing(self._connect()) as con:
            return con.execute("UPDATE tags SET modified = ? WHERE source = ?", (now(), source)).rowcount

    # ------------------------------------------------------------------- meta

    def get_meta(self, key: str) -> Optional[str]:
        with closing(self._connect()) as con:
            row = con.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
            return row["value"] if row else None

    def set_meta(self, key: str, value: str) -> None:
        with closing(self._connect()) as con:
            con.execute("INSERT INTO meta (key, value) VALUES (?, ?) "
                        "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))

    # ---------------------------------------------------------------- devices

    def touch_device(self, device_id: str, user_agent: Optional[str], synced: bool) -> None:
        ts = now()
        with closing(self._connect()) as con:
            con.execute(
                "INSERT INTO devices (device_id, user_agent, first_seen, last_seen, last_sync) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(device_id) DO UPDATE SET user_agent = COALESCE(excluded.user_agent, devices.user_agent), "
                "last_seen = excluded.last_seen, last_sync = COALESCE(excluded.last_sync, devices.last_sync)",
                (device_id, user_agent, ts, ts, ts if synced else None))

    def devices(self) -> List[Dict[str, Any]]:
        with closing(self._connect()) as con:
            return [dict(r) for r in con.execute("SELECT * FROM devices ORDER BY last_seen DESC")]
