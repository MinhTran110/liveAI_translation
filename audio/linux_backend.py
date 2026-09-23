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
        """Try finding a genuine monitor device using sounddevice (never fall back to microphone)."""
        try:
            import sounddevice as sd

            devices = sd.query_devices()
            for idx, dev in enumerate(devices):
                name = dev.get("name", "").lower()
                max_inputs = dev.get("max_input_channels", 0)
                if max_inputs > 0 and (".monitor" in name or "monitor of" in name):
                    logger.info("Found Linux monitor device (sounddevice) [%d]: %s", idx, dev["name"])
                    return idx
        except Exception as e:
            logger.debug("sounddevice detection failed: %s", e)
        return None

    def _find_default_sink(self) -> str:
        """Find the active default sink target for PipeWire / PulseAudio."""
        if self.sink_name:
            return self.sink_name

        # 1. Try wpctl status to find the active playback sink marked with '*'
        try:
            out = subprocess.check_output(["wpctl", "status"], text=True, stderr=subprocess.DEVNULL)
            in_sinks = False
            for line in out.splitlines():
                if "Sinks:" in line:
                    in_sinks = True
                    continue
                if in_sinks:
                    if any(k in line for k in ["Sink endpoints:", "Sources:", "Streams:", "Video:"]):
                        break
                    if "*" in line:
                        for p in line.strip().split():
                            clean = p.rstrip(".")
                            if clean.isdigit():
                                return clean
        except Exception:
            pass

        # 2. Try pactl get-default-sink
        try:
            out = subprocess.check_output(["pactl", "get-default-sink"], text=True, stderr=subprocess.DEVNULL).strip()
            if out:
                return out + ".monitor"
        except Exception:
            pass

        return "@DEFAULT_AUDIO_SINK@"

    def _start_sounddevice(self, device_idx: int) -> bool:
        """Start capturing via sounddevice."""
        try:
            import sounddevice as sd

            def audio_callback(indata, frames, time_info, status):
                if status:
                    logger.debug("Audio status: %s", status)
                chunk = bytes(indata)
                self._current_volume = self.calculate_rms(chunk)
                try:
                    self._queue.put_nowait(chunk)
                except queue.Full:
                    try:
                        self._queue.get_nowait()
                    except queue.Empty:
                        pass
                    self._queue.put_nowait(chunk)

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

    def _start_pw_record(self) -> bool:
        """Capture via native PipeWire pw-record CLI tapping into system audio sink."""
        import shutil

        if not shutil.which("pw-record"):
            return False

        target = self.sink_name or self._find_default_sink()
        cmd = [
            "pw-record",
            "--target",
            str(target),
            "--format",
            "s16",
            "--rate",
            str(self.sample_rate),
            "--channels",
            str(self.channels),
            "-",
        ]
        logger.info("Starting PipeWire pw-record with target sink: %s", target)

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
                        self._current_volume = self.calculate_rms(data)
                        try:
                            self._queue.put(data, timeout=0.1)
                        except queue.Full:
                            pass
                    else:
                        break

            self._thread = threading.Thread(target=reader, daemon=True)
            self._thread.start()
            self._backend_method = "pw-record"
            return True
        except Exception as e:
            logger.debug("pw-record subprocess failed: %s", e)
            return False

    def _start_parec(self) -> bool:
        """Fallback: capture via parec or pulseaudio subprocess."""
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
                        self._current_volume = self.calculate_rms(data)
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

        # 1. Try native PipeWire pw-record first (gold standard on modern Linux)
        if self._start_pw_record():
            logger.info("LinuxAudioCapture started with PipeWire pw-record")
            return

        # 2. Try PulseAudio parec
        if self._start_parec():
            logger.info("LinuxAudioCapture started with parec subprocess")
            return

        # 3. Try sounddevice if an explicit monitor device is present
        dev_idx = self._find_monitor_device_sounddevice()
        if dev_idx is not None and self._start_sounddevice(dev_idx):
            logger.info("LinuxAudioCapture started with sounddevice monitor")
            return

        logger.warning(
            "Neither pw-record nor parec nor sounddevice monitor capture succeeded. "
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
