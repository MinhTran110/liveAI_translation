"""Unit tests for speech segment buffer logic."""

import pytest
import time

from core.segment_buffer import FinalSegment, SegmentBuffer
from transcribe.base import TranscriptSegment


def test_segment_buffer_initialization():
    buf = SegmentBuffer(min_words=5, max_words=20, max_wait_seconds=2.0)
    assert buf.min_words == 5
    assert buf.max_words == 20
    assert buf.max_wait_seconds == 2.0
    assert not buf.has_content
    assert buf.current_word_count == 0


def test_punctuation_and_min_words():
    """Verify that buffer finalizes when reaching min_words AND encountering terminal punctuation."""
    buf = SegmentBuffer(min_words=4, max_words=20, max_wait_seconds=5.0)

    # 1. Below min_words with punctuation: should NOT finalize yet
    seg1 = TranscriptSegment(speaker=0, text="Hello world.", is_final=True, start=0.0, end=1.0)
    res1 = buf.add_transcript(seg1, current_time=1.0)
    assert len(res1) == 0
    assert buf.current_word_count == 2

    # 2. Add more words, reaching 4 words and ending with exclamation
    seg2 = TranscriptSegment(speaker=0, text="Welcome here!", is_final=True, start=1.1, end=2.5)
    res2 = buf.add_transcript(seg2, current_time=2.5)
    assert len(res2) == 1
    assert res2[0].speaker == 0
    assert res2[0].text == "Hello world. Welcome here!"
    assert res2[0].word_count == 4
    assert not buf.has_content


def test_max_words_threshold():
    """Verify that reaching max_words forces finalization even without punctuation."""
    buf = SegmentBuffer(min_words=5, max_words=8, max_wait_seconds=10.0)

    # Add 10 words without punctuation
    seg = TranscriptSegment(
        speaker=1,
        text="one two three four five six seven eight nine ten",
        is_final=True,
        start=0.0,
        end=5.0,
    )
    res = buf.add_transcript(seg, current_time=5.0)

    # First 8 words should finalize immediately
    assert len(res) == 1
    assert res[0].speaker == 1
    assert res[0].word_count == 8
    assert res[0].text == "one two three four five six seven eight"

    # Remaining 2 words remain in buffer
    assert buf.has_content
    assert buf.current_word_count == 2
    assert " ".join(buf._buffered_words) == "nine ten"


def test_speaker_transition():
    """Verify that when a new speaker speaks, the previous speaker's buffer is finalized."""
    buf = SegmentBuffer(min_words=10, max_words=50, max_wait_seconds=10.0)

    # Speaker 0 speaks 3 words (below min_words)
    seg1 = TranscriptSegment(speaker=0, text="I have something", is_final=True, start=0.0, end=1.5)
    res1 = buf.add_transcript(seg1, current_time=1.5)
    assert len(res1) == 0
    assert buf.current_word_count == 3

    # Speaker 1 speaks -> Speaker 0's buffer must finalize immediately
    seg2 = TranscriptSegment(speaker=1, text="Please tell us.", is_final=True, start=2.0, end=3.0)
    res2 = buf.add_transcript(seg2, current_time=2.0)

    assert len(res2) == 1
    assert res2[0].speaker == 0
    assert res2[0].text == "I have something"

    # Now buffer contains Speaker 1's words
    assert buf._current_speaker == 1
    assert buf.current_word_count == 3


def test_inactivity_timeout():
    """Verify that timeout finalizes buffered words after MAX_WAIT_SECONDS."""
    buf = SegmentBuffer(min_words=5, max_words=20, max_wait_seconds=2.0)

    # Add 3 words at t = 100.0
    seg = TranscriptSegment(speaker=0, text="Waiting for more", is_final=True, start=100.0, end=101.0)
    buf.add_transcript(seg, current_time=100.0)

    # At t = 101.5 (elapsed 1.5s < 2.0s): should not time out
    assert buf.check_timeout(current_time=101.5) is None

    # At t = 102.5 (elapsed 2.5s >= 2.0s): should time out and finalize
    timed_out = buf.check_timeout(current_time=102.5)
    assert timed_out is not None
    assert timed_out.speaker == 0
    assert timed_out.text == "Waiting for more"
    assert timed_out.word_count == 3
    assert not buf.has_content


def test_flush():
    """Verify manual flush empties buffer."""
    buf = SegmentBuffer(min_words=5, max_words=20, max_wait_seconds=5.0)
    buf.add_transcript(TranscriptSegment(speaker=2, text="trailing unfinished sentence", is_final=True), current_time=10.0)

    assert buf.has_content
    flushed = buf.flush(current_time=12.0)
    assert flushed is not None
    assert flushed.speaker == 2
    assert flushed.text == "trailing unfinished sentence"
    assert not buf.has_content
