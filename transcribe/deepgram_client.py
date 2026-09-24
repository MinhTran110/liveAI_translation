"""Deepgram pre-recorded audio transcription client with speaker diarization."""

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
import urllib.request
import urllib.error

from transcribe.base import TranscriptSegment

logger = logging.getLogger(__name__)


class DeepgramPreRecordedTranscriber:
    """Transcribes audio files using Deepgram's pre-recorded API with speaker diarization."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "nova-2",
        language: str = "multi",
        diarize: bool = True,
        smart_format: bool = True,
        punctuate: bool = True,
    ):
        self.api_key = api_key or os.getenv("DEEPGRAM_API_KEY", "").strip() or None
        self.model = model
        self.language = language
        self.diarize = diarize
        self.smart_format = smart_format
        self.punctuate = punctuate

    def transcribe_file(
        self,
        audio_file_path: str | Path,
        source_lang: Optional[str] = None,
    ) -> List[TranscriptSegment]:
        """Transcribe an audio file and return speaker diarized segments.

        Args:
            audio_file_path: Local path to the audio file (.mp3, .wav, etc.)
            source_lang: Optional language override (e.g. 'ja', 'en', 'vi', 'multi')

        Returns:
            List of TranscriptSegment objects with speaker, text, start, end.
        """
        path = Path(audio_file_path)
        if not path.is_file():
            raise FileNotFoundError(f"Audio file not found: {path}")

        # If no API key, automatically delegate to Local Faster-Whisper
        if not self.api_key:
            logger.info(
                "DEEPGRAM_API_KEY not configured. Running Local Faster-Whisper on full audio track..."
            )
            from transcribe.local_whisper import LocalWhisperFileTranscriber
            local_transcriber = LocalWhisperFileTranscriber()
            return local_transcriber.transcribe_file(audio_file_path, source_lang=source_lang)

        lang = source_lang or self.language or "multi"
        url = (
            f"https://api.deepgram.com/v1/listen"
            f"?model={self.model}"
            f"&language={lang}"
            f"&diarize={'true' if self.diarize else 'false'}"
            f"&smart_format={'true' if self.smart_format else 'false'}"
            f"&punctuate={'true' if self.punctuate else 'false'}"
            f"&utterances=true"
        )

        headers = {
            "Authorization": f"Token {self.api_key}",
            "Content-Type": "audio/*",
        }

        try:
            with open(path, "rb") as f:
                audio_data = f.read()

            req = urllib.request.Request(url, data=audio_data, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=120) as resp:
                resp_data = json.loads(resp.read().decode("utf-8"))

            return self._parse_deepgram_response(resp_data)
        except Exception as e:
            logger.error("Deepgram pre-recorded transcription failed: %s", e)
            logger.info("Falling back to Local Faster-Whisper on full audio track...")
            from transcribe.local_whisper import LocalWhisperFileTranscriber
            local_transcriber = LocalWhisperFileTranscriber()
            return local_transcriber.transcribe_file(audio_file_path, source_lang=source_lang)

    def _parse_deepgram_response(self, data: Dict[str, Any]) -> List[TranscriptSegment]:
        """Parse Deepgram JSON output into list of TranscriptSegment."""
        segments: List[TranscriptSegment] = []
        results = data.get("results", {})

        # Priority 1: results.utterances (cleanest diarized segments with start/end)
        utterances = results.get("utterances", [])
        if utterances:
            for utt in utterances:
                text = utt.get("transcript", "").strip()
                if text:
                    speaker = int(utt.get("speaker", 0))
                    start = float(utt.get("start", 0.0))
                    end = float(utt.get("end", start + 1.0))
                    conf = float(utt.get("confidence", 1.0))
                    segments.append(
                        TranscriptSegment(
                            speaker=speaker,
                            text=text,
                            start=round(start, 2),
                            end=round(end, 2),
                            confidence=round(conf, 2),
                        )
                    )
            if segments:
                return segments

        # Priority 2: results.channels[0].alternatives[0].paragraphs
        channels = results.get("channels", [])
        if channels:
            alt = channels[0].get("alternatives", [{}])[0]
            paragraphs_data = alt.get("paragraphs", {}).get("paragraphs", [])
            for p in paragraphs_data:
                speaker = int(p.get("speaker", 0))
                for sent in p.get("sentences", []):
                    text = sent.get("text", "").strip()
                    if text:
                        start = float(sent.get("start", 0.0))
                        end = float(sent.get("end", start + 1.0))
                        segments.append(
                            TranscriptSegment(
                                speaker=speaker,
                                text=text,
                                start=round(start, 2),
                                end=round(end, 2),
                                confidence=1.0,
                            )
                        )
            if segments:
                return segments

            # Fallback to single transcript if no diarization blocks found
            transcript = alt.get("transcript", "").strip()
            if transcript:
                segments.append(
                    TranscriptSegment(
                        speaker=0,
                        text=transcript,
                        start=0.0,
                        end=10.0,
                        confidence=1.0,
                    )
                )

        return segments

    def _mock_segments(self, title_seed: str) -> List[TranscriptSegment]:
        """Generate realistic conversational dialogue segments for demonstration."""
        return [
            TranscriptSegment(
                speaker=0,
                text="Welcome everyone to today's video presentation and discussion.",
                start=0.5,
                end=3.8,
                confidence=0.98,
            ),
            TranscriptSegment(
                speaker=0,
                text="We are exploring the MemoAI architecture for Linux-based video translation.",
                start=4.2,
                end=8.9,
                confidence=0.96,
            ),
            TranscriptSegment(
                speaker=1,
                text="That is impressive! How does the speaker diarization and translation pipeline operate?",
                start=9.5,
                end=14.3,
                confidence=0.97,
            ),
            TranscriptSegment(
                speaker=0,
                text="The audio track is split into distinct speaker utterances, and each turn is contextually translated.",
                start=15.0,
                end=20.5,
                confidence=0.95,
            ),
            TranscriptSegment(
                speaker=1,
                text="Users can also edit the translated notes directly in the web UI and export subtitles.",
                start=21.2,
                end=26.4,
                confidence=0.99,
            ),
        ]
