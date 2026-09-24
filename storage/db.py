"""SQLite database interface for storing notes and segments."""

import logging
import os
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional

from storage.models import Note, Segment

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "notes.db"


def get_connection(db_path: Optional[str | Path] = None) -> sqlite3.Connection:
    """Create and return a configured SQLite connection."""
    target_path = Path(db_path) if db_path else DEFAULT_DB_PATH
    target_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db(db_path: Optional[str | Path] = None) -> None:
    """Initialize database schema with tables for notes and segments."""
    conn = get_connection(db_path)
    try:
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_url TEXT,
                    file_path TEXT,
                    duration REAL DEFAULT 0.0,
                    source_lang TEXT DEFAULT 'auto',
                    target_lang TEXT DEFAULT 'vi',
                    status TEXT DEFAULT 'completed',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS segments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    note_id INTEGER NOT NULL,
                    speaker INTEGER NOT NULL DEFAULT 0,
                    text TEXT NOT NULL,
                    translation TEXT DEFAULT '',
                    start REAL NOT NULL DEFAULT 0.0,
                    end REAL NOT NULL DEFAULT 0.0,
                    confidence REAL DEFAULT 1.0,
                    idx INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY(note_id) REFERENCES notes(id) ON DELETE CASCADE
                );
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_segments_note_id ON segments(note_id);"
            )
        logger.info("SQLite database initialized at: %s", db_path or DEFAULT_DB_PATH)
    finally:
        conn.close()


def create_note(
    title: str,
    source_type: str = "youtube",
    source_url: Optional[str] = None,
    file_path: Optional[str] = None,
    duration: float = 0.0,
    source_lang: str = "auto",
    target_lang: str = "vi",
    status: str = "completed",
    db_path: Optional[str | Path] = None,
) -> int:
    """Insert a new Note record and return its generated ID."""
    conn = get_connection(db_path)
    try:
        with conn:
            cursor = conn.execute(
                """
                INSERT INTO notes (title, source_type, source_url, file_path, duration, source_lang, target_lang, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (title, source_type, source_url, file_path, duration, source_lang, target_lang, status),
            )
            return cursor.lastrowid
    finally:
        conn.close()


def add_segments(
    note_id: int,
    segments: List[Dict[str, Any] | Segment],
    db_path: Optional[str | Path] = None,
) -> None:
    """Insert transcript & translation segments associated with a Note."""
    conn = get_connection(db_path)
    try:
        rows = []
        for idx, seg in enumerate(segments):
            if isinstance(seg, dict):
                speaker = int(seg.get("speaker", 0))
                text = str(seg.get("text", ""))
                trans = str(seg.get("translation", ""))
                start = float(seg.get("start", 0.0))
                end = float(seg.get("end", 0.0))
                conf = float(seg.get("confidence", 1.0))
            else:
                speaker = int(getattr(seg, "speaker", 0) or 0)
                text = str(getattr(seg, "text", ""))
                trans = str(getattr(seg, "translation", ""))
                start = float(getattr(seg, "start", 0.0))
                end = float(getattr(seg, "end", 0.0))
                conf = float(getattr(seg, "confidence", 1.0))

            rows.append((note_id, speaker, text, trans, start, end, conf, idx))

        with conn:
            conn.executemany(
                """
                INSERT INTO segments (note_id, speaker, text, translation, start, end, confidence, idx)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                """,
                rows,
            )
    finally:
        conn.close()


def get_notes(db_path: Optional[str | Path] = None) -> List[Dict[str, Any]]:
    """Retrieve all notes ordered by most recent creation date."""
    conn = get_connection(db_path)
    try:
        cursor = conn.execute(
            """
            SELECT n.id, n.title, n.source_type, n.source_url, n.file_path,
                   n.duration, n.source_lang, n.target_lang, n.status, n.created_at,
                   COUNT(s.id) as segment_count
            FROM notes n
            LEFT JOIN segments s ON n.id = s.note_id
            GROUP BY n.id
            ORDER BY n.created_at DESC;
            """
        )
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def get_note(note_id: int, db_path: Optional[str | Path] = None) -> Optional[Dict[str, Any]]:
    """Retrieve a single note with all its ordered segments."""
    conn = get_connection(db_path)
    try:
        note_cursor = conn.execute(
            "SELECT * FROM notes WHERE id = ?;", (note_id,)
        )
        note_row = note_cursor.fetchone()
        if not note_row:
            return None

        note_dict = dict(note_row)

        seg_cursor = conn.execute(
            """
            SELECT id, note_id, speaker, text, translation, start, end, confidence, idx
            FROM segments
            WHERE note_id = ?
            ORDER BY idx ASC, start ASC;
            """,
            (note_id,),
        )
        note_dict["segments"] = [dict(r) for r in seg_cursor.fetchall()]
        return note_dict
    finally:
        conn.close()


def update_segment_translation(
    segment_id: int,
    translation: str,
    db_path: Optional[str | Path] = None,
) -> bool:
    """Update manual translation for a specific segment."""
    conn = get_connection(db_path)
    try:
        with conn:
            cursor = conn.execute(
                "UPDATE segments SET translation = ? WHERE id = ?;",
                (translation, segment_id),
            )
            return cursor.rowcount > 0
    finally:
        conn.close()


def delete_note(note_id: int, db_path: Optional[str | Path] = None) -> bool:
    """Delete a note and cascade delete all its segments."""
    conn = get_connection(db_path)
    try:
        with conn:
            cursor = conn.execute("DELETE FROM notes WHERE id = ?;", (note_id,))
            return cursor.rowcount > 0
    finally:
        conn.close()
