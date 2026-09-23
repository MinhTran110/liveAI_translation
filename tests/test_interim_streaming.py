"""Unit tests for real-time interim streaming subtitles, font resolution, and emoji-free UI."""

import pytest
from core.segment_buffer import SegmentBuffer
from transcribe.base import TranscriptSegment
from ui.theme import get_ui_font_family, get_mono_font_family
from ui.terminal_window import TerminalWindow, SOURCE_LANGUAGES, TARGET_LANGUAGES


def test_font_family_resolves_to_arial():
    """Verify that font resolution strictly prioritizes Arial TrueType font."""
    assert get_ui_font_family() == "Arial"
    assert get_mono_font_family() == "Arial"


def test_no_emojis_in_language_dropdowns():
    """Verify that broken emoji characters are completely eradicated from language dropdown options."""
    emoji_chars = ["💬", "🎙", "🌐", "📌", "⏸", "🗑", "⚡", "🇯🇵", "🇺🇸", "🇨🇳", "🇰🇷", "🇻🇳", "🇫🇷", "🇩🇪", "🇪🇸", "🇷🇺"]
    for code, label in SOURCE_LANGUAGES:
        for em in emoji_chars:
            assert em not in label, f"Emoji '{em}' found in SOURCE_LANGUAGES option '{label}'"

    for code, label in TARGET_LANGUAGES:
        for em in emoji_chars:
            assert em not in label, f"Emoji '{em}' found in TARGET_LANGUAGES option '{label}'"


def test_segment_buffer_interim_text():
    """Verify that SegmentBuffer exposes unfinalized text for live interim preview."""
    buf = SegmentBuffer(min_words=5, max_words=20, max_wait_seconds=1.0)
    assert buf.get_current_text() == ""
    assert buf.get_current_speaker() is None

    # Add 2 words (does not trigger finalization)
    seg1 = TranscriptSegment(speaker=0, text="Xin chào", is_final=True, start=0.0, end=1.0)
    finalized = buf.add_transcript(seg1)
    assert len(finalized) == 0
    assert buf.get_current_text() == "Xin chào"
    assert buf.get_current_speaker() == 0

    # Add 2 more words
    seg2 = TranscriptSegment(speaker=0, text="các bạn", is_final=True, start=1.1, end=2.0)
    finalized2 = buf.add_transcript(seg2)
    assert len(finalized2) == 0
    assert buf.get_current_text() == "Xin chào các bạn"
    assert buf.get_current_speaker() == 0

    # Finalize by flush
    flushed = buf.flush()
    assert flushed is not None
    assert flushed.text == "Xin chào các bạn"
    assert buf.get_current_text() == ""


def test_segment_buffer_cjk_interim_text():
    """Verify that SegmentBuffer properly formats CJK text without unwanted spaces."""
    buf = SegmentBuffer(min_words=4, max_words=20, max_wait_seconds=1.0)
    seg = TranscriptSegment(speaker=1, text="こんにちは", is_final=True, start=0.0, end=1.0)
    buf.add_transcript(seg)
    assert buf.get_current_text() == "こんにちは"
    assert buf.get_current_speaker() == 1


def test_terminal_window_interim_queueing():
    """Verify that TerminalWindow correctly enqueues interim and final subtitle events."""
    tw = TerminalWindow()
    tw.render_interim(0, "Đang nói một câu gì đó")
    assert not tw._queue.empty()
    item = tw._queue.get_nowait()
    assert item[0] == "interim"
    assert item[1] == 0
    assert item[2] == "Đang nói một câu gì đó"

    tw.clear_interim()
    item2 = tw._queue.get_nowait()
    assert item2[0] == "clear_interim"

    tw.render(0, "Câu gốc", "Bản dịch")
    item3 = tw._queue.get_nowait()
    assert item3[0] == "final"
    assert item3[1] == 0
    assert item3[2] == "Câu gốc"
    assert item3[3] == "Bản dịch"
