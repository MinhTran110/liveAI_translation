"""Local speech-to-text transcriber using faster-whisper."""

import asyncio
import io
import logging
import time
from typing import Optional

from transcribe.base import TranscriberBase, TranscriptSegment

logger = logging.getLogger(__name__)


class LocalWhisperTranscriber(TranscriberBase):
    """Local ASR engine using faster-whisper with VAD and model caching."""

    def __init__(
        self,
        model_size: str = "base",
        device: str = "cpu",
        compute_type: str = "int8",
        download_root: Optional[str] = "models_cache",
        sample_rate: int = 16000,
        language: str = "auto",
        min_chunk_duration: float = 1.5,
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

                # Check if buffer has reached minimum duration or elapsed timeout
                if (current_duration >= self.min_chunk_duration and elapsed >= self.min_chunk_duration) or (
                    current_duration >= self.max_chunk_duration
                ):
                    raw_bytes = bytes(self._audio_buffer)
                    self._audio_buffer.clear()
                    self._last_process_time = now
                else:
                    raw_bytes = b""

            if raw_bytes and self._model:
                try:
                    segments = await asyncio.to_thread(self._transcribe_bytes, raw_bytes)
                    for seg in segments:
                        if seg.text.strip():
                            await self._queue.put(seg)
                except Exception as e:
                    logger.error("Error in local whisper transcription: %s", e)

    def _transcribe_bytes(self, pcm_bytes: bytes) -> list[TranscriptSegment]:
        """Convert PCM bytes to float32 array and run Whisper inference."""
        import numpy as np

        # Convert 16-bit PCM bytes to float32 normalized [-1.0, 1.0]
        audio_np = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0

        lang = None if self.language in ("auto", "multi", "") else self.language

        segments_gen, info = self._model.transcribe(
            audio_np,
            beam_size=5,
            language=lang,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=500),
        )

        results = []
        for segment in segments_gen:
            text = segment.text.strip()
            if text:
                results.append(
                    TranscriptSegment(
                        text=text,
                        speaker=0,
                        is_final=True,
                        start=segment.start,
                        end=segment.end,
                        confidence=segment.avg_logprob,
                    )
                )
        return results
