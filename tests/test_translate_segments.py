"""Unit and integration tests for MemoAI video translate & notes architecture."""

import os
from pathlib import Path
import tempfile
import pytest

from storage.db import (
    init_db,
    create_note,
    add_segments,
    get_notes,
    get_note,
    update_segment_translation,
    delete_note,
)
from storage.models import Note, Segment
from export.srt_exporter import export_srt, format_srt_timestamp
from export.vtt_exporter import export_vtt, format_vtt_timestamp
from export.markdown_exporter import export_markdown
from transcribe.base import TranscriptSegment
from transcribe.deepgram_client import DeepgramPreRecordedTranscriber
from translate.llm_translator import LLMTranslator


@pytest.fixture
def temp_db():
    """Create a temporary SQLite database for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    init_db(db_path)
    yield db_path
    if os.path.exists(db_path):
        os.remove(db_path)


def test_sqlite_note_and_segment_lifecycle(temp_db):
    """Test creating note, adding segments, updating translation, and deleting note."""
    note_id = create_note(
        title="Test Anime Episode 1",
        source_type="youtube",
        source_url="https://youtube.com/watch?v=sample",
        duration=120.5,
        source_lang="ja",
        target_lang="vi",
        db_path=temp_db,
    )
    assert note_id > 0

    segments = [
        TranscriptSegment(speaker=0, text="こんにちは", start=1.0, end=2.5),
        TranscriptSegment(speaker=1, text="お元気ですか", start=3.0, end=4.8),
    ]
    add_segments(note_id, segments, db_path=temp_db)

    note = get_note(note_id, db_path=temp_db)
    assert note is not None
    assert note["title"] == "Test Anime Episode 1"
    assert len(note["segments"]) == 2
    assert note["segments"][0]["text"] == "こんにちは"
    assert note["segments"][1]["speaker"] == 1

    # Test manual translation update (ô sửa tay bản dịch)
    seg_id = note["segments"][0]["id"]
    success = update_segment_translation(seg_id, "Xin chào bạn!", db_path=temp_db)
    assert success is True

    updated_note = get_note(note_id, db_path=temp_db)
    assert updated_note["segments"][0]["translation"] == "Xin chào bạn!"

    # Test delete
    assert delete_note(note_id, db_path=temp_db) is True
    assert get_note(note_id, db_path=temp_db) is None


def test_srt_and_vtt_exporters():
    """Test SRT and VTT subtitle formatting."""
    segments = [
        {
            "speaker": 0,
            "text": "Hello world",
            "translation": "Xin chào thế giới",
            "start": 1.25,
            "end": 3.75,
        },
        {
            "speaker": 1,
            "text": "How are you?",
            "translation": "Bạn khỏe không?",
            "start": 4.10,
            "end": 6.80,
        },
    ]

    srt_out = export_srt(segments, bilingual=True)
    assert "00:00:01,250 --> 00:00:03,750" in srt_out
    assert "[Speaker 0] Xin chào thế giới" in srt_out
    assert "(Hello world)" in srt_out
    assert "00:00:04,100 --> 00:00:06,800" in srt_out

    vtt_out = export_vtt(segments, bilingual=False)
    assert vtt_out.startswith("WEBVTT")
    assert "00:00:01.250 --> 00:00:03.750" in vtt_out
    assert "<v Speaker 0>Xin chào thế giới" in vtt_out


def test_markdown_exporter():
    """Test Markdown notes exporter formatting."""
    note_data = {
        "title": "AI Project Strategy",
        "duration": 150.0,
        "source_lang": "en",
        "target_lang": "vi",
        "created_at": "2026-09-24 08:30:00",
        "source_url": "https://example.com/video",
        "segments": [
            {
                "speaker": 0,
                "text": "First topic of our discussion.",
                "translation": "Chủ đề đầu tiên của cuộc thảo luận.",
                "start": 5.0,
                "end": 10.0,
            }
        ],
    }
    md_out = export_markdown(note_data)
    assert "# AI Project Strategy" in md_out
    assert "Người nói 0" in md_out
    assert "Chủ đề đầu tiên của cuộc thảo luận." in md_out
    assert "[00:05 - 00:10]" in md_out


def test_deepgram_diarization_parser():
    """Test parsing Deepgram pre-recorded utterances format."""
    client = DeepgramPreRecordedTranscriber(api_key=None)
    mock_response = {
        "results": {
            "utterances": [
                {
                    "speaker": 0,
                    "transcript": "Hello and welcome.",
                    "start": 0.5,
                    "end": 2.1,
                    "confidence": 0.99,
                },
                {
                    "speaker": 1,
                    "transcript": "Thank you for having me.",
                    "start": 2.5,
                    "end": 4.8,
                    "confidence": 0.98,
                },
            ]
        }
    }
    parsed = client._parse_deepgram_response(mock_response)
    assert len(parsed) == 2
    assert parsed[0].speaker == 0
    assert parsed[0].text == "Hello and welcome."
    assert parsed[1].speaker == 1
    assert parsed[1].start == 2.5


def test_contextual_translation():
    """Test LLMTranslator context tracking and segment translation."""
    translator = LLMTranslator(target_language="vi")
    segments = [
        TranscriptSegment(speaker=0, text="Hello", start=0.0, end=1.0),
        TranscriptSegment(speaker=1, text="Good morning", start=1.5, end=2.5),
    ]
    translated = translator.translate_segments(segments, target_lang="vi")
    assert len(translated) == 2
    assert translated[0].translation != ""
    assert len(translator.history) == 2
