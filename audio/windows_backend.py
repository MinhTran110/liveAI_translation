"""Windows audio capture backend using WASAPI loopback."""

import logging
import queue
import threading
from typing import Optional

from audio.base import SystemAudioCapture

logger = logging.getLogger(__name__)


class WindowsAudioCapture(SystemAudioCapture):
    """Captures system audio output on Windows using WASAPI loopback."""

    def __init__(
        self,
        sample_rate: int = 16000,
        channels: int = 1,
        chunk_size: int = 4096,
    ):
        super().__init__(sample_rate, channels, chunk_size)
        self._queue: queue.Queue[bytes] = queue.Queue(maxsize=100)
        self._thread: Optional[threading.Thread] = None

    def _capture_loop(self) -> None:
        """Capture loop using soundcard WASAPI loopback."""
        try:
            import soundcard as sc
            import numpy as np

            speaker = sc.default_speaker()
            if not speaker:
                logger.error("No default speaker found on Windows")
                return

            mic = sc.get_microphone(id=str(speaker.name), include_loopback=True)
            if not mic:
                logger.error("Could not obtain WASAPI loopback microphone for %s", speaker.name)
                return

            num_frames = self.chunk_size // (2 * self.channels)
            with mic.recorder(samplerate=self.sample_rate, channels=self.channels) as recorder:
                while self._is_active:
                    data = recorder.record(numframes=num_frames)
                    # Convert float32 [-1.0, 1.0] to int16 PCM bytes
                    int16_data = (np.clip(data, -1.0, 1.0) * 32767).astype(np.int16).tobytes()
                    try:
                        self._queue.put(int16_data, timeout=0.1)
                    except queue.Full:
                        try:
                            self._queue.get_nowait()
                        except queue.Empty:
                            pass
                        self._queue.put_nowait(int16_data)
        except ImportError:
            logger.error("soundcard package is required for Windows WASAPI loopback capture.")
        except Exception as e:
            logger.error("Windows WASAPI loopback error: %s", e)

    def start(self) -> None:
        """Start Windows WASAPI loopback capture."""
        if self._is_active:
            return
        self._is_active = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()
        logger.info("WindowsAudioCapture (WASAPI loopback) started")

    def stop(self) -> None:
        """Stop Windows WASAPI loopback capture."""
        self._is_active = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._thread = None
        logger.info("WindowsAudioCapture stopped")

    def read_chunk(self, timeout: float = 1.0) -> Optional[bytes]:
        """Read a chunk from the queue."""
        if not self._is_active:
            return None
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None
