"""Base abstract class and common interfaces for system audio capture backends."""

from abc import ABC, abstractmethod
import asyncio
import time
from typing import Optional


class SystemAudioCapture(ABC):
    """Abstract base class for system audio capture across different OS backends."""

    def __init__(
        self,
        sample_rate: int = 16000,
        channels: int = 1,
        chunk_size: int = 4096,
    ):
        self.sample_rate = sample_rate
        self.channels = channels
        self.chunk_size = chunk_size
        self._is_active = False
        self._current_volume: float = 0.0

    @property
    def is_active(self) -> bool:
        """Check if audio capture is currently running."""
        return self._is_active

    def get_current_volume(self) -> float:
        """Get current audio volume level (RMS) in range [0.0, 1.0]."""
        return self._current_volume

    @staticmethod
    def calculate_rms(pcm_bytes: bytes) -> float:
        """Calculate normalized RMS volume (0.0 to 1.0) from 16-bit PCM bytes."""
        if not pcm_bytes:
            return 0.0
        try:
            import numpy as np

            data = np.frombuffer(pcm_bytes, dtype=np.int16)
            if len(data) == 0:
                return 0.0
            rms = np.sqrt(np.mean(data.astype(np.float32) ** 2))
            # 32767 is max amplitude for 16-bit signed audio
            norm = min(1.0, float(rms / 10000.0))
            return round(norm, 3)
        except Exception:
            return 0.0

    @abstractmethod
    def start(self) -> None:
        """Start capturing system audio."""
        pass

    @abstractmethod
    def stop(self) -> None:
        """Stop capturing system audio."""
        pass

    @abstractmethod
    def read_chunk(self, timeout: float = 1.0) -> Optional[bytes]:
        """Read a single chunk of raw PCM 16-bit audio data (synchronous).

        Returns:
            bytes: Audio bytes (16-bit mono/stereo PCM) or None if timeout / stopped.
        """
        pass

    async def async_read_chunk(self, timeout: float = 1.0) -> Optional[bytes]:
        """Read an audio chunk asynchronously."""
        return await asyncio.to_thread(self.read_chunk, timeout)


class MockAudioCapture(SystemAudioCapture):
    """Mock audio capture backend for automated testing, headless environments, and demos."""

    def __init__(
        self,
        sample_rate: int = 16000,
        channels: int = 1,
        chunk_size: int = 4096,
        synthetic_pattern: str = "silence",
    ):
        super().__init__(sample_rate, channels, chunk_size)
        self.synthetic_pattern = synthetic_pattern
        self._last_time = time.time()
        self._phase = 0.0

    def start(self) -> None:
        self._is_active = True
        self._last_time = time.time()

    def stop(self) -> None:
        self._is_active = False
        self._current_volume = 0.0

    def read_chunk(self, timeout: float = 1.0) -> Optional[bytes]:
        if not self._is_active:
            return None

        # Simulate real-time audio chunk duration
        bytes_per_sample = 2 * self.channels
        duration = (self.chunk_size // bytes_per_sample) / self.sample_rate
        time.sleep(min(duration, timeout))

        if self.synthetic_pattern == "silence":
            self._current_volume = 0.0
            return b"\x00" * self.chunk_size
        else:
            # Vary mock volume realistically for UI VU meter animation
            import math

            self._phase += 0.3
            self._current_volume = round(0.4 + 0.35 * math.sin(self._phase), 2)
            # Alternating small PCM values to simulate ambient sound
            return b"\x01\x00\xff\xff" * (self.chunk_size // 4)

