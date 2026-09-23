"""Speech-to-text transcription module."""

from transcribe.base import MockTranscriber, TranscriberBase, TranscriptSegment
from transcribe.deepgram_client import DeepgramStreamingTranscriber
from transcribe.local_whisper import LocalWhisperTranscriber
from transcribe.model_selector import ModelRecommendation, SystemSpecs, print_system_specs, scan_system, suggest_model

__all__ = [
    "TranscriberBase",
    "TranscriptSegment",
    "MockTranscriber",
    "DeepgramStreamingTranscriber",
    "LocalWhisperTranscriber",
    "SystemSpecs",
    "ModelRecommendation",
    "scan_system",
    "suggest_model",
    "print_system_specs",
]
