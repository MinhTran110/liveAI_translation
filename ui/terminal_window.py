"""Tkinter always-on-top terminal subtitle window with audio VU meter and opacity controls."""

from datetime import datetime
import logging
import queue
import threading
import time
from typing import Callable, Optional

from ui.theme import (
    BACKGROUND_COLOR,
    BORDER_COLOR,
    CONTAINER_COLOR,
    FONT_SIZE_ORIGINAL,
    FONT_SIZE_SPEAKER,
    FONT_SIZE_TIMESTAMP,
    FONT_SIZE_TRANSLATED,
    HEADER_BG,
    ORIGINAL_TEXT_COLOR,
    TEXT_COLOR,
    TRANSLATED_TEXT_COLOR,
    get_speaker_color,
)

logger = logging.getLogger(__name__)

LANGUAGES = [
    ("vi", "Tiếng Việt"),
    ("en", "English"),
    ("ja", "日本語 (Japanese)"),
    ("zh", "中文 (Chinese)"),
    ("ko", "한국어 (Korean)"),
    ("fr", "Français"),
    ("de", "Deutsch"),
    ("es", "Español"),
]


class TerminalWindow:
    """Always-on-top Tkinter window styled like a terminal for real-time translation subtitles."""

    def __init__(
        self,
        title: str = "Live Voice Translate",
        width: int = 720,
        height: int = 460,
        always_on_top: bool = True,
        status_info: str = "Ready",
        target_language: str = "vi",
        on_language_change: Optional[Callable[[str], None]] = None,
        audio_volume_provider: Optional[Callable[[], float]] = None,
    ):
        self.window_title = title
        self.width = width
        self.height = height
        self.always_on_top = always_on_top
        self.status_info = status_info
        self.target_language = target_language
        self.on_language_change = on_language_change
        self.audio_volume_provider = audio_volume_provider

        self._queue: queue.Queue = queue.Queue()
        self._root = None
        self._text_area = None
        self._status_var = None
        self._topmost_var = None
        self._opacity_var = None
        self._lang_var = None
        self._vu_canvas = None
        self._font_size = FONT_SIZE_TRANSLATED
        self._is_paused = False
        self._is_closed = False
        self._speaker_tag_counter = 0

    def start_in_thread(self) -> threading.Thread:
        """Start Tkinter window in a dedicated background thread."""
        thread = threading.Thread(target=self.run, daemon=True)
        thread.start()
        return thread

    def run(self) -> None:
        """Create and run Tkinter window main loop."""
        try:
            import tkinter as tk
            from tkinter import ttk, scrolledtext
        except ImportError:
            logger.warning("Tkinter is not available. Falling back to console rendering.")
            self._run_fallback_loop()
            return

        try:
            self._root = tk.Tk()
        except Exception as e:
            logger.warning("Could not initialize Tkinter display (%s). Falling back to console renderer.", e)
            self._run_fallback_loop()
            return

        self._root.title(self.window_title)
        self._root.geometry(f"{self.width}x{self.height}")
        self._root.configure(bg=BACKGROUND_COLOR)

        # Configure always-on-top & default opacity
        try:
            self._root.wm_attributes("-topmost", self.always_on_top)
            self._root.wm_attributes("-alpha", 0.94)
        except Exception:
            pass

        # 1. Top Control Header
        header_frame = tk.Frame(self._root, bg=HEADER_BG, padx=8, pady=4)
        header_frame.pack(side=tk.TOP, fill=tk.X)

        title_lbl = tk.Label(
            header_frame,
            text="▶ LIVE AI TRANSLATE",
            bg=HEADER_BG,
            fg="#58a6ff",
            font=("Consolas", 10, "bold"),
        )
        title_lbl.pack(side=tk.LEFT, padx=(0, 8))

        # Status text
        self._status_var = tk.StringVar(value=self.status_info)
        status_lbl = tk.Label(
            header_frame,
            textvariable=self._status_var,
            bg=HEADER_BG,
            fg="#8b949e",
            font=("Consolas", 9),
        )
        status_lbl.pack(side=tk.LEFT, padx=4)

        # Audio VU Level Meter (Mini Canvas)
        vu_frame = tk.Frame(header_frame, bg=HEADER_BG)
        vu_frame.pack(side=tk.LEFT, padx=10)

        vu_label = tk.Label(vu_frame, text="AUDIO", bg=HEADER_BG, fg="#6e7681", font=("Consolas", 7, "bold"))
        vu_label.pack(side=tk.LEFT, padx=2)

        self._vu_canvas = tk.Canvas(vu_frame, width=60, height=10, bg="#111111", highlightthickness=1, highlightbackground="#333333")
        self._vu_canvas.pack(side=tk.LEFT)

        # Language dropdown selector
        lang_frame = tk.Frame(header_frame, bg=HEADER_BG)
        lang_frame.pack(side=tk.RIGHT, padx=4)

        self._lang_var = tk.StringVar(value=self.target_language)
        lang_dropdown = ttk.Combobox(
            lang_frame,
            textvariable=self._lang_var,
            values=[code for code, _ in LANGUAGES],
            width=5,
            state="readonly",
        )
        lang_dropdown.pack(side=tk.RIGHT)
        lang_dropdown.bind("<<ComboboxSelected>>", self._handle_lang_change)

        lang_label = tk.Label(lang_frame, text="Target:", bg=HEADER_BG, fg="#8b949e", font=("Consolas", 8))
        lang_label.pack(side=tk.RIGHT, padx=2)

        # Always-on-top checkbox
        self._topmost_var = tk.BooleanVar(value=self.always_on_top)
        topmost_chk = tk.Checkbutton(
            header_frame,
            text="Pin Top",
            variable=self._topmost_var,
            command=self._toggle_topmost,
            bg=HEADER_BG,
            fg="#8b949e",
            selectcolor="#1e1e1e",
            activebackground=HEADER_BG,
            activeforeground="#ffffff",
            font=("Consolas", 8),
        )
        topmost_chk.pack(side=tk.RIGHT, padx=4)

        # Clear button
        clear_btn = tk.Button(
            header_frame,
            text="Clear",
            command=self.clear,
            bg="#21262d",
            fg="#c9d1d9",
            activebackground="#30363d",
            activeforeground="#ffffff",
            bd=0,
            padx=6,
            pady=1,
            font=("Consolas", 8),
        )
        clear_btn.pack(side=tk.RIGHT, padx=4)

        # 2. Secondary Utility Bar (Opacity & Font scaling)
        sub_bar = tk.Frame(self._root, bg="#141414", padx=8, pady=2)
        sub_bar.pack(side=tk.TOP, fill=tk.X)

        # Font zoom buttons
        font_down_btn = tk.Button(
            sub_bar,
            text="A-",
            command=self._decrease_font,
            bg="#1c1c1c",
            fg="#8b949e",
            bd=0,
            padx=4,
            font=("Consolas", 8),
        )
        font_down_btn.pack(side=tk.RIGHT, padx=2)

        font_up_btn = tk.Button(
            sub_bar,
            text="A+",
            command=self._increase_font,
            bg="#1c1c1c",
            fg="#8b949e",
            bd=0,
            padx=4,
            font=("Consolas", 8),
        )
        font_up_btn.pack(side=tk.RIGHT, padx=2)

        # Opacity Slider
        opacity_lbl = tk.Label(sub_bar, text="Opacity:", bg="#141414", fg="#6e7681", font=("Consolas", 8))
        opacity_lbl.pack(side=tk.LEFT, padx=(0, 4))

        self._opacity_var = tk.DoubleVar(value=0.94)
        opacity_slider = tk.Scale(
            sub_bar,
            from_=0.4,
            to=1.0,
            resolution=0.02,
            orient=tk.HORIZONTAL,
            variable=self._opacity_var,
            command=self._update_opacity,
            showvalue=0,
            length=80,
            bg="#141414",
            fg="#8b949e",
            troughcolor="#222222",
            highlightthickness=0,
            bd=0,
        )
        opacity_slider.pack(side=tk.LEFT)

        # Pause / Resume Button
        self._pause_btn = tk.Button(
            sub_bar,
            text="⏸ Pause",
            command=self._toggle_pause,
            bg="#1c1c1c",
            fg="#8b949e",
            bd=0,
            padx=6,
            font=("Consolas", 8),
        )
        self._pause_btn.pack(side=tk.LEFT, padx=12)

        # 3. Scrolled Text Subtitle Display
        content_frame = tk.Frame(self._root, bg=BACKGROUND_COLOR, padx=6, pady=4)
        content_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        self._text_area = scrolledtext.ScrolledText(
            content_frame,
            wrap=tk.WORD,
            bg=CONTAINER_COLOR,
            fg=TEXT_COLOR,
            insertbackground="#ffffff",
            selectbackground="#264f78",
            bd=0,
            highlightthickness=1,
            highlightbackground=BORDER_COLOR,
            padx=10,
            pady=8,
            font=("Consolas", self._font_size),
        )
        self._text_area.pack(fill=tk.BOTH, expand=True)

        # Configure default text formatting tags
        self._text_area.tag_configure("timestamp", foreground="#6e7681", font=("Consolas", FONT_SIZE_TIMESTAMP))
        self._text_area.tag_configure(
            "original", foreground=ORIGINAL_TEXT_COLOR, font=("Consolas", FONT_SIZE_ORIGINAL, "italic")
        )
        self._text_area.tag_configure(
            "translated", foreground=TRANSLATED_TEXT_COLOR, font=("Consolas", self._font_size, "bold")
        )
        self._text_area.tag_configure("divider", foreground="#252526", font=("Consolas", 8))

        self._root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Schedule loops
        self._root.after(50, self._process_queue)
        self._root.after(100, self._update_vu_meter)
        self._root.mainloop()

    def _handle_lang_change(self, event=None) -> None:
        """Handle target language selection from dropdown."""
        new_lang = self._lang_var.get()
        self.target_language = new_lang
        if self.on_language_change:
            self.on_language_change(new_lang)
        self.set_status(f"Target: {new_lang.upper()}")

    def _update_opacity(self, val: str) -> None:
        """Update window transparency."""
        if self._root:
            try:
                self._root.wm_attributes("-alpha", float(val))
            except Exception:
                pass

    def _toggle_pause(self) -> None:
        """Toggle subtitle rendering pause state."""
        self._is_paused = not self._is_paused
        if self._is_paused:
            self._pause_btn.config(text="▶ Resume", fg="#e3b341")
            self.set_status("Paused")
        else:
            self._pause_btn.config(text="⏸ Pause", fg="#8b949e")
            self.set_status("Listening...")

    def _increase_font(self) -> None:
        """Increase subtitle font size."""
        self._font_size = min(22, self._font_size + 1)
        if self._text_area:
            self._text_area.tag_configure("translated", font=("Consolas", self._font_size, "bold"))

    def _decrease_font(self) -> None:
        """Decrease subtitle font size."""
        self._font_size = max(9, self._font_size - 1)
        if self._text_area:
            self._text_area.tag_configure("translated", font=("Consolas", self._font_size, "bold"))

    def _update_vu_meter(self) -> None:
        """Update audio level VU meter bar from provider."""
        if self._vu_canvas and self.audio_volume_provider:
            try:
                vol = max(0.0, min(1.0, self.audio_volume_provider()))
                w = int(vol * 58)
                self._vu_canvas.delete("bar")
                # Green to yellow/red color based on level
                bar_color = "#3fb950" if vol < 0.75 else ("#d29922" if vol < 0.9 else "#ff7b72")
                self._vu_canvas.create_rectangle(1, 1, 1 + w, 9, fill=bar_color, outline="", tags="bar")
            except Exception:
                pass

        if not self._is_closed and self._root:
            self._root.after(100, self._update_vu_meter)

    def _toggle_topmost(self) -> None:
        """Toggle window always-on-top state."""
        if self._root and self._topmost_var:
            state = self._topmost_var.get()
            self._root.wm_attributes("-topmost", state)

    def _on_close(self) -> None:
        """Handle window close event."""
        self.close()

    def close(self) -> None:
        """Close window and stop processing loops."""
        self._is_closed = True
        if self._root:
            try:
                self._root.destroy()
            except Exception:
                pass

    def set_status(self, text: str) -> None:
        """Update header status message."""
        self.status_info = text
        if self._status_var and self._root:
            self._root.after(0, lambda: self._status_var.set(text))

    def render(self, speaker: Optional[int | str], original_text: str, translated_text: str) -> None:
        """Post a subtitle item to be displayed on the terminal window (thread-safe)."""
        if self._is_paused or self._is_closed:
            return
        self._queue.put((speaker, original_text, translated_text, datetime.now()))

    def _process_queue(self) -> None:
        """Poll queued subtitle events and append them to the text widget."""
        while not self._queue.empty():
            try:
                speaker, orig, trans, timestamp = self._queue.get_nowait()
                self._insert_subtitle(speaker, orig, trans, timestamp)
                self._queue.task_done()
            except queue.Empty:
                break

        if not self._is_closed and self._root:
            self._root.after(50, self._process_queue)

    def _insert_subtitle(
        self,
        speaker: Optional[int | str],
        orig: str,
        trans: str,
        timestamp: datetime,
    ) -> None:
        """Format and insert subtitle entry into Tkinter text widget."""
        if not self._text_area:
            return

        spk_str = f"Speaker {speaker}" if isinstance(speaker, int) else str(speaker or "Speaker")
        time_str = timestamp.strftime("[%H:%M:%S] ")

        # Dynamic tag for speaker color
        spk_color = get_speaker_color(speaker)
        spk_tag = f"spk_{self._speaker_tag_counter}"
        self._speaker_tag_counter += 1
        self._text_area.tag_configure(
            spk_tag,
            foreground=spk_color,
            font=("Consolas", FONT_SIZE_SPEAKER, "bold"),
        )

        # Insert timestamp & speaker header
        self._text_area.insert("end", time_str, "timestamp")
        self._text_area.insert("end", f"[{spk_str}]\n", spk_tag)

        # Insert original spoken text (dimmed)
        if orig:
            self._text_area.insert("end", f"  {orig}\n", "original")

        # Insert translated text (prominent)
        if trans:
            self._text_area.insert("end", f"▶ {trans}\n", "translated")

        # Divider line
        self._text_area.insert("end", "─" * 60 + "\n\n", "divider")

        # Auto-scroll to end
        self._text_area.see("end")

    def clear(self) -> None:
        """Clear subtitle display."""
        if self._text_area:
            self._text_area.delete("1.0", "end")

    def _run_fallback_loop(self) -> None:
        """Headless console fallback loop when Tkinter/GUI display is unavailable."""
        try:
            from rich.console import Console

            console = Console()
        except ImportError:
            console = None

        logger.info("Running terminal window in headless console mode.")
        while not self._is_closed:
            try:
                speaker, orig, trans, timestamp = self._queue.get(timeout=0.5)
                time_str = timestamp.strftime("[%H:%M:%S]")
                spk_str = f"Speaker {speaker}" if isinstance(speaker, int) else str(speaker or "Speaker")
                color = get_speaker_color(speaker)

                if console:
                    console.print(f"[dim]{time_str}[/dim] [bold {color}][{spk_str}][/bold {color}]")
                    if orig:
                        console.print(f"  [dim italic]{orig}[/dim italic]")
                    if trans:
                        console.print(f"  [bold white]▶ {trans}[/bold white]")
                    console.print("[dim]──────────────────────────────────────────────[/dim]")
                else:
                    print(f"{time_str} [{spk_str}]")
                    if orig:
                        print(f"  {orig}")
                    if trans:
                        print(f"  ▶ {trans}")
                    print("-" * 50)
                self._queue.task_done()
            except queue.Empty:
                continue
            except Exception:
                break
