"""Linux audio capture backend using PulseAudio / PipeWire .monitor sources."""

import logging
import queue
import subprocess
import threading
from typing import Optional

from audio.base import SystemAudioCapture

logger = logging.getLogger(__name__)


class LinuxAudioCapture(SystemAudioCapture):
    """Captures system audio and/or microphone on Linux using PipeWire/PulseAudio/ALSA."""

    def __init__(
        self,
        sample_rate: int = 16000,
        channels: int = 1,
        chunk_size: int = 4096,
        sink_name: Optional[str] = None,
        source_name: Optional[str] = None,
        audio_source: str = "both",  # 'both', 'mic', 'system'
    ):
        super().__init__(sample_rate, channels, chunk_size)
        self.sink_name = sink_name
        self.source_name = source_name
        self.audio_source = audio_source.lower().strip()
        self._queue: queue.Queue[bytes] = queue.Queue(maxsize=100)
        self._threads: list[threading.Thread] = []
        self._stream = None
        self._processes: list[subprocess.Popen] = []
        self._backend_method = "auto"
        self._sink_volume: float = 0.0
        self._mic_volume: float = 0.0

    def get_audio_source(self) -> str:
        """Get current audio capture mode ('both', 'mic', 'system')."""
        return self.audio_source

    def set_audio_source(self, mode: str) -> None:
        """Switch audio capture mode at runtime ('both', 'mic', 'system')."""
        clean_mode = mode.lower().strip()
        if clean_mode not in ("both", "mic", "system"):
            return
        if clean_mode == self.audio_source and self._is_active:
            return

        logger.info("Switching audio capture source to: %s", clean_mode)
        was_active = self._is_active
        if was_active:
            self.stop()
        self.audio_source = clean_mode
        if was_active:
            self.start()

    def _find_monitor_device_sounddevice(self) -> Optional[int]:
        """Try finding a genuine monitor device using sounddevice."""
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
        """Find active playback sink target for PipeWire."""
        if self.sink_name:
            return self.sink_name

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

        return "@DEFAULT_AUDIO_SINK@"

    def _find_default_source(self) -> str:
        """Find active microphone / capture source target for PipeWire."""
        if self.source_name:
            return self.source_name

        try:
            out = subprocess.check_output(["wpctl", "status"], text=True, stderr=subprocess.DEVNULL)
            in_sources = False
            for line in out.splitlines():
                if "Sources:" in line:
                    in_sources = True
                    continue
                if in_sources:
                    if any(k in line for k in ["Source endpoints:", "Streams:", "Video:"]):
                        break
                    if "*" in line:
                        for p in line.strip().split():
                            clean = p.rstrip(".")
                            if clean.isdigit():
                                return clean
        except Exception:
            pass

        return "@DEFAULT_AUDIO_SOURCE@"

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

    def _spawn_pw_proc(self, target: str) -> Optional[subprocess.Popen]:
        """Spawn a single pw-record subprocess for a given target."""
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
        try:
            return subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                bufsize=self.chunk_size,
            )
        except Exception as e:
            logger.debug("pw-record target %s failed to spawn: %s", target, e)
            return None

    def _start_pw_record(self) -> bool:
        """Capture via native PipeWire pw-record CLI tapping into sink, mic, or both."""
        import shutil
        import numpy as np

        if not shutil.which("pw-record"):
            return False

        sink_target = self._find_default_sink()
        source_target = self._find_default_source()

        logger.info(
            "Starting PipeWire capture (mode=%s | sink=%s | mic=%s)",
            self.audio_source,
            sink_target,
            source_target,
        )

        if self.audio_source == "both":
            proc_sink = self._spawn_pw_proc(sink_target)
            proc_mic = self._spawn_pw_proc(source_target)

            if not proc_sink and not proc_mic:
                return False

            self._processes = [p for p in (proc_sink, proc_mic) if p is not None]

            q_sink: queue.Queue[bytes] = queue.Queue(maxsize=15)
            q_mic: queue.Queue[bytes] = queue.Queue(maxsize=15)

            def make_reader(proc, q, is_mic=False):
                def reader():
                    while self._is_active and proc.poll() is None:
                        data = proc.stdout.read(self.chunk_size)
                        if data:
                            vol = self.calculate_rms(data)
                            if is_mic:
                                self._mic_volume = vol
                            else:
                                self._sink_volume = vol
                            try:
                                q.put(data, timeout=0.08)
                            except queue.Full:
                                try:
                                    q.get_nowait()
                                except queue.Empty:
                                    pass
                                q.put_nowait(data)
                        else:
                            break
                return reader

            if proc_sink:
                t_sink = threading.Thread(target=make_reader(proc_sink, q_sink, False), daemon=True)
                t_sink.start()
                self._threads.append(t_sink)

            if proc_mic:
                t_mic = threading.Thread(target=make_reader(proc_mic, q_mic, True), daemon=True)
                t_mic.start()
                self._threads.append(t_mic)

            def mixer():
                while self._is_active:
                    c_sink = None
                    c_mic = None
                    if proc_sink:
                        try:
                            c_sink = q_sink.get(timeout=0.04)
                        except queue.Empty:
                            pass
                    if proc_mic:
                        try:
                            c_mic = q_mic.get(timeout=0.04)
                        except queue.Empty:
                            pass

                    out_chunk = None
                    if c_sink and c_mic:
                        min_len = min(len(c_sink), len(c_mic))
                        s = np.frombuffer(c_sink[:min_len], dtype=np.int16).astype(np.int32)
                        m = np.frombuffer(c_mic[:min_len], dtype=np.int16).astype(np.int32)
                        mixed = np.clip(s + m, -32768, 32767).astype(np.int16).tobytes()
                        out_chunk = mixed
                    elif c_sink:
                        out_chunk = c_sink
                    elif c_mic:
                        out_chunk = c_mic

                    if out_chunk:
                        self._current_volume = self.calculate_rms(out_chunk)
                        try:
                            self._queue.put(out_chunk, timeout=0.05)
                        except queue.Full:
                            try:
                                self._queue.get_nowait()
                            except queue.Empty:
                                pass
                            self._queue.put_nowait(out_chunk)

            t_mix = threading.Thread(target=mixer, daemon=True)
            t_mix.start()
            self._threads.append(t_mix)
            self._backend_method = "pw-record (dual mix)"
            return True

        else:
            # Single target: mic or system
            target = source_target if self.audio_source == "mic" else sink_target
            proc = self._spawn_pw_proc(target)
            if not proc:
                return False

            self._processes = [proc]

            def reader():
                while self._is_active and proc.poll() is None:
                    data = proc.stdout.read(self.chunk_size)
                    if data:
                        self._current_volume = self.calculate_rms(data)
                        try:
                            self._queue.put(data, timeout=0.1)
                        except queue.Full:
                            try:
                                self._queue.get_nowait()
                            except queue.Empty:
                                pass
                            self._queue.put_nowait(data)
                    else:
                        break

            t = threading.Thread(target=reader, daemon=True)
            t.start()
            self._threads.append(t)
            self._backend_method = f"pw-record ({self.audio_source})"
            return True

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

        for proc in self._processes:
            try:
                proc.terminate()
                proc.wait(timeout=0.5)
            except Exception:
                pass
        self._processes.clear()

        # Clear active threads
        self._threads.clear()
        self._current_volume = 0.0
        self._sink_volume = 0.0
        self._mic_volume = 0.0

    def read_chunk(self, timeout: float = 1.0) -> Optional[bytes]:
        """Read an audio chunk from the buffer queue."""
        if not self._is_active:
            return None
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None
