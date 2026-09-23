"""Central async coordinator pipeline for live-voice-translate.
Pipes AudioCapture -> Transcriber -> SegmentBuffer -> LLMTranslator -> UI.
"""

import asyncio
import logging
from typing import Callable, Optional

from audio.base import SystemAudioCapture
from core.segment_buffer import FinalSegment, SegmentBuffer
from transcribe.base import TranscriberBase
from translate.llm_translator import LLMTranslator

logger = logging.getLogger(__name__)

RenderCallback = Callable[[Optional[int | str], str, str], None]


class TranslationPipeline:
    """Orchestrates real-time audio capture, transcription, buffering, translation, and UI rendering."""

    def __init__(
        self,
        audio_capture: SystemAudioCapture,
        transcriber: TranscriberBase,
        segment_buffer: SegmentBuffer,
        translator: LLMTranslator,
        render_callback: Optional[RenderCallback] = None,
    ):
        self.audio = audio_capture
        self.transcriber = transcriber
        self.segment_buffer = segment_buffer
        self.translator = translator
        self.render_callback = render_callback or (lambda spk, orig, trans: None)

        self._is_running = False
        self._tasks: list[asyncio.Task] = []

    @property
    def is_running(self) -> bool:
        """Check if pipeline is currently active."""
        return self._is_running

    async def start(self) -> None:
        """Start all pipeline components and background asynchronous loops."""
        if self._is_running:
            return

        self._is_running = True
        logger.info("Starting TranslationPipeline...")

        # Start audio backend and transcriber
        self.audio.start()
        await self.transcriber.start()

        # Launch cooperative tasks
        loop = asyncio.get_running_loop()
        self._tasks = [
            loop.create_task(self._audio_pump(), name="audio_pump"),
            loop.create_task(self._transcription_consumer(), name="transcription_consumer"),
            loop.create_task(self._timeout_monitor(), name="timeout_monitor"),
        ]
        logger.info("TranslationPipeline running with %d tasks.", len(self._tasks))

    async def stop(self) -> None:
        """Gracefully stop pipeline, flush remaining buffer, and clean up resources."""
        if not self._is_running:
            return

        self._is_running = False
        logger.info("Stopping TranslationPipeline...")

        # Flush any trailing words in segment buffer
        trailing = self.segment_buffer.flush()
        if trailing:
            await self._process_final_segment(trailing)

        # Stop audio capture and transcriber
        self.audio.stop()
        await self.transcriber.stop()

        # Cancel tasks
        for task in self._tasks:
            if not task.done():
                task.cancel()

        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        logger.info("TranslationPipeline stopped successfully.")

    async def _audio_pump(self) -> None:
        """Read audio chunks from hardware/backend and forward to transcriber."""
        while self._is_running:
            try:
                chunk = await self.audio.async_read_chunk(timeout=0.1)
                if chunk:
                    await self.transcriber.send_audio(chunk)
                else:
                    await asyncio.sleep(0.01)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error in audio pump: %s", e)
                await asyncio.sleep(0.1)

    async def _transcription_consumer(self) -> None:
        """Consume incoming transcript segments, buffer them, and dispatch finalized sentences."""
        async for segment in self.transcriber.get_transcripts():
            if not self._is_running:
                break
            try:
                finalized_list = self.segment_buffer.add_transcript(segment)
                for final_seg in finalized_list:
                    await self._process_final_segment(final_seg)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error processing transcript: %s", e)

    async def _timeout_monitor(self) -> None:
        """Periodically evaluate buffer timeout to finalize pauses in speech."""
        while self._is_running:
            try:
                await asyncio.sleep(0.3)
                timed_out_seg = self.segment_buffer.check_timeout()
                if timed_out_seg:
                    await self._process_final_segment(timed_out_seg)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error in timeout monitor: %s", e)

    async def _process_final_segment(self, segment: FinalSegment) -> None:
        """Translate finalized sentence and invoke the render callback."""
        clean_text = segment.text.strip()
        if not clean_text:
            return

        try:
            translated = await self.translator.translate(clean_text, speaker=segment.speaker)
            # Dispatch to UI callback
            self.render_callback(segment.speaker, clean_text, translated)
        except Exception as e:
            logger.error("Error during translation or UI callback: %s", e)
            self.render_callback(segment.speaker, clean_text, f"[Translation error: {e}]")
