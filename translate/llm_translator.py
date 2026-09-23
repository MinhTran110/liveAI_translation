"""Real-time LLM translation service with conversational context memory."""

import asyncio
from collections import deque
from dataclasses import dataclass
import json
import logging
import os
from typing import Deque, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ConversationTurn:
    """A single dialogue turn used for contextual translation."""

    speaker: str
    original: str
    translated: str


class LLMTranslator:
    """Translates finalized speech segments using LLM APIs while preserving context."""

    def __init__(
        self,
        provider: str = "anthropic",  # 'anthropic' or 'openai'
        api_key: Optional[str] = None,
        source_language: str = "auto",
        target_language: str = "vi",
        model_name: Optional[str] = None,
        max_context_turns: int = 5,
    ):
        self.provider = provider.lower()
        self.api_key = api_key
        self.source_language = source_language
        self.target_language = target_language
        self.max_context_turns = max_context_turns
        self.history: Deque[ConversationTurn] = deque(maxlen=max_context_turns)

        # Default fast, low-latency models for real-time translation
        if model_name:
            self.model_name = model_name
        elif self.provider == "anthropic":
            self.model_name = "claude-3-5-haiku-20241022"
        elif self.provider == "openai":
            self.model_name = "gpt-4o-mini"
        else:
            self.model_name = "mock"

        self._client = None
        self._init_client()

    def _init_client(self) -> None:
        """Initialize the API client if keys are present."""
        if not self.api_key:
            logger.warning(
                "No API key provided for LLMTranslator (%s). Running in mock/fallback mode.",
                self.provider,
            )
            return

        try:
            if self.provider == "anthropic":
                from anthropic import AsyncAnthropic

                self._client = AsyncAnthropic(api_key=self.api_key)
            elif self.provider == "openai":
                from openai import AsyncOpenAI

                self._client = AsyncOpenAI(api_key=self.api_key)
        except ImportError as e:
            logger.warning("SDK for %s not installed (%s). Fallback mode enabled.", self.provider, e)

    def _build_system_prompt(self) -> str:
        """Construct the translation system prompt."""
        lang_map = {
            "vi": "Vietnamese",
            "en": "English",
            "es": "Spanish",
            "fr": "French",
            "de": "German",
            "ja": "Japanese",
            "ko": "Korean",
            "zh": "Chinese",
        }
        target_name = lang_map.get(self.target_language.lower(), self.target_language)
        return (
            f"You are a real-time live voice translator.\n"
            f"Your task is to translate incoming spoken dialogue into natural, fluent {target_name}.\n"
            f"Rules:\n"
            f"1. Output ONLY the translated text. Do NOT add notes, explanations, or quotes.\n"
            f"2. Maintain conversational tone, natural spoken vocabulary, and appropriate pronouns based on context.\n"
            f"3. Keep punctuation clean and aligned with spoken delivery."
        )

    def _format_context(self) -> str:
        """Format recent dialogue history to supply to LLM."""
        if not self.history:
            return ""
        lines = ["Recent dialogue context for reference:"]
        for turn in self.history:
            lines.append(f"[{turn.speaker}] Original: {turn.original} -> Translated: {turn.translated}")
        return "\n".join(lines) + "\n\n"

    async def translate(self, text: str, speaker: Optional[int | str] = 0) -> str:
        """Translate a finalized sentence segment and update context history."""
        clean_text = text.strip()
        if not clean_text:
            return ""

        speaker_label = f"Speaker {speaker}" if isinstance(speaker, int) else str(speaker or "Speaker")

        # Fallback/mock mode when no client is configured
        if not self._client:
            translated = await asyncio.to_thread(self._mock_translate, clean_text)
            self.history.append(ConversationTurn(speaker_label, clean_text, translated))
            return translated

        system_prompt = self._build_system_prompt()
        context_str = self._format_context()
        user_prompt = f"{context_str}Now translate this new spoken line from [{speaker_label}]:\n{clean_text}"

        try:
            if self.provider == "anthropic":
                translated = await self._call_anthropic(system_prompt, user_prompt)
            elif self.provider == "openai":
                translated = await self._call_openai(system_prompt, user_prompt)
            else:
                translated = await asyncio.to_thread(self._mock_translate, clean_text)
        except Exception as e:
            logger.error("LLM translation failed: %s. Using fallback.", e)
            translated = await asyncio.to_thread(self._mock_translate, clean_text)

        self.history.append(ConversationTurn(speaker_label, clean_text, translated))
        return translated

    async def _call_anthropic(self, system_prompt: str, user_prompt: str) -> str:
        """Call Anthropic Messages API."""
        response = await self._client.messages.create(
            model=self.model_name,
            max_tokens=300,
            temperature=0.3,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return response.content[0].text.strip()

    async def _call_openai(self, system_prompt: str, user_prompt: str) -> str:
        """Call OpenAI Chat Completions API."""
        response = await self._client.chat.completions.create(
            model=self.model_name,
            max_tokens=300,
            temperature=0.3,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        return response.choices[0].message.content.strip()

    def _free_online_translate(self, text: str, target_lang: str) -> Optional[str]:
        """Free real-time translation using Google Translate endpoint without requiring API keys."""
        import json
        import urllib.parse
        import urllib.request

        try:
            url = (
                f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl={target_lang}&dt=t&q="
                + urllib.parse.quote(text)
            )
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=3.5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                translated = "".join(part[0] for part in data[0] if part and part[0])
                if translated.strip():
                    return translated.strip()
        except Exception as e:
            logger.debug("Free translation fallback error: %s", e)
        return None

    def _mock_translate(self, text: str) -> str:
        """Translate using free online endpoint or fallback dictionary."""
        # 1. Attempt free online translation
        online_res = self._free_online_translate(text, self.target_language)
        if online_res:
            return online_res

        # 2. Simple dictionary for offline demo testing
        phrases = {
            "welcome everyone to today's project presentation.": "Chào mừng mọi người đến với buổi thuyết trình dự án hôm nay.",
            "we are discussing the new real-time translation architecture.": "Chúng tôi đang thảo luận về kiến trúc dịch thuật thời gian thực mới.",
            "that sounds great! can you explain how the segment buffer works?": "Nghe tuyệt quá! Bạn có thể giải thích bộ đệm phân đoạn hoạt động như thế nào không?",
            "sure! it aggregates words and finalizes based on punctuation or speaker turns.": "Chắc chắn rồi! Nó tổng hợp các từ và chốt đoạn dựa trên dấu câu hoặc lượt nói.",
            "hello": "Xin chào",
            "thank you": "Cảm ơn bạn",
            "good morning": "Chào buổi sáng",
        }
        lower = text.lower().strip()
        if lower in phrases:
            return phrases[lower]
        return text

    def set_target_language(self, new_lang: str) -> None:
        """Update target translation language at runtime."""
        self.target_language = new_lang.lower().strip()
        logger.info("Updated translation target language to: %s", self.target_language)

    def clear_context(self) -> None:
        """Reset conversation context history."""
        self.history.clear()

