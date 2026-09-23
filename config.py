"""Configuration manager for live-voice-translate.
Loads settings from .env file and environment variables with sensible defaults.
"""

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Optional


def _load_dotenv_fallback(dotenv_path: Path) -> None:
    """Fallback .env parser if python-dotenv is not installed."""
    if not dotenv_path.is_file():
        return
    try:
        with open(dotenv_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, val = line.split("=", 1)
                key = key.strip()
                val = val.strip().strip("'\"")
                if key and key not in os.environ:
                    os.environ[key] = val
    except Exception:
        pass


# Try loading python-dotenv, fallback if not available
_env_path = Path(__file__).resolve().parent / ".env"
try:
    from dotenv import load_dotenv

    load_dotenv(dotenv_path=_env_path)
except ImportError:
    _load_dotenv_fallback(_env_path)


@dataclass
class AppConfig:
    """Application configuration container."""

    # API Keys
    deepgram_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None

    # Translation settings
    translator_provider: str = "anthropic"  # 'anthropic' or 'openai'
    source_language: str = "auto"
    target_language: str = "vi"  # Vietnamese default

    # Transcriber settings
    transcriber_provider: str = "deepgram"  # 'deepgram' or 'local'
    whisper_model: str = "base"
    whisper_device: str = "cpu"  # 'cpu', 'cuda', 'mps'
    whisper_compute_type: str = "int8"
    models_cache_dir: str = "models_cache"

    # Segment buffer thresholds
    min_words: int = 5
    max_words: int = 25
    max_wait_seconds: float = 1.0

    # Audio capture settings
    sample_rate: int = 16000
    channels: int = 1
    chunk_size: int = 4096


def load_config() -> AppConfig:
    """Load configuration from environment variables."""
    deepgram_key = os.getenv("DEEPGRAM_API_KEY", "").strip() or None
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "").strip() or None
    openai_key = os.getenv("OPENAI_API_KEY", "").strip() or None

    transcriber_provider = os.getenv("TRANSCRIBER_PROVIDER", "deepgram").lower()
    # Default to local if no Deepgram key is present and provider was not explicitly forced
    if transcriber_provider == "deepgram" and not deepgram_key:
        transcriber_provider = "local"

    translator_provider = os.getenv("TRANSLATOR_PROVIDER", "anthropic").lower()
    if translator_provider == "anthropic" and not anthropic_key and openai_key:
        translator_provider = "openai"

    return AppConfig(
        deepgram_api_key=deepgram_key,
        anthropic_api_key=anthropic_key,
        openai_api_key=openai_key,
        translator_provider=translator_provider,
        source_language=os.getenv("SOURCE_LANGUAGE", "auto"),
        target_language=os.getenv("TARGET_LANGUAGE", "vi"),
        transcriber_provider=transcriber_provider,
        whisper_model=os.getenv("WHISPER_MODEL", "base"),
        whisper_device=os.getenv("WHISPER_DEVICE", "cpu"),
        whisper_compute_type=os.getenv("WHISPER_COMPUTE_TYPE", "int8"),
        models_cache_dir=os.getenv("MODELS_CACHE_DIR", "models_cache"),
        min_words=int(os.getenv("MIN_WORDS", "5")),
        max_words=int(os.getenv("MAX_WORDS", "25")),
        max_wait_seconds=float(os.getenv("MAX_WAIT_SECONDS", "1.0")),
        sample_rate=int(os.getenv("SAMPLE_RATE", "16000")),
        channels=int(os.getenv("CHANNELS", "1")),
        chunk_size=int(os.getenv("CHUNK_SIZE", "4096")),
    )
