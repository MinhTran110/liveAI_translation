"""Audio backend selector based on operating system."""

import logging
import platform
from typing import Optional

from audio.base import MockAudioCapture, SystemAudioCapture

logger = logging.getLogger(__name__)


def get_audio_backend(
    os_name: Optional[str] = None,
    sample_rate: int = 16000,
    channels: int = 1,
    chunk_size: int = 4096,
    mock: bool = False,
    synthetic_pattern: str = "silence",
    audio_source: str = "both",
    sink_name: Optional[str] = None,
    source_name: Optional[str] = None,
) -> SystemAudioCapture:
    """Select and instantiate the appropriate audio capture backend for the OS.

    Args:
        os_name: Override OS name ('Linux', 'Windows', 'Darwin'). If None, uses platform.system().
        sample_rate: Audio sampling frequency in Hz (default 16000).
        channels: Number of audio channels (default 1 for mono).
        chunk_size: Chunk buffer size in bytes (default 4096).
        mock: Force use of MockAudioCapture (useful for testing and demos).
        synthetic_pattern: 'silence' or 'ambient' for MockAudioCapture.
        audio_source: 'both' (mix mic + system), 'mic' (microphone only), 'system' (system audio only).
        sink_name: Explicit sink target name or ID.
        source_name: Explicit source target name or ID.

    Returns:
        SystemAudioCapture instance.
    """
    if mock:
        logger.info("Using MockAudioCapture backend (synthetic=%s)", synthetic_pattern)
        return MockAudioCapture(
            sample_rate=sample_rate,
            channels=channels,
            chunk_size=chunk_size,
            synthetic_pattern=synthetic_pattern,
        )

    current_os = os_name or platform.system()
    logger.info("Detecting audio capture backend for OS: %s (source=%s)", current_os, audio_source)

    if current_os == "Linux":
        from audio.linux_backend import LinuxAudioCapture

        return LinuxAudioCapture(
            sample_rate=sample_rate,
            channels=channels,
            chunk_size=chunk_size,
            sink_name=sink_name,
            source_name=source_name,
            audio_source=audio_source,
        )

    elif current_os == "Windows":
        from audio.windows_backend import WindowsAudioCapture

        return WindowsAudioCapture(
            sample_rate=sample_rate,
            channels=channels,
            chunk_size=chunk_size,
        )

    elif current_os == "Darwin":
        from audio.macos_backend import MacOSAudioCapture

        return MacOSAudioCapture(
            sample_rate=sample_rate,
            channels=channels,
            chunk_size=chunk_size,
        )

    else:
        logger.warning(
            "Unsupported OS '%s' for native audio loopback. Falling back to MockAudioCapture.",
            current_os,
        )
        return MockAudioCapture(
            sample_rate=sample_rate,
            channels=channels,
            chunk_size=chunk_size,
            synthetic_pattern=synthetic_pattern,
        )
