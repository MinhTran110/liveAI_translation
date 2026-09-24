"""Contextual translation service with conversational and document-level memory."""

import asyncio
from collections import deque
from dataclasses import dataclass
import json
import logging
import os
from typing import Any, Deque, Dict, List, Optional
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)


@dataclass
class ConversationTurn:
    """A single dialogue turn used for contextual translation memory."""

    speaker: str
    original: str
    translated: str


class LLMTranslator:
    """Translates speech segments while maintaining dialogue and document context."""

    def __init__(
        self,
        provider: str = "anthropic",  # 'anthropic', 'openai', 'free'
        api_key: Optional[str] = None,
        source_language: str = "auto",
        target_language: str = "vi",
        model_name: Optional[str] = None,
        max_context_turns: int = 6,
    ):
        self.provider = provider.lower()
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY") or os.getenv("OPENAI_API_KEY")
        self.source_language = source_language
        self.target_language = target_language
        self.max_context_turns = max_context_turns
        self.history: Deque[ConversationTurn] = deque(maxlen=max_context_turns)

        if model_name:
            self.model_name = model_name
        elif self.provider == "anthropic":
            self.model_name = "claude-3-5-haiku-20241022"
        elif self.provider == "openai":
            self.model_name = "gpt-4o-mini"
        else:
            self.model_name = "free"

    def _format_context(self) -> str:
        """Format recent dialogue history for the LLM prompt."""
        if not self.history:
            return ""
        lines = []
        for turn in self.history:
            lines.append(f"{turn.speaker}: {turn.original} -> {turn.translated}")
        return "\n".join(lines)

    def _free_online_translate(self, text: str, target_lang: str) -> Optional[str]:
        """Free real-time translation using Google Translate endpoint without requiring API keys."""
        try:
            sl = self.source_language if self.source_language not in ("auto", "multi", "") else "auto"
            url = (
                f"https://translate.googleapis.com/translate_a/single?client=gtx&sl={sl}&tl={target_lang}&dt=t&q="
                + urllib.parse.quote(text)
            )
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                translated = "".join(part[0] for part in data[0] if part and part[0])
                if translated.strip():
                    return translated.strip()
        except Exception as e:
            logger.debug("Free translation endpoint error: %s", e)
        return None

    def translate_text(self, text: str, speaker_label: str = "Speaker 0") -> str:
        """Translate a single line of text synchronously while tracking context."""
        clean_text = text.strip()
        if not clean_text:
            return ""

        # 1. Try LLM if API key is present
        translated = None
        if self.api_key and self.provider in ("anthropic", "openai"):
            try:
                translated = self._call_llm_sync(clean_text, speaker_label)
            except Exception as e:
                logger.warning("LLM API call failed: %s. Falling back to free translator.", e)

        # 2. Try Free Google Translate endpoint
        if not translated:
            translated = self._free_online_translate(clean_text, self.target_language)

        # 3. Fallback to original text if offline
        if not translated:
            translated = clean_text

        self.history.append(ConversationTurn(speaker_label, clean_text, translated))
        return translated

    def _call_llm_sync(self, text: str, speaker_label: str) -> str:
        """Synchronously invoke Anthropic or OpenAI API."""
        context_str = self._format_context()
        sys_prompt = (
            f"You are an expert video translator translating spoken dialogue into natural, fluent Vietnamese ({self.target_language}).\n"
            f"Rules:\n"
            f"1. Output ONLY the translated text without extra explanation or formatting.\n"
            f"2. Preserve the speaker's tone and align pronouns naturally based on conversation flow."
        )

        user_prompt = ""
        if context_str:
            user_prompt += f"Recent dialogue context:\n{context_str}\n\n"
        user_prompt += f"Now translate this segment from {speaker_label}:\n\"{text}\""

        if self.provider == "anthropic":
            import urllib.request
            headers = {
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            }
            body = {
                "model": self.model_name,
                "max_tokens": 300,
                "system": sys_prompt,
                "messages": [{"role": "user", "content": user_prompt}],
            }
            req = urllib.request.Request(
                "https://api.anthropic.com/v1/messages",
                data=json.dumps(body).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                res = json.loads(r.read().decode("utf-8"))
                return res["content"][0]["text"].strip()

        elif self.provider == "openai":
            import urllib.request
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
            body = {
                "model": self.model_name,
                "messages": [
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.3,
            }
            req = urllib.request.Request(
                "https://api.openai.com/v1/chat/completions",
                data=json.dumps(body).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                res = json.loads(r.read().decode("utf-8"))
                return res["choices"][0]["message"]["content"].strip()

        return text

    def translate_segments(
        self,
        segments: List[Any],
        target_lang: Optional[str] = None,
        source_lang: Optional[str] = None,
    ) -> List[Any]:
        """Translate a batch of transcript segments with context awareness."""
        if target_lang:
            self.target_language = target_lang
        if source_lang:
            self.source_language = source_lang

        for seg in segments:
            speaker_id = getattr(seg, "speaker", 0) if hasattr(seg, "speaker") else seg.get("speaker", 0)
            text = getattr(seg, "text", "") if hasattr(seg, "text") else seg.get("text", "")
            spk_label = f"Speaker {speaker_id}"
            translation = self.translate_text(text, spk_label)

            if isinstance(seg, dict):
                seg["translation"] = translation
            else:
                setattr(seg, "translation", translation)

        return segments

    def set_target_language(self, new_lang: str) -> None:
        self.target_language = new_lang.lower().strip()

    def set_source_language(self, new_lang: str) -> None:
        self.source_language = new_lang.lower().strip()

    def clear_context(self) -> None:
        self.history.clear()
