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

    @property
    def is_active(self) -> bool:
        """Check if audio capture is currently running."""
        return self._is_active

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

    def start(self) -> None:
        self._is_active = True
        self._last_time = time.time()

    def stop(self) -> None:
        self._is_active = False

    def read_chunk(self, timeout: float = 1.0) -> Optional[bytes]:
        if not self._is_active:
            return None

        # Simulate real-time audio chunk duration
        # bytes_per_sample = 2 (16-bit) * channels
        bytes_per_sample = 2 * self.channels
        duration = (self.chunk_size // bytes_per_sample) / self.sample_rate
        time.sleep(min(duration, timeout))

        if self.synthetic_pattern == "silence":
            return b"\x00" * self.chunk_size
        else:
            # Alternating small PCM values to simulate ambient sound
            return b"\x01\x00\xff\xff" * (self.chunk_size // 4)
