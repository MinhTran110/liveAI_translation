"""Unit tests for translation module."""

import pytest
import asyncio
from translate.llm_translator import LLMTranslator


def test_translator_init():
    translator = LLMTranslator(target_language="vi")
    assert translator.target_language == "vi"
    assert len(translator.history) == 0


def test_translator_switch_language():
    translator = LLMTranslator(target_language="vi")
    translator.set_target_language("ja")
    assert translator.target_language == "ja"


def test_translate_text():
    translator = LLMTranslator(target_language="vi")
    result = asyncio.run(translator.translate(speaker=0, text="Hello world"))
    assert result is not None
    assert len(result) > 0
    assert len(translator.history) == 1
    assert translator.history[0].speaker == "Speaker 0"


def test_translator_set_source_language():
    translator = LLMTranslator(source_language="auto", target_language="vi")
    assert translator.source_language == "auto"
    translator.set_source_language("ja")
    assert translator.source_language == "ja"

