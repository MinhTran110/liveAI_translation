"""Unit tests for language stabilization and source language selection."""

import pytest
from transcribe.local_whisper import LocalWhisperTranscriber, LANGUAGE_PROMPTS
from transcribe.deepgram_client import DeepgramStreamingTranscriber
from ui.terminal_window import TerminalWindow, SOURCE_LANGUAGES, TARGET_LANGUAGES


def test_language_prompts():
    assert "ja" in LANGUAGE_PROMPTS
    assert "zh" in LANGUAGE_PROMPTS
    assert "ko" in LANGUAGE_PROMPTS
    assert "en" in LANGUAGE_PROMPTS
    assert "vi" in LANGUAGE_PROMPTS
    assert "日本語" in LANGUAGE_PROMPTS["ja"]


def test_local_whisper_language_locking():
    # 1. Fixed language initialization
    tw_ja = LocalWhisperTranscriber(language="ja")
    assert tw_ja.language == "ja"
    assert tw_ja._locked_language == "ja"

    # 2. Auto language initialization
    tw_auto = LocalWhisperTranscriber(language="auto")
    assert tw_auto.language == "auto"
    assert tw_auto._locked_language is None

    # 3. Dynamic language lock
    tw_auto.set_language("ja")
    assert tw_auto.language == "ja"
    assert tw_auto._locked_language == "ja"

    # 4. Switch back to auto
    tw_auto.set_language("auto")
    assert tw_auto.language == "auto"
    assert tw_auto._locked_language is None


def test_deepgram_set_language():
    dg = DeepgramStreamingTranscriber(api_key="test_key", language="multi")
    assert dg.language == "multi"
    dg.set_language("ja")
    assert dg.language == "ja"
    dg.set_language("auto")
    assert dg.language == "multi"


def test_ui_language_definitions():
    src_codes = [code for code, _ in SOURCE_LANGUAGES]
    assert "auto" in src_codes
    assert "ja" in src_codes
    assert "en" in src_codes
    assert "zh" in src_codes

    tgt_codes = [code for code, _ in TARGET_LANGUAGES]
    assert "vi" in tgt_codes
    assert "en" in tgt_codes


def test_ui_set_detected_language():
    tw = TerminalWindow()
    tw.set_detected_language("ja", 0.98)
    assert tw._detected_lang_str == "[JA 98%]"
