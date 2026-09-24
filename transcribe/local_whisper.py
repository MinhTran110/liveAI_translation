"""Local faster-whisper file transcriber for Linux."""

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from transcribe.base import TranscriptSegment

logger = logging.getLogger(__name__)


class LocalWhisperFileTranscriber:
    """Transcribes pre-recorded audio files locally using faster-whisper."""

    def __init__(
        self,
        model_name: str = "base",
        device: str = "cpu",
        compute_type: str = "int8",
        cache_dir: str = "models_cache",
    ):
        self.model_name = model_name
        self.device = device
        self.compute_type = compute_type
        self.cache_dir = cache_dir
        self._model = None

    def _get_model(self):
        """Lazy load faster-whisper model with local snapshot detection."""
        if self._model is not None:
            return self._model

        try:
            from faster_whisper import WhisperModel

            cache_root = Path(self.cache_dir)
            model_target = self.model_name

            # Check for cached snapshot offline
            if cache_root.is_dir():
                candidate = cache_root / f"models--Systran--faster-whisper-{self.model_name}"
                snapshots_dir = candidate / "snapshots"
                if snapshots_dir.is_dir():
                    snapshots = [d for d in snapshots_dir.iterdir() if d.is_dir()]
                    if snapshots:
                        model_target = str(snapshots[0])
                        logger.info("Found local cached model snapshot: %s", model_target)

            self._model = WhisperModel(
                model_target,
                device=self.device,
                compute_type=self.compute_type,
                download_root=self.cache_dir,
                local_files_only=Path(model_target).is_dir(),
            )
            return self._model
        except Exception as e:
            logger.warning("Could not load faster-whisper (%s). Fallback mode enabled.", e)
            return None

    def transcribe_file(
        self,
        audio_file_path: str | Path,
        source_lang: Optional[str] = None,
    ) -> List[TranscriptSegment]:
        """Transcribe an audio file and return speaker diarized segments."""
        path = Path(audio_file_path)
        if not path.is_file():
            raise FileNotFoundError(f"Audio file not found: {path}")

        model = self._get_model()
        if model is None:
            raise RuntimeError(
                f"Could not load faster-whisper model '{self.model_name}'. "
                "Please verify model files in models_cache or install internet access."
            )

        lang = source_lang if source_lang not in ("auto", "multi", "", None) else None

        try:
            logger.info("Transcribing audio file with faster-whisper: %s (lang=%s)", path.name, lang)
            segments_gen, info = model.transcribe(
                str(path),
                beam_size=1,
                language=lang,
                vad_filter=True,
                vad_parameters=dict(min_silence_duration_ms=400, speech_pad_ms=250),
            )

            segments: List[TranscriptSegment] = []
            speaker_toggle = 0
            last_end = 0.0

            for seg in segments_gen:
                text = seg.text.strip()
                if not text:
                    continue

                # Acoustic pause turn estimation: pause > 1.8s toggles speaker
                if (seg.start - last_end) > 1.8 and last_end > 0:
                    speaker_toggle = 1 - speaker_toggle

                segments.append(
                    TranscriptSegment(
                        speaker=speaker_toggle,
                        text=text,
                        start=round(seg.start, 2),
                        end=round(seg.end, 2),
                        confidence=round(seg.avg_logprob, 2),
                    )
                )
                last_end = seg.end

            logger.info("Local Whisper finished: %d segments extracted from %s", len(segments), path.name)
            return segments
        except Exception as e:
            logger.error("Local Whisper transcription error: %s", e)
            raise RuntimeError(f"Local Whisper transcription failed: {e}")

    def _mock_segments(self) -> List[TranscriptSegment]:
        return [
            TranscriptSegment(
                speaker=0,
                text="Chào mừng các bạn đến với bản trình bày video hôm nay.",
                start=0.0,
                end=3.5,
                confidence=0.95,
            ),
            TranscriptSegment(
                speaker=1,
                text="Chúng tôi đang thử nghiệm tính năng dịch phụ đề và ghi chú MemoAI trên Linux.",
                start=4.0,
                end=9.2,
                confidence=0.98,
            ),
        ]
