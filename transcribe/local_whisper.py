"""Local speech-to-text transcriber using faster-whisper."""

import asyncio
import io
import logging
import time
from typing import Callable, Optional

from transcribe.base import TranscriberBase, TranscriptSegment

logger = logging.getLogger(__name__)

# Priming prompts inspired by MemoAI to anchor Whisper vocabulary and prevent English drift
LANGUAGE_PROMPTS = {
    "ja": "こんにちは。日本語の会話、アニメ、動画の音声文字起こしです。",
    "zh": "你好，这是中文普通话对话与视频的语音转写。",
    "ko": "안녕하세요, 한국어 동영상 및 대话 음성 텍스트 변환입니다.",
    "en": "Hello, real-time English speech transcription.",
    "vi": "Xin chào, đây là bản ghi âm giọng nói tiếng Việt.",
    "fr": "Bonjour, ceci est une transcription vocale en français.",
    "de": "Hallo, dies ist eine deutsche Sprachübertragung.",
    "es": "Hola, esta es una transcripción de voz en español.",
    "ru": "Здравствуйте, это транскрипция русской речи.",
}


class LocalWhisperTranscriber(TranscriberBase):
    """Local ASR engine using faster-whisper with VAD, language stabilization, and model caching."""

    def __init__(
        self,
        model_size: str = "base",
        device: str = "cpu",
        compute_type: str = "int8",
        download_root: Optional[str] = "models_cache",
        sample_rate: int = 16000,
        language: str = "auto",
        min_chunk_duration: float = 1.2,
        max_chunk_duration: float = 4.0,
    ):
        super().__init__(sample_rate=sample_rate, language=language)
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.download_root = download_root
        self.min_chunk_duration = min_chunk_duration
        self.max_chunk_duration = max_chunk_duration

        self._model = None
        self._audio_buffer = bytearray()
        self._buffer_lock = asyncio.Lock()
        self._worker_task: Optional[asyncio.Task] = None
        self._last_process_time = time.time()

        # Language stabilization states
        self._locked_language: Optional[str] = None if language in ("auto", "multi", "") else language
        self._consecutive_detections: int = 0
        self._language_callback: Optional[Callable[[str, float], None]] = None

    def _load_model(self) -> None:
        """Lazy load faster-whisper model."""
        if self._model is not None:
            return
        try:
            from faster_whisper import WhisperModel

            logger.info(
                "Loading faster-whisper model '%s' (device=%s, compute=%s, cache=%s)...",
                self.model_size,
                self.device,
                self.compute_type,
                self.download_root,
            )
            self._model = WhisperModel(
                self.model_size,
                device=self.device,
                compute_type=self.compute_type,
                download_root=self.download_root,
            )
            logger.info("faster-whisper model loaded successfully.")
        except ImportError:
            raise ImportError(
                "faster-whisper is not installed. Install via: pip install faster-whisper"
            )

    async def start(self) -> None:
        """Initialize model and background inference loop."""
        if self._is_running:
            return

        # Load model in a separate thread so it doesn't block the async loop
        await asyncio.to_thread(self._load_model)

        self._is_running = True
        self._audio_buffer.clear()
        self._last_process_time = time.time()
        self._worker_task = asyncio.create_task(self._process_loop())
        logger.info("LocalWhisperTranscriber started.")

    async def stop(self) -> None:
        """Stop local transcriber."""
        self._is_running = False
        if self._worker_task and not self._worker_task.done():
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        self._audio_buffer.clear()
        logger.info("LocalWhisperTranscriber stopped.")

    async def send_audio(self, chunk: bytes) -> None:
        """Buffer incoming PCM audio chunk."""
        if not self._is_running or not chunk:
            return
        async with self._buffer_lock:
            self._audio_buffer.extend(chunk)

    async def _process_loop(self) -> None:
        """Periodically transcribe buffered audio chunks."""
        # 16-bit mono PCM: 2 bytes per sample
        bytes_per_second = self.sample_rate * 2

        while self._is_running:
            await asyncio.sleep(0.3)
            now = time.time()

            async with self._buffer_lock:
                buf_len = len(self._audio_buffer)
                current_duration = buf_len / bytes_per_second
                elapsed = now - self._last_process_time

                # Check if buffer has reached maximum duration, or has minimum duration and a brief pause
                should_transcribe = False
                if current_duration >= self.max_chunk_duration:
                    should_transcribe = True
                elif current_duration >= self.min_chunk_duration and elapsed >= self.min_chunk_duration:
                    should_transcribe = True

                if should_transcribe:
                    raw_bytes = bytes(self._audio_buffer)
                    self._audio_buffer.clear()
                    self._last_process_time = now
                else:
                    raw_bytes = b""

            if raw_bytes and self._model:
                try:
                    # Skip silence and electronic hum to prevent Whisper hallucinations
                    from audio.base import SystemAudioCapture

                    rms = SystemAudioCapture.calculate_rms(raw_bytes)
                    if rms < 0.004:
                        continue

                    segments = await asyncio.to_thread(self._transcribe_bytes, raw_bytes)
                    for seg in segments:
                        if seg.text.strip():
                            await self._queue.put(seg)
                except Exception as e:
                    logger.error("Error in local whisper transcription: %s", e)

    def set_language(self, language: str) -> None:
        """Update source language at runtime and reset auto-detection lock."""
        super().set_language(language)
        if language in ("auto", "multi", ""):
            self._locked_language = None
            self._consecutive_detections = 0
            logger.info("LocalWhisperTranscriber: Source language set to AUTO (smart stabilization active).")
        else:
            self._locked_language = language
            self._consecutive_detections = 0
            logger.info("LocalWhisperTranscriber: Source language strictly locked to '%s'.", language)

    def set_language_callback(self, callback: Optional[Callable[[str, float], None]]) -> None:
        """Register callback for auto-detected language updates."""
        self._language_callback = callback

    def _estimate_speaker(self, audio_np) -> int:
        """Estimate speaker ID using lightweight acoustic feature clustering (spectral centroid & ZCR)."""
        import numpy as np

        if len(audio_np) < 1600:
            return 0

        # Calculate zero-crossing rate and spectral centroid as a lightweight voice timbre fingerprint
        zcr = float(np.mean(np.abs(np.diff(np.sign(audio_np)))))
        fft_vals = np.abs(np.fft.rfft(audio_np[:16000]))
        freqs = np.fft.rfftfreq(len(audio_np[:16000]), 1.0 / self.sample_rate)
        centroid = float(np.sum(freqs * fft_vals) / (np.sum(fft_vals) + 1e-8))

        feature_vector = np.array([zcr * 1000.0, centroid / 100.0])

        if not hasattr(self, "_speaker_clusters"):
            self._speaker_clusters = []  # List of (speaker_id, mean_vector, count)

        best_speaker = 0
        min_dist = float("inf")

        for spk_id, mean_vec, count in self._speaker_clusters:
            dist = float(np.linalg.norm(feature_vector - mean_vec))
            if dist < min_dist:
                min_dist = dist
                best_speaker = spk_id

        # Distance threshold for speaker distinction
        SPEAKER_DISTANCE_THRESHOLD = 5.5

        if min_dist > SPEAKER_DISTANCE_THRESHOLD and len(self._speaker_clusters) < 8:
            # New speaker identified
            new_speaker_id = len(self._speaker_clusters)
            self._speaker_clusters.append((new_speaker_id, feature_vector, 1))
            return new_speaker_id
        elif self._speaker_clusters:
            # Update running average for best speaker
            idx = [i for i, (s, _, _) in enumerate(self._speaker_clusters) if s == best_speaker][0]
            s_id, m_vec, count = self._speaker_clusters[idx]
            new_mean = (m_vec * count + feature_vector) / (count + 1)
            self._speaker_clusters[idx] = (s_id, new_mean, min(count + 1, 50))
            return best_speaker
        else:
            self._speaker_clusters.append((0, feature_vector, 1))
            return 0

    def _transcribe_bytes(self, pcm_bytes: bytes) -> list[TranscriptSegment]:
        """Convert PCM bytes to float32 array and run Whisper inference with stabilized language."""
        import numpy as np

        # Convert 16-bit PCM bytes to float32 normalized [-1.0, 1.0]
        audio_np = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0

        detected_speaker = self._estimate_speaker(audio_np)

        is_auto = self.language in ("auto", "multi", "")
        effective_lang = self._locked_language if is_auto else self.language
        if effective_lang in ("auto", "multi", ""):
            effective_lang = None

        prompt = LANGUAGE_PROMPTS.get(effective_lang) if effective_lang else None

        segments_gen, info = self._model.transcribe(
            audio_np,
            beam_size=5,
            language=effective_lang,
            initial_prompt=prompt,
            condition_on_previous_text=False,
            temperature=[0.0, 0.2, 0.4],
            compression_ratio_threshold=2.4,
            log_prob_threshold=-1.0,
            no_speech_threshold=0.6,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=400, speech_pad_ms=200, threshold=0.4),
        )

        results = []
        for segment in segments_gen:
            text = segment.text.strip()
            if text:
                results.append(
                    TranscriptSegment(
                        text=text,
                        speaker=detected_speaker,
                        is_final=True,
                        start=segment.start,
                        end=segment.end,
                        confidence=segment.avg_logprob,
                    )
                )

        # Smart Language Stabilizer in Auto mode
        if is_auto and results:
            detected = info.language
            prob = getattr(info, "language_probability", 1.0)

            if self._locked_language is None:
                # Lock onto the first detected language if confidence is reasonable
                if prob >= 0.45:
                    self._locked_language = detected
                    self._consecutive_detections = 1
                    logger.info("Auto-detected and locked language: %s (confidence: %.1f%%)", detected, prob * 100)
                    if self._language_callback:
                        self._language_callback(detected, prob)
            else:
                # Only switch if a different language is sustained with high confidence over 2 chunks
                if detected != self._locked_language:
                    if prob >= 0.85:
                        self._consecutive_detections += 1
                        if self._consecutive_detections >= 2:
                            logger.info(
                                "Language switched from %s to %s (confidence: %.1f%%)",
                                self._locked_language,
                                detected,
                                prob * 100,
                            )
                            self._locked_language = detected
                            self._consecutive_detections = 0
                            if self._language_callback:
                                self._language_callback(detected, prob)
                    else:
                        self._consecutive_detections = 0
                else:
                    self._consecutive_detections = 0

        return results
