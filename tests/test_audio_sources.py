"""Unit tests for multi-source audio capture modes and backend selector."""

import pytest
from audio.base import SystemAudioCapture
from audio.backend_selector import get_audio_backend
from audio.linux_backend import LinuxAudioCapture
from config import AppConfig, load_config


def test_linux_audio_capture_modes_initialization():
    """Verify LinuxAudioCapture properly handles different audio source modes."""
    cap_both = LinuxAudioCapture(audio_source="both")
    assert cap_both.get_audio_source() == "both"

    cap_mic = LinuxAudioCapture(audio_source="mic")
    assert cap_mic.get_audio_source() == "mic"

    cap_sys = LinuxAudioCapture(audio_source="system")
    assert cap_sys.get_audio_source() == "system"


def test_linux_audio_capture_mode_switching():
    """Verify runtime switching of audio source."""
    cap = LinuxAudioCapture(audio_source="both")
    assert cap.get_audio_source() == "both"

    cap.set_audio_source("mic")
    assert cap.get_audio_source() == "mic"

    cap.set_audio_source("system")
    assert cap.get_audio_source() == "system"

    # Invalid mode should be ignored
    cap.set_audio_source("invalid_mode")
    assert cap.get_audio_source() == "system"


def test_backend_selector_forwards_audio_source():
    """Verify get_audio_backend forwards audio_source properly."""
    cap = get_audio_backend(os_name="Linux", audio_source="mic")
    assert isinstance(cap, LinuxAudioCapture)
    assert cap.get_audio_source() == "mic"


def test_app_config_audio_source():
    """Verify AppConfig holds audio_source default."""
    cfg = AppConfig()
    assert cfg.audio_source == "both"
    assert cfg.sink_name is None
    assert cfg.source_name is None
