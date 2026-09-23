"""Linux audio capture backend using PulseAudio / PipeWire .monitor sources."""

import logging
import queue
import subprocess
import threading
from typing import Optional

from audio.base import SystemAudioCapture

logger = logging.getLogger(__name__)


class LinuxAudioCapture(SystemAudioCapture):
    """Captures system audio on Linux by tapping into PulseAudio/PipeWire monitor sinks."""

    def __init__(
        self,
        sample_rate: int = 16000,
        channels: int = 1,
        chunk_size: int = 4096,
        sink_name: Optional[str] = None,
    ):
        super().__init__(sample_rate, channels, chunk_size)
        self.sink_name = sink_name
        self._queue: queue.Queue[bytes] = queue.Queue(maxsize=100)
        self._thread: Optional[threading.Thread] = None
        self._stream = None
        self._process: Optional[subprocess.Popen] = None
        self._backend_method = "auto"

    def _find_monitor_device_sounddevice(self) -> Optional[int]:
        """Try finding a monitor device using sounddevice."""
        try:
            import sounddevice as sd

            devices = sd.query_devices()
            # First search for monitor in name
            for idx, dev in enumerate(devices):
                name = dev.get("name", "").lower()
                max_inputs = dev.get("max_input_channels", 0)
                if max_inputs > 0 and (".monitor" in name or "monitor of" in name):
                    logger.info("Found Linux monitor device (sounddevice) [%d]: %s", idx, dev["name"])
                    return idx

            # Fallback to default input if no explicit monitor found
            default_in = sd.default.device[0]
            if default_in is not None and default_in >= 0:
                logger.info("Using default input device [%d] (sounddevice)", default_in)
                return default_in
        except Exception as e:
            logger.debug("sounddevice detection failed: %s", e)
        return None

    def _start_sounddevice(self, device_idx: int) -> bool:
        """Start capturing via sounddevice."""
        try:
            import sounddevice as sd

            def audio_callback(indata, frames, time_info, status):
                if status:
                    logger.debug("Audio status: %s", status)
                try:
                    self._queue.put_nowait(bytes(indata))
                except queue.Full:
                    try:
                        self._queue.get_nowait()
                    except queue.Empty:
                        pass
                    self._queue.put_nowait(bytes(indata))

            self._stream = sd.RawInputStream(
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype="int16",
                blocksize=self.chunk_size // (2 * self.channels),
                device=device_idx,
                callback=audio_callback,
            )
            self._stream.start()
            self._backend_method = "sounddevice"
            return True
        except Exception as e:
            logger.warning("Failed to start sounddevice capture: %s", e)
            return False

    def _start_parec(self) -> bool:
        """Fallback: capture via parec or pw-record subprocess."""
        cmd = [
            "parec",
            "--format=s16le",
            f"--rate={self.sample_rate}",
            f"--channels={self.channels}",
        ]
        if self.sink_name:
            cmd.extend(["-d", self.sink_name])
        else:
            cmd.extend(["-d", "@DEFAULT_MONITOR@"])

        try:
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                bufsize=self.chunk_size,
            )

            def reader():
                while self._is_active and self._process and self._process.poll() is None:
                    data = self._process.stdout.read(self.chunk_size)
                    if data:
                        try:
                            self._queue.put(data, timeout=0.1)
                        except queue.Full:
                            pass
                    else:
                        break

            self._thread = threading.Thread(target=reader, daemon=True)
            self._thread.start()
            self._backend_method = "parec"
            return True
        except Exception as e:
            logger.debug("parec subprocess failed: %s", e)
            return False

    def start(self) -> None:
        """Start audio capture on Linux."""
        if self._is_active:
            return

        self._is_active = True

        # Try sounddevice first
        dev_idx = self._find_monitor_device_sounddevice()
        if dev_idx is not None and self._start_sounddevice(dev_idx):
            logger.info("LinuxAudioCapture started with sounddevice")
            return

        # Fallback to parec
        if self._start_parec():
            logger.info("LinuxAudioCapture started with parec subprocess")
            return

        logger.warning(
            "Neither sounddevice nor parec monitor capture succeeded. "
            "System audio may not be audible or running in a container without PulseAudio/PipeWire."
        )

    def stop(self) -> None:
        """Stop audio capture."""
        self._is_active = False
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None

        if self._process is not None:
            try:
                self._process.terminate()
                self._process.wait(timeout=1.0)
            except Exception:
                pass
            self._process = None

    def read_chunk(self, timeout: float = 1.0) -> Optional[bytes]:
        """Read an audio chunk from the buffer queue."""
        if not self._is_active:
            return None
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None
