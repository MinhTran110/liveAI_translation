"""Deepgram streaming ASR client with speaker diarization."""

import asyncio
from collections import Counter
import json
import logging
from typing import Optional
from urllib.parse import urlencode

from transcribe.base import TranscriberBase, TranscriptSegment

logger = logging.getLogger(__name__)


class DeepgramStreamingTranscriber(TranscriberBase):
    """Deepgram WebSocket streaming transcriber with real-time speaker diarization."""

    def __init__(
        self,
        api_key: str,
        sample_rate: int = 16000,
        language: str = "multi",
        model: str = "nova-2",
        punctuate: bool = True,
        diarize: bool = True,
        interim_results: bool = True,
    ):
        super().__init__(sample_rate=sample_rate, language=language)
        self.api_key = api_key
        self.model = model
        self.punctuate = punctuate
        self.diarize = diarize
        self.interim_results = interim_results

        self._ws = None
        self._send_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=200)
        self._receiver_task: Optional[asyncio.Task] = None
        self._sender_task: Optional[asyncio.Task] = None

    def set_language(self, language: str) -> None:
        """Update language code for Deepgram streaming."""
        super().set_language("multi" if language in ("auto", "multi", "") else language)
        logger.info("Deepgram language updated to: %s", self.language)

    def _build_ws_url(self) -> str:
        """Construct the WebSocket URL with streaming query parameters."""
        params = {
            "model": self.model,
            "encoding": "linear16",
            "sample_rate": self.sample_rate,
            "channels": 1,
            "punctuate": str(self.punctuate).lower(),
            "diarize": str(self.diarize).lower(),
            "smart_format": "true",
            "numerals": "true",
            "interim_results": str(self.interim_results).lower(),
        }
        if self.language:
            params["language"] = self.language

        query_str = urlencode(params)
        return f"wss://api.deepgram.com/v1/listen?{query_str}"

    async def start(self) -> None:
        """Establish WebSocket connection and start sender/receiver tasks."""
        if not self.api_key:
            raise ValueError("Deepgram API Key is required for DeepgramStreamingTranscriber.")

        if self._is_running:
            return

        try:
            import websockets
        except ImportError:
            raise ImportError("Package 'websockets' is required for Deepgram streaming. Run: pip install websockets")

        url = self._build_ws_url()
        headers = {"Authorization": f"Token {self.api_key}"}

        logger.info("Connecting to Deepgram streaming API (model=%s, diarize=%s)...", self.model, self.diarize)
        self._ws = await websockets.connect(url, extra_headers=headers)
        self._is_running = True

        self._sender_task = asyncio.create_task(self._send_loop())
        self._receiver_task = asyncio.create_task(self._receive_loop())
        logger.info("Deepgram streaming connection established.")

    async def stop(self) -> None:
        """Close connection and stop tasks."""
        self._is_running = False

        if self._sender_task and not self._sender_task.done():
            self._sender_task.cancel()
        if self._receiver_task and not self._receiver_task.done():
            self._receiver_task.cancel()

        if self._ws:
            try:
                # Send close stream message per Deepgram spec
                await self._ws.send(json.dumps({"type": "CloseStream"}))
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

        logger.info("Deepgram transcriber stopped.")

    async def send_audio(self, chunk: bytes) -> None:
        """Enqueue an audio chunk to be sent over WebSocket."""
        if not self._is_running or not chunk:
            return
        try:
            self._send_queue.put_nowait(chunk)
        except asyncio.QueueFull:
            try:
                self._send_queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            self._send_queue.put_nowait(chunk)

    async def _send_loop(self) -> None:
        """Task that transmits audio chunks to Deepgram."""
        while self._is_running and self._ws:
            try:
                chunk = await self._send_queue.get()
                await self._ws.send(chunk)
                self._send_queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error sending audio to Deepgram: %s", e)
                break

    async def _receive_loop(self) -> None:
        """Task that receives and parses transcription events from Deepgram."""
        while self._is_running and self._ws:
            try:
                msg = await self._ws.recv()
                data = json.loads(msg)
                segment = self._parse_deepgram_response(data)
                if segment and segment.text.strip():
                    await self._queue.put(segment)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error receiving from Deepgram: %s", e)
                break

    def _parse_deepgram_response(self, data: dict) -> Optional[TranscriptSegment]:
        """Extract transcript and speaker identity from Deepgram JSON payload."""
        msg_type = data.get("type")
        if msg_type != "Results":
            return None

        channel = data.get("channel", {})
        alternatives = channel.get("alternatives", [])
        if not alternatives:
            return None

        alt = alternatives[0]
        text = alt.get("transcript", "").strip()
        if not text:
            return None

        is_final = data.get("is_final", False)
        speech_final = data.get("speech_final", False)
        start_time = data.get("start", 0.0)
        duration = data.get("duration", 0.0)
        end_time = start_time + duration
        confidence = alt.get("confidence", 1.0)
        words = alt.get("words", [])

        # Determine dominant speaker from word-level diarization
        speaker: Optional[int | str] = 0
        if words:
            speakers = [w.get("speaker") for w in words if "speaker" in w and w["speaker"] is not None]
            if speakers:
                speaker = Counter(speakers).most_common(1)[0][0]

        return TranscriptSegment(
            text=text,
            speaker=speaker,
            is_final=is_final or speech_final,
            start=start_time,
            end=end_time,
            words=words,
            confidence=confidence,
        )
