"""Configuration management for MemoAI Video Translate & Notes."""

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
    """MemoAI Application Configuration container."""

    # API Keys
    deepgram_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None

    # Translation Settings
    translator_provider: str = "anthropic"  # 'anthropic', 'openai', 'free'
    source_language: str = "auto"
    target_language: str = "vi"

    # ASR Settings
    asr_engine: str = "deepgram"  # 'deepgram' or 'local'
    whisper_model: str = "base"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"
    models_cache_dir: str = "models_cache"

    # Server Settings
    host: str = "0.0.0.0"
    port: int = 8000
    data_dir: str = "data"
    uploads_dir: str = "uploads"
    downloads_dir: str = "downloads"


def load_config() -> AppConfig:
    """Load configuration from environment variables."""
    deepgram_key = os.getenv("DEEPGRAM_API_KEY", "").strip() or None
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "").strip() or None
    openai_key = os.getenv("OPENAI_API_KEY", "").strip() or None

    return AppConfig(
        deepgram_api_key=deepgram_key,
        anthropic_api_key=anthropic_key,
        openai_api_key=openai_key,
        translator_provider=os.getenv("TRANSLATOR_PROVIDER", "anthropic").lower(),
        source_language=os.getenv("SOURCE_LANGUAGE", "auto"),
        target_language=os.getenv("TARGET_LANGUAGE", "vi"),
        asr_engine=os.getenv("ASR_ENGINE", "deepgram").lower(),
        whisper_model=os.getenv("WHISPER_MODEL", "base"),
        whisper_device=os.getenv("WHISPER_DEVICE", "cpu"),
        whisper_compute_type=os.getenv("WHISPER_COMPUTE_TYPE", "int8"),
        models_cache_dir=os.getenv("MODELS_CACHE_DIR", "models_cache"),
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
        data_dir=os.getenv("DATA_DIR", "data"),
        uploads_dir=os.getenv("UPLOADS_DIR", "uploads"),
        downloads_dir=os.getenv("DOWNLOADS_DIR", "downloads"),
    )
