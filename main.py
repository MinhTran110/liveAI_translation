"""Main entry point for live-voice-translate.

Workflow:
1. scan_system() -> prints RAM/CPU/GPU/Disk specs
2. suggest_model() -> suggests optimal model (tiny/base/... or cloud Deepgram)
3. get_audio_backend() -> auto-selects audio loopback backend based on OS
4. Initializes TranscriberBase (Deepgram or LocalWhisper)
5. pipeline.run() -> coordinates audio -> transcribe -> segment_buffer -> translate -> UI
"""

import argparse
import asyncio
import logging
import os
import signal
import sys
import threading
import time
from typing import Optional

from audio.backend_selector import get_audio_backend
from config import AppConfig, load_config
from core.pipeline import TranslationPipeline
from core.segment_buffer import SegmentBuffer
from transcribe.base import MockTranscriber, TranscriberBase
from transcribe.deepgram_client import DeepgramStreamingTranscriber
from transcribe.local_whisper import LocalWhisperTranscriber
from transcribe.model_selector import print_system_specs, scan_system, suggest_model
from translate.llm_translator import LLMTranslator
from ui.terminal_window import TerminalWindow

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("main")


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Live Voice Translate - Real-time system audio translation with diarization."
    )
    parser.add_argument(
        "--scan-only",
        action="store_true",
        help="Scan host hardware, display model recommendation, and exit.",
    )
    parser.add_argument(
        "--provider",
        choices=["deepgram", "local", "mock"],
        default=None,
        help="ASR provider override (deepgram, local, or mock).",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Whisper model name override (e.g. tiny, base, small, medium, large-v3).",
    )
    parser.add_argument(
        "--target-lang",
        default=None,
        help="Target translation language code (e.g. vi, en, ja, es).",
    )
    parser.add_argument(
        "--source-lang",
        default=None,
        help="Source audio language code (e.g. auto, en, multi).",
    )
    parser.add_argument(
        "--mock-audio",
        action="store_true",
        help="Use synthetic mock audio capture instead of system hardware loopback.",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Run in demonstration mode with simulated speech and translations.",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run in console headless mode without Tkinter GUI window.",
    )
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Auto-confirm recommended model and configuration without prompting.",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=None,
        help="Run for N seconds then automatically stop (useful for tests/benchmarks).",
    )
    return parser.parse_args()


def init_transcriber(
    provider: str,
    config: AppConfig,
    whisper_model: str,
    device: str,
    compute_type: str,
    demo: bool = False,
) -> TranscriberBase:
    """Instantiate appropriate speech-to-text transcriber."""
    if demo or provider == "mock":
        logger.info("Initializing MockTranscriber for demonstration/testing.")
        return MockTranscriber(sample_rate=config.sample_rate, language=config.source_language)

    if provider == "deepgram":
        if not config.deepgram_api_key:
            logger.warning(
                "DEEPGRAM_API_KEY is not set in .env! Falling back to MockTranscriber. "
                "Add your Deepgram key to .env for real cloud transcription."
            )
            return MockTranscriber(sample_rate=config.sample_rate, language=config.source_language)

        logger.info("Initializing DeepgramStreamingTranscriber (Nova-2)...")
        return DeepgramStreamingTranscriber(
            api_key=config.deepgram_api_key,
            sample_rate=config.sample_rate,
            language=config.source_language,
            punctuate=True,
            diarize=True,
            interim_results=True,
        )

    # Local faster-whisper
    try:
        import faster_whisper  # noqa: F401

        logger.info("Initializing LocalWhisperTranscriber (model=%s, device=%s)...", whisper_model, device)
        return LocalWhisperTranscriber(
            model_size=whisper_model,
            device=device,
            compute_type=compute_type,
            download_root=config.models_cache_dir,
            sample_rate=config.sample_rate,
            language=config.source_language,
        )
    except ImportError:
        logger.warning(
            "faster-whisper is not installed. Falling back to MockTranscriber. "
            "Install faster-whisper via: pip install faster-whisper"
        )
        return MockTranscriber(sample_rate=config.sample_rate, language=config.source_language)


async def async_main(
    pipeline: TranslationPipeline,
    terminal_window: TerminalWindow,
    duration: Optional[float] = None,
) -> None:
    """Async main event loop."""
    await pipeline.start()

    terminal_window.set_status("Listening & Translating...")

    start_time = time.time()
    try:
        while pipeline.is_running:
            await asyncio.sleep(0.5)
            if duration and (time.time() - start_time >= duration):
                logger.info("Reached specified duration of %.1f seconds. Stopping...", duration)
                break
    except (asyncio.CancelledError, KeyboardInterrupt):
        pass
    finally:
        await pipeline.stop()
        terminal_window.set_status("Stopped")


def main() -> None:
    """Main application lifecycle."""
    args = parse_args()
    config = load_config()

    # Apply command-line overrides
    if args.target_lang:
        config.target_language = args.target_lang
    if args.source_lang:
        config.source_language = args.source_lang

    print("\n" + "=" * 65)
    print("        LIVE VOICE TRANSLATE — REAL-TIME DIARIZATION         ")
    print("=" * 65 + "\n")

    # 1. Scan System Hardware
    logger.info("Scanning system hardware capabilities...")
    specs = scan_system(cache_path=config.models_cache_dir)

    # 2. Suggest Optimal Model
    recommendation = suggest_model(specs)
    print_system_specs(specs, recommendation)

    if args.scan_only:
        print("\nScan complete. Exiting (--scan-only specified).")
        return

    # Determine chosen provider and model
    selected_provider = args.provider or config.transcriber_provider
    selected_model = args.model or config.whisper_model
    selected_device = config.whisper_device
    selected_compute = config.whisper_compute_type

    # If user hasn't overridden and hasn't explicitly configured, adopt system recommendation
    if not args.provider and not os.getenv("TRANSCRIBER_PROVIDER"):
        selected_provider = recommendation.recommended_provider
        selected_model = recommendation.model_name
        selected_device = recommendation.device
        selected_compute = recommendation.compute_type

    logger.info(
        "Active Configuration: Provider=%s | Model=%s | Device=%s | TargetLang=%s",
        selected_provider.upper(),
        selected_model,
        selected_device,
        config.target_language,
    )

    # 3. Audio Backend
    use_mock_audio = args.mock_audio or args.demo
    audio_backend = get_audio_backend(
        sample_rate=config.sample_rate,
        channels=config.channels,
        chunk_size=config.chunk_size,
        mock=use_mock_audio,
        synthetic_pattern="ambient" if args.demo else "silence",
    )

    # 4. Transcriber Base
    transcriber = init_transcriber(
        provider=selected_provider,
        config=config,
        whisper_model=selected_model,
        device=selected_device,
        compute_type=selected_compute,
        demo=args.demo,
    )

    # Segment Buffer & LLM Translator
    segment_buffer = SegmentBuffer(
        min_words=config.min_words,
        max_words=config.max_words,
        max_wait_seconds=config.max_wait_seconds,
    )

    translator_key = (
        config.anthropic_api_key
        if config.translator_provider == "anthropic"
        else config.openai_api_key
    )
    translator = LLMTranslator(
        provider=config.translator_provider,
        api_key=translator_key,
        source_language=config.source_language,
        target_language=config.target_language,
    )

    # 5. UI Window Initialization
    status_str = f"[{selected_provider.upper()}] → [{config.target_language.upper()}]"
    terminal_window = TerminalWindow(
        title=f"Live Voice Translate ({status_str})",
        status_info=f"Active: {selected_provider.upper()}",
    )

    # Build Pipeline with render callback into UI
    pipeline = TranslationPipeline(
        audio_capture=audio_backend,
        transcriber=transcriber,
        segment_buffer=segment_buffer,
        translator=translator,
        render_callback=terminal_window.render,
    )

    # If headless requested, or running in an environment without X11
    is_headless = args.headless or (platform.system() == "Linux" and not os.environ.get("DISPLAY"))

    if is_headless:
        # Run console fallback directly in main thread
        ui_thread = threading.Thread(target=terminal_window._run_fallback_loop, daemon=True)
        ui_thread.start()
        try:
            asyncio.run(async_main(pipeline, terminal_window, duration=args.duration))
        except KeyboardInterrupt:
            logger.info("Keyboard interrupt received. Exiting...")
    else:
        # Launch Tkinter GUI in main thread and asyncio pipeline in background thread
        def run_async_loop():
            asyncio.run(async_main(pipeline, terminal_window, duration=args.duration))

        async_thread = threading.Thread(target=run_async_loop, daemon=True)
        async_thread.start()

        # Run Tkinter mainloop on main thread
        try:
            terminal_window.run()
        except KeyboardInterrupt:
            pass

    terminal_window._is_closed = True
    print("\n[Live Voice Translate] Application shutdown complete.")


if __name__ == "__main__":
    main()
