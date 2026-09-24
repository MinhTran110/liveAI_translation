"""Storage package for SQLite database and data models."""

from storage.models import Note, Segment
from storage.db import (
    init_db,
    create_note,
    add_segments,
    get_notes,
    get_note,
    update_segment_translation,
    delete_note,
)

__all__ = [
    "Note",
    "Segment",
    "init_db",
    "create_note",
    "add_segments",
    "get_notes",
    "get_note",
    "update_segment_translation",
    "delete_note",
]
