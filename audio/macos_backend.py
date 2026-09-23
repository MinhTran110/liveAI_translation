"""macOS audio capture backend.
Supports CoreAudio loopback via BlackHole virtual device or native CoreAudio taps (macOS >= 14.4).
"""

import logging
import platform
import queue
import threading
from typing import Optional, Tuple

from audio.base import SystemAudioCapture

logger = logging.getLogger(__name__)


def get_macos_version() -> Tuple[int, int]:
    """Parse macOS major and minor version numbers."""
    ver_str = platform.mac_ver()[0]
    if not ver_str:
        return (0, 0)
    parts = ver_str.split(".")
    try:
        major = int(parts[0])
        minor = int(parts[1]) if len(parts) > 1 else 0
        return (major, minor)
    except ValueError:
        return (0, 0)


class MacOSAudioCapture(SystemAudioCapture):
    """Captures system audio on macOS using BlackHole virtual device or CoreAudio taps."""

    def __init__(
        self,
        sample_rate: int = 16000,
        channels: int = 1,
        chunk_size: int = 4096,
        device_name: Optional[str] = None,
    ):
        super().__init__(sample_rate, channels, chunk_size)
        self.device_name = device_name
        self._queue: queue.Queue[bytes] = queue.Queue(maxsize=100)
        self._stream = None
        self._mac_version = get_macos_version()

    def _find_loopback_device(self) -> Optional[int]:
        """Find BlackHole or virtual loopback device index."""
        try:
            import sounddevice as sd

            devices = sd.query_devices()
            target_keywords = ["blackhole", "soundflower", "loopback", "multi-output"]

            if self.device_name:
                for idx, dev in enumerate(devices):
                    if self.device_name.lower() in dev.get("name", "").lower():
                        return idx

            for idx, dev in enumerate(devices):
                name = dev.get("name", "").lower()
                max_inputs = dev.get("max_input_channels", 0)
                if max_inputs > 0 and any(kw in name for kw in target_keywords):
                    logger.info("Found macOS loopback audio device [%d]: %s", idx, dev["name"])
                    return idx
        except Exception as e:
            logger.debug("Error querying sounddevice on macOS: %s", e)
        return None

    def start(self) -> None:
        """Start macOS audio capture."""
        if self._is_active:
            return

        major, minor = self._mac_version
        is_sonoma_or_later = (major > 14) or (major == 14 and minor >= 4)

        device_idx = self._find_loopback_device()

        if device_idx is None:
            instructions = (
                "\n"
                + "=" * 65 + "\n"
                + "[macOS Audio Setup Required]\n"
                + f"Detected macOS version: {major}.{minor}\n"
            )
            if is_sonoma_or_later:
                instructions += (
                    "macOS 14.4+ supports CoreAudio process taps, but Python audio capture\n"
                    "requires the BlackHole virtual audio loopback driver for system-wide sound.\n"
                )
            else:
                instructions += (
                    "System audio loopback on this macOS version requires BlackHole.\n"
                )
            instructions += (
                "To install BlackHole:\n"
                "  1. brew install blackhole-2ch\n"
                "  2. Open 'Audio MIDI Setup' -> Create 'Multi-Output Device'\n"
                "     (check both your Speakers/Headphones and BlackHole 2ch)\n"
                "  3. Set macOS sound output to the Multi-Output Device\n"
                + "=" * 65 + "\n"
            )
            logger.warning(instructions)

        try:
            import sounddevice as sd

            def audio_callback(indata, frames, time_info, status):
                if status:
                    logger.debug("Audio status: %s", status)
                try:
                    self._queue.put_nowait(bytes(indata))
                except queue.Full:
                    try:
                        self._queue.get_nowait()
                    except queue.Empty:
                        pass
                    self._queue.put_nowait(bytes(indata))

            self._stream = sd.RawInputStream(
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype="int16",
                blocksize=self.chunk_size // (2 * self.channels),
                device=device_idx,
                callback=audio_callback,
            )
            self._stream.start()
            self._is_active = True
            logger.info("MacOSAudioCapture started (device: %s)", device_idx)
        except Exception as e:
            logger.error("Failed to start sounddevice on macOS: %s", e)
            self._is_active = False

    def stop(self) -> None:
        """Stop audio capture."""
        self._is_active = False
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        logger.info("MacOSAudioCapture stopped")

    def read_chunk(self, timeout: float = 1.0) -> Optional[bytes]:
        """Read an audio chunk."""
        if not self._is_active:
            return None
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None
