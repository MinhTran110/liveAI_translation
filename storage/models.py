"""Data models for Notes and Segments."""

from dataclasses import dataclass, field, asdict
from typing import List, Optional


@dataclass
class Segment:
    """Individual transcript and translation segment with speaker diarization."""

    speaker: int
    text: str
    translation: str = ""
    start: float = 0.0
    end: float = 0.0
    confidence: float = 1.0
    id: Optional[int] = None
    note_id: Optional[int] = None

    def to_dict(self) -> dict:
        """Convert segment to serializable dictionary."""
        return asdict(self)


@dataclass
class Note:
    """High-level translation note container for a video or audio file."""

    title: str
    source_type: str = "youtube"  # 'youtube' or 'file'
    source_url: Optional[str] = None
    file_path: Optional[str] = None
    duration: float = 0.0
    source_lang: str = "auto"
    target_lang: str = "vi"
    status: str = "completed"  # 'processing', 'completed', 'failed'
    created_at: str = ""
    id: Optional[int] = None
    segments: List[Segment] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert note and nested segments to dictionary."""
        data = asdict(self)
        data["segments"] = [s.to_dict() if isinstance(s, Segment) else s for s in self.segments]
        return data
