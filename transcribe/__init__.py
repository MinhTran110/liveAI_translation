"""Transcribe package for pre-recorded Deepgram and local Faster-Whisper ASR."""

from transcribe.base import TranscriberBase, TranscriptSegment, MockTranscriber
from transcribe.deepgram_client import DeepgramPreRecordedTranscriber
from transcribe.local_whisper import LocalWhisperFileTranscriber
from transcribe.model_selector import scan_system, suggest_model

__all__ = [
    "TranscriberBase",
    "TranscriptSegment",
    "MockTranscriber",
    "DeepgramPreRecordedTranscriber",
    "LocalWhisperFileTranscriber",
    "scan_system",
    "suggest_model",
]
