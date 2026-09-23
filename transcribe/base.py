"""Base abstract classes and data models for speech-to-text transcribers."""

from abc import ABC, abstractmethod
import asyncio
from dataclasses import dataclass, field
import time
from typing import AsyncGenerator, List, Optional


@dataclass
class TranscriptSegment:
    """Represents a speech segment received from an ASR provider."""

    text: str
    speaker: Optional[int | str] = 0
    is_final: bool = True
    start: float = 0.0
    end: float = 0.0
    words: List[dict] = field(default_factory=list)
    confidence: float = 1.0


class TranscriberBase(ABC):
    """Abstract base class for streaming ASR transcribers."""

    def __init__(self, sample_rate: int = 16000, language: str = "multi"):
        self.sample_rate = sample_rate
        self.language = language
        self._is_running = False
        self._queue: asyncio.Queue[TranscriptSegment] = asyncio.Queue()

    @property
    def is_running(self) -> bool:
        """Check if the transcriber is currently running."""
        return self._is_running

    @abstractmethod
    async def start(self) -> None:
        """Start the transcriber session."""
        pass

    @abstractmethod
    async def stop(self) -> None:
        """Stop the transcriber session."""
        pass

    @abstractmethod
    async def send_audio(self, chunk: bytes) -> None:
        """Send an audio chunk to the transcriber."""
        pass

    async def get_transcripts(self) -> AsyncGenerator[TranscriptSegment, None]:
        """Stream transcription segments as they arrive."""
        while self._is_running or not self._queue.empty():
            try:
                segment = await asyncio.wait_for(self._queue.get(), timeout=0.2)
                yield segment
                self._queue.task_done()
            except asyncio.TimeoutError:
                continue


class MockTranscriber(TranscriberBase):
    """Mock transcriber that produces realistic conversational transcripts for testing."""

    def __init__(
        self,
        sample_rate: int = 16000,
        language: str = "multi",
        script: Optional[List[TranscriptSegment]] = None,
        emit_interval: float = 1.5,
    ):
        super().__init__(sample_rate, language)
        self.emit_interval = emit_interval
        self._task: Optional[asyncio.Task] = None
        self._script = script or [
            TranscriptSegment(
                speaker=0,
                text="Welcome everyone to today's project presentation.",
                is_final=True,
                start=0.0,
                end=2.5,
            ),
            TranscriptSegment(
                speaker=0,
                text="We are discussing the new real-time translation architecture.",
                is_final=True,
                start=2.8,
                end=5.4,
            ),
            TranscriptSegment(
                speaker=1,
                text="That sounds great! Can you explain how the segment buffer works?",
                is_final=True,
                start=6.0,
                end=9.2,
            ),
            TranscriptSegment(
                speaker=0,
                text="Sure! It aggregates words and finalizes based on punctuation or speaker turns.",
                is_final=True,
                start=9.5,
                end=13.0,
            ),
        ]

    async def start(self) -> None:
        self._is_running = True
        self._task = asyncio.create_task(self._emit_loop())

    async def stop(self) -> None:
        self._is_running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def send_audio(self, chunk: bytes) -> None:
        # Mock transcriber doesn't need to process raw audio bytes
        pass

    async def _emit_loop(self) -> None:
        index = 0
        while self._is_running:
            await asyncio.sleep(self.emit_interval)
            if not self._is_running:
                break
            seg = self._script[index % len(self._script)]
            # Update timestamps for simulated stream
            now = time.time()
            sim_seg = TranscriptSegment(
                speaker=seg.speaker,
                text=seg.text,
                is_final=seg.is_final,
                start=now - 1.0,
                end=now,
                confidence=0.98,
            )
            await self._queue.put(sim_seg)
            index += 1
